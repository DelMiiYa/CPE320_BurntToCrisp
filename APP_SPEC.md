# Product Concept & Feature Specification: BurningUpp

> **Document Type:** Product Concept & Idea Specification  
> **Audience:** Autonomous AI Software Engineering Team (Orchestrator & Product Lead, Frontend Specialist, Backend Specialist, QA Verifier)  
> **Directive:** Use the core ideas and domain concepts in this specification to **design and create an original, cohesive web application** (FastAPI + SQLite + HTML/CSS/JS). Do **not** treat this as analyzing an existing app to clone or recreate it verbatim; instead, build a fresh, well-architected web app inspired by this product concept.

---

## 1. Product Vision & Problem Statement

### 1.1 The Problem
In fast-paced workplace environments, occupational burnout develops gradually through chronic workplace stress that has not been successfully managed. Traditional HR surveys are infrequent, clunky, and reactive. Teams lack a lightweight, continuous pulse on emotional exhaustion, cynicism, and mental fatigue.

### 1.2 The Solution
**BurningUpp** is a lightweight, proactive mental wellness and team burnout tracking platform. It bridges individual self-awareness with organizational health by offering:
1. **For Team Members:** Quick daily mood journaling, lifestyle tracking, and evidence-based clinical burnout assessments (MBI).
2. **For Team Managers:** Real-time visibility into team burnout risks through intuitive visual metrics, allowing early support and intervention before burnout leads to severe attrition.

---

## 2. User Roles & Ecosystem

The product operates around two distinct personas:

