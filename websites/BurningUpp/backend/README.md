# BurningUpp backend

ASGI entrypoint: `backend.main:app` from the website root (`websites/BurningUpp`). When the backend directory is on the Python import path, `main:app` also works. Both expose `app` and `create_app(data_dir=None)`. There are no local imports or import fallbacks. Importing initializes the database but never opens a listener. Use the host's ASGI runner with the appropriate entrypoint; this package does not invoke uvicorn or add a server dependency.

The target environment is Python 3.12.13, FastAPI 0.143.0 and Pydantic 2.12.5. Validation uses Pydantic V2 `ConfigDict`, `field_validator` and `ValidationInfo`; no Pydantic V1 API is used. Runtime dependencies are FastAPI and Pydantic plus the Python standard library, including SQLite. QA additionally uses httpx 0.28.1 and pytest 9.1.1. No email-validator, password library, async test plugin or additional dependency is required.

`create_app(data_dir=None)` constructs an independent application. An explicit `data_dir` overrides `APP_DATA_DIR`; otherwise `APP_DATA_DIR` is read on each factory call, falling back to `backend/data`. The database is `burningupp.sqlite3` inside that directory. Keep the same directory across application restarts to retain accounts, sessions, memberships, check-ins and follow-up tasks. The directory is created as needed. Schema initialization runs during factory construction, so httpx ASGITransport does not need to trigger lifespan. Initialization uses CREATE IF NOT EXISTS and preserves existing rows; there is no drop, reset or reseed. This is not a migration framework for incompatible existing schemas.

All connections enable foreign keys. Registering an organization, registering a member and creating a team commit related rows together. Check-ins use UNIQUE(user_id,date) and an atomic upsert. Organization and user scope come only from a hashed, expiring session. Owners can access all teams in their organization; other users need membership, and managers can manage only their teams. Unknown or inaccessible teams return 404; accessible resources with insufficient role return 403. A team code permits joining under the contract but never substitutes for authenticated resource authorization. Profile goals, journal notes and activity are returned only to the account owner.

Opaque cookies contain at least 32 random bytes; the database stores only SHA256 hashes. Sessions last seven days. Cookies are HttpOnly, SameSite=Lax, Path=/, and Secure for HTTPS requests. Passwords use PBKDF2-HMAC-SHA256 with random 16-byte salts, 600000 iterations and constant-time digest comparison. Password strings retain their original whitespace for hashing and login. Other payload strings are trimmed before strict type/length validation, emails are lowercased, and unknown payload fields are forbidden. Never expose the application directly through an untrusted forwarded Host/protocol configuration: deployment must pass the correct public scheme and host using trusted proxy settings.

The frontend is served through exact `/`, `/styles.css` and `/app.js` routes resolved relative to this source file. Unknown API paths remain 404; there is no catch-all route or cross-origin CORS middleware. Mutations reject supplied Origins that differ from the actual request origin, including logout; supplied bodies must use application/json. The confirmed contract requires same-origin hosting and supplies no cross-origin allowlist. The supplied frontend displays participation_rate directly, so an API value of 50 renders as 50%.

## Deterministic calculations

`app.state.clock` is a callable returning an aware datetime, defaulting to UTC system time. QA can replace it with a fixed or mutable clock. Bangkok date uses UTC+07:00. User-supplied dates never control writes. Mood is a strict integer from 0 through 4; bools, strings and fractional values are rejected.

Personal insight and team trend always compare today-6 through today with today-13 through today-7, inclusive, regardless of the requested history range. Each available eligible check-in contributes once, so days with more entries have proportionally more weight. Daily means are never averaged to obtain a period mean. Period means and delta are rounded to two decimal places in API responses using Python round; delta is calculated from the unrounded period means. Counts are actual entry counts. Empty means are null; delta is null unless both periods contain entries. Stored moods are unchanged. History defaults to the last 30 days, permits at most 366 inclusive days and rejects malformed, future or reversed ranges.

Dashboard returns all seven days from today-6 through today in ascending order. Current members are eligible on a day only when joined_on is on or before that day. Check-ins before joined_on do not contribute to team statistics or signals. The owner's manager membership is included. Daily participation is 100 * checkin_count / eligible_members, rounded to one decimal place, or null if there are no eligible members. Daily mean_mood is rounded to two decimal places, or null if there are no entries.

Follow-up candidates use the latest eligible check-in from joined_on through today for each current team member. `low_mood` applies only when that latest entry is today or yesterday and mood is 0 or 1. A newer mood of 2–4 removes that signal. `missing_3_days` applies when joined_on is on or before today-2 and there is no eligible entry from today-2 through today. People who joined today or yesterday are not flagged for missing three days. Pre-join and future entries do not count. Each candidate appears once, ordered by user_id, with only user_id, display_name and applicable reasons. These two reasons cannot occur together under the confirmed rules. Candidate queries do not read activity, private_note or personal_goal.

These are self-reported mood and conversation signals, not burnout scores, clinical thresholds or diagnoses. Manual follow-up endpoints remain available to authorized owners and team managers; tasks belong to the team, can be read and edited by its authorized leaders, and persist in the same SQLite database independently of the current candidate list. Assessment remains pending_rules with the exact contract message; no assessment formula or risk classification is invented. Organizations retain trial/active with no automatic expiry or payment integration.

## Validation handoff

The current checked-in backend is covered by the website tests. QA owns Python files under this website's `tests/`; the existing backend suite is included through a wrapper, alongside independent regression tests.

From the repository root, the host runs:

```text
uv run --locked python scripts/check.py --website
```

QA must set a temporary APP_DATA_DIR before importing backend.main or direct-module main, because the exported app initializes eagerly. Scenario factories should use temporary directories and an aware mutable clock. Tests must not reset, reseed or otherwise alter the preview database.

Required regression focus: AC1 import under Pydantic V2 in both import modes, factory isolation/reopen and exact static/API routes; AC5 strict types, post-trim constraints and unchanged password whitespace; AC7 eligibility boundaries, percentages and nulls; AC8 uneven daily counts, fixed windows and raw-mean delta rounding, including current [0,0,1] versus previous [0,0,0,0,0,1] yielding delta 0.17; AC9 latest eligible signals, pre-join exclusion, new members, deterministic ordering, team isolation and shared owner/manager follow-up create/read/update/reopen across factory restart. Existing authentication, privacy and cross-tenant regression coverage must also run.

The existing website suite passed 125 automated checks during handoff preparation. Browser journeys and outstanding acceptance evidence are tracked in the website README; this does not claim full product acceptance.

No unresolved contract conflict was identified in this correction. A future cross-origin deployment would require a separately supplied origin list and deployment design; it is outside the confirmed same-origin contract.

Prototype limitations: no account recovery, email verification, brute-force rate limiting, session administration UI, migration framework or multi-process schema migration coordination. Deployment should provide HTTPS, backup/restore operations and appropriate access controls for the SQLite data directory. No billing system or additional product features are included.
