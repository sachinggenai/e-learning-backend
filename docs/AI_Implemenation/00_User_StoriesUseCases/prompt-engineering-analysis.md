# Prompt Engineering Analysis — MCP Architecture Session

> **Source:** `session-prompts-log.md` (62 prompts)
> **Role:** Prompt Engineer / AI Architect Review
> **Date:** 2026-06-29

---

## Analysis Format

Each prompt is analyzed across 4 dimensions:

| Dimension | What We Check |
|-----------|---------------|
| **Intent Clarity** | Is the goal unambiguous? Could the LLM misinterpret? |
| **Context Completeness** | What implicit context is missing that the LLM needs? |
| **Constraints & Guardrails** | Are there explicit do's/don'ts, format, scope limits? |
| **Verification Criteria** | How would the LLM know it succeeded? Accept/reject criteria? |

---

## Prompt 1: Session History

**Original:**
> Provide me the session history which is running previously which was closed recently

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ Ambiguous — "session history" could mean transcript, git log, or file listing |
| **Context Missing** | Location of session files unknown to LLM. Which directory? What format? |
| **Constraints** | None — no time range, no format preference, no length limit |
| **Verification** | No definition of "done" |

**Engineered Version:**
> Locate and summarize the most recent Claude Code session transcript
> from `~/.claude/projects/C--Users-ADMIN-e-learning-backend/`.
> Return: session ID, date range, branch, files modified, key tasks completed,
> and what was in-progress when it closed. Limit to the 2 most recent sessions.

**Improvements:** Specified exact path, output format, scope limit, defined "done."

---

## Prompt 5: Proxy Strategy Discussion

**Original:**
> then instead of buliding adopter to convert local llm to anthropic or wise versa,
> can we think another possible solutions, the code should be able to connect with
> any llms(may be use stratgy pattter, or may some morder Agient architecture to
> handle it) perfrom unbiase Analysis as an Archtect, come up best solutions for
> current senrio

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ "another possible solutions" is vague. "Best" is subjective. |
| **Context Missing** | Doesn't mention existing architecture, constraints (GPU VRAM, local vs cloud) |
| **Constraints** | No mention of: must preserve existing API contracts, must work with 836 tests, latency budget |
| **Verification** | No criteria for evaluating "best" |

**Engineered Version:**
> **Role:** Solution Architect
> **Context:** Our `llm_client.py` is tightly coupled to Anthropic SDK via `LLMProvider.ANTHROPIC`.
> Adding Ollama required a translation proxy (`local_proxy.py`) — fragile, hard to maintain.
> We need the app to work with Anthropic, OpenAI, Ollama, and DeepSeek without proxy layers.
>
> **Constraints:**
> - Zero breaking changes to `LLMClient` public API (862 tests must pass)
> - Must support streaming + tool calling across all providers
> - Local GPU: RTX 2060 (6GB VRAM) limits model size to 7B params
> - Latency budget: PLANNER <3s, GENERATOR <15s
>
> **Deliverable:** Present 3 architecture options with trade-off matrix (effort, risk, maintainability,
> provider coverage). Include recommendation with justification. Use existing patterns in the
> codebase (`LLMProvider` enum, `ModelTierRouter`, `AIConfig` model registry).

**Improvements:** Set explicit role, provided full context, listed hard constraints, defined deliverable format.

---

## Prompt 6: MCP Architecture Plan

**Original:**
> As Agentic AI Architect, I would like to find out impactected code(area) file, class,
> method, lines of code to implment option 3, than care fully desing solution to update
> code to achive option 3 vai production grade solutions, and build compleete TRD,
> make sure you perfrom enough research in all 3 modules, Local LLM, AI Implemeantion
> and cources generation module, make srue seperation of concern achived at production
> grade level

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ "Option 3" requires prior context (MCP Architecture from previous response) |
| **Context Missing** | Which modules are "all 3"? Not explicitly named. Research depth undefined. |
| **Constraints** | "Production grade" is vague. No error budget, latency SLA, backward compat requirement. |
| **Verification** | What defines "complete TRD"? No template or sections specified. |