```
┌─────────────────────────────────────────────────────────────┐
│                       Team Manager                          │
│  - Creates Team & receives unique 6-character Team Code     │
│  - Monitors team burnout distribution (1-3 Flame Level)     │
│  - Inspects subscale burnout metrics to guide interventions │
└──────────────────────────────┬──────────────────────────────┘
                               │ Shares Team Code
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Team Member                           │
│  - Enters Team Code upon registration                       │
│  - Completes baseline wellness intake (sleep, stress, etc.) │
│  - Logs daily mood & activities                             │
│  - Takes tiered burnout self-assessments (Screening & MBI)  │
│  - Views historical calendar trends & personal analytics    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Core Feature Specifications

### Feature 1: Dual-Role Authentication & Team Pairing
- **Manager Sign-Up:**
  - Manager provides: Name, Team Name, Email, Password.
  - The system auto-generates a unique 6-character alphanumeric `teamCode` (e.g., `A9K3X2`).
  - System provisions a team entity linked to the manager's account.
- **Member Sign-Up & Team Join:**
  - Member provides: Name, Email, Password, Birthday, Gender, and a valid `teamCode`.
  - The system validates that the `teamCode` exists.
  - Upon successful registration, the member is appended to the team's membership roster.
- **Role-Aware Navigation:**
  - Upon authentication, users are automatically directed to their respective workspace:
    - Managers $\rightarrow$ Team Management Dashboard
    - Members $\rightarrow$ Main Menu Hub

---

### Feature 2: Baseline Health & Lifestyle Profiling
Collected during member onboarding or profile management to establish a holistic baseline:
- **Demographics:** Name, Birthdate, Gender (Male / Female / Other).
- **Average Sleep Duration:** Categorized into brackets (1–3h, 4–6h, 8–10h, >12h).
- **Physical Activity:** Exercise frequency per week (0, 1–2, 3–4, >4 times).
- **Baseline Subjective Stress:** 1-to-5 star scale representing current stress perception.

---

### Feature 3: Tiered Clinical Burnout Assessment
The assessment is divided into two phases to reduce cognitive friction:

#### Stage 1: Basic Burnout Screening
- **Format:** 10 binary (Yes / No) questions covering mental exhaustion, detachment, concentration lapses, and somatic complaints.
- **Scoring:** 1 point per "Yes".
- **Logic:**
  - **Score < 5 (Low Risk):** User is assigned `Burnout Level 1`. Test completes with prevention advice.
  - **Score ≥ 5 (Elevated Risk):** User is flagged for clinical evaluation and immediately routed to Stage 2.

#### Stage 2: Maslach Burnout Inventory (MBI) Assessment
- **Format:** 22 standardized items evaluated on a 7-point Likert frequency scale:
  - `0`: Never
  - `1`: A few times a year
  - `2`: Once a month
  - `3`: A few times a month
  - `4`: Once a week
  - `5`: A few times a week
  - `6`: Every day
- **Clinical Subscales:**
  1. **Emotional Exhaustion (EE)** (9 items): Measures feelings of being emotionally overextended and exhausted by one's work.
     - *High Risk:* Score $\ge 27$
     - *Moderate Risk:* Score $17 - 26$
     - *Low Risk:* Score $< 17$
  2. **Depersonalization / Cynicism (DP)** (5 items): Measures unfeeling and impersonal responses toward recipients of one's service or colleagues.
     - *High Risk:* Score $\ge 13$
     - *Moderate Risk:* Score $7 - 12$
     - *Low Risk:* Score $< 7$
  3. **Personal Accomplishment (PA)** (8 items, Reverse-Scored: `6 - response`): Measures feelings of competence and successful achievement at work.
     - *High Risk (Low Accomplishment):* Score $\le 31$
     - *Moderate Risk:* Score $32 - 38$
     - *Low Risk (High Accomplishment):* Score $> 38$
- **Composite Burnout Level Outcome:**
  - If any subscale indicates high risk ($EE \ge 27 \lor DP \ge 13 \lor PA \le 31$):
    - Overall Result: **High Burnout** $\rightarrow$ `Burnout Level 3` (3 Flames 🔥🔥🔥).
  - Otherwise:
    - Overall Result: **Low/Moderate Burnout** $\rightarrow$ `Burnout Level 1 or 2`.

---

### Feature 4: Daily Mood & Activity Journaling
- **Daily Mood Check-in:**
  - 5-point emotional scale:
    - `0`: Very Bad (แย่มาก)
    - `1`: Bad (แย่)
    - `2`: Neutral (ปานกลาง / เฉยๆ)
    - `3`: Good (ดี)
    - `4`: Very Good (ดีมาก)
- **Contextual Logging:**
  - Date selection (defaults to current date; restricts future dates).
  - Activity description (text input summarizing what the user worked on or did).
  - Notes / Journal (free-form reflections or comments).
- **Idempotency Rule:** One primary log per user per calendar day (updating the existing entry if resubmitted).

---

### Feature 5: Visual Mood Calendar & Entry Inspector
- **Monthly Calendar Matrix:**
  - Interactive grid displaying the days of the month.
  - Automatically loads and highlights logged days with corresponding mood icons/colors.
- **Entry Inspector Modal:**
  - Tapping on any day reveals an entry detail dialog displaying:
    - Logged Date
    - Mood icon & status
    - Specific activities recorded
    - Personal reflection notes

---

### Feature 6: Member Analytics & Profile Hub
- **Profile Summary:** Displays member bio, birthday, and lifestyle baseline.
- **Mood Distribution Visualizer:** Interactive Pie Chart breaking down logged moods across time with distinct color coding (Red $\rightarrow$ Green).
- **Assessment History:** Shows latest burnout screening outcome and date taken.

---

### Feature 7: Manager Team Dashboard & Risk Radar
- **Team Code Card:** Displays the team's joining code for easy sharing.
- **Member Overview Table:**
  - Displays list of all joined team members.
  - **Flame Risk Indicator:** Visual 3-flame gauge indicating individual burnout severity:
    - 🔥: Level 1 (Healthy / Low Risk)
    - 🔥🔥: Level 2 (Moderate Stress)
    - 🔥🔥🔥: Level 3 (Severe Burnout Risk)
    - `N/A`: Has not yet completed an assessment
- **Detailed Member Assessment Drill-Down:**
  - Managers can open a detail modal for a member to view their clinical breakdown (`emoExhaust`, `dePerson`, `personalAch`) to understand whether exhaustion, cynicism, or lack of accomplishment is driving the risk.

---

### Feature 8: Burnout Education & Coping Tips
- Library of actionable coping strategies:
  - Self-awareness and recognizing early symptoms.
  - Sleep hygiene and restorative rest protocols.
  - Cardiovascular exercise routines.
  - Mindfulness, meditation, and structured breathing exercises.
  - Work-life boundary management and professional help disclaimers.

---

## 4. Domain Data Model (Entities & Relationships)

```
┌─────────────────────────────────┐       1:N       ┌─────────────────────────────────┐
│              Team               │ ─────────────── │              User               │
├─────────────────────────────────┤                 ├─────────────────────────────────┤
│ id: string (teamCode, 6-char PK)│                 │ id: string (PK)                 │
│ name: string                    │                 │ role: "manager" | "member"      │
│ managerId: string (FK -> User)  │                 │ teamId: string (FK -> Team)     │
│ createdAt: timestamp            │                 │ name: string                    │
│ memberIds: string[]             │                 │ email: string                   │
└─────────────────────────────────┘                 │ birthday: date                  │
                                                    │ gender: enum                    │
                                                    │ sleepHoursBracket: enum         │
                                                    │ exerciseFrequencyBracket: enum  │
                                                    │ baselineStressLevel: int (1-5)  │
                                                    │ currentBurnoutLevel: int (1-3)  │
                                                    └────────────────┬────────────────┘
                                                                     │
                                           ┌─────────────────────────┴─────────────────────────┐
                                       1:N │                                               1:N │
                                           ▼                                                   ▼
                        ┌─────────────────────────────────────┐             ┌─────────────────────────────────────┐
                        │              MoodEntry              │             │          BurnoutAssessment          │
                        ├─────────────────────────────────────┤             ├─────────────────────────────────────┤
                        │ id: string (userId_YYYY-MM-DD)      │             │ id: string (PK)                     │
                        │ userId: string (FK -> User)         │             │ userId: string (FK -> User)         │
                        │ date: string (YYYY-MM-DD)           │             │ stage1Score: int (0-10)             │
                        │ moodScore: int (0-4)                │             │ emotionalExhaustionScore: int       │
                        │ activity: string                    │             │ depersonalizationScore: int         │
                        │ notes: string                       │             │ personalAccomplishmentScore: int    │
                        │ createdAt: timestamp                │             │ compositeLevel: int (1-3)           │
                        └─────────────────────────────────────┘             │ completedAt: timestamp              │
                                                                            └─────────────────────────────────────┘
```

---

## 5. Architectural Considerations for the AI SE Team

When designing and creating a new web application from this product concept:
1. **Create from the Idea, Do Not Clone:**
   - Use these features and domain concepts as the creative and functional foundation for a new full-stack web application (`FastAPI` + `SQLite` backend and vanilla `HTML5/CSS3/JS` frontend). Simplify or adapt UI flows so the entire experience works seamlessly as a unified, self-contained single-page web app.
2. **Privacy vs. Surveillance Trade-off:**
   - Balance manager visibility into team burnout levels (1–3 Flames and subscale scores) with supportive, constructive presentation.
3. **Clinical Formula Integrity:**
   - Ensure the Stage 1 screening threshold ($\ge 5$), MBI reverse-scoring on Personal Accomplishment (`6 - raw_score`), subscale risk cutoffs ($EE \ge 27$, $DP \ge 13$, $PA \le 31$), and daily mood log idempotency are rigorously verified via automated `pytest` unit tests.
