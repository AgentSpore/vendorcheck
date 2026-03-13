# VendorCheck — Development Log

## v1.6.0 (2026-03-13)
- **Vendor categories**: 10 categories (ai_ml, cloud, security, analytics, communication, database, devops, fintech, hr_tech, other)
- Category filter on GET /vendors?category=ai_ml
- Per-category analytics: GET /categories/stats (vendor count, avg score, risk distribution)
- **Review scheduling**: next_review_date field on vendors, GET /vendors/due-for-review with days_overdue
- **Contract tracking**: vendor_contracts table — POST/GET /vendors/{id}/contracts, PATCH/DELETE /contracts/{id}
- Expiring contracts endpoint: GET /vendors/expiring-contracts?within_days=30
- Contract fields: contract_name, start_date, end_date, annual_value, auto_renew, notes
- Bumped v1.5.0 → v1.6.0

## v1.5.0 (2026-03-13)
- Evaluation weighting and recommendation improvements
- Minor fixes and stability

## v1.4.0 (2026-03-13)
- **Tags**: vendor_tags table, POST/DELETE /vendors/{id}/tags, GET /tags, GET /tags/{tag}/vendors
- **Portfolio risk**: GET /portfolio/risk — aggregate score, risk distribution, critical vendors list
- **Bug fix**: removed broken create_evaluation import, fixed init_db() call (no db param needed)
- **Docs**: added DEEP.md (architecture), MEMORY.md (this file)
- Tags now included in all vendor responses and comparison output
- Vendor deletion cascades to tags + evaluations
- Bumped v1.4.0

## v1.3.0
- Vendor comparison: GET /vendors/compare?ids=1,2,3
- Evaluation history with trend: GET /vendors/{id}/history
- CSV export: GET /evaluations/export/csv
- Evaluation stats: GET /evaluations/stats
- Vendor CRUD: PATCH, DELETE

## v1.2.0
- Assessment scoring engine: 14 boolean + 2 numeric fields
- Weighted scoring with critical field override
- Risk levels: low/medium/high/critical
- Auto-generated recommendations

## v1.0.0
- Initial: vendor CRUD + basic evaluation storage
