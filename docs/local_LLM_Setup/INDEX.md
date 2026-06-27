# Local LLM Setup — Index

> **Branch:** `demo-course-AI-pradeep-01`
> **Date:** 2026-06-27

---

## Documents

| # | File | Description |
|---|------|-------------|
| 1 | [01_Current_LLM_Architecture.md](01_Current_LLM_Architecture.md) | Full audit of every LLM call site, model, provider, and env var in the codebase |
| 2 | [02_Local_LLM_Options.md](02_Local_LLM_Options.md) | Options for running local LLMs (Ollama, LM Studio, vLLM, LiteLLM proxy) with setup steps |
| 3 | [03_Implementation_Roadmap.md](03_Implementation_Roadmap.md) | Phased plan: Phase 0 (zero-code proxy, 30 min) → Phase 3 (production-hardened local support) |
| 4 | [**04_System_Analysis_And_Recommendation.md**](04_System_Analysis_And_Recommendation.md) | **Your system analyzed → specific recommendation** |

---

## Key Takeaways

### What LLMs does the app use?

The app uses the **Anthropic SDK** to call models. The model registry has 4 models:

| Model | Tier | Purpose |
|-------|------|---------|
| `deepseek-v4-pro[1m]` | GENERATOR | Content generation, proposals, assessments |
| `deepseek-v4-flash` | PLANNER | Intent classification, tool selection, planning |
| `claude-sonnet-4-20250514` | GENERATOR | Premium fallback |
| `claude-haiku-4-20250514` | PLANNER | Budget fallback |

**All** chat/streaming goes through `LLMClient` → `anthropic.AsyncAnthropic` SDK.

Embeddings use OpenAI SDK (`text-embedding-ada-002`) with a Mock fallback.

### Can I run local LLMs?

**Yes, two ways:**

1. **Today (zero code changes):** Set `ANTHROPIC_BASE_URL=http://localhost:4000` and run LiteLLM proxy → Ollama/LM Studio
2. **With code changes (Phase 1):** Add `LLMProvider.OPENAI` to `LLMClient`, then point directly at Ollama/LM Studio

### Quickest path

```
winget install Ollama.Ollama
ollama pull llama3.1:8b
ollama pull phi3:mini
pip install litellm[proxy]
litellm --config litellm_config.yaml --port 4000

# .env:
ANTHROPIC_BASE_URL=http://localhost:4000
ANTHROPIC_API_KEY=sk-local-proxy-key
AI_GENERATION_PROVIDER=llm
```

Then start the app. All LLM calls route to your local models.

### What about embeddings?

For dev, use `EMBEDDING_PROVIDER=mock` (zero dependencies). For local production embeddings, point `OPENAI_BASE_URL` at Ollama with `nomic-embed-text`.

---

## File Map — All LLM-Related Code

```
app/services/ai/
├── llm_client.py              ← THE central abstraction (anthropic SDK)
├── config.py                  ← AIConfig, ModelConfig, model registry
├── model_tier_router.py       ← Task → tier (planner/generator) routing
├── embedding_provider.py      ← OpenAI embeddings + mock fallback
├── chat_orchestrator.py       ← Main chat loop, SSE streaming
├── course_generator.py        ← AI_GENERATION_PROVIDER env var
├── agents/
│   ├── planner_agent.py       ← Page breakdown (PLANNER tier)
│   ├── template_selector_agent.py ← Template selection (PLANNER tier)
│   └── content_generator_agent.py ← Page content (GENERATOR tier)
├── langgraph/
│   ├── supervisor.py           ← Anomaly routing (optional LLM)
│   ├── course_generation_graph.py ← Orchestration graph
│   └── fanout/__init__.py     ← Parallel content generation
├── safety_service.py          ← Regex safety (no LLM)
├── nemo_guard.py              ← ML safety (local NeMo, no LLM API)
├── cost_tracker.py            ← Token usage recording
└── context_manager.py         ← Token counting + pruning
```
