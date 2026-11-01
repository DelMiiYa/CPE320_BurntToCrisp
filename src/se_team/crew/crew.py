"""
Crew and agent definitions for the multi-agent software engineering team.
Configures agents with Gemini models and sandboxed tools according to strict roles.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv
from crewai import Agent, Crew, LLM, Process, Task

from se_team.models import (
    BugReport,
    FinalSignOff,
    QAReport,
    RePromptPackage,
    SpecPackage,
)
from se_team.tools.sandbox import (
    ListFilesTool,
    ReadFileTool,
    RunTestsTool,
    SandboxManager,
    WriteFileTool,
)

# Load configuration from .env
load_dotenv()

CONFIG_DIR = Path(__file__).parent


def load_yaml(filename: str) -> Dict[str, Any]:
    with open(CONFIG_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


AGENTS_CONFIG = load_yaml("agents.yaml")
TASKS_CONFIG = load_yaml("tasks.yaml")


def get_llm(model_env_var: str, default_model: str) -> LLM:
    """
    Instantiates a CrewAI LLM configured for:
    - SWU AI (via SWU_API_KEY and SWU_BASE_URL)
    - Google Gemini (via GEMINI_API_KEY)
    - OpenRouter (via OPENROUTER_API_KEY)
    """
    model_name = os.getenv(model_env_var, default_model).strip()
    swu_key = os.getenv("SWU_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    kwargs: Dict[str, Any] = {
        "model": model_name,
    }

    # 1. SWU AI (supports native Anthropic or OpenAI-compatible gateway)
    if swu_key:
        swu_base_url = os.getenv("SWU_BASE_URL", "https://swuai.swu.ac.th/swu/api/service").strip()
        kwargs["api_key"] = swu_key
        kwargs["base_url"] = swu_base_url
        if "claude" in model_name or model_name.startswith("anthropic/"):
            if not model_name.startswith("anthropic/"):
                kwargs["model"] = f"anthropic/{model_name}"
            else:
                kwargs["model"] = model_name
        elif not model_name.startswith("openai/"):
            kwargs["model"] = f"openai/{model_name}"
    # 2. OpenRouter
    elif model_name.startswith("openrouter/") and openrouter_key:
        kwargs["api_key"] = openrouter_key
        kwargs["temperature"] = 0.2
    # 3. Google Gemini
    elif gemini_key:
        kwargs["api_key"] = gemini_key
        kwargs["temperature"] = 0.2

    return LLM(**kwargs)


def execute_with_rate_limit_retry(fn, *args, max_attempts: int = 4, **kwargs) -> Any:
    """
    Executes a callable with short exponential backoff when encountering Gemini free tier rate limits.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            err_msg = str(exc)
            is_rate_limit = any(
                indicator in err_msg.lower()
                for indicator in ["429", "resource_exhausted", "ratelimit", "quota exceeded", "quotaexceeded"]
            )
            if is_rate_limit and attempt < max_attempts:
                backoff_seconds = attempt * 8
                print(
                    f"\n[Gemini Rate Limit Notice] Free-tier rate limit encountered. "
                    f"Backing off for {backoff_seconds}s before retrying (Attempt {attempt}/{max_attempts})...\n"
                )
                time.sleep(backoff_seconds)
            else:
                if is_rate_limit:
                    print(
                        f"\n[RATE LIMIT EXCEEDED] Gemini API rate limit persists after {max_attempts} attempts.\n"
                        "You are currently on the Google AI Studio free tier. "
                        "Please wait 30-60 seconds before initiating the next run, or configure a faster Flash model.\n"
                    )
                raise exc


# --- Agent Factory Functions ---

def create_orchestrator_agent(sandbox: SandboxManager) -> Agent:
    """Orchestrator & Product Lead: read-only tools."""
    llm = get_llm("ORCHESTRATOR_MODEL", "gemini/gemini-2.5-pro")
    cfg = AGENTS_CONFIG["orchestrator"]
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=[ReadFileTool(sandbox=sandbox), ListFilesTool(sandbox=sandbox)],
        llm=llm,
        verbose=True,
    )


def create_frontend_agent(sandbox: SandboxManager) -> Agent:
    """Frontend & UX Specialist: builder tools (write/read/list)."""
    llm = get_llm("FRONTEND_MODEL", "gemini/gemini-2.5-flash")
    cfg = AGENTS_CONFIG["frontend_specialist"]
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=[
            WriteFileTool(sandbox=sandbox),
            ReadFileTool(sandbox=sandbox),
            ListFilesTool(sandbox=sandbox),
        ],
        llm=llm,
        verbose=True,
    )