**Engineered Version:**
> **Role:** Agentic AI Architect designing an MCP (Model Context Protocol) based
> LLM provider abstraction layer.
>
> **Research Scope (3 modules):**
> 1. `app/services/ai/` — LLMClient, ChatOrchestrator, config, model_tier_router, all agents
> 2. `app/mcp/` — existing MCP servers (content_writer, safety_scan, template_registry)
> 3. `app/services/ai/course_generator.py` + `agents/` + `langgraph/` — course generation pipeline
>
> **Deliverable — TRD with these sections:**
> 1. Impacted files matrix (file, class, method, lines changed)
> 2. Architecture diagram (ASCII)
> 3. New class hierarchy (ABCs, interfaces)
> 4. Canonical message format specification
> 5. Phased migration plan (P0-P5 with verification gates)
> 6. Degradation strategy (MCP-down fallback tiers)
> 7. Test protection plan (how 836 tests survive)
> 8. Configuration changes (new env vars)
>
> **Constraints:**
> - Zero breaking changes to router layer (ai_chat.py, ai_tools.py, etc.)
> - Mock provider MUST stay in-process (no MCP dependency for tests)
> - Streaming and tool calling must work across all backends
> - Must support dynamic provider registration at runtime

**Improvements:** Named exact modules, provided TRD template, set hard constraints, defined research depth.

---

## Prompt 13: Real LLM Validation

**Original:**
> don't try to run any thing with mock we need use actual llm, mcp, RAG, AI Agent to
> validate. mock is not an to validate its regration, now restart validate, every fail
> when it fails perfrom RCA, and coument it in old docs c:\Users\ADMIN\e-learning-backend\docs\TPO-Gap-Analysis-TRD.md
> c:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\E-Learning_AI_Postman_Collection.json,
> make sure you use local llm actal call whcih recetnly setup completed

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ "validate" is broad — which endpoints? What's pass/fail? |
| **Context Missing** | Postman collection has 52 endpoints; should all be tested? In what order? |
| **Constraints** | No timeout limits, no retry policy, no data cleanup after validation |
| **Verification** | RCA depth undefined. Where exactly to document? |

**Engineered Version:**
> **Goal:** Validate the Postman collection (`E-Learning_AI_Postman_Collection.json`)
> against the live API using ONLY real local LLM (Ollama qwen2.5:7b + phi3:mini via
> MCP Gateway). No mock backend, no cloud API.
>
> **Validation Rules:**
> - Every endpoint must receive a real LLM response (verify Gateway logs for POST
>   /v1/chat/completions with 200 OK)
> - RAG calls must reach tier1 pgvector (verify `retrieval_tier_used` in response)
> - Session trace must show actual model names, not "mock"
> - Document ANY failure with: root cause chain (3+ levels deep), code location,
>   fix approach, before/after evidence
>
> **Documentation targets:**
> - RCA → `docs/TPO-Gap-Analysis-TRD.md` (new Part E)
> - Postman fixes → update the collection JSON directly
>
> **Success criteria:** 90%+ endpoints return 2xx with real LLM content and
> correct token usage. All failures have documented RCA.

**Improvements:** Defined "validate" precisely, set success criteria, specified RCA depth, named exact doc targets.

---

## Prompt 17: RAG Vector DB Seed

**Original:**
> now As RAG is returning empty, now try to understant what quest we are makeing from RAG,
> expected data should existing in vectordb, check if data existing, data if so data follow
> exect same embading encoding as expected by llm, if data did not exting identfy what data
> need to store, what source we can use to populate vector db and which embeding encoding
> need to use which compitble, validate you research if it will work or not, make sure
> perfrom above analysis not only for one flow for all flow defined under .mmd files, make
> a script to populate vectore db carefully to achive intented output, take a un-bias
> architect review after you design solutions and address feedback, revalidate use case by
> use case after runing thing script, vctordb are returning intent data, wirte unit test
> case to validate and run those test, make sure I should be able to run this scipt any
> time in future to update vector db, the first line should take back of vector db solution
> we can re-store data incase if issue occured

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ Long run-on sentence buries the core ask. Multiple asks interleaved. |
| **Context Missing** | Which .mmd files? Where are the RAG flows defined? What data sources exist? |
| **Constraints** | No mention of: embedding dimension, Ollama model to use, backup location |
| **Verification** | "Return intent data" is vague — what queries should return what? |

