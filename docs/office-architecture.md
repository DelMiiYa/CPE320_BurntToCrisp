# Local Agent Office

Office is a local FastAPI application layered over the existing role-specific Codex
runner. It adds project continuity and observability rather than replacing the
user's Codex authentication or making model inference offline.

## Request lifecycle

1. A project stores its original brief and durable conversation in SQLite.
2. A message is committed as a queued command before work begins. A single worker
   atomically claims commands in order, avoiding conflicting edits to the same source.
3. The supervisor receives the previous complete specification, the current source,
   the project brief, the last 30 messages, and the latest instruction.
4. A discussion returns a reply without replacing the latest website. A build creates
   a work-log row and dispatches affected specialists into the same stable folder.
   Every project has one readable directory: `websites/<project-name>/`.
5. Independent QA authors tests. The host executes pytest with temporary APP_DATA_DIR;
   measured counts override the model's claims. Reproduced defects return to their
   owners within a bounded correction loop. Missing browser/manual evidence does not
   create fictional builder defects; it returns to the supervisor as a review gap.
6. A short final decision, test counts, changed paths, line counts and hashes are
   persisted. Source baselines exist only in memory; no source copies or full diffs
   are retained. Failures/cancellations keep partial changes in the current folder.
7. A separate preview process serves generated FastAPI API routes and static frontend
   on one origin. APP_DATA_DIR is `websites/<project-name>/data/`. Tests use temporary
   data. Preview stops before builds and restarts afterward; only its latest log remains.
8. Legacy storage is migrated on startup while the worker is stopped. The latest
   website and user data are moved and hash-checked before deleting old snapshots.
   Historical specifications, full diffs, raw pytest output and model artifacts are
   discarded; the current project spec and conversations remain.

## Observable activity

`crew/job_events.py` provides context-local callbacks and cancellation. `codex_runtime`
uses the CLI's public JSONL lifecycle events while Office runs. Public start/finish,
file handoffs and real test results become durable events. Private reasoning is not
stored. The browser consumes Server-Sent Events with an event cursor and can recover
missed updates from SQLite. A slower state refresh is a reconnect fallback.

Office character positions depend on current tasks: a working agent moves to its
workstation and returns when the job finishes. Idle animation never generates events
or fabricates task activity. Names are interface personas for role-specific Codex jobs.

## Boundaries

- Office binds only to 127.0.0.1. Host/origin checks and per-process request tokens
  protect mutating control endpoints. No CORS access is granted to generated apps.
- Generated pages run on a separate port in a sandboxed iframe. Opening a preview
  switches the single preview process and always serves the current working folder.
- File browsing is scoped through stored project IDs and a source allowlist.
  Proposed source paths must belong to the assigned specialist. Only generated source
  is handed to Codex, not the project's .env or stored credentials.
- Generated Python and tests execute locally. This is a private developer tool, not
  an isolation service for arbitrary untrusted users. There is no public deployment.
- Stopping cancels queued commands and terminates active Codex subprocesses. Already
  running pytest has its own timeout. Restart recovery marks interrupted work explicitly.
- Product data migrations remain the backend agent's responsibility when a requested
  edit changes schema. Current source and runtime user data have separate lifecycles.

## Verification

Tests cover durable requests, in-place edits, compact history, hash-verified migration, targeted changes, project/file
boundaries, origin/token protection, interruption recovery, genuine QA counts,
conversation-only replies, source failures, history export and preview routing.
Browser checks exercise project creation, chat submission, live state, queueing,
refresh continuity and opening the generated website.
