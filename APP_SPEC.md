# Product Concept & Feature Specification: BurningUpp (Corporate B2B SaaS Platform)

> **Document Type:** Product Concept & Feature Specification  
> **Audience:** Autonomous AI Software Engineering Team (Orchestrator & Product Lead, Frontend Specialist, Backend Specialist, QA Verifier)  
> **Directive:** Use the core ideas and domain concepts in this specification to **design and create an original, cohesive multi-tenant B2B SaaS web application** (FastAPI + SQLite + HTML/CSS/JS, using only packages pinned in `requirements.txt` plus Python standard library). Do **not** treat this as analyzing an existing app to clone or recreate it verbatim; instead, build a fresh, well-architected corporate wellness platform inspired by this product concept.

---

## 1. Product Vision & Problem Statement

### 1.1 The Problem
In modern corporations, chronic workplace stress leads to silent attrition, absenteeism, and declining team performance. Traditional annual HR surveys are infrequent and disconnected from day-to-day reality, while ad-hoc team trackers lack the organizational structure, subscription governance, and employee privacy guarantees that companies require before rolling out a mental wellness platform company-wide.

### 1.2 The Solution
**BurningUpp** is a **multi-tenant corporate B2B SaaS platform** for proactive workplace mental wellness and team burnout prevention. Companies purchase a subscription tier (or start a 14-day trial), provision departments/teams, and empower employees while protecting psychological safety:
1. **For Company Admins (HR / Buyers):** Self-serve B2B subscription & billing management, team/seat provisioning, customizable corporate EAP/support resources, and **privacy-preserving organization & department burnout heatmaps** (`k >= 5` anonymity).
2. **For Team Managers:** Visibility into aggregated team burnout health—and individual risk metrics **only when employees explicitly opt in**—plus personal wellness tracking.
3. **For Employees:** Private daily mood journaling, lifestyle profiling, evidence-based clinical burnout self-assessments (Stage 1 + 22-item MBI), personal trend analytics, and access to coping guides and company-specific support resources.

---

## 2. Multi-Tenant Hierarchy, User Roles & Privacy Model

Every company operates as an isolated tenant (`companyId`). Cross-company data access is strictly forbidden.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Company (Tenant + Subscription Plan)                     │
│  Plan: Starter / Growth / Enterprise | Status: trial / active / expired /    │
│  canceled | Seat Cap (maxSeats) & Team Cap (maxTeams)                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  1. Company Admin (HR / Buyer)                                               │
│     - Registers company & picks plan (trial or simulated card checkout)      │
│     - Manages billing, upgrades/downgrades, and invoice history              │
│     - Creates/edits Teams, appoints/invites Managers, invites/reassigns/     │
│       deactivates Employees                                                  │
│     - Views ONLY anonymized/aggregated org & team metrics (k >= 5 rule)      │
│     - Customizes Company EAP links & exports CSV executive summary (Growth+) │
│     - Uses personal "My Wellness" tab (excluded from team risk aggregates)   │
├──────────────────────────────────────────────────────────────────────────────┤
│  2. Team Manager                                                             │
│     - Joins via Admin invite token; can lead 1 or more Teams within company  │
│     - Views team aggregated burnout stats (respecting k >= 5 threshold)      │
│     - Views named employee Flame Level & MBI subscales ONLY for employees    │
│       who explicitly enabled "Share burnout status with Manager"             │
│     - Uses personal "My Wellness" tab (excluded from managed team aggregates)│
├──────────────────────────────────────────────────────────────────────────────┤
│  3. Employee                                                                 │
│     - Joins a Team via Admin invite token OR 6-character teamCode            │
│     - Completes baseline wellness profile & tiered clinical assessments      │
│     - Logs strictly private daily mood & reflection journal                  │
│     - Controls opt-in consent: shareRiskWithManager (default: false)         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Privacy & Surveillance Guardrails (Mandatory)
1. **Strict Mood Privacy:** Daily mood scores, activity tags, and reflection notes (`MoodEntry`) are **strictly private** to the individual user. Neither Team Managers nor Company Admins may ever view another user's mood logs or notes.
2. **k-Anonymity Aggregation (`k >= 5`):**
   - Company Admins **never** see individual employee burnout scores or names in wellness reports.
   - Company-wide and department/team aggregates only render breakdown metrics (flame distribution, average MBI subscales, participation rate) when the group has **`>= 5` assessed active employees**.
   - Teams with `< 5` assessed employees display `"Protected (requires >= 5 assessed employees)"` for disaggregated breakdowns while still rolling safely into the overall Company total (provided the company itself has `>= 5` assessed employees).