**Engineered Version:**
> **Goal:** Populate pgvector `course_embeddings` table so the 3-tier RAG pipeline
> returns results at tier1 (cosine similarity), not just tier3 (keyword fallback).
>
> **Phase 1 — Audit:**
> 1. Check all `.mmd` flow files under `docs/AI_Implemenation/` for RAG query patterns
> 2. Verify `course_embeddings` table exists + check current vector dimension
> 3. Confirm embedding model compatibility (nomic-embed-text = 768-dim)
> 4. List all courses in DB and check if any have embeddings
>
> **Phase 2 — Design:**
> 1. Identify data sources for seed content (existing courses, sample data, templates)
> 2. Fix any dimension mismatches (ALTER TABLE if needed)
> 3. Design backup strategy (first line of script = export to JSON)
>
> **Phase 3 — Implementation:**
> Create `scripts/seed_vectordb.py` with:
> - `--backup-only` flag (export course_embeddings to timestamped JSON)
> - `--restore FILE` flag (import from backup)
> - Auto-seed 5 sample courses if DB is empty
> - Embed using `nomic-embed-text` via Ollama `/api/embed`
> - Validate with 6 test queries (expect correct course match with score >0.5)
> - Idempotent: check `content_hash` to skip unchanged courses
>
> **Phase 4 — Validation:**
> 1. Run script, verify tier1 returns results via `POST /api/v1/ai/tools/query_similar_courses`
> 2. Check session trace confirms `retrieval_tier_used: tier1`
> 3. Run script again — must be idempotent (no duplicate embeddings)

**Improvements:** Structured into 4 clear phases, specified exact flags, defined success criteria with thresholds.

---

## Prompt 27: LLM-Driven Breakdown

**Original:**
> implement option C, make sure you pass desire context incuding relevent embedding from
> RAG, Template details etc as much as needed

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ "Option C" requires context from previous analysis response |
| **Context Missing** | Which function to replace? What's the current behavior? What context is "desired"? |
| **Constraints** | No fallback behavior specified. No model choice. No max_tokens consideration. |
| **Verification** | How to confirm LLM breakdown is better than rule-based? |

**Engineered Version:**
> **Goal:** Replace the rule-based `_suggest_template()` function in
> `app/routers/ai_ingestion.py` with an LLM-powered `_llm_propose_breakdown()`
> that semantically understands document content to select the best template type.
>
> **Context to pass to the LLM:**
> 1. Full TEMPLATE_SCHEMAS from `ContentGeneratorAgent` (all 5 types with component JSON)
> 2. RAG similar courses via pgvector (top 3 by cosine similarity)
> 3. Section content previews (first 500 chars each)
> 4. Section char_counts (to decide merge/split)
>
> **LLM Configuration:**
> - Model: phi3:mini (PLANNER tier, fast classification)
> - temperature: 0.3 (deterministic template selection)
> - max_tokens: 8192 (large JSON output needs headroom)
> - Via MCP Gateway (`http://localhost:8004/v1/chat/completions`)
>
> **Output Schema:**
> ```json
> [{"title": "Descriptive Page Title", "template_type": "final-assessment",
>   "rationale": "Why this template was chosen", "source_section_ids": [0,1],
>   "order": 0}]
> ```
>
> **Fallback:** If LLM unavailable or returns invalid JSON, fall back to
> `_rule_based_breakdown()` (existing keyword matching).
>
> **Success Criteria:**
> - LLM correctly identifies assessment content (quiz/test/final-exam sections)
> as `final-assessment` template type
> - Page titles are descriptive (not filename)
> - At least one `final-assessment` page detected in CSA docx

**Improvements:** Named exact function to replace, specified all context sources, set model params, defined JSON schema, set success criteria.

---

## Prompt 33: Deep RCA Request

**Original:**
> Now act as AI Architect trage Chat (real LLM — qwen2.5:7b) 3/4 ⚠️ 1 fail (token count cosmetic)
> + Proposals 4/5 ⚠️ 1 fail (cancel 403) perfrom deep RCA, provide root cause analusis with
> possible soluoution and recommendation

