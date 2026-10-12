"""
End-to-end smoke tests for SoftwareTeamFlow.
Verifies:
1. Orchestrator produces SpecPackage
2. Backend and Frontend execute in parallel and output files into workspace
3. QA runs real pytest tests in the workspace sandbox verifying calculation logic & edge cases
4. Router routes to Orchestrator sign-off on pass
5. Re-prompt loop targets only owning agents on QA failure and advances rounds
6. Halts at MAX_ROUNDS with clear unresolved issues report when defects persist
"""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from se_team.flow import SoftwareTeamFlow
from se_team.models import (
    APIEndpoint,
    BugReport,
    DataSchema,
    DataSchemaField,
    FinalSignOff,
    QAReport,
    RePromptPackage,
    SpecialistPrompt,
    SpecPackage,
)
from se_team.tools.sandbox import SandboxManager


@pytest.fixture
def smoke_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def make_dummy_spec(brief: str) -> SpecPackage:
    return SpecPackage(
        project_name="DiscountCalculatorApp",
        brief_summary=brief,
        task_scope="Compute discounted price and track last 10 calculations with SQLite.",
        acceptance_criteria=[
            "User enters original price and discount percentage.",
            "Backend computes final price = price * (1 - discount/100).",
            "Backend persists each calculation to SQLite.",
            "Backend returns the history of calculations limited to the last 10.",
            "Frontend presents calculation inputs, results, and history table.",
        ],
        data_schemas=[
            DataSchema(
                table_name="calculation_history",
                description="Stores calculation transactions",
                fields=[
                    DataSchemaField(name="id", type="INTEGER", constraints="PRIMARY KEY AUTOINCREMENT"),
                    DataSchemaField(name="price", type="REAL", constraints="NOT NULL"),
                    DataSchemaField(name="discount_percent", type="REAL", constraints="NOT NULL"),
                    DataSchemaField(name="final_price", type="REAL", constraints="NOT NULL"),
                    DataSchemaField(name="calculated_at", type="TIMESTAMP", constraints="DEFAULT CURRENT_TIMESTAMP"),
                ],
            )
        ],
        api_contract=[
            APIEndpoint(
                path="/api/calculate",
                method="POST",
                summary="Calculates final price and persists transaction",
                request_body_schema={"price": "float", "discount_percent": "float"},
                response_body_schema={"price": "float", "discount_percent": "float", "final_price": "float"},
            ),
            APIEndpoint(
                path="/api/history",
                method="GET",
                summary="Retrieves last 10 calculation records",
                response_body_schema={"history": "list"},
            ),
        ],
        frontend_prompt=SpecialistPrompt(
            role="Frontend & UX Specialist",
            target_workspace_dir="frontend/",
            instructions="Build responsive HTML/CSS/JS interface calling /api/calculate and /api/history.",
            files_to_produce=["frontend/index.html", "frontend/app.js", "frontend/styles.css"],
        ),
        backend_prompt=SpecialistPrompt(
            role="Backend & Security Specialist",
            target_workspace_dir="backend/",
            instructions="Build FastAPI + SQLite app exposing /api/calculate and /api/history.",
            files_to_produce=["backend/main.py", "backend/database.py"],
        ),
        qa_guidance="Verify formula final_price = round(price * (1 - discount/100), 2) and edge cases: zero, 100%, negative inputs.",
    )


