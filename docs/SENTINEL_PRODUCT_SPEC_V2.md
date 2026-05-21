# Sentinel Trade Surveillance — Product Spec v2

**Status:** Approved for implementation  
**Last updated:** 2026-05-21  
**Repos:** `trade-surveillance-api` (FastAPI), `trade-surveillance-web` (Next.js)

This document is the single source of truth for the v2 redesign: personas, enums, RBAC, APIs, UI structure, and phased delivery. It supersedes ad-hoc UI layout decisions in the current codebase where they conflict.

---

## Table of contents

1. [North star](#1-north-star)
2. [Decision log](#2-decision-log)
3. [Personas & RBAC](#3-personas--rbac)
4. [Canonical enums & state machines](#4-canonical-enums--state-machines)
5. [Information architecture](#5-information-architecture)
6. [API design](#6-api-design)
7. [Screen specifications](#7-screen-specifications)
8. [Case page — field visibility](#8-case-page--field-visibility)
9. [Metrics & SLA](#9-metrics--sla)
10. [Frontend structure](#10-frontend-structure)
11. [Demo accounts](#11-demo-accounts)
12. [Implementation backlog](#12-implementation-backlog)
13. [Explicitly out of scope (v2)](#13-explicitly-out-of-scope-v2)
14. [Appendix: Current vs v2](#14-appendix-current-vs-v2)

---

## 1. North star

**Analyst** triages ML flags, runs on-demand AI investigation, approves AI output, documents findings, and **escalates** to the compliance officer.

**Compliance officer** monitors queue health, **assigns** work, reviews escalations, and is the **only role that can close** alerts with a disposition.

### Success metrics (prioritized)

| Priority | Goal | How we measure it in product |
|----------|------|------------------------------|
| **B — Trust** | Analysts trust AI output | Explainability (SHAP), formatted investigation sections, human approval gate, audit timeline, neutral copy on AI dismiss |
| **C — Coverage** | Credible US surveillance story in demos | Six anomaly types with US rule themes, disposition glossary, data gaps surfaced, officer/analyst RBAC |

### AI behavior

- **On-demand only** — analyst or officer clicks “Run AI investigation”; no auto-close or auto-dismiss.
- **One investigation per alert** (enforced in API).
- AI verdict is a **suggestion** until analyst approves (`review_status`).

### Design principles

- **Case-centric** primary workflow (`/cases/{alertId}`).
- **Entity explorers** remain as secondary routes (alerts, trades, investigations).
- Show **useful** trade/surveillance fields only; hide noise (global ticker, unrelated recent trades, raw JSON by default).
- **US regulatory** framing in labels; always show **data gaps** when present.
- **Desktop-first**, responsive collapse (Case → tabs on narrow viewports).
- **Dark mode default**; light mode supported via theme toggle.

---

## 2. Decision log

| # | Decision |
|---|----------|
| 1 | Only **compliance officers** (`COMPLIANCE_LEAD`) may close alerts with disposition |
| 2 | **Canonical enums** defined in §4; DB stores `UPPER_SNAKE`, API JSON snake_case, UI camelCase |
| 3 | Assignment by **`users.id`** (`alerts.assigned_to`); deprecate email-based assign writes |
| 4 | **One investigation** per alert |
| 5 | **Fixed demo logins** (§11) |
| 6 | **US** jurisdiction for rule/disposition language |
| 7 | Show **data gaps** prominently; map rules where possible, label gaps when not |
| 8 | Minimal UI — case-first, remove decorative/low-value widgets |
| 9 | **Neutral** UI on AI dismiss with explicit “AI suggests dismiss” hint |
| 10 | **Formatted investigation sections** via stable API DTO (`InvestigationPresentation`) |
| 11 | **Human approval required** before investigation counts as complete for workflow |
| 12 | **Role-based landing:** analyst → `/queue`, officer → `/overview` |
| 13 | Desktop-first, responsive |
| 14 | **3s polling** for AI status; websockets later |
| 15 | **Dark default**, light supported |
| 16 | **Stale alert** = open work older than **24 hours** (`updated_at`) |
| 17 | Compute **SLA / queue metrics** on overview where data allows |
| 18 | **Open-high badge** in sidebar for **both** roles |
| 19 | Add **`GET /cases/{id}`** and related backend support |
| 20 | Add **`POST` assign / take / escalate / close** endpoints |
| 21 | Add **`GET /auth/session`** with role; extend login user payload |

---

## 3. Personas & RBAC

### Roles (`users.role`)

| Value | UI label | Default route after login |
|-------|----------|---------------------------|
| `ANALYST` | Analyst | `/queue` |
| `COMPLIANCE_LEAD` | Compliance officer | `/overview` |

### Permission matrix

| Action | Analyst | Officer |
|--------|---------|---------|
| View queue / case | ✓ | ✓ |
| Take ownership (self-assign) | ✓ | ✓ |
| Assign to another user | ✗ | ✓ |
| Run AI investigation (HIGH/MEDIUM) | ✓ | ✓ |
| Approve AI investigation findings | ✓ | ✓ |
| Add human note | ✓ | ✓ |
| Escalate → `PENDING_OFFICER_REVIEW` | ✓ | ✓ |
| Close alert + disposition | ✗ | ✓ |
| Team / users admin | ✗ | ✓ |
| Command overview (full KPIs) | Limited | ✓ |

**UI rule:** Disable actions the role cannot perform, with tooltip (“Compliance officer only”). Do not rely on API 403 alone.

**Server rule:** Enforce the same rules in FastAPI dependencies (`require_compliance_lead` for close, etc.).

---

## 4. Canonical enums & state machines

### 4.1 Alert status (`alerts.status`)

Stored in DB as `UPPER_SNAKE`. Do **not** use `ESCALATED` as a status — use `PENDING_OFFICER_REVIEW` for internal escalation to officer; use disposition `ESCALATED_TO_REGULATOR` for regulatory escalation on close.

| Status | Meaning | Typical actor |
|--------|---------|---------------|
| `OPEN` | New / unworked | System (model) |
| `IN_PROGRESS` | Analyst working and/or AI running | Analyst, system |
| `PENDING_OFFICER_REVIEW` | Analyst escalated to officer | Analyst (`POST .../escalate`) |
| `CLOSED` | Terminal | Officer (`POST .../close`) |

**Allowed transitions**

```
OPEN → IN_PROGRESS          (take, assign, run AI)
IN_PROGRESS → IN_PROGRESS   (AI running)
IN_PROGRESS → PENDING_OFFICER_REVIEW   (escalate; requires investigation approved)
IN_PROGRESS → CLOSED        (officer only)
PENDING_OFFICER_REVIEW → IN_PROGRESS   (officer reassign / send back)
PENDING_OFFICER_REVIEW → CLOSED        (officer only)
```

**API input normalization:** accept `open`, `in-progress`, `in_progress`, `pending_officer_review`, `closed` → canonical DB values.

**UI labels:** Open · In progress · Pending officer review · Closed

### 4.2 Alert severity (`alerts.severity`)

| DB | UI label | AI investigation |
|----|----------|------------------|
| `HIGH` | High | Allowed |
| `MEDIUM` | Medium | Allowed |
| `LOW` | Low | Blocked — show reason in UI |
| `NONE` | None | Blocked |

**Filter aliases:** `med`, `medium` → `MEDIUM`

### 4.3 Anomaly type (`alerts.anomaly_type`)

Pipeline values (unchanged). UI uses US surveillance language:

| DB value | UI label | US theme (display only) |
|----------|----------|-------------------------|
| `fat_finger` | Fat finger | Erroneous entry / control failure |
| `volume_spike` | Volume spike | Unusual volume |
| `off_hours` | Off-hours | Trading hours / policy |
| `spoofing` | Spoofing | Layering / spoofing (Exchange Act context) |
| `wash_trade` | Wash trade pattern | Wash / self-trade risk |
| `multi_flag` | Multiple signals | Combined hit |
| `unknown` | Unclassified | Manual review — show data gap |

### 4.4 Disposition (`alerts.disposition`)

**Required when** `status = CLOSED`. **Officer only.**

| Value | UI label |
|-------|----------|
| `FALSE_POSITIVE` | False positive |
| `NO_ACTION_REQUIRED` | No action required |
| `CLEARED_WITH_MONITORING` | Cleared — continue monitoring |
| `ESCALATED_TO_REGULATOR` | Escalated to regulator |

*Note: replaces informal `UNDER_INVESTIGATION` / `NO_ACTION` strings in old UI where needed.*

### 4.5 Investigation AI verdict (`investigations.verdict`)

Set by LangGraph agent: `ESCALATE` | `MONITOR` | `DISMISS`

| Verdict | UI headline | Subtext |
|---------|-------------|---------|
| `ESCALATE` | AI recommends escalation | Not a final regulatory action |
| `MONITOR` | AI recommends monitoring | Continue surveillance |
| `DISMISS` | AI suggests dismiss | **Suggestion only** — human approval required |

### 4.6 Investigation review status (`investigations.review_status`) — **new column**

| Value | Meaning | UI |
|-------|---------|-----|
| `AI_COMPLETE` | Agent finished; awaiting analyst approval | Show full memo + **Approve** CTA |
| `ANALYST_APPROVED` | Analyst accepted AI output | Read-only; enable escalate |
| `OFFICER_APPROVED` | Officer signed off (optional) | For escalated cases if needed |

**Workflow “complete” for escalation:** `review_status >= ANALYST_APPROVED`  
**Optional stricter path:** require `OFFICER_APPROVED` before close on `PENDING_OFFICER_REVIEW` cases (defer to P1 if needed).

**Agent:** on successful run, set `review_status = AI_COMPLETE`, `completed_at = now()`.

### 4.7 Note type (`investigation_notes.note_type`)

| Value | UI |
|-------|-----|
| `SYSTEM` | System event |
| `HUMAN` | Comment |

### 4.8 Timeline event types

Emit as system notes or dedicated audit rows:

`ASSIGNED` · `STATUS_CHANGED` · `AI_STARTED` · `AI_COMPLETED` · `ANALYST_APPROVED` · `ESCALATED_TO_OFFICER` · `CLOSED`

---

## 5. Information architecture

### Routes

| Route | Audience | Purpose |
|-------|----------|---------|
| `/login` | All | Auth; demo account hints |
| `/queue` | Both (analyst home) | Filterable work queue |
| `/cases/[alertId]` | Both | **Primary case workspace** |
| `/overview` | Officer home | Command center + SLA |
| `/team` | Officer | Assignments & escalations inbox |
| `/alerts` | Both | Alert explorer (browse / deep filters) |
| `/trades`, `/trades/[id]` | Both | Trade explorer → link to case |
| `/investigations`, `/investigations/[id]` | Both | Investigation explorer → link to case |
| `/users` | Officer | Users, roles, active flag |

### Redirects / removals (v2)

| Item | Action |
|------|--------|
| `/alerts/[alertId]` minimal page | **Remove** → redirect to `/cases/[alertId]` |
| Global market **ticker** strip | **Remove** from shell |
| Overview **recent trades** table | **Remove** |
| Investigations as **primary** nav story | **Demote** — case holds investigation UI |
| Drawer-only alert detail | **Replace** with Case route; optional quick-preview later |

### Navigation (sidebar)

**Primary:** Queue · Overview · Investigations (explorer)  
**Secondary:** Users (officer)  
**Badge:** Open alert count on Alerts/Queue; high-severity count for **both** roles (from metrics or lightweight query)

---

## 6. API design

Base path: `/api/v1`. All authenticated routes use `get_current_user` unless noted.

### 6.1 Auth session

```
GET /auth/session
Authorization: Bearer <token>

200 →
{
  "user": {
    "id": "uuid",
    "email": "analyst@demo.sentinel",
    "display_name": "Demo Analyst",
    "role": "ANALYST"
  }
}
```

**Extend** `POST /auth/login` and `POST /auth/refresh` response `user` object with `role` and `display_name` (same shape as session).

Web: store in session; drive RBAC and post-login redirect.

### 6.2 Case bundle

```
GET /cases/{alert_id}
```

**Response (conceptual):**

```json
{
  "alert": {
    "id": "uuid",
    "trade_id": "uuid",
    "symbol": "TSLA",
    "severity": "HIGH",
    "status": "IN_PROGRESS",
    "anomaly_type": "spoofing",
    "anomaly_score": 0.91,
    "top_shap_feature": "depth_imbalance",
    "top_3_shap_features": [["depth_imbalance", 0.42]],
    "assigned_to": "user-uuid",
    "assignee": { "id": "uuid", "email": "a@firm.com", "display_name": "Alex" },
    "age_hours": 5.2,
    "is_stale": false,
    "created_at": "...",
    "updated_at": "..."
  },
  "trade": { },
  "investigation": { },
  "notes": [ ],
  "permissions": {
    "can_assign": false,
    "can_take": true,
    "can_close": false,
    "can_escalate": true,
    "can_run_ai": true,
    "can_approve_investigation": true
  }
}
```

Implement via service layer joining `alerts`, `trades`, `traders`, `clients`, `counterparties`, latest `investigation` (one per alert), `investigation_notes`.

### 6.3 Assignment

```
POST /alerts/{alert_id}/assign
Body: { "assigned_to": "user-uuid" }
```

- **Officer:** may assign any active analyst.
- **Analyst:** may only set `assigned_to` to self (or use `/take`).

```
POST /alerts/{alert_id}/take
```

Sets `assigned_to = current_user.id`, optionally `status = IN_PROGRESS` if `OPEN`.

**Deprecate:** PATCH alert with `assignee` email for writes. Keep resolved email on `AlertRead` for backward-compatible reads until web migrates.

### 6.4 Escalate to officer

```
POST /alerts/{alert_id}/escalate
Body: { "note": "string, min 3 chars" }
```

- Sets `status = PENDING_OFFICER_REVIEW`
- Creates `HUMAN` note + `SYSTEM` timeline entry
- **Requires:** investigation exists and `review_status` in (`ANALYST_APPROVED`, `OFFICER_APPROVED`)

### 6.5 Close (officer only)

```
POST /alerts/{alert_id}/close
Body: {
  "disposition": "FALSE_POSITIVE",
  "note": "string, min 3 chars"
}
```

- Sets `status = CLOSED`, `disposition`, `reviewed_by`, `reviewed_at`
- Creates human note

### 6.6 Investigation — run (existing)

```
POST /investigations/run/{alert_id}  → 202
```

- Guards: severity HIGH/MEDIUM, not already in progress, `ANTHROPIC_API_KEY` set
- Sets alert `IN_PROGRESS` if was `OPEN`
- Background: LangGraph orchestrator
- **Enforce:** at most one investigation row per `alert_id`

### 6.7 Investigation — approve (new)

```
POST /investigations/{investigation_id}/approve
Body: {
  "override_note": null
}
```

- Sets `review_status = ANALYST_APPROVED`
- System note: analyst approved AI findings
- Optional `override_note` if analyst disagrees but acknowledges (stored as human note)

```
POST /investigations/{investigation_id}/officer-approve
```

- Officer only; sets `OFFICER_APPROVED` (P1)

### 6.8 Investigation presentation DTO (new)

Built server-side for UI — do not require frontend to parse `memo_json`.

```json
{
  "id": "uuid",
  "alert_id": "uuid",
  "review_status": "AI_COMPLETE",
  "headline": {
    "verdict": "DISMISS",
    "verdict_label": "AI suggests dismiss",
    "verdict_hint": "Suggestion only — not a final disposition",
    "confidence": "HIGH",
    "confidence_label": "High confidence",
    "model_version": "claude-haiku-…",
    "completed_at": "2026-05-21T12:00:00Z"
  },
  "sections": [
    {
      "id": "summary",
      "title": "Executive summary",
      "body": "…",
      "emphasis": "default"
    },
    {
      "id": "rules",
      "title": "US regulatory screening",
      "items": [
        {
          "rule_code": "SPOOFING_LAYERING",
          "label": "Spoofing / layering",
          "status": "triggered",
          "detail": "…"
        }
      ]
    },
    {
      "id": "evidence",
      "title": "Evidence",
      "bullets": ["…"]
    },
    {
      "id": "recommended_action",
      "title": "Recommended next steps",
      "body": "…"
    },
    {
      "id": "data_gaps",
      "title": "Data gaps & limitations",
      "body": "…",
      "emphasis": "warning"
    }
  ],
  "error": null
}
```

`emphasis`: `default` | `warning` | `critical`

Parse `rule_violated` text into `rules.items` (semicolon-separated segments today).

### 6.9 Metrics overview (extend existing)

```
GET /metrics/overview
```

**Add fields:**

| Field | Definition |
|-------|------------|
| `open_unassigned_high` | `OPEN` or `IN_PROGRESS`, `severity = HIGH`, `assigned_to IS NULL` |
| `pending_officer_review` | `status = PENDING_OFFICER_REVIEW` |
| `stale_open_24h` | `OPEN` or `IN_PROGRESS`, `updated_at < now() - 24h` |
| `sla_breach_count` | Same as `stale_open_24h` for v2 (alias) |
| `alerts_per_assignee` | `[{ user_id, email, display_name, open_count }]` |

Keep existing: `total_alerts`, `total_trades`, `alerts_by_status`, `alerts_by_severity`, `alerts_by_anomaly_type`, `open_alerts_by_severity`, `open_high_severity_count`, `top_symbols_by_alerts`.

### 6.10 List alerts (queue) — extend filters

Existing query params plus:

| Param | Description |
|-------|-------------|
| `assigned_to` | UUID, or magic `me` resolved to current user |
| `unassigned` | boolean |
| `stale` | boolean (24h) |
| `status` | includes `pending_officer_review` |

### 6.11 Data model migrations

| Table | Change |
|-------|--------|
| `investigations` | Add `review_status VARCHAR(30) NOT NULL DEFAULT 'AI_COMPLETE'` |
| `investigations` | **Unique index** on `alert_id` (one per alert) |
| `alerts` | Migrate any legacy `ESCALATED` status rows → `PENDING_OFFICER_REVIEW` or `CLOSED` as appropriate |

No change to core ML columns on `alerts` / `trades`.

---

## 7. Screen specifications

### 7.1 Login

- Email / password → API login
- **Demo hints:** `analyst@demo.sentinel` / `officer@demo.sentinel`
- On success: redirect by `role` (§3)

### 7.2 Queue (`/queue`)

**Columns:** Symbol · Anomaly (US label) · Score · Severity · Status · Assignee · Age · AI verdict (if approved) · Stale indicator

**Saved views (presets):**

| View | Filter |
|------|--------|
| My cases | `assigned_to=me` |
| Unassigned high | `severity=high`, `unassigned=true` |
| Pending officer | `status=pending_officer_review` |
| Stale >24h | `stale=true` |

**Interactions:** Row click → `/cases/{id}`; officer bulk assign (P1); analyst “Take case”

**Empty states:** No alerts / no matches — clear copy + reset filters

### 7.3 Case (`/cases/[alertId]`)

**Layout:** 3 columns desktop; stacked tabs mobile

| Column | Content |
|--------|---------|
| **Header** | Symbol, ids, badges, assignee, age, stale |
| **Left** | Trade facts + ML signal (SHAP) |
| **Center** | Investigation panel (states below) |
| **Right** | Workflow (assign, escalate, close) + activity timeline |

**Investigation UI states**

1. No investigation — CTA Run AI (if allowed)
2. Running — spinner; poll every 3s
3. `AI_COMPLETE` — presentation sections + dismiss hint + **Approve findings**
4. `ANALYST_APPROVED` — read-only + approved timestamp
5. Error — message + retry if allowed

**Workflow gating**

- **Escalate:** disabled until investigation `ANALYST_APPROVED`
- **Close:** officer only; disposition required

### 7.4 Overview (`/overview`) — officer

**Action cards (click → filtered queue):**

- Open high (with unassigned subcount)
- Pending officer review
- Stale >24h (SLA breach)
- Total open

**Charts:** Anomaly mix + open-by-severity (clickable drill-down)

**Team table:** `alerts_per_assignee`

**Analyst view (limited):** My open cases + stale count only (optional P1)

### 7.5 Team (`/team`) — officer

- Analyst roster with open case counts
- Escalations inbox (`PENDING_OFFICER_REVIEW`) → open case
- Quick assign from row actions (P1)

### 7.6 Users (`/users`) — officer

- List users: email, role, active
- PATCH role (`ANALYST` | `COMPLIANCE_LEAD`) and `is_active`
- No Supabase admin duplication

### 7.7 Entity explorers

**Alerts / trades / investigations:** read-heavy tables with links to `/cases/{alertId}` where applicable. No duplicate investigation detail — case is canonical.

---

## 8. Case page — field visibility

### Trade facts (show if present)

| Field | Notes |
|-------|--------|
| Timestamp (US/Eastern) | Always |
| Side, price, volume, notional | Always |
| Off-hours, OTC, block flags | Only if true |
| Trader id + desk/region | Join `traders` |
| Client id + MiFID category | Join `clients` |
| Counterparty | Join `counterparties` |
| Spread, vs NBBO bps | If non-null |

**Hide:** empty fields, full `model_features` JSON (optional “Advanced” accordion later)

### ML signal

- SHAP top 3 + anomaly score
- `feature_spec_version` (small print)
- If missing: “Explainability unavailable — use anomaly type and trade context”

### Data gaps block

Always render `data_gaps` section when non-empty. For `unknown` anomaly type, show default gap copy.

---

## 9. Metrics & SLA

| Metric | Rule |
|--------|------|
| Stale | `status IN (OPEN, IN_PROGRESS)` AND `updated_at < now() - 24 hours` |
| SLA breach (v2) | Same count as stale |
| Open high | `OPEN` + `HIGH` severity |
| Sidebar badge | `open_high_severity_count` or dedicated endpoint — visible to **both** roles |

---

## 10. Frontend structure

```
src/
  features/
    cases/
      CasePage.tsx
      components/
        CaseHeader.tsx
        TradeFactsCard.tsx
        MlSignalCard.tsx
        InvestigationPanel.tsx
        WorkflowPanel.tsx
        ActivityTimeline.tsx
    queue/
      QueuePage.tsx
    overview/
      OfficerOverview.tsx
  lib/
    auth/
      usePermissions.ts      # role + case.permissions
    api/
      endpoints/cases.ts
      endpoints/session.ts
      types/investigationPresentation.ts
```

**Auth:** `AuthContext` holds `user.role`, `displayName`; bootstrap via `GET /auth/session`.

**Permissions:** Prefer `permissions` from case bundle over client-only role checks.

**Theme:** Default dark in theme provider; persist user preference.

**Polling:** `refetchInterval: 3000` when investigation running or alert `IN_PROGRESS` from AI.

---

## 11. Demo accounts

Provision in Supabase Auth + `ensure_app_user` role override:

| Email | Role | Display name |
|-------|------|----------------|
| `analyst@demo.sentinel` | `ANALYST` | Demo Analyst |
| `officer@demo.sentinel` | `COMPLIANCE_LEAD` | Demo Officer |

Passwords: set in Supabase dashboard; document in API `.env.example` or internal demo doc (not committed).

---

## 12. Implementation backlog

### Phase P0 — Foundation

| ID | API | Web |
|----|-----|-----|
| P0-1 | Status enum + migration (`PENDING_OFFICER_REVIEW`) | Status labels, filters, badges |
| P0-2 | `investigations.review_status` + approve endpoint | Approve UI + workflow gating |
| P0-3 | `GET /auth/session`; extend login `user` | Role, landing redirect, `usePermissions` |
| P0-4 | `GET /cases/{id}` | `/cases/[alertId]` page |
| P0-5 | `POST assign`, `take`, `escalate`, `close` | Workflow panel |
| P0-6 | Demo user role mapping | Login demo hints |
| P0-7 | Extended metrics | Overview cards + sidebar badges |
| P0-8 | Unique investigation per `alert_id` | — |

### Phase P1 — Trust & US narrative

| ID | Work |
|----|------|
| P1-1 | `InvestigationPresentation` builder | Section-based UI |
| P1-2 | Data gaps + dismiss hint banner | |
| P1-3 | System notes on assign / escalate / close / approve | Activity timeline |
| P1-4 | `/team` page | |
| P1-5 | Rule parsing from `rule_violated` | |

### Phase P2 — Polish

| ID | Work |
|----|------|
| P2-1 | Remove ticker; redirect `/alerts/[id]` → `/cases/[id]` | |
| P2-2 | Trade & investigation explorers | |
| P2-3 | Responsive Case (tabs) | |
| P2-4 | Export case PDF (optional) | |

---

## 13. Explicitly out of scope (v2)

- Auto-close on AI `DISMISS`
- Multiple investigations per alert
- WebSockets (polling only for v2)
- Native mobile app
- Full OMS / IBOR integration
- Assign-by-email writes
- Global live market ticker in shell
- Public unauthenticated alert lists

---

## 14. Appendix: Current vs v2

| Area | Current (v1) | v2 |
|------|----------------|-----|
| Home | `/overview` for everyone | Role-based: `/queue` or `/overview` |
| Alert detail | Drawer on `/alerts` | `/cases/[id]` full page |
| Escalation | Unclear / `ESCALATED` status | `PENDING_OFFICER_REVIEW` |
| Close | PATCH with role check | `POST /close` officer only |
| Assign | Email string | `users.id` |
| Investigation complete | When AI returns | After analyst approve |
| Session | JWT only | JWT + `role` in session |
| Investigation UI | Raw fields in drawer | `InvestigationPresentation` sections |
| Ticker | Global yfinance strip | Removed |

---

## References

- API architecture: `CLAUDE.md` in `trade-surveillance-api`
- Web setup: `README.md` in `trade-surveillance-web`
- Agent memo schema: `trade_surveillance/agents/prompts.py`
- MVP goal (historical): analyst alert → disposition in &lt; 2 minutes (still valid for analyst path up to escalate)
