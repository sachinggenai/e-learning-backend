# Current LLM Architecture — E-Learning Backend

> **Date:** 2026-06-27
> **Branch:** `demo-course-AI-pradeep-01`
> **Purpose:** Document every LLM integration point, model, and provider in the codebase before planning local LLM setup.

---

## 1. LLM Provider Abstraction

### 1.1 `LLMClient` (`app/services/ai/llm_client.py`)

The central LLM abstraction. All AI chat/streaming goes through this class.

| Aspect | Detail |
|--------|--------|
| **File** | `app/services/ai/llm_client.py` |
| **Class** | `LLMClient` |
| **Provider enum** | `LLMProvider.ANTHROPIC` or `LLMProvider.MOCK` |
| **SDK** | `anthropic` Python SDK (`anthropic.AsyncAnthropic`) |
| **Methods** | `chat()` — non-streaming, `chat_stream()` — SSE streaming |
| **Streaming** | Anthropic SDK native `client.messages.stream()` |
| **Mock** | Deterministic mock returns help/echo text (no network, no cost) |

### 1.2 `ANTHROPIC_BASE_URL` — Custom Endpoint

```python
# llm_client.py lines 243-246 (chat) and 323-326 (stream)
base_url = os.getenv("ANTHROPIC_BASE_URL", "")
if base_url:
    client_kwargs["base_url"] = base_url
```

**This is the key integration point for local LLMs.** When `ANTHROPIC_BASE_URL` is set, the Anthropic SDK connects to that URL instead of `https://api.anthropic.com`. This means any proxy/server that speaks the Anthropic Messages API can serve as the backend.

---

## 2. Model Registry

Defined in `app/services/ai/config.py` — `AIConfig._build_model_registry()`.

### 2.1 Active Models (hardcoded allowlist)

| Model ID | Provider | API Model Name | Tier | Max Tokens | Cost/1K in | Cost/1K out |
|----------|----------|----------------|------|------------|------------|-------------|
| `deepseek-v4-pro[1m]` | anthropic | deepseek-v4-pro[1m] | GENERATOR | 8192 | $0.001 | $0.005 |
| `deepseek-v4-flash` | anthropic | deepseek-v4-flash | PLANNER | 4096 | $0.0003 | $0.0015 |
| `claude-sonnet-4-20250514` | anthropic | claude-sonnet-4-20250514 | GENERATOR | 16384 | $3.00/M | $15.00/M |
| `claude-haiku-4-20250514` | anthropic | claude-haiku-4-20250514 | PLANNER | 4096 | $0.80/M | $4.00/M |

### 2.2 Model Tiers (Two-Tier Architecture)

```
User Request
    │
    ▼
ModelTierRouter.classify_task()
    │
    ├── PLANNER Tier (fast/cheap)
    │   ├── deepseek-v4-flash
    │   └── claude-haiku-4-20250514
    │   Used for: intent classification, tool selection, simple queries,
    │             list_pages, fetch_page, help, validate
    │
    └── GENERATOR Tier (powerful/expensive)
        ├── deepseek-v4-pro[1m]
        └── claude-sonnet-4-20250514
        Used for: content creation, proposals, assessments, generate_course
```

### 2.3 Model Selection Env Vars

```bash
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]     # Default primary
AI_FALLBACK_MODEL=deepseek-v4-flash      # Default fallback
```

---

## 3. All LLM Call Sites

### 3.1 Chat Orchestrator (`app/services/ai/chat_orchestrator.py`)

| Method | LLM Call | Purpose |
|--------|----------|---------|
| `process_message_stream()` | `client.chat_stream()` | Real-time SSE token streaming to frontend |
| `process_message()` | `client.chat()` | Non-streaming chat (backward compat) |
| `run_llm_loop()` | `client.chat()` | Tool-calling loop with tool definitions |

**Model routing**: Uses `ModelTierRouter` to select Planner vs Generator model based on task type.

### 3.2 Specialist Agents (`app/services/ai/agents/`)

| Agent | File | Model Tier | Purpose |
|-------|------|------------|---------|
| **PlannerAgent** | `planner_agent.py` | PLANNER | Page breakdown from document sections |
| **TemplateSelectorAgent** | `template_selector_agent.py` | PLANNER | Template type selection (hybrid rules+LLM) |
| **ContentGeneratorAgent** | `content_generator_agent.py` | GENERATOR | Page content generation + JSON repair |

All three use `LLMClient` with `LLMProvider.ANTHROPIC`. They degrade gracefully to deterministic fallbacks when LLM is unavailable.

### 3.3 LangGraph Course Generation (`app/services/ai/langgraph/`)

