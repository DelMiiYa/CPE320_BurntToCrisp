"""
Main entry point for running the multi-agent software engineering team.
CLI interface supporting custom briefs and a locally invoked Codex backend.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure se_team is importable from src directory
src_path = str(Path(__file__).parent.parent.resolve())
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from se_team.flow import SoftwareTeamFlow
from se_team.crew.runtime import (
    check_provider_login,
    get_backend,
    uses_antigravity,
    uses_codex,
)

DEFAULT_BRIEF = (
    "BurningUpp: a shared workplace mental wellness and team burnout tracking service. "
    "Multiple organizations can register independently, each with multiple teams and isolated data.\n"
    "Core Vision & Pillars:\n"
    "1. Dual-Role Team Dynamic: Team Managers create teams with a shareable team access code and monitor team-level "
    "burnout risks without invasive micro-surveillance. Team Members join with the team code, complete baseline health & lifestyle profiling, "
    "and access personal wellness tools.\n"
    "2. Low-Friction Daily Mood & Energy Pulse: Quick daily check-in (emotional scale, activities, and reflection notes) "
    "with idempotent one-log-per-day persistence.\n"
    "3. Interactive Wellness Calendar & Timeline: Visual monthly calendar matrix highlighting emotional trends over time, "
    "with an entry inspector to review specific past days.\n"
    "4. Burnout Self-Assessment: Support screening and burnout dimensions using explicitly supplied scoring rules. "
    "Document missing rules or demo assumptions; do not invent validated thresholds or clinical claims. "
    "Keep raw/reversed scoring and risk mapping mathematically consistent.\n"
    "5. Manager Wellness Radar & Insights: High-level team risk dashboard featuring visual risk indicators (e.g. 3-level gauge) and "
    "subscale drill-down insights to guide supportive 1-on-1 interventions.\n"
    "6. Coping & Recovery Library: Supportive educational resources.\n"
    "7. Organization Onboarding & Service Plans: Owners register an organization, set up teams and manage a trial/manual subscription status. "
    "Do not connect live payments or invent real prices.\n"
    "8. Useful Follow-up: Summarize longitudinal trends and missing data; let authorized managers record a follow-up action and status, "
    "with explicit permissions that protect private journal notes."
)


def main() -> None:
    # Ensure UTF-8 output on Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Supervisor-led Software Engineering Team powered by local Codex jobs"
    )
    parser.add_argument(
        "--brief",
        type=str,
        default=DEFAULT_BRIEF,
        help="Project brief in Thai or English describing the web app to build.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="Maximum QA-reprompt rounds before halting (overrides MAX_ROUNDS from .env).",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="workspace",
        help="Root workspace directory for storing runs and generated code (default: workspace).",
    )
    args = parser.parse_args()
    if args.max_rounds is not None and args.max_rounds < 1:
        parser.error("--max-rounds must be at least 1")

    swu_key = os.getenv("SWU_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    has_valid_key = (
        (swu_key and swu_key != "your_swu_token_here") or
        (openrouter_key and openrouter_key != "your_openrouter_api_key_here") or
        (gemini_key and gemini_key != "your_gemini_api_key_here")
    )

    backend = get_backend()
    if backend in {"antigravity", "codex"}:
        try:
            check_provider_login()
        except (RuntimeError, OSError) as exc:
            provider_title = "Google Antigravity" if backend == "antigravity" else "Codex"
            print(f"\n[{provider_title} setup required]: {exc}")
            sys.exit(1)
    elif not has_valid_key:
        print("\n" + "=" * 65)
        print(" [!] ERROR: No LLM API Key is configured.")
        print("=" * 65)
        print(" Please create or update your .env file with one of the following:")
        print("   Option 1: SWU AI (มศว - Free for Students & Staff)")
        print("        SWU_API_KEY=your_swu_token_here")
        print("   Option 2: Google Gemini (Free Tier from Google AI Studio)")
        print("        GEMINI_API_KEY=AIzaSy...")
        print("   Option 3: OpenRouter (Free or Paid models)")
        print("        OPENROUTER_API_KEY=sk-or-v1-...")
        print("   Copy .env.example to .env to get started:")
        print("        cp .env.example .env")
        print("=" * 65 + "\n")
        sys.exit(1)

    print("\n" + "=" * 65)
    print(" Supervisor-led Software Engineering Team")
    print("=" * 65)
    print(f" Brief: {args.brief}")
    print(f" Max Rounds: {args.max_rounds or os.getenv('MAX_ROUNDS', '3')}")
    print(f" Workspace Root: {args.workspace}")
    if uses_codex():
        print(" Backend: Local Codex CLI (inference requires network access)")
        for role in ("ORCHESTRATOR", "FRONTEND", "BACKEND", "QA"):
            model = os.getenv(f"{role}_CODEX_MODEL", "").strip() or os.getenv("CODEX_MODEL", "").strip()
            print(f" {role.title()} Model: {model or 'Codex CLI default'}")
    else:
        print(" Backend: Legacy API provider")
    print("=" * 65 + "\n")

    flow = SoftwareTeamFlow(
        project_brief=args.brief,
        max_rounds=args.max_rounds,
        workspace_root=args.workspace,
    )

    try:
        flow.kickoff()
    except Exception as exc:
        print(f"\n[Execution Error]: {exc}")
        sys.exit(1)

    print("\n" + "=" * 65)
    print(" EXECUTION SUMMARY")
    print("=" * 65)
    print(f" Status:           {flow.state.status}")
    print(f" Total Rounds:     {flow.state.current_round}")
    print(f" Timestamp:        {flow.state.run_timestamp}")
    latest_run_dir = Path(flow.state.workspace_root) / "runs" / flow.state.run_timestamp / f"round_{flow.state.current_round}"
    print(f" Output Directory: {latest_run_dir.resolve()}")

    if flow.state.qa_report:
        print(f" QA Tests Run:     {flow.state.qa_report.tests_executed}")
        print(f" QA Tests Passed:  {flow.state.qa_report.tests_passed}")
        print(f" QA Tests Failed:  {flow.state.qa_report.tests_failed}")
        print(f" Bugs Identified:  {len(flow.state.qa_report.bugs)}")

    if flow.state.status == "SUCCESS":
        print("\n [SUCCESS] The application was built and signed off by the Orchestrator.")
        print(f" Backend path:  {latest_run_dir / 'backend'}")
        print(f" Frontend path: {latest_run_dir / 'frontend'}")
        print("\n To run the generated application:")
        print(f"   cd {latest_run_dir / 'backend'}")
        print("   uvicorn main:app --reload --port 8000")
        print(f"   Then open {latest_run_dir / 'frontend' / 'index.html'} in your browser.\n")
    else:
        print("\n [NOTICE] Flow stopped with unresolved issues:")
        for issue in flow.state.unresolved_issues:
            print(f"   - {issue}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
