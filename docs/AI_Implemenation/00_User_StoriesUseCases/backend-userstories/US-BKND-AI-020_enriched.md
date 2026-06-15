# US-BKND-AI-020: Admin Audit, Compliance, and Recovery Views

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 6
**Implemented:** 2026-06-15

## Summary

Admin audit query service with filtering (user, course, operation, session, outcome, date range, text search), pagination, operations summary aggregation, and per-course change history. Read-only compliance endpoints for admin dashboard.

## Endpoints Added

| Endpoint | Description |
|---|---|
| GET /api/v1/ai/admin/audit-logs | Query with filters + pagination |
| GET /api/v1/ai/admin/audit-summary | Aggregated ops by type/user/outcome |
| GET /api/v1/ai/admin/audit-logs/course/{id} | Time-ordered course change history |