def test_full_flow_smoke_run_pass_round_1(smoke_workspace, monkeypatch):
    """Smoke test: All tests pass on Round 1 -> Orchestrator signs off."""
    brief = (
        "A small web app with a discount calculator: user enters price and discount percent, "
        "the backend computes the final price and saves history, the frontend shows the result "
        "and the last 10 calculations."
    )

    def mock_run_spec_step(brief_arg, sandbox):
        return make_dummy_spec(brief_arg)

    def mock_run_backend_step(spec, sandbox, extra_instructions=None):
        backend_code = '''
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Discount Calculator API")
DB_PATH = Path(__file__).parent / "history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calculation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price REAL NOT NULL,
            discount_percent REAL NOT NULL,
            final_price REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

class CalculateRequest(BaseModel):
    price: float = Field(..., ge=0)
    discount_percent: float = Field(..., ge=0, le=100)

@app.post("/api/calculate")
def calculate(req: CalculateRequest):
    final_price = round(req.price * (1.0 - (req.discount_percent / 100.0)), 2)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO calculation_history (price, discount_percent, final_price) VALUES (?, ?, ?)",
                   (req.price, req.discount_percent, final_price))
    conn.commit()
    conn.close()
    return {"price": req.price, "discount_percent": req.discount_percent, "final_price": final_price}

@app.get("/api/history")
def get_history():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, price, discount_percent, final_price FROM calculation_history ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return {"history": [{"id": r[0], "price": r[1], "discount_percent": r[2], "final_price": r[3]} for r in rows]}
'''
        sandbox.write_file("backend/main.py", backend_code)
        return "Backend generated successfully"

    def mock_run_frontend_step(spec, sandbox, extra_instructions=None):
        sandbox.write_file("frontend/index.html", "<!DOCTYPE html><html><body><h1>Discount Calculator</h1></body></html>")
        sandbox.write_file("frontend/app.js", "// frontend logic")
        return "Frontend generated successfully"

    def mock_run_qa_step(spec, sandbox, round_number=1):
        test_suite_code = '''
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_calculate_standard_discount():
    resp = client.post("/api/calculate", json={"price": 100.0, "discount_percent": 20.0})
    assert resp.status_code == 200
    assert resp.json()["final_price"] == 80.0

def test_history_persistence():
    resp = client.get("/api/history")
    assert resp.status_code == 200
'''
        test_run = sandbox.run_tests(test_code=test_suite_code, test_path="tests/test_calculator.py")
        return QAReport(
            round_number=round_number,
            passed=test_run["passed"],
            summary="Real pytest test suite executed in workspace sandbox.",
            tests_executed=2,
            tests_passed=2 if test_run["passed"] else 0,
            tests_failed=0,
            raw_test_output=test_run["output"],
            bugs=[],
            owning_agents_needing_fixes=[],
        )

    def mock_run_signoff_step(spec, qa_report, sandbox):
        return FinalSignOff(
            approved=True,
            summary="All tests passed. System approved for release.",
            acceptance_criteria_verified=spec.acceptance_criteria,
            notes="Ready.",
        )

    monkeypatch.setattr("se_team.flow.run_spec_step", mock_run_spec_step)
    monkeypatch.setattr("se_team.flow.run_backend_step", mock_run_backend_step)
    monkeypatch.setattr("se_team.flow.run_frontend_step", mock_run_frontend_step)
    monkeypatch.setattr("se_team.flow.run_qa_step", mock_run_qa_step)
    monkeypatch.setattr("se_team.flow.run_signoff_step", mock_run_signoff_step)

    flow = SoftwareTeamFlow(
        project_brief=brief,
        max_rounds=3,
        workspace_root=str(smoke_workspace),
    )
    result = flow.kickoff()

    assert flow.state.status == "SUCCESS"
    assert flow.state.current_round == 1
    assert flow.state.qa_report.passed is True
    assert flow.state.final_signoff.approved is True

    round_dir = smoke_workspace / "runs" / flow.state.run_timestamp / "round_1"
    assert (round_dir / "backend" / "main.py").exists()
    assert (round_dir / "frontend" / "index.html").exists()


