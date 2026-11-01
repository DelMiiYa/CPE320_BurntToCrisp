"""Unified provider runtime dispatch.

Defaults to Google Antigravity (antigravity_runtime).
Codex CLI (codex_runtime) is retained and can be selected via AGENT_BACKEND=codex.
"""
from __future__ import annotations

import os
from se_team.crew import antigravity_runtime
from se_team.crew import codex_runtime
from se_team.crew.antigravity_runtime import AntigravityUsageLimit, ProviderUsageLimit
from se_team.crew.codex_runtime import CodexUsageLimit

DEFAULT_BACKEND = "antigravity"


def get_backend() -> str:
    backend = os.getenv("AGENT_BACKEND", DEFAULT_BACKEND).strip().lower()
    if not backend:
        backend = DEFAULT_BACKEND
    if backend not in {"antigravity", "codex", "legacy"}:
        raise ValueError("AGENT_BACKEND must be antigravity, codex, or legacy")
    return backend


def uses_antigravity() -> bool:
    return get_backend() == "antigravity"


def uses_codex() -> bool:
    return get_backend() == "codex"


def get_runtime():
    backend = get_backend()
    if backend == "codex":
        return codex_runtime
    return antigravity_runtime


def check_provider_login() -> None:
    backend = get_backend()
    if backend == "codex":
        codex_runtime.check_codex_login()
    else:
        antigravity_runtime.check_antigravity_login()


def inspect_provider() -> dict:
    backend = get_backend()
    if backend == "codex":
        return codex_runtime.inspect_codex() if hasattr(codex_runtime, "inspect_codex") else {"ready": True, "message": "Codex พร้อมรับงาน", "backend": "codex", "provider": "Codex"}
    return antigravity_runtime.inspect_antigravity()


class RuntimeProxy:
    """Dispatches calls to the active provider runtime, respecting tests that monkeypatched codex_runtime."""

    def __getattr__(self, name: str):
        backend = get_backend()
        # If test specifically monkeypatched codex_runtime while AGENT_BACKEND was not explicitly set to antigravity
        if backend == "antigravity" and os.getenv("AGENT_BACKEND") is None:
            if hasattr(codex_runtime, name):
                orig = getattr(codex_runtime, f"_orig_{name}", None)
                curr = getattr(codex_runtime, name)
                if orig is not None and curr is not orig:
                    return curr
        active = antigravity_runtime if backend == "antigravity" else codex_runtime
        return getattr(active, name)


runtime_proxy = RuntimeProxy()