3. **Opt-In Manager Drill-Down:**
   - Team Managers see aggregated team risk (when `>= 5` assessed employees) by default.
   - A Manager may view an employee's individual Flame Level and clinical MBI subscale breakdown (`emoExhaust`, `dePerson`, `personalAch`) **only** if that employee has toggled `shareRiskWithManager = true`. Otherwise, the employee appears only as an anonymized participation/protected entry or status-hidden row.
4. **Role Metric Separation:** Personal mood logs and burnout assessments taken by a `company_admin` or `manager` in their **"My Wellness"** workspace are strictly excluded from subordinate team and employee-risk aggregates so managers do not skew their own team's radar.

---

## 3. B2B SaaS Storefront, Subscription Tiers & Lifecycle Rules

### 3.1 Storefront & Entry Experience
The landing page functions as a clean B2B SaaS storefront and workspace gateway:
- **Public Pricing & Plans View:** Displays **Starter**, **Growth**, and **Enterprise** tiers with a **Monthly vs. Annual (20% discount)** billing toggle, feature comparison, and **"Start 14-Day Free Trial"** or **"Subscribe Now"** CTA.
- **Sign In Tab:** Email + password login with quick-fill demo accounts for evaluating `Company Admin`, `Team Manager`, and `Employee` views.
- **Join Company / Team Tab:** Allows invited Managers/Employees to activate an Admin **Invite Token** or employees to register with a 6-character **`teamCode`**.

### 3.2 Subscription Plan Catalog & Pricing Math

| Tier | Monthly Price | Annual Price (20% off) | Max Active Seats | Max Teams | Gated Features |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Starter** | `$49.00` | `$470.40` (`49 * 12 * 0.8`) | `25` | `3` | Core Mood & MBI Wellness, Team & Seat Management, `k >= 5` Org Overview, Billing & Invoices |
| **Growth** | `$199.00` | `$1,910.40` (`199 * 12 * 0.8`) | `150` | `15` | Everything in Starter + Department Burnout Heatmap & Trends, Participation Rate Tracking, Custom Company EAP Resources, CSV Executive Export |
| **Enterprise** | `$499.00` | `$4,790.40` (`499 * 12 * 0.8`) | `1,000` | Unlimited (`null`) | Everything in Growth at Enterprise scale + Priority SLA badge |

### 3.3 Billing, Quotas & Lifecycle Enforcement
1. **Trial & Simulated Checkout:**
   - Companies starting on a **14-day Free Trial** receive `subscriptionStatus = "trial"` with `trialEndsAt = now + 14 days` and a `$0.00` trial invoice record.
   - Instant simulated card checkout (validating simulated cardholder name, last-4 digits/expiry format, billing cycle `monthly | annual`) sets `subscriptionStatus = "active"`, updates `currentPeriodEnd`, and writes an immutable `Invoice` record (`round(monthlyPrice * 12 * 0.8, 2)` for annual).
2. **Active Seat Counting:**
   - Every active user (`isActive = 1`) in the company—across `company_admin`, `manager`, and `employee` roles—counts toward `maxSeats`.
   - Any registration via `teamCode`, registration via `inviteToken`, or invite creation when `activeSeats >= maxSeats` must be rejected (`HTTP 402` or `403`, e.g., `"Company seat limit reached"`).
   - Company Admins can **deactivate** offboarded employees (`isActive = 0`), immediately freeing a seat and revoking login tokens while preserving anonymized historical aggregate statistics.
3. **Team Quota & Downgrade Protection:**
   - Creating a new team when `activeTeams >= maxTeams` (for non-unlimited plans) is rejected (`HTTP 402` or `403`).
   - Switching to a lower tier is **blocked (`HTTP 400` or `409`)** if `activeSeats > targetPlan.maxSeats` or (`targetPlan.maxTeams != null` and `activeTeams > targetPlan.maxTeams`).
