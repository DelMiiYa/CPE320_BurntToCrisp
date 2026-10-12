# Multi-Agent Software Engineering Team (SE-Agent-Team)

A multi-agent software engineering team built with **CrewAI Flows** and **Google Gemini** models. The team automatically transforms plain-language product briefs (in English or Thai) into functioning full-stack web applications backed by SQLite and FastAPI, complete with real automated test verification and targeted corrective feedback loops.

---

## Architecture & Team Design

The team consists of 4 specialized agents coordinated via a CrewAI Flow:

1. **Orchestrator & Product Lead**
   - **Role**: Translates user briefs into a formal `SpecPackage` containing task scope, acceptance criteria, SQLite data schemas, REST API contract, and specialist instructions.
   - **Re-Prompt**: On QA failures, analyzes the `QAReport` and formulates targeted instructions only for the agents responsible for the bugs. Gives final sign-off upon test success.
   - **Tools**: Read-only (`read_file`, `list_files`).

2. **Frontend & UX Specialist**
   - **Role**: Builds pure HTML5/CSS3/JavaScript user interfaces (no build step required) adhering strictly to the API contract.
   - **Output**: Writes all files to `workspace/runs/<timestamp>/round_N/frontend/`.
   - **Tools**: Builder tools (`write_file`, `read_file`, `list_files`).

3. **Backend & Security Specialist**
   - **Role**: Implements the REST API and data layer with FastAPI and SQLite according to data schemas and API contracts. Implements input validation, error handling, CORS, and SQL injection protection.
   - **Output**: Writes all files to `workspace/runs/<timestamp>/round_N/backend/`.
   - **Tools**: Builder tools (`write_file`, `read_file`, `list_files`).

4. **QA & Logic Verifier**
   - **Role**: Formulates and runs pytest test suites directly within the workspace sandbox. Empirically verifies calculation formulas, boundary conditions (zero, negative, huge values, rounding), bad inputs, and API contract fidelity. Produces structured `QAReport`.
   - **Tools**: Sandboxed test execution (`run_tests` running pytest only with timeout).

---

## Workflow Diagram

```text
       +---------------------------------------------+
       |           User Project Brief                |
       |      (Thai or English plain text)           |
       +---------------------------------------------+
                              |
                              v
       +---------------------------------------------+
       |       Orchestrator & Product Lead           |
       |          Produces: SpecPackage              |
       +---------------------------------------------+
                              |
              +---------------+---------------+
              |                               |
              v (Async / Parallel)            v (Async / Parallel)
   +-----------------------+     +-----------------------+
   |  Frontend Specialist  |     |  Backend Specialist   |
   |   (HTML / CSS / JS)   |     |   (FastAPI + SQLite)  |
   +-----------------------+     +-----------------------+
              |                               |
              +---------------+---------------+
                              |
                              v
       +---------------------------------------------+
       |             QA & Logic Verifier             |
       |   Runs real pytest in workspace sandbox     |
       |            Produces: QAReport               |
       +---------------------------------------------+
                              |
                              v
                      [ Router Decision ]
                     /         |         \
                    /          |          \
       (Passed)    /  (Failed & < MAX)     \  (Failed & >= MAX)
                  v            |            v
   +-----------------------+   |   +-----------------------+
   |     Orchestrator      |   |   |   Halt & Report       |
   |    Final Sign-off     |   |   |   Unresolved Issues   |
   +-----------------------+   |   +-----------------------+
                               v
               +-------------------------------+
               |   Orchestrator Re-Prompt      |
               | Targets ONLY Owning Agents    |
               +-------------------------------+
                               |
                               +---> [ Re-run targeted builders -> QA ]
```

---

## Repository Structure

```text
se-agent-team/
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules (.env, .venv, workspace/, etc.)
├── README.md                 # Project documentation and guide
├── requirements.txt          # Pinned Python package dependencies
├── src/
│   └── se_team/
│       ├── __init__.py       # Package marker
│       ├── main.py           # CLI entry point
│       ├── flow.py           # CrewAI Flow state machine & routing
│       ├── models.py         # Pydantic schemas (SpecPackage, QAReport, BugReport)
│       ├── crew/
│       │   ├── __init__.py   # Crew exports
│       │   ├── agents.yaml   # Agent definitions & backstories
│       │   ├── tasks.yaml    # Task templates & expected outputs
│       │   └── crew.py       # LLM instantiation, rate-limit backoff & agents
│       └── tools/
│           ├── __init__.py   # Tool exports
│           └── sandbox.py    # Sandboxed file operations & pytest execution
├── tests/
│   ├── __init__.py           # Tests marker
│   ├── test_sandbox.py       # Unit tests for sandbox path isolation & security
│   └── test_flow_smoke.py    # End-to-end smoke test for Flow states & loops
└── workspace/                # Git-ignored run outputs (runs/<timestamp>/round_N/)
```

---

## Setup & Installation

### 1. Requirements
- Python 3.10 to 3.13 (Verified on Python 3.13.0)
- Git

### 2. Virtual Environment Setup
```powershell
# From the se-agent-team directory:
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install pinned dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```

Configure `.env` with your Google AI Studio Gemini API key:
```ini
# Google Gemini API Key (Obtain from https://aistudio.google.com)
GEMINI_API_KEY=AIzaSy...

# Agent Model Assignments (CrewAI / LiteLLM format)
ORCHESTRATOR_MODEL=gemini/gemini-2.5-pro
FRONTEND_MODEL=gemini/gemini-2.5-flash
BACKEND_MODEL=gemini/gemini-2.5-flash
QA_MODEL=gemini/gemini-2.5-pro

# Maximum QA-Fix feedback loop iterations
MAX_ROUNDS=3
```

---

## How to Run the Flow

### 1. Default Run (Discount Calculator)
```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe src/se_team/main.py
```

### 2. Custom Brief & Options
```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe src/se_team/main.py `
    --brief "A small web app for currency conversion with live exchange rate mockup and history" `
    --max-rounds 3
```

### 3. Running Test Suites
```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m pytest -v tests/
```

---

## Sandboxed Security Design
All agent file operations are strictly restricted to the active workspace directory (`workspace/runs/<timestamp>/round_N/`):
- Any attempt to access outside paths (`../`, absolute paths, symlinks) raises a `ValueError` security violation.
- Pytest execution runs strictly inside the workspace without shell execution (`shell=False`).
- Role-based tool access is strictly enforced:
  - Orchestrator: `[read_file, list_files]`
  - Builders (Frontend, Backend): `[write_file, read_file, list_files]`
  - QA Verifier: `[run_tests, read_file, list_files]`

---

## Gemini Free-Tier Rate Limit Handling
Gemini free API limits (15 RPM) are handled gracefully:
- Automated exponential backoff retry mechanism (up to 4 attempts: 8s, 16s, 24s backoff).
- Clear, actionable user messages when quotas are temporarily exhausted, preventing unhandled crash traces.
