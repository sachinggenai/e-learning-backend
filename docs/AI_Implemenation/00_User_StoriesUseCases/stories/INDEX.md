# User Story Index — AI Authoring Epic

**Total Stories:** 55 (5 prerequisites + 50 AI stories)
**Last Updated:** 2026-06-14

---

## How to Use This Index

Each story exists as an individual file in `stories/` directory. Stories marked **COMPLETE** have full 8-section enriched specs. Stories marked **DRAFT** need additional enrichment.

**Status Legend:**
- ✅ **COMPLETE** — Full enriched spec with all 8 sections: Functional, Technical, NFRs, Current State, Expansion, Validation, DoD, Tasks
- ⚠️ **EXISTS** — Content available in epic file but not yet extracted to individual file
- ❌ **MISSING** — Needs to be written

---

## Prerequisites (Sprint 0 — Auth/AuthZ/Tenancy)

| Story ID | Title | Status | File |
|---|---|---|---|
| US-AI-PR01 | Mock Authentication Service | ✅ COMPLETE | [PREREQUISITE_MOCK_STORIES.md](../PREREQUISITE_MOCK_STORIES.md) § US-AI-PR01 |
| US-AI-PR02 | Mock Authorization Service | ✅ COMPLETE | [PREREQUISITE_MOCK_STORIES.md](../PREREQUISITE_MOCK_STORIES.md) § US-AI-PR02 |
| US-AI-PR03 | Mock Multi-Tenancy Context | ✅ COMPLETE | [PREREQUISITE_MOCK_STORIES.md](../PREREQUISITE_MOCK_STORIES.md) § US-AI-PR03 |
| US-AI-PR04 | Mock Session Auth Middleware | ✅ COMPLETE | [PREREQUISITE_MOCK_STORIES.md](../PREREQUISITE_MOCK_STORIES.md) § US-AI-PR04 |
| US-AI-PR05 | Mock User & Organization Resolver | ✅ COMPLETE | [PREREQUISITE_MOCK_STORIES.md](../PREREQUISITE_MOCK_STORIES.md) § US-AI-PR05 |

---

## Foundations (US-AI-001 through US-AI-010)

| Story ID | Title | Status | File |
|---|---|---|---|
| US-AI-001 | Preserve Manual Authoring While Adding AI Entry Points | ✅ COMPLETE | [US-AI-001_enriched.md](US-AI-001_enriched.md) |
| US-AI-002 | Configure AI Feature Flags, Models, and Provider Routing | ✅ COMPLETE | [US-AI-002_enriched.md](US-AI-002_enriched.md) |
| US-AI-003 | Create an Isolated AI API Module | ✅ COMPLETE | [US-AI-003_enriched.md](US-AI-003_enriched.md) |
| US-AI-004 | Add AI Persistence Foundations | ✅ COMPLETE | [US-AI-004_enriched.md](US-AI-004_enriched.md) |
| US-AI-005 | Version Tool Schemas and Template Contracts | ✅ COMPLETE | [US-AI-005_enriched.md](US-AI-005_enriched.md) |
| US-AI-006 | Create Scoped AI Authoring Sessions | ✅ COMPLETE | [US-AI-006_enriched.md](US-AI-006_enriched.md) |
| US-AI-007 | List and Fetch Course Pages for AI Context | ✅ COMPLETE | [US-AI-007_enriched.md](US-AI-007_enriched.md) |
| US-AI-008 | Unify Course, Page, Schema, Export, and Accessibility Validation | ✅ COMPLETE | [US-AI-008_enriched.md](US-AI-008_enriched.md) |
| US-AI-009 | Implement Generic Proposal Lifecycle | ✅ COMPLETE | [US-AI-009_enriched.md](US-AI-009_enriched.md) |
| US-AI-010 | Apply Proposals with Idempotency, Audit, and Outbox Events | ✅ COMPLETE | [US-AI-010_enriched.md](US-AI-010_enriched.md) |

---

## Core Flows (US-AI-011 through US-AI-022)

| Story ID | Title | Status | File |
|---|---|---|---|
| US-AI-011 | Propose and Apply AI-Created Pages | ✅ COMPLETE | [US-AI-011_enriched.md](US-AI-011_enriched.md) |
| US-AI-012 | Propose and Apply AI Updates to Existing Pages | ✅ COMPLETE | [US-AI-012_enriched.md](US-AI-012_enriched.md) |
| US-AI-013 | Propose and Confirm Destructive Page Deletes | ❌ MISSING | — |
| US-AI-014 | Support Simple Chat Edit Scenario | ✅ COMPLETE | [US-AI-014_enriched.md](US-AI-014_enriched.md) |
| US-AI-015 | Retrieve Similar Courses for Examples and Tone | ✅ COMPLETE | [US-AI-015_enriched.md](US-AI-015_enriched.md) |
| US-AI-016 | Add File Upload and Ingestion Job Foundation for AI | ✅ COMPLETE | [US-AI-016_enriched.md](US-AI-016_enriched.md) |
| US-AI-017 | Extract Documents and Review Proposed Page Breakdown | ✅ COMPLETE | [US-AI-017_enriched.md](US-AI-017_enriched.md) |
| US-AI-018 | Display Course Validation Reports to Authors and Reviewers | ❌ MISSING | — |
| US-AI-019 | Generate a Full Course From an Uploaded File | ❌ MISSING | — |
| US-AI-020 | Provide Admin Audit, Compliance, and Recovery Views | ❌ MISSING | — |
| US-AI-021 | Add Production Observability, Rate Limits, and Rollout Gates | ❌ MISSING | — |
| US-AI-022 | Build End-to-End Regression and Release Readiness Tests | ❌ MISSING | — |