4. **Feature Gating:**
   - Endpoints for Department Heatmap, Custom Company EAP Resources, and CSV Executive Export return `HTTP 403` when the company is on `starter` (unless upgrading to `growth` or `enterprise`).
5. **Read-Only Grace Mode on Expiration / Cancellation:**
   - When `subscriptionStatus` is `"expired"` or `"canceled"` (or a trial's `trialEndsAt` has passed):
     - Existing users can still authenticate and **read** their personal history, calendar, and existing dashboards.
     - Company Admins can still access **Billing & Subscriptions** to renew or upgrade (which restores `"active"` status).
     - All write/expansion operations—new user joins, creating invites, creating teams, submitting mood entries, and submitting burnout assessments—are blocked with `HTTP 402` (`"Subscription inactive: read-only grace mode"`).

---

## 4. Core Feature Specifications

### Feature 1: Multi-Tenant Authentication, Corporate Onboarding & Team Provisioning
- **Authentication & Security:**
  - Passwords hashed with per-user random salt using Python stdlib `hashlib.pbkdf2_hmac("sha256", ...)`.
  - Authenticated sessions use HMAC-SHA256 signed or DB-persisted Bearer tokens (`Authorization: Bearer <token>`), enforcing strict RBAC and `companyId` tenant checks on every protected route.
- **Company Sign-Up (Creates Company + Company Admin):**
  - Buyer provides: Company Name, Admin Name, Work Email, Password, Selected Tier (`starter | growth | enterprise`), Billing Cycle (`monthly | annual`), and Start Trial vs. Simulated Checkout.
  - Provisions `Company`, `Invoice`, and initial `company_admin` user (occupying Seat 1).
- **Team & Invite Provisioning (Company Admin):**
  - Creates Teams/Departments (auto-generating unique 6-character alphanumeric `teamCode`, e.g., `A9K3X2`).
  - Appoints/invites **Team Managers** via unique `inviteToken` (with assigned team IDs; a Manager can lead `>= 1` teams).
  - Generates **Employee Invite Tokens** or shares a team's `teamCode`.
  - Can reassign an Employee to another Team within the same company and deactivate/reactivate user seats (cannot deactivate self if last active admin).
- **Employee Sign-Up & Team Join:**
  - Employee supplies Name, Email, Password, Birthday, Gender, and either an `inviteToken` or a valid `teamCode`.
  - Backend checks: invite/team exists, target company subscription is `trial` (unexpired) or `active`, and `activeSeats < maxSeats`.

### Feature 2: Baseline Health & Lifestyle Profiling
Collected during member onboarding or in the **"My Wellness"** profile settings:
- **Demographics:** Name, Birthdate, Gender (`male | female | other | prefer_not_to_say`).
- **Average Sleep Duration Bracket:** `1-3h`, `4-6h`, `6-8h`, `8-10h`, `>12h`.
- **Physical Activity Frequency:** `0`, `1-2`, `3-4`, `>4` times per week.
- **Baseline Subjective Stress:** `1` to `5` star scale.
- **Privacy Preference:** `shareRiskWithManager` boolean toggle (default `false`).

### Feature 3: Tiered Clinical Burnout Assessment
Available to all active users under **"My Wellness"** (with assessments by `employee` role feeding team/org risk metrics):

#### Stage 1: Basic Burnout Screening
- **Format:** 10 binary (`Yes` / `No`, i.e., `1` / `0`) questions covering mental exhaustion, detachment, concentration lapses, and somatic complaints.
- **Scoring:** `stage1Score` = sum of `"Yes"` responses (`0–10`).
- **Routing Logic:**
  - **`stage1Score < 5` (Low Risk):** User is assigned `Burnout Level 1` (1 Flame 🔥). Assessment completes immediately with prevention tips.
  - **`stage1Score >= 5` (Elevated Risk):** User is flagged for clinical evaluation and routed to **Stage 2 (MBI)**.

#### Stage 2: Maslach Burnout Inventory (MBI) Assessment
- **Format:** 22 standardized items evaluated on a 7-point Likert frequency scale (`0` = Never, `1` = A few times a year, `2` = Once a month, `3` = A few times a month, `4` = Once a week, `5` = A few times a week, `6` = Every day).
- **Clinical Subscales:**
  1. **Emotional Exhaustion (`EE`)** — 9 items (raw sum `0–54`):
     - *High Risk:* `EE >= 27`
     - *Moderate Risk:* `17 <= EE <= 26`
     - *Low Risk:* `EE < 17`
  2. **Depersonalization / Cynicism (`DP`)** — 5 items (raw sum `0–30`):
     - *High Risk:* `DP >= 13`
     - *Moderate Risk:* `7 <= DP <= 12`
     - *Low Risk:* `DP < 7`
  3. **Personal Accomplishment (`PA`)** — 8 items, **Reverse-Scored** (`sum(6 - response)` per item, total `0–48`):
     - *High Risk (Low Accomplishment):* `PA <= 31`
     - *Moderate Risk:* `32 <= PA <= 38`
     - *Low Risk (High Accomplishment):* `PA > 38`
- **Composite Burnout Level Outcome:**
  - **Level 3 (High Burnout 🔥🔥🔥):** If ANY subscale is High Risk (`EE >= 27` OR `DP >= 13` OR `PA <= 31`).
  - **Level 2 (Moderate Stress 🔥🔥):** Else if ANY subscale is Moderate Risk (`17 <= EE <= 26` OR `7 <= DP <= 12` OR `32 <= PA <= 38`).
  - **Level 1 (Low Risk 🔥):** Else (all three subscales are Low Risk).

### Feature 4: Private Daily Mood & Activity Journaling
- **5-Point Mood Scale** (supports EN/TH labels):
  - `0`: Very Bad (แย่มาก)
  - `1`: Bad (แย่)
  - `2`: Neutral (ปานกลาง / เฉยๆ)
  - `3`: Good (ดี)
  - `4`: Very Good (ดีมาก)
- **Contextual Logging:** Date (`YYYY-MM-DD`, defaults to today; rejects future dates with HTTP `400/422`), `activity` summary, and private `notes`.
- **Idempotency Rule:** Strictly one primary entry per user per calendar date `(userId, date)`. Resubmitting for the same user and date updates the existing entry rather than creating duplicates.

### Feature 5: Visual Mood Calendar, Entry Inspector & Personal Analytics
- Interactive monthly calendar grid color-coded by mood score (`0–4`) with click-to-inspect modal showing date, mood icon, activity, and reflection notes.
- Personal mood distribution visualizer (Red → Green breakdown) and personal burnout assessment history timeline.

### Feature 6: Privacy-First Manager Team Dashboard & Risk Radar
- Displays teams managed by the logged-in `manager` (supports switching between multiple managed teams) and each team's `teamCode`.
- **Aggregated Team Health Card:** Shows team flame distribution (Level 1 / 2 / 3 / Unassessed) and team average subscales **only when assessed active employees in that team `>= 5`**; otherwise displays a `k-anonymity` privacy notice (`"Team has < 5 assessed employees; aggregate metrics hidden to protect privacy"`).
- **Employee Roster & Opt-In Risk Radar:** Lists active employees in the team:
  - Employees with `shareRiskWithManager = true` display their Flame Risk gauge (🔥 / 🔥🔥 / 🔥🔥🔥 / `N/A`) and allow opening the clinical subscale drill-down modal (`EE`, `DP`, `PA`).
  - Employees with `shareRiskWithManager = false` show `"Private (Opt-out)"` with no individual score or subscale access.

### Feature 7: Company Admin (HR) Executive Portal & Billing Hub
- **Subscription & Billing Console:** Displays active tier, seat usage bar (`activeSeats / maxSeats`), team usage bar (`activeTeams / maxTeams`), trial countdown / status badge, Monthly/Annual plan switch & simulated checkout modal, and downloadable/viewable Invoice History.
- **Organization & Team Directory:** Create teams, invite Managers/Employees, copy `teamCode` or invite links, reassign employees across teams, and deactivate/reactivate user seats.
- **Org Burnout Heatmap & Analytics (`Growth` / `Enterprise` for heatmap & export; basic `k >= 5` org summary on `Starter`):**
  - Company-wide burnout risk breakdown & participation rate (`assessed active employees / total active employees`).
  - Per-department/team comparison matrix enforcing `k >= 5` per team.
  - **CSV Executive Summary Export (`Growth` / `Enterprise`):** Downloads an **anonymized, k-anonymity-compliant** CSV report (`team_name, active_employees, assessed_employees, participation_rate, level_1_count, level_2_count, level_3_count, status`)—suppressing counts (`"REDACTED (<5)"`) for teams under `k = 5` and never containing individual names or emails.
- **Custom Company EAP & Support Resources (`Growth` / `Enterprise`):** Admin configures corporate wellness links (e.g., EAP hotline, counseling portal, HR wellness contact) surfaced alongside Coping Tips.

### Feature 8: Burnout Education, Coping Tips & EN/TH Toggle
- Evidence-based coping library (recognizing early burnout, sleep hygiene, aerobic recovery, mindfulness/breathing, work-life boundaries, and medical disclaimer) + Company-configured EAP cards.
- Clean **EN / TH language switcher** in the UI header.

---

## 5. Corporate Domain Data Model (SQLite Entities)

```
┌──────────────────────────────┐        1:N        ┌─────────────────────────────────┐
│           Company            │ ───────────────── │              Team               │
├──────────────────────────────┤                   ├─────────────────────────────────┤
│ id: TEXT PK                  │                   │ id: TEXT PK (6-char teamCode)   │
│ name: TEXT NOT NULL          │                   │ companyId: TEXT FK -> Company   │
│ planTier: starter|growth|ent │                   │ name: TEXT NOT NULL             │
│ billingCycle: monthly|annual │                   │ managerId: TEXT FK -> User      │
│ subscriptionStatus:          │                   │ isActive: INTEGER DEFAULT 1     │
│   trial|active|expired|      │                   │ createdAt: TIMESTAMP            │
│   canceled                   │                   └────────────────┬────────────────┘
│ maxSeats: INTEGER            │                                    │ 1:N (employees)
│ maxTeams: INTEGER (nullable) │                                    ▼
│ trialEndsAt: TIMESTAMP       │                   ┌─────────────────────────────────┐
│ currentPeriodEnd: TIMESTAMP  │                   │              User               │
│ createdAt: TIMESTAMP         │                   ├─────────────────────────────────┤
└───────┬──────────────┬───────┘                   │ id: TEXT PK                     │
        │ 1:N          │ 1:N                       │ companyId: TEXT FK -> Company   │
        ▼              ▼                           │ teamId: TEXT FK -> Team (null)  │
┌────────────────┐ ┌──────────────────────┐        │ role: company_admin|manager|    │
│    Invoice     │ │    CompanyResource   │        │       employee                  │
├────────────────┤ ├──────────────────────┤        │ name: TEXT NOT NULL             │
│ id: TEXT PK    │ │ id: TEXT PK          │        │ email: TEXT UNIQUE NOT NULL     │
│ companyId: FK  │ │ companyId: FK        │        │ passwordHash: TEXT NOT NULL     │
│ planTier: TEXT │ │ title: TEXT          │        │ isActive: INTEGER DEFAULT 1     │
│ billingCycle   │ │ category: TEXT       │        │ shareRiskWithManager: INT (0/1) │
│ amountUsd: REAL│ │ contactOrUrl: TEXT   │        │ birthday: TEXT                  │
│ status: TEXT   │ │ description: TEXT    │        │ gender: TEXT                    │
│ createdAt: TS  │ │ createdAt: TIMESTAMP │        │ sleepHoursBracket: TEXT         │
└────────────────┘ └──────────────────────┘        │ exerciseFrequencyBracket: TEXT  │
                                                   │ baselineStressLevel: INT (1-5)  │
┌─────────────────────────────────────────┐        │ currentBurnoutLevel: INT (1-3)  │
│                 Invite                  │        └────────┬───────────────┬────────┘
├─────────────────────────────────────────┤             1:N │               │ 1:N
│ token: TEXT PK                          │                 ▼               ▼
│ companyId: TEXT FK -> Company           │   ┌───────────────────┐ ┌──────────────────────┐
│ teamId: TEXT FK -> Team (nullable)      │   │     MoodEntry     │ │  BurnoutAssessment   │
│ role: manager | employee                │   ├───────────────────┤ ├──────────────────────┤
│ email: TEXT (optional)                  │   │ id: TEXT PK       │ │ id: TEXT PK          │
│ usedByUserId: TEXT (nullable)           │   │ userId: FK -> User│ │ userId: FK -> User   │
│ expiresAt: TIMESTAMP                    │   │ companyId: FK     │ │ companyId: FK        │
│ createdAt: TIMESTAMP                    │   │ date: YYYY-MM-DD  │ │ stage1Score: INT     │
└─────────────────────────────────────────┘   │ moodScore: 0..4   │ │ eeScore: INT (null)  │
                                              │ activity: TEXT    │ │ dpScore: INT (null)  │
                                              │ notes: TEXT       │ │ paScore: INT (null)  │
                                              │ UNIQUE(userId,    │ │ compositeLevel: 1..3 │
                                              │        date)      │ │ completedAt: TS      │
                                              └───────────────────┘ └──────────────────────┘
```

---

## 6. Seeded Demo Data & QA Verification Requirements

### 6.1 Seeded Demo Corporate Workspace
On fresh database initialization, seed a realistic demo corporation (e.g., **Acme Tech Corp**, `Growth` monthly plan) containing:
- **1 Company Admin**, **2 Team Managers**, and **8 Active Employees** across 2 teams:
  - **Engineering Team (`>= 5` assessed employees, e.g., 6 employees):** Mix of Burnout Levels 1, 2, and 3, with some employees having `shareRiskWithManager = true` and others `false`—demonstrating both aggregate k-anonymity visibility and opt-in drill-down.
  - **Design Team (`< 5` assessed employees, e.g., 2 employees):** Demonstrates k-anonymity protection (team aggregates suppressed with `< 5` notice).
- Sample MoodEntries, Invoice history, and Company EAP resources, plus one-click Demo Login buttons on the Sign-In view (without weakening real password/token auth in API endpoints).

### 6.2 Mandatory Automated Verification (`pytest`)
The QA test suite must empirically verify:
1. **Clinical Formulas & Boundaries:**
   - Stage 1 `< 5` → Level 1 (`eeScore/dpScore/paScore` null); Stage 1 `>= 5` → requires Stage 2 MBI.
   - MBI reverse scoring (`PA = sum(6 - raw_i)`), high-risk cutoffs (`EE >= 27`, `DP >= 13`, `PA <= 31` → Level 3), moderate cutoffs → Level 2, all-low → Level 1.
   - Out-of-range inputs (`stage1` outside `0/1`, Likert outside `0..6`, wrong item counts `!= 10` or `!= 22`, mood outside `0..4`, future mood dates) rejected with HTTP `400/422`.
2. **Daily Mood Idempotency & Privacy:**
   - Submitting two moods for the same `(userId, date)` updates the single row rather than inserting a duplicate.
   - Mood endpoints never expose one user's entries/notes to another user, Manager, or Company Admin.
3. **Subscription Math, Quotas & Lifecycle:**
   - Annual price = `round(monthlyPrice * 12 * 0.8, 2)`.
   - Seat cap blocks new joins/invites when `activeSeats >= maxSeats`; deactivating an employee reduces `activeSeats` and unblocks joining while preserving anonymized aggregates.
   - Team cap blocks team creation on Starter (`3`) / Growth (`15`).
   - Downgrade blocked (`400/409`) when active seats/teams exceed target plan limits.
   - Feature gating returns `403` on Starter for CSV export / custom EAP / heatmap.
   - Expired/canceled subscription enforces read-only grace mode (`402` on writes/joins, `200` on personal reads & billing renewal).
4. **Corporate Privacy & Tenant Isolation:**
   - `k >= 5` threshold hides disaggregated team metrics when assessed employees `< 5` and reveals aggregates when `>= 5`.
   - Manager cannot view individual Flame Level or MBI subscales when `shareRiskWithManager = false` (`403` or redacted), and CAN when `true`.
   - Cross-company requests and unauthorized role requests fail with `401/403`.
