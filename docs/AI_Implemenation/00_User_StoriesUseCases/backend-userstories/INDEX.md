# Backend AI User Stories — Index

**Total Backend Stories:** 47 (5 prerequisites + 42 AI backend stories)
**Last Updated:** 2026-06-14

---

## Story ID Convention

- `US-BKND-AI-PR01` through `US-BKND-AI-PR05` — Prerequisites (mock auth/authz/tenant/session/user)
- `US-BKND-AI-001` through `US-BKND-AI-050` — Backend AI implementation stories

Each story has a corresponding file: `US-BKND-AI-XXX_enriched.md`

---

## Sprint 0 — Prerequisites (Auth/AuthZ/Tenancy)

| Story ID | Title | Status | Priority |
|---|---|---|---|
| [US-BKND-AI-PR01](US-BKND-AI-PR01_enriched.md) | Mock Authentication Service | ✅ COMPLETE | MUST |
| [US-BKND-AI-PR02](US-BKND-AI-PR02_enriched.md) | Mock Authorization Service | ✅ COMPLETE | MUST |
| [US-BKND-AI-PR03](US-BKND-AI-PR03_enriched.md) | Mock Multi-Tenancy Context | ✅ COMPLETE | MUST |
| [US-BKND-AI-PR04](US-BKND-AI-PR04_enriched.md) | Mock Session Auth Middleware | ✅ COMPLETE | MUST |
| [US-BKND-AI-PR05](US-BKND-AI-PR05_enriched.md) | Mock User & Organization Resolver | ✅ COMPLETE | MUST |

---

## Sprint 1 — Foundations

| Story ID | Title | Status | Priority |
|---|---|---|---|
| [US-BKND-AI-001](US-BKND-AI-001_enriched.md) | Preserve Manual Authoring (Backend) | ✅ COMPLETE | MUST |
| [US-BKND-AI-002](US-BKND-AI-002_enriched.md) | Configure AI Feature Flags, Models, Provider Routing | ✅ COMPLETE | MUST |
| [US-BKND-AI-003](US-BKND-AI-003_enriched.md) | Create Isolated AI API Module | ✅ COMPLETE | MUST |
| [US-BKND-AI-004](US-BKND-AI-004_enriched.md) | Add AI Persistence Foundations | ✅ COMPLETE | MUST |
| [US-BKND-AI-005](US-BKND-AI-005_enriched.md) | Version Tool Schemas and Template Contracts | ✅ COMPLETE | MUST |

---

## Sprint 2 — Sessions & Validation

| Story ID | Title | Status | Priority |
|---|---|---|---|
| [US-BKND-AI-006](US-BKND-AI-006_enriched.md) | Create Scoped AI Authoring Sessions | ✅ COMPLETE | MUST |
| [US-BKND-AI-007](US-BKND-AI-007_enriched.md) | List and Fetch Course Pages for AI Context | ✅ COMPLETE | MUST |
| [US-BKND-AI-008](US-BKND-AI-008_enriched.md) | Unify Course/Page/Schema/Export/Accessibility Validation | ✅ COMPLETE | MUST |
| [US-BKND-AI-009](US-BKND-AI-009_enriched.md) | Implement Generic Proposal Lifecycle | ✅ COMPLETE | MUST |
| [US-BKND-AI-010](US-BKND-AI-010_enriched.md) | Apply Proposals with Idempotency, Audit, Outbox | ✅ COMPLETE | MUST |
| [US-BKND-AI-049](US-BKND-AI-049_enriched.md) | Confirmation Token System for Destructive Operations | ❌ TODO | MUST |

---

## Sprint 3 — Core CRUD Flows

| Story ID | Title | Status | Priority |
|---|---|---|---|
| [US-BKND-AI-011](US-BKND-AI-011_enriched.md) | Propose and Apply AI-Created Pages | ✅ COMPLETE | MUST |
| [US-BKND-AI-012](US-BKND-AI-012_enriched.md) | Propose and Apply AI Updates to Existing Pages | ✅ COMPLETE | MUST |
| US-BKND-AI-013 | Propose and Confirm Destructive Page Deletes | ❌ TODO | MUST |
| [US-BKND-AI-014](US-BKND-AI-014_enriched.md) | Simple Chat Edit Orchestration (Backend) | ✅ COMPLETE | MUST |
| [US-BKND-AI-029](US-BKND-AI-029_enriched.md) | Batch Proposal and All-or-Nothing Semantics | ✅ COMPLETE | SHOULD |

---

## Sprint 4 — RAG, File Ingestion, Course Generation

