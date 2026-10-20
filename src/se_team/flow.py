"""
CrewAI Flow implementation for the multi-agent software engineering team.
Orchestrates the workflow, parallel specialist builds, QA verification, and feedback loop.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from crewai.flow.flow import Flow, listen, router, start
from dotenv import load_dotenv

from se_team.crew.crew import (
    run_backend_step,
    run_frontend_step,
    run_qa_step,
    run_reprompt_step,
    run_signoff_step,
    run_spec_step,
)
from se_team.models import (
    BugReport,
    FinalSignOff,
    QAReport,
    RePromptPackage,
    SpecPackage,
)
from se_team.tools.sandbox import SandboxManager

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP_SPEC_PATH = PROJECT_ROOT / "APP_SPEC.md"

DEFAULT_BRIEF = (
    "Create an original proactive workplace mental wellness and team burnout tracking web application "
    "(BurningUpp concept). Do NOT analyze or clone an existing app; use this product idea to design and "
    "build a brand-new FastAPI + SQLite + HTML/CSS/JS web app featuring: "
    "(1) Dual-role Team Manager and Team Member accounts paired via a unique 6-character alphanumeric teamCode, "
    "including member baseline health profiling (sleep hours bracket, exercise frequency, baseline stress 1-5); "
    "(2) Tiered Clinical Burnout Assessment with Stage 1 Basic Screening (10 Yes/No questions: score < 5 -> "
    "Burnout Level 1; score >= 5 -> routes to Stage 2) and Stage 2 Maslach Burnout Inventory (MBI, 22 items on "
    "a 0-6 Likert frequency scale across Emotional Exhaustion [9 items, high risk >= 27], Depersonalization "
    "[5 items, high risk >= 13], and reverse-scored Personal Accomplishment [8 items, 6 - response, high risk <= 31] "
    "producing a composite Burnout Level of 1 to 3 Flames); "
    "(3) Daily Mood (0-4 scale) & Activity Journaling with one-entry-per-user-per-day upsert idempotency, "
    "interactive monthly mood calendar, mood distribution analytics, burnout coping tips, and a Manager Team "
    "Risk Radar dashboard showing member flame levels and subscale breakdowns."
)


def load_app_spec_brief(spec_path: Optional[Path] = None) -> str:
    """
    Loads the product concept from APP_SPEC.md and frames it as a creative product brief
    so agents use the idea from the app spec to create a new web app rather than analyzing
    an existing app to recreate it. Falls back to DEFAULT_BRIEF if the file is unavailable.
    """
    target_path = spec_path or DEFAULT_APP_SPEC_PATH
    if target_path.exists() and target_path.is_file():
        spec_content = target_path.read_text(encoding="utf-8").strip()
        return (
            "Use the product concept and domain ideas from APP_SPEC.md below to design and create "
            "a brand-new, original web application (FastAPI + SQLite backend and vanilla HTML/CSS/JS frontend). "
            "Do NOT treat this task as analyzing an existing app and recreating/cloning it; instead, use the "
            "ideas, formulas, and user flows described in the spec to build a fresh, cohesive web application:\n\n"
            f"{spec_content}"
        )
    return DEFAULT_BRIEF


class SoftwareTeamFlowState(BaseModel):
    """State tracked across the CrewAI Flow execution."""
    project_brief: str = ""
    run_timestamp: str = ""
    current_round: int = 1
    max_rounds: int = 3
    spec_package: Optional[SpecPackage] = None
    qa_report: Optional[QAReport] = None
    reprompt_package: Optional[RePromptPackage] = None
    final_signoff: Optional[FinalSignOff] = None
    status: str = "INITIALIZED"  # SUCCESS, MAX_ROUNDS_REACHED, FAILED
    unresolved_issues: List[str] = Field(default_factory=list)
    workspace_root: str = "workspace"


class SoftwareTeamFlow(Flow[SoftwareTeamFlowState]):
    """
    CrewAI Flow orchestrating the 4-agent software engineering team:
    1. Orchestrator -> SpecPackage
    2. Backend and Frontend execute in parallel (async execution)
    3. QA & Logic Verifier runs pytest and checks edge cases -> QAReport
    4. Router:
       - pass -> Orchestrator sign-off -> completion
       - fail & round < MAX_ROUNDS -> Orchestrator re-prompts owning agents -> re-run targeted agents -> QA
       - fail & round >= MAX_ROUNDS -> stop & report unresolved issues
    """

    def __init__(self, project_brief: str = "", max_rounds: Optional[int] = None, workspace_root: str = "workspace"):
        super().__init__()
        # Configure UTF-8 stdout on Windows to support emojis cleanly
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8")
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass

        env_max_rounds = int(os.getenv("MAX_ROUNDS", "3"))
        resolved_max_rounds = max_rounds if max_rounds is not None else env_max_rounds
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        self.state.project_brief = project_brief if project_brief else load_app_spec_brief()
        self.state.run_timestamp = timestamp
        self.state.current_round = 1
        self.state.max_rounds = resolved_max_rounds
        self.state.workspace_root = workspace_root

    def get_round_sandbox(self, round_num: int) -> SandboxManager:
        """Returns the SandboxManager for a specific round directory under workspace/runs/<timestamp>/round_N/."""
        round_dir = (
            Path(self.state.workspace_root)
            / "runs"
            / self.state.run_timestamp
            / f"round_{round_num}"
        ).resolve()
        round_dir.mkdir(parents=True, exist_ok=True)
        sandbox = SandboxManager(round_dir)
        if DEFAULT_APP_SPEC_PATH.exists() and not (round_dir / "APP_SPEC.md").exists():
            try:
                sandbox.write_file("APP_SPEC.md", DEFAULT_APP_SPEC_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return sandbox

    def prepare_next_round_workspace(self, from_round: int, to_round: int) -> SandboxManager:
        """Copies code from previous round to create the baseline for the next round."""
        src_dir = (
            Path(self.state.workspace_root)
            / "runs"
            / self.state.run_timestamp
            / f"round_{from_round}"
        ).resolve()
        dest_dir = (
            Path(self.state.workspace_root)
            / "runs"
            / self.state.run_timestamp
            / f"round_{to_round}"
        ).resolve()

        dest_dir.mkdir(parents=True, exist_ok=True)
        if src_dir.exists():
            for item in src_dir.iterdir():
                dest_item = dest_dir / item.name
                if item.name == ".pytest_cache" or item.name == "__pycache__":
                    continue
                if item.is_dir():
                    if dest_item.exists():
                        shutil.rmtree(dest_item)
                    shutil.copytree(item, dest_item)
                else:
                    shutil.copy2(item, dest_item)

        return SandboxManager(dest_dir)

    @start()
    def orchestrator_spec_stage(self) -> SpecPackage:
        """Step 1: Orchestrator translates brief into structured SpecPackage."""
        print("\n=======================================================")
        print(f"[*] ROUND {self.state.current_round}: Orchestrator formulating SpecPackage...")
        print("=======================================================")
        
        sandbox = self.get_round_sandbox(self.state.current_round)
        spec = run_spec_step(self.state.project_brief, sandbox)
        self.state.spec_package = spec
        
        print(f"[+] SpecPackage created: {spec.project_name}")
        print(f"    - Task Scope: {spec.task_scope}")
        print(f"    - Endpoints defined: {len(spec.api_contract)}")
        print(f"    - Data schemas defined: {len(spec.data_schemas)}")
        return spec

    @listen(orchestrator_spec_stage)
    def parallel_build_stage(self) -> str:
        """Step 2: Backend and Frontend execute concurrently in parallel from SpecPackage."""
        print("\n=======================================================")
        print(f"[*] ROUND {self.state.current_round}: Running Frontend and Backend in PARALLEL...")
        print("=======================================================")
        
        sandbox = self.get_round_sandbox(self.state.current_round)
        spec = self.state.spec_package
        if not spec:
            raise ValueError("SpecPackage missing prior to build stage.")

        # Execute Backend and Frontend in parallel threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            backend_future = executor.submit(run_backend_step, spec, sandbox, None)
            frontend_future = executor.submit(run_frontend_step, spec, sandbox, None)
            
            concurrent.futures.wait([backend_future, frontend_future])
            
            backend_res = backend_future.result()
            frontend_res = frontend_future.result()

        print(f"[+] Parallel build round {self.state.current_round} complete.")
        return f"round_{self.state.current_round}_built"

    @listen(parallel_build_stage)
    def qa_verification_stage(self) -> QAReport:
        """Step 3: QA & Logic Verifier writes and runs pytest tests inside sandbox."""
        print("\n=======================================================")
        print(f"[*] ROUND {self.state.current_round}: QA Verifier executing tests & formulas...")
        print("=======================================================")
        
        sandbox = self.get_round_sandbox(self.state.current_round)
        spec = self.state.spec_package
        if not spec:
            raise ValueError("SpecPackage missing prior to QA stage.")

        report = run_qa_step(spec, sandbox, round_number=self.state.current_round)
        self.state.qa_report = report

        print(f"[+] QA Round {self.state.current_round} Result: {'PASSED' if report.passed else 'FAILED'}")
        print(f"    - Tests Executed: {report.tests_executed}")
        print(f"    - Tests Passed: {report.tests_passed}")
        print(f"    - Tests Failed: {report.tests_failed}")
        if report.bugs:
            print(f"    - Bugs Found ({len(report.bugs)}):")
            for bug in report.bugs:
                print(f"      * [{bug.severity.upper()}] {bug.id} - {bug.title} (Owner: {bug.owning_agent})")
        return report

    @router(qa_verification_stage)
    def route_qa_decision(self) -> str:
        """
        Step 4: Router
        - pass -> Orchestrator signs off
        - fail and round < MAX_ROUNDS -> Orchestrator re-prompts only the owning agents
        - fail and round >= MAX_ROUNDS -> stop and print unresolved issues
        """
        report = self.state.qa_report
        if not report:
            return "route_halt"

        if report.passed:
            print("\n[--> Router]: QA PASSED -> Routing to Orchestrator Sign-off.")
            return "route_sign_off"

        if self.state.current_round < self.state.max_rounds:
            print(
                f"\n[--> Router]: QA FAILED (Round {self.state.current_round}/{self.state.max_rounds}) "
                f"-> Routing to Targeted Re-Prompt."
            )
            return "route_reprompt"

        print(
            f"\n[--> Router]: QA FAILED & MAX_ROUNDS reached ({self.state.current_round}/{self.state.max_rounds}) "
            f"-> Halting flow."
        )
        return "route_halt"

    @listen("route_reprompt")
    def handle_reprompt_loop(self) -> str:
        """
        Feedback Loop:
        Orchestrator generates targeted instructions for owning agents only.
        Executes fixes, advances round, and re-triggers QA until pass or max rounds reached.
        """
        while self.state.current_round < self.state.max_rounds and not (self.state.qa_report and self.state.qa_report.passed):
            prev_round = self.state.current_round
            next_round = prev_round + 1
            print("\n=======================================================")
            print(f"[*] RE-PROMPT CYCLE: Round {prev_round} -> Round {next_round}")
            print("=======================================================")

            prev_sandbox = self.get_round_sandbox(prev_round)
            spec = self.state.spec_package
            report = self.state.qa_report
            if not spec or not report:
                break

            # 1. Orchestrator writes targeted re-prompt for owning agents only
            reprompt = run_reprompt_step(report, spec, prev_sandbox, round_number=prev_round)
            self.state.reprompt_package = reprompt
            print(f"[+] Targeted re-prompt issued for: {reprompt.target_agents}")

            # 2. Prepare next round workspace (copy baseline)
            next_sandbox = self.prepare_next_round_workspace(from_round=prev_round, to_round=next_round)
            self.state.current_round = next_round

            # 3. Run ONLY the owning agents
            target_agents = reprompt.target_agents
            futures = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                if "backend" in target_agents:
                    print(f"    - Executing targeted fixes on BACKEND Specialist...")
                    futures.append(
                        executor.submit(run_backend_step, spec, next_sandbox, reprompt.backend_fixes)
                    )
                if "frontend" in target_agents:
                    print(f"    - Executing targeted fixes on FRONTEND Specialist...")
                    futures.append(
                        executor.submit(run_frontend_step, spec, next_sandbox, reprompt.frontend_fixes)
                    )
                concurrent.futures.wait(futures)

            # 4. QA verifies again in the new round
            print(f"    - Running QA on Round {next_round}...")
            new_report = run_qa_step(spec, next_sandbox, round_number=next_round)
            self.state.qa_report = new_report

            if new_report.passed:
                print(f"[+] Round {next_round} QA PASSED!")
                return self.handle_sign_off_action()

        if self.state.qa_report and self.state.qa_report.passed:
            return self.handle_sign_off_action()

        return self.handle_halt_action()

    @listen("route_sign_off")
    def handle_sign_off_action(self) -> str:
        """Final sign-off when QA passes."""
        print("\n=======================================================")
        print(f"[*] Orchestrator Final Sign-off (Round {self.state.current_round})...")
        print("=======================================================")
        
        sandbox = self.get_round_sandbox(self.state.current_round)
        spec = self.state.spec_package
        report = self.state.qa_report or QAReport(passed=True, summary="All checks passed")

        signoff = run_signoff_step(spec, report, sandbox)
        self.state.final_signoff = signoff
        self.state.status = "SUCCESS"

        print(f"\n[SIGN-OFF APPROVED]: {signoff.summary}")
        if signoff.acceptance_criteria_verified:
            print("Verified Acceptance Criteria:")
            for item in signoff.acceptance_criteria_verified:
                print(f"  [v] {item}")
        return "SUCCESS"

    @listen("route_halt")
    def handle_halt_action(self) -> str:
        """Halts the workflow when MAX_ROUNDS is reached without resolution."""
        print("\n=======================================================")
        print(f"[!] WORKFLOW HALTED: MAX_ROUNDS ({self.state.max_rounds}) reached with unresolved issues.")
        print("=======================================================")
        
        self.state.status = "MAX_ROUNDS_REACHED"
        if self.state.qa_report and self.state.qa_report.bugs:
            print("\nUnresolved Issues:")
            for b in self.state.qa_report.bugs:
                issue_str = f"[{b.id}] ({b.severity}) {b.title} [Owner: {b.owning_agent}]: {b.description}"
                self.state.unresolved_issues.append(issue_str)
                print(f"  - {issue_str}")
        return "MAX_ROUNDS_REACHED"