| Component | File | LLM Usage |
|-----------|------|-----------|
| **SupervisorRouter** | `supervisor.py` | Optional LLM call for anomaly routing decisions |
| **Course Generation Graph** | `course_generation_graph.py` | Orchestrates Planner → Selector → Generator agents |
| **Fanout** | `fanout/__init__.py` | Parallel template selection and content generation |

### 3.4 Course Generator (`app/services/ai/course_generator.py`)

- Controlled by `AI_GENERATION_PROVIDER` env var (`llm`/`anthropic`/`mock`)
- In LLM mode: calls agents for each page
- In Mock mode: deterministic placeholder content (no LLM calls)

### 3.5 Workflow Engine (`app/services/workflow/`)

| Step | LLM Usage |
|------|-----------|
| `course_generation.py` | Calls CourseGenerator (which may call LLM) |
| `scorm_export.py` | No LLM (pure file I/O + XSD validation) |

---

## 4. Embeddings (RAG/Similar Courses)

| Aspect | Detail |
|--------|--------|
| **File** | `app/services/ai/embedding_provider.py` |
| **Provider** | `OpenAIBackend` (via `openai.AsyncOpenAI`) or `MockEmbeddingProvider` |
| **Model** | `text-embedding-ada-002` (configurable via `EMBEDDING_MODEL`) |
| **Dimension** | 1536 |
| **Env var** | `EMBEDDING_PROVIDER` — `"openai"` or `"mock"` |
| **Database** | pgvector extension (PostgreSQL), with JSONB fallback |

---

## 5. Safety / Guardrails

### 5.1 SafetyService (`app/services/ai/safety_service.py`)

- **First line**: Regex-based pattern matching (9 injection patterns + 10 PII patterns)
- **No LLM dependency**: Pure rule-based, no API calls
- **Always active** when safety is enabled

### 5.2 NeMo Guardrails (`app/services/ai/nemo_guard.py`)

- **Second line**: ML-based semantic detection (optional)
- **No LLM dependency**: Uses local NeMo models, no API calls
- **Graceful degradation**: Falls back to regex-only when NeMo unavailable

---

## 6. Cost Tracking

| File | Purpose |
|------|---------|
| `app/services/ai/cost_tracker.py` | Records token usage after each LLM call |
| `app/services/ai/model_tier_router.py` | Tracks routing stats (planner vs generator calls) |

---

## 7. Key Env Vars Summary

```bash
# ── Master switch ─────────────────────────────────────
AI_AUTHORING_ENABLED=true          # Master toggle

# ── API credentials ──────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...       # Anthropic API key
ANTHROPIC_BASE_URL=                # Custom endpoint (LOCAL LLM KEY!)

# ── Model selection ──────────────────────────────────
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]
AI_FALLBACK_MODEL=deepseek-v4-flash

# ── Generation provider ──────────────────────────────
AI_GENERATION_PROVIDER=mock         # "llm" / "anthropic" / "mock"

# ── Embeddings ────────────────────────────────────────
EMBEDDING_PROVIDER=mock             # "openai" / "mock"
OPENAI_API_KEY=sk-...               # Required for OpenAI embeddings
EMBEDDING_MODEL=text-embedding-ada-002

# ── Token budgets ────────────────────────────────────
AI_MAX_INPUT_TOKENS=8000
AI_MAX_OUTPUT_TOKENS=4096
AI_TOTAL_TOKEN_BUDGET=12000

# ── Safety ───────────────────────────────────────────
AI_PROMPT_SAFETY_ENABLED=true
AI_OUTPUT_SAFETY_ENABLED=true
```

---

## 8. Dependency Graph

```
ChatOrchestrator ───► LLMClient ───► anthropic.AsyncAnthropic
     │                    │
     │                    └──► ANTHROPIC_BASE_URL (custom endpoint)
     │
     ├──► ModelTierRouter (planner vs generator)
     ├──► SafetyService (regex, no LLM)
     └──► NeMoGuardrailsService (ML, optional, no LLM)

PlannerAgent ───► LLMClient ───► same as above
TemplateSelectorAgent ───► LLMClient ───► same as above
ContentGeneratorAgent ───► LLMClient ───► same as above

SupervisorRouter ───► LLMClient (optional) ───► same as above

CourseGenerator ───► PlannerAgent + TemplateSelectorAgent + ContentGeneratorAgent

EmbeddingProvider ───► openai.AsyncOpenAI (embeddings only)
```

---

> **Next:** See [02_Local_LLM_Options.md](02_Local_LLM_Options.md) for local LLM setup options.
