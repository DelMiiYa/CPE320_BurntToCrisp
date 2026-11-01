"""Verify Google Antigravity runtime, backend routing, structured output and error handling."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError
from fastapi.testclient import TestClient

from se_team.crew import antigravity_runtime as runtime
from se_team.crew import crew
from se_team.crew.runtime import (
    AntigravityUsageLimit,
    ProviderUsageLimit,
    get_backend,
    uses_antigravity,
    uses_codex,
)
from se_team.models import FinalSignOff, QAReport, RePromptPackage, SpecPackage
from se_team.office.server import create_app
from se_team.tools.sandbox import SandboxManager
from tests.test_flow_smoke import make_dummy_spec


@pytest.fixture
def sandbox(tmp_path):
    return SandboxManager(tmp_path)


def test_default_backend_is_antigravity(monkeypatch, sandbox):
    monkeypatch.delenv("AGENT_BACKEND", raising=False)
    assert get_backend() == "antigravity"
    assert uses_antigravity() is True
    assert uses_codex() is False


def test_default_antigravity_ignores_old_swu_key(monkeypatch, sandbox):
    monkeypatch.delenv("AGENT_BACKEND", raising=False)
    monkeypatch.setenv("SWU_API_KEY", "stale-swu-value")
    expected = make_dummy_spec("calculator")
    monkeypatch.setattr(runtime, "run_spec_step", lambda brief, box: expected)
    monkeypatch.setattr(crew, "create_orchestrator_agent", lambda *a: pytest.fail("legacy provider invoked"))
    assert crew.run_spec_step("calculator", sandbox) is expected


def test_backend_selection_values(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "antigravity")
    assert uses_antigravity() is True
    assert uses_codex() is False

    monkeypatch.setenv("AGENT_BACKEND", "codex")
    assert uses_antigravity() is False
    assert uses_codex() is True

    monkeypatch.setenv("AGENT_BACKEND", "unknown_backend")
    with pytest.raises(ValueError, match="AGENT_BACKEND must be"):
        get_backend()


def test_antigravity_binary_resolution(monkeypatch):
    monkeypatch.setenv("AGY_BIN", "/custom/bin/agy")
    monkeypatch.setattr(runtime.shutil, "which", lambda cmd: "/custom/bin/agy" if cmd == "/custom/bin/agy" else None)
    assert runtime.antigravity_binary() == "/custom/bin/agy"


def test_antigravity_binary_not_found(monkeypatch):
    monkeypatch.setenv("AGY_BIN", "nonexistent_agy_binary")
    monkeypatch.setattr(runtime.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(runtime.Path, "is_file", lambda self: False)
    with pytest.raises(RuntimeError, match="Antigravity CLI \\(agy\\) was not found"):
        runtime.antigravity_binary()


def test_antigravity_subprocess_contract_json_mode(monkeypatch, sandbox):
    class Reply(BaseModel):
        ok: bool
        message: str

    def fake_run(command, **kwargs):
        assert "agy" in command[0]
        assert "--output-format" in command
        assert "--json-schema" in command
        assert "--print-timeout" in command
        assert kwargs["input"] and kwargs["timeout"] > 0
        payload = {
            "conversation_id": "test-123",
            "status": "SUCCESS",
            "structured_output": {"ok": True, "message": "Antigravity works"},
            "response": '{"ok": true, "message": "Antigravity works"}',
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(runtime, "antigravity_binary", lambda: "/fake/agy")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    result = runtime.run_job("orchestrator", "orchestrator_spec_task", {"project_brief": "test"}, Reply, sandbox)
    assert result.ok is True
    assert result.message == "Antigravity works"
    assert json.loads(sandbox.read_file("artifacts/orchestrator_spec_task.json")) == {"ok": True, "message": "Antigravity works"}


def test_antigravity_stream_process_contract(monkeypatch, sandbox):
    class Reply(BaseModel):
        ok: bool

    stream_lines = [
        '{"event":"init","conversation_id":"c1","init":{"tools":[]}}\n',
        '{"event":"step_update","step_update":{"state":"ACTIVE","step_type":"agent_response"}}\n',
        '{"event":"step_update","step_update":{"state":"DONE","step_type":"agent_response","usage":{"total_tokens":50}}}\n',
        '{"event":"result","result":{"status":"SUCCESS","structured_output":{"ok":true},"response":"{\\"ok\\":true}"}}\n',
    ]

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self.stdin = SimpleNamespace(write=lambda s: None, close=lambda: None)
            self.stdout = stream_lines
            self.stderr = []
            self.pid = 9999

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(runtime, "antigravity_binary", lambda: "/fake/agy")
    monkeypatch.setattr(runtime.subprocess, "Popen", FakeProcess)

    events_emitted = []
    from se_team.crew.job_events import bind_job
    import threading

    def record_emit(kind, data):
        events_emitted.append((kind, data))

    with bind_job(record_emit, threading.Event()):
        result = runtime.run_job("orchestrator", "orchestrator_spec_task", {"project_brief": "test"}, Reply, sandbox)

    assert result.ok is True
    assert any(ev == "agent.progress" and data.get("phase") == "turn.started" for ev, data in events_emitted)
    assert any(ev == "agent.progress" and data.get("phase") == "turn.completed" for ev, data in events_emitted)


@pytest.mark.parametrize("phrase", [
    "hit your usage limit",
    "usage limit reached",
    "quota exceeded",
    "resource has been exhausted",
    "resource_exhausted",
    "rate limit exceeded",
    "credit balance is too low",
    "insufficient quota",
    "too many requests",
])
def test_antigravity_usage_limit_detection(monkeypatch, sandbox, phrase):
    class Reply(BaseModel):
        ok: bool

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"Error: {phrase}. Please try again later.",
        )

    monkeypatch.setattr(runtime, "antigravity_binary", lambda: "/fake/agy")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    with pytest.raises(AntigravityUsageLimit) as exc_info:
        runtime.run_job("orchestrator", "orchestrator_spec_task", {"project_brief": "test"}, Reply, sandbox)
    assert issubclass(AntigravityUsageLimit, ProviderUsageLimit)
    assert phrase in str(exc_info.value).lower()


@pytest.mark.parametrize("failure", ["exit", "missing", "invalid", "timeout"])
def test_antigravity_failed_or_invalid_result_is_not_accepted(monkeypatch, sandbox, failure):
    class Reply(BaseModel):
        ok: bool

    def fake_run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if failure == "invalid":
            payload = {"status": "SUCCESS", "structured_output": {"invalid_field": 123}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        if failure == "missing":
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Internal agent error")

    monkeypatch.setattr(runtime, "antigravity_binary", lambda: "/fake/agy")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    with pytest.raises((RuntimeError, ValidationError)):
        runtime.run_job("orchestrator", "orchestrator_spec_task", {"project_brief": "test"}, Reply, sandbox)


def test_antigravity_bundle_validates_ownership_and_paths(sandbox):
    bundle = runtime.FileBundle(summary="bad", files=[
        runtime.ProposedFile(path="frontend/index.html", content="allowed"),
        runtime.ProposedFile(path="backend/main.py", content="wrong specialist"),
    ])
    with pytest.raises(ValueError, match="cannot write"):
        runtime.apply_bundle(bundle, "frontend", sandbox)
    assert not sandbox.validate_path("frontend/index.html").exists()

    for escape_path in ("../outside.py", "frontend/../../etc/passwd"):
        with pytest.raises(ValueError):
            runtime.apply_bundle(
                runtime.FileBundle(summary="bad", files=[runtime.ProposedFile(path=escape_path, content="x")]),
                "frontend",
                sandbox,
            )

    qa_conftest = runtime.FileBundle(summary="bad", files=[runtime.ProposedFile(path="tests/conftest.py", content="x")])
    with pytest.raises(ValueError, match="QA may propose Python test files"):
        runtime.apply_bundle(qa_conftest, "tests", sandbox)


def test_antigravity_qa_measured_facts_override_model_claims(monkeypatch, sandbox):
    spec = make_dummy_spec("calculator")
    bundle = runtime.FileBundle(summary="one test", files=[runtime.ProposedFile(
        path="tests/test_calc.py", content="def test_fail():\n    assert 1 == 0\n",
    )])

    def fake_job(role, task, values, output, box):
        if task == "qa_verification_task":
            return bundle
        return QAReport(passed=True, summary="claims pass falsely", tests_executed=100, tests_passed=100)

    monkeypatch.setattr(runtime, "run_job", fake_job)
    report = runtime.run_qa_step(spec, sandbox)
    assert not report.passed
    assert report.tests_executed == 1 and report.tests_failed == 1 and report.tests_passed == 0
    assert "assert 1 == 0" in report.raw_test_output
    assert report.bugs and report.owning_agents_needing_fixes


def test_office_bootstrap_and_provider_status_shows_antigravity(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_BACKEND", raising=False)
    monkeypatch.setattr("se_team.crew.runtime.antigravity_runtime.check_antigravity_login", lambda: None)
    app = create_app(tmp_path / "office", start_worker=False)
    with TestClient(app) as client:
        boot = client.get("/office-api/bootstrap").json()
        assert boot["backend"] == "antigravity"
        assert boot["provider_name"] == "Google Antigravity"

        prov = client.get("/office-api/provider").json()
        assert prov["ready"] is True
        assert "Google Antigravity" in prov["message"]

        codex_compat = client.get("/office-api/codex").json()
        assert codex_compat["ready"] is True
        assert "Google Antigravity" in codex_compat["message"]
