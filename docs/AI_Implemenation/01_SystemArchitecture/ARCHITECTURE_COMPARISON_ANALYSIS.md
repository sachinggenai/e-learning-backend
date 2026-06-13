# AI Architecture Comparison: Attached Plans vs. New Production Prompt

**Date:** 2026-06-13  
**Analysis Scope:** Evaluate attached AI implementation documents against new senior architect production requirements

---

## Executive Summary

| Dimension | Attached Docs | New Prompt | Winner | Gap Severity |
|-----------|---------------|-----------|--------|--------------|
| **Contract/Tool Definition** | ⚠️ Present in `TOOL_SCHEMAS_CLAUDE_NATIVE.md` but not fully integrated into the main narrative | ✅ Explicit JSON schema + tool specs | New Prompt | **HIGH** |
| **State Management** | ⚠️ Mentions "session" vaguely | ✅ Detailed re-fetch + DB-source-of-truth rule | New Prompt | **HIGH** |
| **Change Validation Pipeline** | ⚠️ "Validator blocks invalid" | ✅ Propose→Validate→Confirm→Apply gating | New Prompt | **HIGH** |
| **File Ingestion** | ❌ Missing entirely | ✅ Deterministic parsing + LLM segmentation + human checkpoint | New Prompt | **CRITICAL** |
| **RAG vs. Tools Strategy** | ❌ Not addressed | ✅ Explicit definition + refresh strategy | New Prompt | **MEDIUM** |
| **Security/Permissions** | ⚠️ Brief mention | ✅ Tool-scoping, audit logging, rate limits, server-side enforcement | New Prompt | **MEDIUM** |
| **Failure/Fallback Behavior** | ✅ Detailed per-tool | ⚠️ Generic framework | Attached Docs | **LOW** |
| **Implementation Phasing** | ✅ 8 chunks + delivery modes | ⚠️ Not in new prompt scope | Attached Docs | **LOW** |
| **Deliverable Specificity** | ⚠️ Strategy + narrative | ✅ Architecture diagram + schemas + system prompt | New Prompt | **MEDIUM** |

---

## Section-by-Section Comparison

### 1. Tool/Function Contract Layer

#### Attached Docs
**Strengths:**
- Mentions template registry and JSON schema validation
- Includes high-level API contracts (request/response shape)
- Notes "validator blocks invalid structures before UI apply"