---

## Orchestration & Platform (US-AI-023 through US-AI-032)

| Story ID | Title | Status | File |
|---|---|---|---|
| US-AI-023 | AI Chat Endpoint and LLM Interaction Loop | ❌ MISSING | — |
| US-AI-024 | Frontend AI Integration Layer | ❌ MISSING | — |
| US-AI-025 | Prompt Safety and Content Guardrails | ❌ MISSING | — |
| US-AI-026 | Multi-Provider Model Routing and Fallback | ✅ COMPLETE | [US-AI-026_enriched.md](US-AI-026_enriched.md) |
| US-AI-027 | JSON Repair and Structured Output Recovery | ❌ MISSING | — |
| US-AI-028 | Context Pruning and Token Optimization | ❌ MISSING | — |
| US-AI-029 | Batch Proposal and All-or-Nothing Semantics | ✅ COMPLETE | [US-AI-029_enriched.md](US-AI-029_enriched.md) |
| US-AI-030 | Course Assembly into Existing Editor State | ❌ MISSING | — |
| US-AI-031 | RLHF Feedback and Provenance Tracking | ✅ COMPLETE | [US-AI-031_enriched.md](US-AI-031_enriched.md) |
| US-AI-032 | Policy Engine for Auto-Apply Decisions | ❌ MISSING | — |

---

## Operations & Improvement (US-AI-033 through US-AI-042)

| Story ID | Title | Status | File |
|---|---|---|---|
| US-AI-033 | Event-Driven Outbox for Downstream Consumers | ✅ COMPLETE | [US-AI-033_enriched.md](US-AI-033_enriched.md) |
| US-AI-034 | Durable Workflow Engine for Long-Running AI Jobs | ❌ MISSING | — |
| US-AI-035 | AI Content Accessibility Compliance | ✅ COMPLETE | [US-AI-035_enriched.md](US-AI-035_enriched.md) |
| US-AI-036 | Cost Tracking and Token Budget Enforcement | ❌ MISSING | — |
| US-AI-037 | Template Definition Harvesting from AI Content | ❌ MISSING | — |
| US-AI-038 | SCORM Export Readiness for AI-Generated Content | ❌ MISSING | — |
| US-AI-039 | Session Context Window Recovery | ❌ MISSING | — |
| US-AI-040 | AI Content Versioning and Rollback | ❌ MISSING | — |
| US-AI-041 | Async Preview Generation Service | ❌ MISSING | — |
| US-AI-042 | System Prompt Versioning and A/B Testing | ❌ MISSING | — |

---

## Cross-Cutting Gaps (US-AI-043 through US-AI-050)

| Story ID | Title | Status | File |
|---|---|---|---|
| US-AI-043 | Concurrency Control and Page Locking | ❌ MISSING | — |
| US-AI-044 | Two-Tier Model Architecture (Planner + Generator) | ❌ MISSING | — |
| US-AI-045 | Real-Time Job Status and Notifications | ❌ MISSING | — |
| US-AI-046 | AI-Assisted Course-Level Operations | ❌ MISSING | — |
| US-AI-047 | Multi-User Collaboration on AI-Authored Content | ❌ MISSING | — |
| US-AI-048 | Dead Letter Queue and Failed Job Recovery | ❌ MISSING | — |
| US-AI-049 | Confirmation Token System for Destructive Operations | ❌ MISSING | — |
| US-AI-050 | Stale Detection and Merge Resolution | ❌ MISSING | — |

---

## Quick Stats

- ✅ **COMPLETE (ready for implementation):** 24 stories (5 PR + 19 AI)
- ❌ **MISSING (needs writing):** 31 stories
- **Total:** 55 stories

## Priority for Writing Missing Stories

1. **Immediate:** US-AI-013, US-AI-018 through US-AI-025 (core MVP)
2. **Next:** US-AI-027, US-AI-028, US-AI-030, US-AI-032 (orchestration gaps)
3. **Then:** US-AI-034, US-AI-036 through US-AI-050 (operations + new gaps)

---

## Related Documents

- [USER_STORIES.md](../USER_STORIES.md) — Dependency order, flow coverage, MVP recommendations
- [PREREQUISITE_MOCK_STORIES.md](../PREREQUISITE_MOCK_STORIES.md) — 5 prerequisite mock service stories
- [RESEARCH_AUDIT.md](../RESEARCH_AUDIT.md) — Coverage audit with 20 identified gaps
- [EPIC_COMPREHENSIVE_PART1.md](../EPIC_COMPREHENSIVE_PART1.md) — Monolithic enriched epic (1.3MB, source for extracted stories)
