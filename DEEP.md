# VendorCheck — Architecture

## Overview
AI vendor risk assessment platform. Evaluates SaaS/AI vendors against a weighted checklist (GDPR, data privacy, lock-in, SLA) and provides portfolio-level risk dashboards.

## Data Model

```
vendors ───────────────────────────
  id, name, vendor_url, use_case, category, next_review_date, created_at
  └── 1:N → evaluations
  └── 1:N → vendor_tags
  └── 1:N → vendor_contracts

evaluations ───────────────────────
  id, vendor_id, answers (JSON), total_score, risk_level,
  passed, failed, critical_fails (JSON), recommendations (JSON), created_at

vendor_tags ───────────────────────
  id, vendor_id, tag, created_at
  UNIQUE(vendor_id, tag)

vendor_contracts ──────────────────
  id, vendor_id, contract_name, start_date, end_date,
  annual_value, auto_renew, notes, created_at
```

## Scoring Engine

14 boolean checklist fields + 2 numeric (SLA uptime %, incident response hours).

**Weights** (total max = 104 with SLA + IR bonuses):
- Critical (10): gdpr_compliant, no_training_on_your_data, exit_clause_clean
- High (8-9): data_deletion_guaranteed, pricing_predictable, lock_in_risk_low
- Medium (5-7): data_residency, drift_monitoring, explainability, benchmarks, support, onboarding

**Risk thresholds**: >=80 low, >=60 medium, >=40 high, <40 critical.
**Override**: >=2 critical field failures → always "critical".

## Vendor Categories
10 predefined categories: ai_ml, cloud, security, analytics, communication, database, devops, fintech, hr_tech, other.
Vendors can be assigned a category for filtering and analytics.

## Review Scheduling
Vendors have an optional next_review_date. The /vendors/due-for-review endpoint returns vendors past their review date with days_overdue calculation.

## Contract Tracking
Each vendor can have multiple contracts with start/end dates, annual value, and auto-renew flag. The /vendors/expiring-contracts endpoint returns contracts expiring within a configurable window (default 30 days).

## Key Decisions

### 1. Checklist-based scoring (not LLM)
Deterministic, auditable scoring. Every point traceable to a specific field+weight.
LLM could be added for recommendation text generation later.

### 2. Tags as separate table
Many-to-many via vendor_tags. Enables cross-cutting queries:
"show all AI vendors" or "vendors used by team-data". UNIQUE constraint prevents duplicates.

### 3. Portfolio risk = aggregate of latest evaluations
Each vendor contributes its most recent evaluation. Critical vendors bubble up.
Overall risk level determined by: any critical vendor → portfolio is critical.

### 4. Contracts as separate table (v1.6.0)
One vendor → many contracts. Tracks annual value, renewal status, expiry. Enables proactive contract management with expiring-contracts endpoint.

## API Surface (v1.6.0)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| /vendors | POST | Create vendor (with optional category) |
| /vendors | GET | List vendors (filter by category) |
| /vendors/{id} | GET/PATCH/DELETE | Vendor CRUD (set category, next_review_date) |
| /vendors/{id}/assess | POST | Run checklist evaluation |
| /vendors/{id}/history | GET | Score trend over time |
| /vendors/{id}/tags | POST/GET | Add/list tags |
| /vendors/{id}/tags/{tag} | DELETE | Remove tag |
| /vendors/{id}/contracts | POST/GET | Create/list contracts |
| /vendors/compare?ids= | GET | Side-by-side comparison |
| /vendors/due-for-review | GET | Vendors past review date |
| /vendors/expiring-contracts | GET | Contracts expiring within N days |
| /contracts/{id} | PATCH/DELETE | Update/delete contract |
| /categories/stats | GET | Per-category vendor analytics |
| /tags | GET | All unique tags with counts |
| /tags/{tag}/vendors | GET | Vendors by tag |
| /portfolio/risk | GET | Aggregate risk dashboard |
| /evaluations | GET | List evaluations |
| /evaluations/{id} | GET/DELETE | Evaluation detail |
| /evaluations/stats | GET | Stats across all evals |
| /evaluations/export/csv | GET | CSV download |
| /health | GET | Health + version |