| Dimension | Analysis |
|-----------|----------|
| **Intent Clarity** | ⚠️ References a table from a previous response — not self-contained |
| **Context Missing** | Which test are these failures from? What's the expected behavior? |
| **Constraints** | RCA depth undefined. "Deep" means how many levels? |
| **Verification** | No definition of acceptable resolution |

**Engineered Version:**
> **Role:** AI Architect performing Root Cause Analysis on production test failures.
>
> **Failure 1 — Token Usage 0/0:**
> - Test: `scripts/validate_api_flows.py` Flow 5 (Chat)
> - Symptom: `token_usage: {input: 0, output: 0}` despite valid content returned
> - Expected: `token_usage: {input: >0, output: >0}`
> - Trace shows phi3:mini (PLANNER tier) was used for this call
>
> **Failure 2 — Cancel Proposal 403:**
> - Test: Flow 6 (Proposals) — cancel step
> - Symptom: `PERMISSION_DENIED: Session doesn't own this proposal`
> - Session and proposal were created in same validator run
>
> **RCA Depth Required:** Minimum 4 levels — symptom → code path → root cause →
> architectural gap. Include: exact file:line, variable values at failure point,
> why existing tests didn't catch this.
>
> **Deliverable:** For each failure — root cause statement, 3 fix options with
> effort/risk ratings, recommended approach with justification.

**Improvements:** Made each failure self-contained, specified RCA depth (4 levels), required file:line precision, structured fix options format.

---

## Prompt 6 (Plan Mode): Quick Reference Card

**What made this prompt effective:**
- Explicit role assignment ("Agentic AI Architect")
- Specific artifact requested ("complete TRD")
- Named 3 modules for research scope
- Required production-grade separation of concerns

**What could improve it:**
- Add a TRD template/sections list so the LLM knows exact sections expected
- Specify phase count and verification gates per phase
- Include backward-compatibility constraint explicitly

---

## Prompt 13 (Real LLM Validation): Quick Reference Card

**What made this prompt effective:**
- Strong constraint: "no mock" repeated twice for emphasis
- Specific file paths for documentation output
- Clear acceptance criteria: use local LLM calls only

**What could improve it:**
- Define "validate" with a checklist: status codes, response fields, trace evidence
- Set a minimum pass rate threshold
- Specify which endpoints need LLM vs which are pure CRUD

---

## Prompt 17 (Vector DB Seed): Quick Reference Card

**What made this prompt effective:**
- Explicit phases: audit, design, implement, validate
- Reusability requirement ("run this script any time in future")
- Backup-first principle ("first line should take backup")
- Verification: unit tests + revalidation

**What could improve it:**
- Separate into numbered sub-tasks for easier tracking
- Add specific data source candidates
- Define validation queries and expected matches explicitly

---

## Summary: Pattern Anti-Patterns

### Common Anti-Patterns Found

| Anti-Pattern | Example | Fix |
|-------------|---------|-----|
| **Pronoun without antecedent** | "Option 3", "that approach", "continue with task 5" | Always name the thing: "MCP Architecture (Option 3)" |
| **Implicit context from chat history** | "Proceed to Phase 2" | Include 1-line context: "Phase 2 = Integration — wire main app to MCP Gateway" |
| **"Best" without criteria** | "best solution for current scenario" | Define criteria: "lowest code change, 100% test compat, streaming support" |
| **Run-on multi-asks** | Prompt 17 (6 asks in 1 sentence) | Number sub-tasks, separate phases with clear gates |
| **Missing verification** | "validate it works" | Add: "verify Gateway log shows 200 OK, trace shows real model name" |

### Prompt Engineering Principles Applied

1. **Role assignment** — "Act as AI Architect" frames the response quality
2. **Context injection** — Provide file paths, line numbers, existing patterns
3. **Constraint enumeration** — "Zero breaking changes", "Must pass 836 tests"
4. **Deliverable format** — "Return JSON array", "Create MD with these sections"
5. **Verification gate** — "Success when tier1 returns results at >0.5 similarity"
6. **Fallback specification** — "If LLM unavailable, use rule-based keyword matching"