| Story ID | Title | Status | Priority |
|---|---|---|---|
| [US-BKND-AI-015](US-BKND-AI-015_enriched.md) | Retrieve Similar Courses for Examples and Tone | ✅ COMPLETE | SHOULD |
| [US-BKND-AI-016](US-BKND-AI-016_enriched.md) | File Upload and Ingestion Job Foundation | ✅ COMPLETE | MUST |
| [US-BKND-AI-017](US-BKND-AI-017_enriched.md) | Extract Documents and Review Page Breakdown | ✅ COMPLETE | MUST |
| US-BKND-AI-019 | Generate Full Course From Uploaded File | ❌ TODO | SHOULD |

---

## Sprint 5 — Chat Orchestration & Platform

| Story ID | Title | Status | Priority |
|---|---|---|---|
| US-BKND-AI-023 | AI Chat Endpoint and LLM Interaction Loop | ❌ TODO | MUST |
| US-BKND-AI-025 | Prompt Safety and Content Guardrails | ❌ TODO | MUST |
| [US-BKND-AI-026](US-BKND-AI-026_enriched.md) | Multi-Provider Model Routing and Fallback | ✅ COMPLETE | SHOULD |
| US-BKND-AI-027 | JSON Repair and Structured Output Recovery | ❌ TODO | SHOULD |
| US-BKND-AI-028 | Context Pruning and Token Optimization | ❌ TODO | SHOULD |
| [US-BKND-AI-031](US-BKND-AI-031_enriched.md) | RLHF Feedback and Provenance Tracking | ✅ COMPLETE | SHOULD |
| US-BKND-AI-032 | Policy Engine for Auto-Apply Decisions | ❌ TODO | COULD |
| US-BKND-AI-034 | Durable Workflow Engine for Long-Running AI Jobs | ❌ TODO | COULD |
| US-BKND-AI-041 | Async Preview Generation Service | ❌ TODO | COULD |
| US-BKND-AI-042 | System Prompt Versioning and A/B Testing | ❌ TODO | COULD |
| US-BKND-AI-044 | Two-Tier Model Architecture (Planner + Generator) | ❌ TODO | SHOULD |

---

## Sprint 6 — Operations & Governance

| Story ID | Title | Status | Priority |
|---|---|---|---|
| US-BKND-AI-020 | Admin Audit, Compliance, and Recovery Views | ❌ TODO | SHOULD |
| US-BKND-AI-021 | Production Observability, Rate Limits, Rollout Gates | ❌ TODO | MUST |
| US-BKND-AI-022 | E2E Regression and Release Readiness Tests (Backend) | ❌ TODO | MUST |
| [US-BKND-AI-033](US-BKND-AI-033_enriched.md) | Event-Driven Outbox for Downstream Consumers | ✅ COMPLETE | SHOULD |
| [US-BKND-AI-035](US-BKND-AI-035_enriched.md) | AI Content Accessibility Compliance | ✅ COMPLETE | SHOULD |
| US-BKND-AI-036 | Cost Tracking and Token Budget Enforcement | ❌ TODO | SHOULD |
| US-BKND-AI-037 | Template Definition Harvesting from AI Content | ❌ TODO | COULD |
| US-BKND-AI-038 | SCORM Export Readiness for AI-Generated Content | ❌ TODO | SHOULD |
| US-BKND-AI-039 | Session Context Window Recovery | ❌ TODO | SHOULD |
| US-BKND-AI-040 | AI Content Versioning and Rollback | ❌ TODO | COULD |

---

## Sprint 7 — Cross-Cutting Concerns

| Story ID | Title | Status | Priority |
|---|---|---|---|
| US-BKND-AI-030 | Course Assembly into Existing Editor State | ❌ TODO | MUST |
| US-BKND-AI-043 | Concurrency Control and Page Locking | ❌ TODO | MUST |
| US-BKND-AI-045 | Real-Time Job Status Service | ❌ TODO | SHOULD |
| US-BKND-AI-046 | AI-Assisted Course-Level Operations | ❌ TODO | SHOULD |
| US-BKND-AI-047 | Multi-User Collaboration Service | ❌ TODO | COULD |
| US-BKND-AI-048 | Dead Letter Queue and Failed Job Recovery | ❌ TODO | SHOULD |
| US-BKND-AI-050 | Stale Detection and Merge Resolution | ❌ TODO | SHOULD |

---

## Quick Stats

- ✅ **COMPLETE:** 26 stories ready for implementation
- ❌ **TODO:** 21 stories need writing
- **Total:** 47 backend stories

---

## Related Documents

- [Frontend Stories Index](../frontend-userstories/INDEX.md) — Frontend companion stories
- [Original USER_STORIES.md](../USER_STORIES.md) — Dependency order and MVP recommendations
- [Prerequisite Mock Stories](../PREREQUISITE_MOCK_STORIES.md) — Full prerequisite specs
- [Research Audit](../RESEARCH_AUDIT.md) — Coverage gaps and completeness audit
