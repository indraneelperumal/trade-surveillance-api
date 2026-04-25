# Trade Surveillance MVP Stack (Recommended)

## Goals

1. Separate Next.js frontend repo
2. Separate backend API repo
3. Use Supabase instead of S3-heavy AWS stack

---

## Best MVP Stack

### Frontend repo
- Next.js (App Router) + TypeScript
- Tailwind + shadcn/ui
- TanStack Query for API data fetching/caching
- Deploy on Vercel

### Backend repo
- FastAPI (Python)
- Pydantic for request/response contracts
- SQLAlchemy + Alembic (or Supabase Postgres client directly)
- Deploy on Railway / Render / Fly.io

### Data/Auth/Storage
- Supabase Postgres (primary database)
- Supabase Auth (sessions, roles)
- Supabase Storage (memo JSON, artifacts, files)
- Row Level Security (RLS) from day 1

### Background jobs
- Start with simple scheduled backend jobs
- Add Celery + Redis or pg_cron only when needed

---

## What To Avoid For MVP

Avoid these now unless scale/compliance forces it:
- Kinesis
- Glue
- Athena
- Lambda fan-out pipelines
- Complex orchestration frameworks

---

## Minimal v1 Architecture

- Next.js frontend calls FastAPI endpoints
- FastAPI reads/writes Supabase Postgres
- Scoring runs as backend batch job (periodic)
- Results stored in DB tables
- Frontend reads from API only

---

## Core MVP Tables

- trades_raw
- trade_features
- alerts
- investigations
- investigation_notes
- model_runs
- users/roles mapping (with RLS policies)

Keep queryable state in Postgres; store large files in Supabase Storage.

---

## Why This Is The Right MVP Choice

- Keeps Python for ML/scoring
- Clean frontend/backend separation
- Lower ops burden versus AWS-heavy architecture
- Faster iteration with small team
- Clear upgrade path later

---

## 3-Step Execution Plan

1. Freeze MVP scope: alert list, detail, disposition, audit trail
2. Set up two repos: `surveillance-web` and `surveillance-api`
3. Build DB schema + APIs first, then integrate model jobs