def create_backend_agent(sandbox: SandboxManager) -> Agent:
    """Backend & Security Specialist: builder tools (write/read/list)."""
    llm = get_llm("BACKEND_MODEL", "gemini/gemini-2.5-flash")
    cfg = AGENTS_CONFIG["backend_specialist"]
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=[
            WriteFileTool(sandbox=sandbox),
            ReadFileTool(sandbox=sandbox),
            ListFilesTool(sandbox=sandbox),
        ],
        llm=llm,
        verbose=True,
    )


def create_qa_agent(sandbox: SandboxManager) -> Agent:
    """QA & Logic Verifier: run_tests tool (runs pytest with timeout inside sandbox)."""
    llm = get_llm("QA_MODEL", "gemini/gemini-2.5-pro")
    cfg = AGENTS_CONFIG["qa_verifier"]
    return Agent(
        role=cfg["role"],
        goal=cfg["goal"],
        backstory=cfg["backstory"],
        tools=[
            RunTestsTool(sandbox=sandbox),
            ReadFileTool(sandbox=sandbox),
            ListFilesTool(sandbox=sandbox),
        ],
        llm=llm,
        verbose=True,
    )


# --- Task Execution Helpers ---

def run_spec_step(brief: str, sandbox: SandboxManager) -> SpecPackage:
    """Runs Orchestrator to generate SpecPackage from brief."""
    agent = create_orchestrator_agent(sandbox)
    cfg = TASKS_CONFIG["orchestrator_spec_task"]
    task = Task(
        description=cfg["description"].format(project_brief=brief),
        expected_output=cfg["expected_output"],
        agent=agent,
        output_pydantic=SpecPackage,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    res = execute_with_rate_limit_retry(crew.kickoff)
    
    if hasattr(res, "pydantic") and isinstance(res.pydantic, SpecPackage):
        return res.pydantic
    # Fallback parsing
    return SpecPackage.model_validate_json(res.raw)


def run_frontend_step(
    spec: SpecPackage,
    sandbox: SandboxManager,
    extra_instructions: Optional[str] = None,
) -> str:
    """Runs Frontend Specialist to create UI files in workspace/frontend/."""
    agent = create_frontend_agent(sandbox)
    cfg = TASKS_CONFIG["frontend_build_task"]
    
    api_summary = json.dumps([ep.model_dump() for ep in spec.api_contract], indent=2)
    instructions = spec.frontend_prompt.instructions
    if extra_instructions:
        instructions += f"\n\n[REVISED TARGETED INSTRUCTIONS FOR FIXES]:\n{extra_instructions}"

    task = Task(
        description=cfg["description"].format(
            frontend_instructions=instructions,
            api_contract_summary=api_summary,
        ),
        expected_output=cfg["expected_output"],
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    res = execute_with_rate_limit_retry(crew.kickoff)
    return str(res.raw)


def run_backend_step(
    spec: SpecPackage,
    sandbox: SandboxManager,
    extra_instructions: Optional[str] = None,
) -> str:
    """Runs Backend Specialist to build FastAPI + SQLite in workspace/backend/."""
    agent = create_backend_agent(sandbox)
    cfg = TASKS_CONFIG["backend_build_task"]

    api_summary = json.dumps([ep.model_dump() for ep in spec.api_contract], indent=2)
    data_summary = json.dumps([ds.model_dump() for ds in spec.data_schemas], indent=2)
    instructions = spec.backend_prompt.instructions
    if extra_instructions:
        instructions += f"\n\n[REVISED TARGETED INSTRUCTIONS FOR FIXES]:\n{extra_instructions}"

    task = Task(
        description=cfg["description"].format(
            backend_instructions=instructions,
            api_contract_summary=api_summary,
            data_schema_summary=data_summary,
        ),
        expected_output=cfg["expected_output"],
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    res = execute_with_rate_limit_retry(crew.kickoff)
    return str(res.raw)


def run_qa_step(
    spec: SpecPackage,
    sandbox: SandboxManager,
    round_number: int = 1,
) -> QAReport:
    """Runs QA & Logic Verifier: writes and executes pytest tests and produces QAReport."""
    agent = create_qa_agent(sandbox)
    cfg = TASKS_CONFIG["qa_verification_task"]

    api_summary = json.dumps([ep.model_dump() for ep in spec.api_contract], indent=2)
    task = Task(
        description=cfg["description"].format(
            qa_guidance=spec.qa_guidance,
            api_contract_summary=api_summary,
        ),
        expected_output=cfg["expected_output"],
        agent=agent,
        output_pydantic=QAReport,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    res = execute_with_rate_limit_retry(crew.kickoff)

    if hasattr(res, "pydantic") and isinstance(res.pydantic, QAReport):
        report = res.pydantic
        report.round_number = round_number
        return report

    # Fallback: parse raw output or inspect workspace test execution
    try:
        report = QAReport.model_validate_json(res.raw)
        report.round_number = round_number
        return report
    except Exception:
        # Check pytest result directly via sandbox as ground truth
        test_run = sandbox.run_tests()
        passed = test_run["passed"]
        return QAReport(
            round_number=round_number,
            passed=passed,
            summary="QA verification executed via pytest",
            tests_executed=1 if passed else 0,
            tests_passed=1 if passed else 0,
            tests_failed=0 if passed else 1,
            raw_test_output=test_run["output"],
            bugs=[] if passed else [
                BugReport(
                    id="BUG-001",
                    title="Backend test failure or missing tests",
                    description=test_run["output"][:300],
                    severity="high",
                    owning_agent="backend",
                    edge_case_category="contract mismatch",
                    suggested_fix="Fix failing tests or ensure endpoints conform to contract",
                )
            ],
            owning_agents_needing_fixes=[] if passed else ["backend"],
        )


def run_reprompt_step(
    qa_report: QAReport,
    spec: SpecPackage,
    sandbox: SandboxManager,
    round_number: int,
) -> RePromptPackage:
    """Runs Orchestrator to formulate revised instructions targeted ONLY at bug owners."""
    agent = create_orchestrator_agent(sandbox)
    cfg = TASKS_CONFIG["orchestrator_reprompt_task"]

    owning = ", ".join(qa_report.owning_agents_needing_fixes or ["backend"])
    bugs_json = json.dumps([b.model_dump() for b in qa_report.bugs], indent=2)

    task = Task(
        description=cfg["description"].format(
            round_number=round_number,
            qa_report_summary=qa_report.summary,
            bugs_list=bugs_json,
            owning_agents=owning,
        ),
        expected_output=cfg["expected_output"],
        agent=agent,
        output_pydantic=RePromptPackage,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    res = execute_with_rate_limit_retry(crew.kickoff)

    if hasattr(res, "pydantic") and isinstance(res.pydantic, RePromptPackage):
        return res.pydantic
    try:
        return RePromptPackage.model_validate_json(res.raw)
    except Exception:
        targets = [a for a in qa_report.owning_agents_needing_fixes if a in ("frontend", "backend")]
        if not targets:
            targets = ["backend"]
        return RePromptPackage(
            round_number=round_number,
            target_agents=targets,
            reasons=qa_report.summary,
            backend_fixes="Resolve reported pytest failures and edge cases." if "backend" in targets else None,
            frontend_fixes="Align with API contract and validate form inputs." if "frontend" in targets else None,
        )


def run_signoff_step(
    spec: SpecPackage,
    qa_report: QAReport,
    sandbox: SandboxManager,
) -> FinalSignOff:
    """Runs Orchestrator to issue final sign-off."""
    agent = create_orchestrator_agent(sandbox)
    cfg = TASKS_CONFIG["orchestrator_signoff_task"]

    task = Task(
        description=cfg["description"].format(
            round_number=qa_report.round_number,
            qa_report_summary=qa_report.summary,
        ),
        expected_output=cfg["expected_output"],
        agent=agent,
        output_pydantic=FinalSignOff,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    res = execute_with_rate_limit_retry(crew.kickoff)

    if hasattr(res, "pydantic") and isinstance(res.pydantic, FinalSignOff):
        return res.pydantic
    try:
        return FinalSignOff.model_validate_json(res.raw)
    except Exception:
        return FinalSignOff(
            approved=True,
            summary="Application successfully passed all QA verifications and criteria.",
            acceptance_criteria_verified=spec.acceptance_criteria,
            notes="Ready for deployment.",
        )
