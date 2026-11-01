# Office performance changes

Existing websites remain in `websites/<project>/`. This change does not rebuild or
modify a website by itself. Subsequent commands use the optimized pipeline.

## Work routing

- Existing projects use a small `EditDecision`: work orders, affected paths and verification scope.
  The saved specification/API/schema are reused exactly. A contract change explicitly requests
  full planning; first builds still produce a complete specification.
- The supervisor receives a source inventory and a bounded conversation, not all source code.
  Builders receive selected files and the shared API contract. Missing source can be fetched
  through a validated `need_files` response, once per work order.
- Existing-file changes normally use exact search/replace edits. Preconditions and optional
  SHA256 hashes are checked for the entire proposal before writes. New files/full rewrites
  remain available when needed. Python syntax and role/path boundaries are validated locally.
- Frontend/backend run concurrently only when the supervisor's contract and batches permit.
  Adding agents to an already small edit would add handoffs and model calls.

## Antigravity transport

The default uses the available Gemini 3.8 Flash Low/Medium slugs with matching effort.
Planning small edits, cosmetic frontend changes and evidence summaries use Low. Initial/full
planning, functional frontend work, backend and test authoring use Medium. Explicit per-role
or global model/effort settings take precedence. No automatic switch to another provider occurs.
Global CLI settings, account credentials and credit/overage settings are not modified.

Per-session CLI settings deny filesystem, shell, browser and MCP tools: these jobs return
proposals using attached source; the host owns writes/tests. Slash-command expansion is
disabled. Internal structured completion remains available. Text deltas are deduplicated into
lifecycle events, with bounded progress notices. A terminal result ends the read loop immediately;
a lingering CLI is closed instead of waiting until the job timeout.

The job timeout is still bounded (600 seconds by default). Raising it is not the optimization.
Timing, input character counts, configured model/effort and provider-reported token counts are
recorded per task. The Office UI displays actual task times, including running elapsed time.
Old duplicate ACTIVE notifications are compacted; chats, work results and test evidence remain.

## Verification without unnecessary regeneration

Cosmetic/copy edits with an existing test suite reuse it, followed by a compact QA evidence
review. Production changes outside `.css`, `.html`, `.svg` force full QA even if the planner
requested the cheaper path. New behavior/authentication/API/data changes require full QA.
Correction rounds rerun the existing reproducing tests instead of regenerating them each time.
QA receives measured pytest counts and one bounded output excerpt, not three copies of stdout.
No tests or skipped-only tests cannot establish readiness. Missing browser/manual evidence
remains `needs_attention`; another model call cannot manufacture that evidence.

## Measurements (1 November 2026)

- Live synthetic CSS edit, using invented source only: supervisor 11.76s, frontend 12.17s,
  pytest plus QA review 9.37s; total 33.30s. Only the CSS changed. Its one regression test passed;
  unrelated unverified criteria correctly kept delivery status at `needs_attention`.
- Local prompt construction for a one-file CSS edit against the real website, with transport
  mocked (no transmission or source writes): planner 24,154 characters; frontend 31,272.
  The previous failed frontend job logged 211,397 characters. This is 85.2% less input text
  for the sampled CSS edit; the instructions/tasks differ, so this is not a controlled latency
  comparison or a guarantee about future jobs.
- The real website's existing 125 tests passed locally using isolated temporary test data.

Details are in local `workspace/office/performance-check.json` and `context-check.json`.
The live experiment deliberately used synthetic source. Automatic approval review rejected a
proposed experiment transmitting the real website source; that experiment was not run.
