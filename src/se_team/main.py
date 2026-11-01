"""
Main entry point for running the multi-agent software engineering team.
CLI interface supporting custom project briefs, configurable rounds, and Gemini backend.
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

DEFAULT_BRIEF = (
    "A small web app with a discount calculator: user enters price and discount percent, "
    "the backend computes the final price and saves history, the frontend shows the result "
    "and the last 10 calculations."
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
        description="Multi-Agent Software Engineering Team powered by CrewAI Flows & Google Gemini"
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

    swu_key = os.getenv("SWU_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    has_valid_key = (
        (swu_key and swu_key != "your_swu_token_here") or
        (openrouter_key and openrouter_key != "your_openrouter_api_key_here") or
        (gemini_key and gemini_key != "your_gemini_api_key_here")
    )

    if not has_valid_key:
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
    print(" Multi-Agent Software Engineering Team (CrewAI Flows + Gemini)")
    print("=" * 65)
    print(f" Brief: {args.brief}")
    print(f" Max Rounds: {args.max_rounds or os.getenv('MAX_ROUNDS', '3')}")
    print(f" Workspace Root: {args.workspace}")
    print(f" Orchestrator Model: {os.getenv('ORCHESTRATOR_MODEL', 'gemini/gemini-2.5-pro')}")
    print(f" Frontend Model:     {os.getenv('FRONTEND_MODEL', 'gemini/gemini-2.5-flash')}")
    print(f" Backend Model:      {os.getenv('BACKEND_MODEL', 'gemini/gemini-2.5-flash')}")
    print(f" QA Model:           {os.getenv('QA_MODEL', 'gemini/gemini-2.5-pro')}")
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
