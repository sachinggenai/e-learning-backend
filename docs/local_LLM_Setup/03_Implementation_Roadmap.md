# Implementation Roadmap — Local LLM Support

> **Date:** 2026-06-27
> **Goal:** Add native local LLM support to the e-learning backend with minimal code changes.

---

## Phase 0: Zero-Code-Change Quick Start (30 min)

**Use LiteLLM proxy — no app changes needed.**

```
You already have everything you need:
  ANTHROPIC_BASE_URL=http://localhost:4000   ← routes to local
```

### Steps

1. Install Ollama: `winget install Ollama.Ollama`
2. Pull models: `ollama pull llama3.1:8b && ollama pull phi3:mini`
3. Install LiteLLM: `pip install litellm[proxy]`
4. Create LiteLLM config mapping model names → local models
5. Start proxy: `litellm --config litellm_config.yaml --port 4000`
6. Set `.env`:
   ```bash
   ANTHROPIC_BASE_URL=http://localhost:4000
   ANTHROPIC_API_KEY=sk-local-proxy-key
   AI_GENERATION_PROVIDER=llm
   ```

**Done.** The app now routes through LiteLLM → Ollama. Zero app changes.

### Pros/Cons

| Pros | Cons |
|------|------|
| Zero code changes | Extra network hop (localhost → 4000 → 11434) |
| Works today | LiteLLM is another process to manage |
| Model swapping via config | Anthropic → OpenAI translation may lose some fidelity |
| Production-proven pattern | Tool calling might need tuning |

---

## Phase 1: Add OpenAI Provider to LLMClient (2-3 days)

**Remove the proxy — app speaks OpenAI API directly.**

### Changes needed

#### 1.1 `LLMProvider` enum — add `OPENAI`

```python
# app/services/ai/llm_client.py:35
class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"      # NEW
    MOCK = "mock"
```

#### 1.2 `LLMClient.__init__()` — detect provider from env

```python
# app/services/ai/llm_client.py:147-159
def __init__(self, provider=None, ...):
    if provider is None:
        provider_env = os.getenv("LLM_PROVIDER", "anthropic").lower()
        if provider_env == "openai":
            provider = LLMProvider.OPENAI
        elif provider_env == "anthropic":
            provider = LLMProvider.ANTHROPIC
        else:
            provider = LLMProvider.MOCK
    self.provider = provider
```

#### 1.3 `_openai_chat()` — new method

```python
async def _openai_chat(self, messages, tools, system_prompt, max_tokens, temperature):
    import openai

    base_url = os.getenv("OPENAI_BASE_URL", "")
    client = openai.AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "not-needed"),
        base_url=base_url or None,  # None = use default api.openai.com
    )

    # Convert messages to OpenAI format
    openai_messages = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    for msg in messages:
        if msg.role == "system":
            continue  # Already handled
        openai_msg = {"role": msg.role, "content": msg.content or ""}
        if msg.tool_calls:
            openai_msg["tool_calls"] = msg.tool_calls
        openai_messages.append(openai_msg)

    # Convert tool definitions
    openai_tools = None
    if tools:
        openai_tools = [{
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
        } for t in tools]

    kwargs = {
        "model": self.model,
        "messages": openai_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if openai_tools:
        kwargs["tools"] = openai_tools

    import time
    start = time.time()
    response = await client.chat.completions.create(**kwargs)
    latency = (time.time() - start) * 1000

    choice = response.choices[0]
    content = choice.message.content or ""

    # Parse tool calls from OpenAI response
    tool_calls = []
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "input": json.loads(tc.function.arguments),
            })

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        token_usage={
            "input": response.usage.prompt_tokens if response.usage else 0,
            "output": response.usage.completion_tokens if response.usage else 0,
        },
        model=self.model,
        stop_reason=choice.finish_reason or "stop",
        latency_ms=latency,
    )
```

#### 1.4 `_openai_stream()` — new method

Similar to `_anthropic_stream()` but using `client.chat.completions.create(stream=True)` and yielding `LLMStreamEvent` objects.

#### 1.5 `chat_orchestrator.py` — auto-detect provider

```python
# Line ~914: Replace hardcoded provider
client = LLMClient(
    provider=LLMProvider.ANTHROPIC,  # ← currently hardcoded
    model=model,
)
# With:
client = LLMClient(model=model)  # Provider auto-detected from LLM_PROVIDER env
```

#### 1.6 Agent files — same fix

All three agents (`planner_agent.py`, `template_selector_agent.py`, `content_generator_agent.py`) hardcode `LLMProvider.ANTHROPIC`. Update to auto-detect.

### Result

```bash
# .env for local Ollama
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
AI_PRIMARY_MODEL=llama3.1:8b
AI_FALLBACK_MODEL=phi3:mini
AI_GENERATION_PROVIDER=llm
```

---

## Phase 2: Local Embeddings (1 day)

### Option A: Ollama embeddings via existing OpenAI path

The `OpenAIBackend` in `embedding_provider.py` already works with any OpenAI-compatible endpoint. Just point `OPENAI_BASE_URL` at Ollama:

```bash
EMBEDDING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL=nomic-embed-text
```

### Option B: Add native SentenceTransformers backend

Per the sketch in [02_Local_LLM_Options.md](02_Local_LLM_Options.md), add a `SentenceTransformersBackend` to `embedding_provider.py`. This removes the need for Ollama for embeddings entirely.

---

## Phase 3: Production Hardening (2-3 days)

### 3.1 Dynamic model registry

Currently models are hardcoded in `_build_model_registry()`. Add a `models.yaml` config file:

```yaml
# config/models.yaml
models:
  - id: local-llama-8b
    provider: openai
    api_model_name: llama3.1:8b
    tier: generator
    max_tokens: 8192
    supports_tool_calling: true
  - id: local-phi-mini
    provider: openai
    api_model_name: phi3:mini
    tier: planner
    max_tokens: 4096
    supports_tool_calling: true
```

### 3.2 Provider health checks

Add a `/api/v1/ai/health` endpoint that calls the LLM with a lightweight ping to verify connectivity.

### 3.3 Graceful degradation chain

```
Local LLM (Ollama)
    ↓ unavailable?
    ├── Fallback: Local LLM (LM Studio)
    ↓ unavailable?
    ├── Fallback: Cloud Anthropic
    ↓ unavailable?
    └── Fallback: Mock (deterministic, zero-cost)
```

---

## Summary: Effort vs Value

| Phase | Effort | Value | Prerequisite |
|-------|--------|-------|-------------|
| **Phase 0** (LiteLLM proxy) | 30 min | Works today, zero code changes | Ollama installed |
| **Phase 1** (OpenAI provider) | 2-3 days | No proxy needed, full control | Phase 0 validated |
| **Phase 2** (Local embeddings) | 1 day | Fully offline embeddings | Phase 1 complete |
| **Phase 3** (Production hardening) | 2-3 days | Dynamic config, health checks, fallback chain | Phase 1+2 validated |

**Recommendation: Start with Phase 0 today to validate that local models meet quality needs. If they do, invest in Phase 1-3.**