**Weaknesses:**
- No explicit tool definitions with JSON schema
- No function-calling contract (assumes tools exist; doesn't define them)
- No input/output validation examples
- No permission scoping rules at tool level
- No idempotency guarantees per tool
- Treats tools as backend responsibility; doesn't specify tool-calling API format for Claude

**Code Example Gap:**
```
# Attached docs show this (incomplete):
GET /ai/models
POST /ai/chat (create mode only)

# Missing (new prompt requires):
- Tool schema: create_page { courseId, pageTitle, templateType, ... }
- Input constraints: enum for templateType, required vs optional fields
- Output error shape: { code, field, message } for validation failures
- Idempotency: "create_page with same requestId = no-op"
- Permission scoping: "tool execution scoped server-side to session courseId"
```

**Verdict:** ⚠️ **Attached docs include tool schema artifacts in `TOOL_SCHEMAS_CLAUDE_NATIVE.md`, but they need stronger integration with the narrative and execution flow.** The new prompt still adds higher operational rigor around how tool schemas are used in production.

---

### 2. Session & State Management

#### Attached Docs
**Strengths:**
- Mentions "courseContext" in request/response
- Notes "preserve current course unchanged" on failure
- Discusses "course assembly into existing UI state"

**Weaknesses:**
- No explicit rule: "re-fetch state before each edit"
- No conversation-to-session mapping strategy
- No guidance on how to survive context window truncation
- Assumes state syncs via prior turns; doesn't enforce backend source-of-truth
- No explicit session lifecycle (creation, scope, timeout)

**Governance Gap:**
```
# Attached docs assume:
"courseContext": { "courseId": "optional", "currentCourse": {} }

# New prompt requires (production-critical):
- "Any edit operation must first re-fetch current page state via tool call"
- DB = source of truth, not conversation history
- Session mapping: session_id → user_id, org_id, courseId
- Context truncation strategy: how state survives?
```

**Verdict:** ⚠️ **Attached docs risky.** If AI relies on prior conversation turns for state, and context truncates, AI will operate on stale data. New prompt's "re-fetch before edit" rule is **production-essential**.

---

### 3. Change Validation & Confirmation Gating

#### Attached Docs
**Strengths:**
- Mentions "validator blocks invalid structures"
- Includes schema validation + business rules
- Notes "review-before-apply UX" for refinements (Chunk 6)
- Discusses one-time repair retry for JSON

**Weaknesses:**
- No explicit propose → validate → confirm → apply pipeline
- No "destructive operations require separate confirmation step"
- No distinction between validation error vs. business rule violation
- No multi-page batch operation strategy (all-or-nothing vs. per-page status)
- No preview diff mechanism before apply
- Assumes "user sees generation summary" but doesn't define how

**Missing Production Flow:**
```
# Attached docs stop here:
1. AI generates plan
2. Validator checks schema + rules
3. "User can review before publish/export"

# New prompt requires (detailed):
1. Propose tool call (returns diff/preview, NO mutation)
2. Validate step (JSON schema + business rules, server-side)
3. Confirm step (user approval for destructive ops)
4. Apply step (only then mutate DB)
5. Define: batch operation failure mode (all-or-nothing vs per-page)
6. Define: error response when validation fails
```

**Verdict:** ⚠️ **Attached docs incomplete.** New prompt's gating pipeline is stricter and production-safe. Without explicit confirm-before-apply, AI could accidentally delete/overwrite on retry.

---

### 4. File Ingestion Pipeline

#### Attached Docs
**Coverage:** ❌ **MISSING ENTIRELY**

The attached docs mention:
- "optionally from uploaded files (PDF/DOCX)" in the new prompt context
- No strategy in any of the three attached files

**New Prompt Requirement:**
```
1. Deterministic extraction step (structured parsing of PDF/DOCX)
   - Extract sections/headings/tables BEFORE LLM segmentation
2. LLM segmentation step (map sections to template suggestions)
3. Human-review checkpoint (propose page breakdown to user before page-creation tool calls)
4. Error handling (malformed/scanned documents)
```

**Verdict:** 🔴 **CRITICAL GAP.** New prompt adds a critical workflow (file ingestion) that attached docs don't address. This is a major addition required for production.

---

### 5. Retrieval Strategy (RAG vs. Tools)

#### Attached Docs
**Coverage:** ❌ **MISSING**

No discussion of:
- When to use RAG vs. strict tool contracts
- What to index (pedagogical examples, similar courses, tone references)
- RAG refresh strategy
- What NOT to RAG on (API contracts, validation rules, template definitions)

**New Prompt Requirement:**
```
RAG: pedagogical examples, similar existing course content, style/tone references
Tools/schemas: anything agent needs to act correctly (API contracts, 
               validation rules, template field definitions)
Indexing strategy: how to refresh RAG store?
```

**Verdict:** ⚠️ **Attached docs incomplete.** New prompt explicitly separates concerns (RAG for examples; tools for execution). This prevents the AI from "RAG'ing" API contracts (a major hallucination risk).

---

### 6. Security & Permissions

#### Attached Docs
**Strengths:**
- Mentions "multi-tenant" permission model (from answers)
- References "feature flag" for beta control

**Weaknesses:**
- No explicit tool-scoping rule: "tool execution scoped server-side to session courseId"
- No audit logging requirements (before/after diffs, user ID, timestamp)
- No rate limits / cost controls
- No mention of "no direct DB access tool exposed"
- No secret/credential redaction in logs

**Missing Production Guardrails:**
```
# Attached docs don't specify:
- "Tool execution must be scoped server-side to the session's course UUID"
- "Agent cannot be trusted to self-limit via prompt text"
- "Every tool call is audit-logged: before/after diffs, user ID, timestamp"
- "Rate limits / cost controls per session"
```

**Verdict:** ⚠️ **Attached docs insufficient.** New prompt's server-side scoping rule is critical: **the LLM cannot be trusted to respect boundaries in its prompt instructions alone.** Server must enforce scope.

---

### 7. Failure & Fallback Behavior

#### Attached Docs
**Strengths:**
- Detailed fallback model strategy (GPT-4.1 → GPT-4.1-mini)
- Chunk 8 covers regression testing + fallback simulation
- Mentions "friendly error messages" in chat panel
- Includes retry logic (one repair pass for invalid JSON)

**Weaknesses:**
- No strategy for timeout / backend unavailability
- No RAG retrieval failure handling
- No guidance on what to do if tool call validation fails mid-stream
- No circuit breaker / degraded mode

**New Prompt Requirement:**
```
For each tool category, define what agent does when:
- Tool call returns validation error
- Tool call times out or backend unavailable
- RAG retrieval returns nothing relevant
```

**Verdict:** ✅ **Attached docs stronger here.** New prompt doesn't detail fallback strategy. Attached docs' approach to model fallback is solid.

---

### 8. Implementation Phasing & Delivery

#### Attached Docs
**Strengths:**
- 8-chunk plan with clear exit criteria per chunk
- Template-wise rollout (T0–T5)
- Course-wise rollout (C1–C5)
- Page-wise rollout (single page optimization)
- Cross-chunk regression suite
- Go/No-Go checklist for demo

**Weaknesses:**
- Tied to demo-specific scope (5 templates only)
- Assumes manual-first, then AI-second narrative
- Heavy on test cases; light on security/audit design

**New Prompt Coverage:**
- Not in scope (new prompt is architecture-only, not phasing)

**Verdict:** ✅ **Attached docs stronger.** For **delivery**, attached docs are superior. New prompt is architecture; attached docs are implementation roadmap.

---

### 9. Deliverable Format & Specificity

#### Attached Docs
**Output:**
- Narrative prose + JSON examples
- High-level component diagram (ASCII)
- Chunk-by-chunk test cases
- Implementation roadmap

#### New Prompt **Output:**
- Architecture diagram (component-level with data flows)
- Explicit JSON schemas (create_page, update_page, delete_page, etc.)
- System prompt (concise, <1 page)

**Verdict:** 📊 **Different scope.** Attached docs = implementation roadmap; new prompt = production architecture specification. Both needed.

---

## Improvement Areas Not Covered by Attached Docs

| Area | Why Critical | Recommendation |
|------|--------------|-----------------|
| **File Ingestion Pipeline** | Workflow is missing entirely; new files must be handled deterministically | Create upstream document: parsing + segmentation + checkpoint flow |
| **Tool Scoping Enforcement** | LLM cannot be trusted to limit itself via prompt | Require server-side tool-scope validation in every tool call |
| **Propose vs. Apply Separation** | Prevents accidental mutations on retry | Explicit tool contract: propose returns diff only; apply tool is separate |
| **RAG vs. Tools Boundary** | Prevents LLM from hallucinating API contracts | Define indexing scope: no API contracts in RAG store |
| **Session Lifecycle** | State survives context truncation only if DB = source of truth | Document session creation, scope, timeout, cleanup |
| **Audit Logging** | Compliance + debugging requirement missing | Every tool call logged: who, what changed, when, diff |
| **Batch Operation Semantics** | Multi-page edits need clear all-or-nothing or per-page error reporting | Define failure mode explicitly per use case |

---

## Recommendation: Synthesized Approach

✅ **Use Attached Docs For:**
1. Chunk-based phasing (rollout safety)
2. Test case strategy and regression suite
3. Model fallback / cost management
4. Cross-template consistency rules

❌ **Replace/Enhance Attached Docs With New Prompt For:**
1. **Tool/Function Contracts** → Generate explicit JSON schemas from OpenAPI spec
2. **Session/State Management** → Enforce "re-fetch before edit" rule + DB source-of-truth
3. **Change Validation Pipeline** → Propose → Validate → Confirm → Apply gating
4. **File Ingestion Pipeline** → Create upstream deterministic parsing + segmentation + checkpoint
5. **RAG vs. Tools Boundary** → Define scoping: RAG for examples only; tools for execution
6. **Security & Permissions** → Server-side tool-scoping + audit logging + rate limits
7. **Architectural Diagram** → Add component-level diagram with data flows for (a) simple edit, (b) file import, (c) delete

---

## Merged Proposal: "Production-Ready AI Architecture"

If you want a **single, production-grade deliverable**, combine:

1. **Architecture Component Diagram** (new prompt requirement)
2. **Tool/Function Schemas** (new prompt requirement: JSON contract per tool)
3. **Session & State Rules** (new prompt requirement: re-fetch + DB source-of-truth)
4. **File Ingestion Pipeline** (new prompt requirement: parsing + segmentation + checkpoint)
5. **Change Validation Gating** (new prompt requirement: propose → confirm → apply)
6. **Implementation Phasing** (attached docs strength: 8 chunks + template-wise rollout)
7. **Regression & Test Strategy** (attached docs strength: chunk-wise test cases)
8. **Audit & Security** (new prompt requirement: logging + scoping + rate limits)

**This would be ~15–20 pages, but production-complete and immediately implementable.**

---

## Summary Table

| Aspect | Attached | New Prompt | Merged Winner |
|--------|----------|-----------|---------------|
| Implementation roadmap | ✅ Strong | ❌ Not included | **Attached** |
| Tool contracts | ⚠️ Conceptual | ✅ Explicit | **New Prompt** |
| State management | ⚠️ Vague | ✅ Detailed | **New Prompt** |
| File ingestion | ❌ Missing | ✅ Complete | **New Prompt** |
| Security/audit | ⚠️ Brief | ✅ Thorough | **New Prompt** |
| Fallback/resilience | ✅ Good | ⚠️ Generic | **Attached** |
| Deliverable format | ✅ Narrative | ✅ Diagrams + schemas | **Equally good** |
| **OVERALL** | **Development-focused** | **Architecture-focused** | **Use both; merge** |

