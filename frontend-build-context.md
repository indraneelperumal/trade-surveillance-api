# Frontend Build Context (Trade Surveillance MVP)

## 1) Product Context

This project is a trade surveillance MVP.

- **Frontend**: separate Next.js app (`surveillance-web`)
- **Backend**: this FastAPI repo (`surveillance-api`)
- **Data/Auth/Storage**: Supabase (Postgres, Auth, Storage)

The backend owns all data access and business logic.  
Frontend should consume backend APIs only.

---

## 2) Project Goals (MVP)

1. Give compliance analysts a fast way to review flagged trades.
2. Support core investigation workflow:
   - view alert
   - inspect related trade and context
   - add/update investigation notes
   - set disposition/status
3. Keep an auditable trail of who changed what and when.
4. Expose model run metadata for transparency and operations.

---

## 3) Intended User Roles (MVP)

- **Analyst**
  - triage alerts
  - write notes
  - run/update investigations
- **Compliance Lead**
  - review analyst outcomes
  - finalize disposition/escalation
  - monitor model-run quality

Role-based restrictions can be tightened later with Supabase Auth + RLS.

---

## 4) Current Backend API Surface

Base path: `/api/v1`

### Health
- `GET /health` (root)
- `GET /api/v1/health`

### Trades
- `POST /api/v1/trades`
- `GET /api/v1/trades?offset=0&limit=50&symbol=AAPL`
- `GET /api/v1/trades/{trade_id}`
- `PATCH /api/v1/trades/{trade_id}`
- `DELETE /api/v1/trades/{trade_id}`

### Alerts
- `POST /api/v1/alerts`
- `GET /api/v1/alerts?offset=0&limit=50`
- `GET /api/v1/alerts/{alert_id}`
- `PATCH /api/v1/alerts/{alert_id}`
- `DELETE /api/v1/alerts/{alert_id}`

### Investigations
- `POST /api/v1/investigations`
- `GET /api/v1/investigations?offset=0&limit=50&alert_id={uuid}`
- `GET /api/v1/investigations/{investigation_id}`
- `PATCH /api/v1/investigations/{investigation_id}`
- `DELETE /api/v1/investigations/{investigation_id}`

### Investigation Notes
- `POST /api/v1/investigation-notes`
- `GET /api/v1/investigation-notes?offset=0&limit=100&alert_id={uuid}&investigation_id={uuid}`
- `GET /api/v1/investigation-notes/{note_id}`
- `PATCH /api/v1/investigation-notes/{note_id}`
- `DELETE /api/v1/investigation-notes/{note_id}`

### Model Runs
- `POST /api/v1/model-runs`
- `GET /api/v1/model-runs?offset=0&limit=50`
- `GET /api/v1/model-runs/{model_run_id}`
- `PATCH /api/v1/model-runs/{model_run_id}`
- `DELETE /api/v1/model-runs/{model_run_id}`

### Users
- `POST /api/v1/users`
- `GET /api/v1/users?offset=0&limit=50`
- `GET /api/v1/users/{user_id}`
- `PATCH /api/v1/users/{user_id}`
- `DELETE /api/v1/users/{user_id}`

---

## 5) Response Contracts (Important)

### List endpoints (paginated)
All list endpoints return:

```json
{
  "items": [],
  "total": 0,
  "offset": 0,
  "limit": 50
}
```

### Error envelope
All errors are normalized:

```json
{
  "error": {
    "code": "404",
    "message": "Alert not found",
    "details": null
  }
}
```

Use this for centralized frontend error handling.

---

## 6) What Frontend Should Show (MVP)

## A) Dashboard / Overview
- total alerts (open/in-progress/closed)
- severity split (HIGH/MEDIUM/LOW/NONE)
- anomaly type split
- latest model run status and metrics

## B) Alerts List (Primary Screen)
- sortable/filterable table:
  - alert id
  - symbol
  - anomaly type
  - severity
  - status
  - disposition
  - created/updated time
  - assignee
- filters:
  - status
  - severity
  - anomaly type
  - symbol (via trade relation)
- pagination controls (offset/limit)

## C) Alert Detail
- full alert metadata
- linked trade snapshot (price, volume, side, symbol, timestamp, off-hours, otc)
- latest investigation result
- timeline of investigation notes
- action panel:
  - change status/disposition
  - assign/reassign
  - add note
  - trigger/create investigation

## D) Investigations
- investigation list (global + per-alert)
- detail view:
  - verdict
  - confidence
  - summary
  - evidence points
  - recommended action
  - data gaps
- edit/update controls for analyst workflow

## E) Notes / Audit Trail
- chronological note stream
- note author + timestamp + note type
- system vs human notes indicator

## F) Model Runs (Ops/QA Tab)
- recent runs with status
- metrics card (recall, precision, flagged count, total records)
- runtime and failure reasons
- run metadata view (parameters/artifacts)

## G) User Admin (Lightweight)
- list users
- edit role / active status
- create user records mapped to supabase uid

---

## 7) What Frontend Should NOT Show (MVP)

- Raw backend implementation details:
  - internal DB ids not useful to analysts
  - stack traces
  - internal exception text (beyond safe message)
- Low-level model internals unless needed:
  - full artifact blobs
  - giant JSON dumps by default
- AWS legacy pipeline controls:
  - Kinesis/Glue/Athena-specific operations
- Destructive actions in top-level UI:
  - hard-delete buttons in high-visibility screens without guardrails
- Overly complex analytics pages before core workflow is smooth.

---

## 8) Suggested Frontend Information Architecture

1. **Overview**
2. **Alerts**
   - list
   - alert detail drawer/page
3. **Investigations**
4. **Model Runs**
5. **Users** (admin only)

Navigation should prioritize analyst triage speed over deep menu depth.

---

## 9) UX Notes for Trade Surveillance

- Default to newest/highest-risk first.
- Keep critical signal fields always visible:
  - severity, anomaly type, status, verdict
- Make actions frictionless:
  - status change, note add, assign in one place
- Preserve auditability:
  - show who updated and when
- Avoid noisy dashboards that hide real alerts.

---

## 10) Frontend Technical Recommendations

- Next.js App Router + TypeScript
- TanStack Query for API state/caching
- React Hook Form + Zod for form validation
- Table library (TanStack Table) for filter/sort/pagination UX
- Centralized API client:
  - typed request/response models
  - shared error envelope parser

Environment in frontend:

- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`

---

## 11) API Gaps to Add Next (Backend backlog)

To improve frontend ergonomics, add:

1. Combined alert-detail endpoint (`alert + trade + latest investigation + notes preview`)
2. Alert aggregate endpoint (counts by status/severity/type)
3. Search endpoints (symbol/trader/client quick search)
4. Bulk actions (bulk assign / bulk status update)
5. Soft delete/archive semantics instead of hard delete in analyst workflows.

---

## 12) MVP Success Criteria

- Analyst can move from alert queue to disposition in < 2 minutes.
- Every alert action is traceable in notes/audit timeline.
- Frontend never directly touches DB; only backend APIs.
- Error handling is consistent and user-safe.
- Core screens remain performant with large datasets (200k+ trades backing data).

