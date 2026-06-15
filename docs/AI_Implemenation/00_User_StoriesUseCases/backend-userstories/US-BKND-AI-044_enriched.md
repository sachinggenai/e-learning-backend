# US-BKND-AI-044: Two-Tier Model Architecture

**Status:** ✅ COMPLETE
**Priority:** SHOULD
**Sprint:** 5
**Implemented:** 2026-06-15

## Summary

Two-tier model router that classifies AI tasks and routes them to the appropriate model: PLANNER (fast/cheap haiku-class, $0.80/M input) for list/fetch/help tasks, and GENERATOR (powerful sonnet-class, $3.00/M input) for create/update/delete/generate tasks. Estimated 60-80% cost savings vs. all-generator routing.

## Task Classification

| Tier | Model | Use Cases |
|---|---|---|
| PLANNER | claude-haiku-4 | list_pages, fetch_page, help, validate, search |
| GENERATOR | claude-sonnet-4 | propose_create/update/delete, generate_course, assessments |
