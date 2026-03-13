# VendorCheck — Development Log

## v1.4.0 (2026-03-13)
- **Tags**: vendor_tags table, POST/DELETE /vendors/{id}/tags, GET /tags, GET /tags/{tag}/vendors
- **Portfolio risk**: GET /portfolio/risk — aggregate score, risk distribution, critical vendors list
- **Bug fix**: removed broken `create_evaluation` import, fixed `init_db()` call (no db param needed)
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