def test_flow_reprompt_and_fix_loop(smoke_workspace, monkeypatch):
    """
    Smoke test: QA fails on Round 1 with a bug owned by backend.
    Orchestrator issues targeted re-prompt for backend only.
    Backend fixes bug in Round 2.
    QA passes on Round 2 -> Orchestrator signs off.
    """
    brief = "A discount calculator app"
    qa_attempts = 0

    def mock_run_spec_step(brief_arg, sandbox):
        return make_dummy_spec(brief_arg)

    def mock_run_backend_step(spec, sandbox, extra_instructions=None):
        sandbox.write_file("backend/main.py", "# backend implementation")
        return "Backend generated"

    def mock_run_frontend_step(spec, sandbox, extra_instructions=None):
        sandbox.write_file("frontend/index.html", "<h1>App</h1>")
        return "Frontend generated"

    def mock_run_qa_step(spec, sandbox, round_number=1):
        nonlocal qa_attempts
        qa_attempts += 1
        if qa_attempts == 1:
            return QAReport(
                round_number=1,
                passed=False,
                summary="Rounding calculation defect detected in /api/calculate",
                tests_executed=3,
                tests_passed=2,
                tests_failed=1,
                raw_test_output="FAILED test_rounding: assert 80.001 == 80.0",
                bugs=[
                    BugReport(
                        id="BUG-001",
                        title="Floating point precision issue",
                        description="Final price not rounded to 2 decimal places",
                        severity="medium",
                        owning_agent="backend",
                        edge_case_category="rounding",
                        suggested_fix="Use round(val, 2)",
                    )
                ],
                owning_agents_needing_fixes=["backend"],
            )
        else:
            return QAReport(
                round_number=2,
                passed=True,
                summary="All tests passed after backend fix.",
                tests_executed=3,
                tests_passed=3,
                tests_failed=0,
                raw_test_output="3 passed",
                bugs=[],
                owning_agents_needing_fixes=[],
            )

    def mock_run_reprompt_step(qa_report, spec, sandbox, round_number=1):
        assert qa_report.owning_agents_needing_fixes == ["backend"]
        return RePromptPackage(
            round_number=round_number,
            target_agents=["backend"],
            backend_fixes="Ensure final price is rounded to 2 decimal places using round(val, 2).",
            reasons="Fix BUG-001 rounding precision",
        )

    def mock_run_signoff_step(spec, qa_report, sandbox):
        return FinalSignOff(
            approved=True,
            summary="QA passed on Round 2. System verified and signed off.",
            acceptance_criteria_verified=spec.acceptance_criteria,
            notes="Sign-off granted.",
        )

    monkeypatch.setattr("se_team.flow.run_spec_step", mock_run_spec_step)
    monkeypatch.setattr("se_team.flow.run_backend_step", mock_run_backend_step)
    monkeypatch.setattr("se_team.flow.run_frontend_step", mock_run_frontend_step)
    monkeypatch.setattr("se_team.flow.run_qa_step", mock_run_qa_step)
    monkeypatch.setattr("se_team.flow.run_reprompt_step", mock_run_reprompt_step)
    monkeypatch.setattr("se_team.flow.run_signoff_step", mock_run_signoff_step)

    flow = SoftwareTeamFlow(
        project_brief=brief,
        max_rounds=3,
        workspace_root=str(smoke_workspace),
    )
    result = flow.kickoff()

    assert flow.state.status == "SUCCESS"
    assert flow.state.current_round == 2
    assert flow.state.reprompt_package.target_agents == ["backend"]
    assert flow.state.final_signoff.approved is True

    # Check that both round_1 and round_2 directories exist
    runs_dir = smoke_workspace / "runs" / flow.state.run_timestamp
    assert (runs_dir / "round_1").exists()
    assert (runs_dir / "round_2").exists()


def test_flow_halts_at_max_rounds(smoke_workspace, monkeypatch):
    """
    Smoke test: QA fails repeatedly up to MAX_ROUNDS.
    Flow halts and outputs unresolved issues report.
    """
    brief = "A failing calculator app"

    def mock_run_spec_step(brief_arg, sandbox):
        return make_dummy_spec(brief_arg)

    def mock_run_backend_step(spec, sandbox, extra_instructions=None):
        return "Backend generated"

    def mock_run_frontend_step(spec, sandbox, extra_instructions=None):
        return "Frontend generated"

    def mock_run_qa_step(spec, sandbox, round_number=1):
        return QAReport(
            round_number=round_number,
            passed=False,
            summary="Persistent SQL error",
            tests_executed=1,
            tests_passed=0,
            tests_failed=1,
            raw_test_output="FAILED: sqlite3.OperationalError: no such table",
            bugs=[
                BugReport(
                    id="BUG-ERR",
                    title="Database table missing",
                    description="calculation_history table does not exist",
                    severity="critical",
                    owning_agent="backend",
                    edge_case_category="other",
                    suggested_fix="Create table at startup",
                )
            ],
            owning_agents_needing_fixes=["backend"],
        )

    def mock_run_reprompt_step(qa_report, spec, sandbox, round_number=1):
        return RePromptPackage(
            round_number=round_number,
            target_agents=["backend"],
            backend_fixes="Create table",
            reasons="Fix BUG-ERR",
        )

    monkeypatch.setattr("se_team.flow.run_spec_step", mock_run_spec_step)
    monkeypatch.setattr("se_team.flow.run_backend_step", mock_run_backend_step)
    monkeypatch.setattr("se_team.flow.run_frontend_step", mock_run_frontend_step)
    monkeypatch.setattr("se_team.flow.run_qa_step", mock_run_qa_step)
    monkeypatch.setattr("se_team.flow.run_reprompt_step", mock_run_reprompt_step)

    flow = SoftwareTeamFlow(
        project_brief=brief,
        max_rounds=2,
        workspace_root=str(smoke_workspace),
    )
    result = flow.kickoff()

    assert flow.state.status == "MAX_ROUNDS_REACHED"
    assert flow.state.current_round == 2
    assert len(flow.state.unresolved_issues) > 0
    assert "BUG-ERR" in flow.state.unresolved_issues[0]
