# Local LLM Setup Options — E-Learning Backend

> **Date:** 2026-06-27
> **Context:** The app uses Anthropic SDK exclusively for chat. Embeddings use OpenAI SDK.
> **Key Env Var:** `ANTHROPIC_BASE_URL` — set this to route all LLM calls to a local endpoint.

---

## 1. Architecture Constraint

The app speaks **Anthropic Messages API** (not OpenAI Chat Completions API). Any local LLM solution must either:

| Approach | Effort | Description |
|----------|--------|-------------|
| **A. Use a protocol-translating proxy** | Low | LiteLLM proxy translates Anthropic ↔ OpenAI API formats. No code changes. |
| **B. Add OpenAI provider to LLMClient** | Medium | Add `LLMProvider.OPENAI` to `llm_client.py`, implement `_openai_chat()` / `_openai_stream()`. Most local tools speak OpenAI API natively. |
| **C. Use an Anthropic-compatible server** | Low | Very few local servers speak Anthropic API natively. |

**Recommendation: Approach A (LiteLLM proxy) for zero code changes, Approach B for maximum flexibility.**

---

## 2. Option A: LiteLLM Proxy (Zero Code Changes)

### How it works

```
App (Anthropic SDK)
    │
    │ ANTHROPIC_BASE_URL=http://localhost:4000
    │ Anthropic API format
    ▼
LiteLLM Proxy (localhost:4000)
    │
    │ Translates Anthropic → OpenAI API format
    ▼
Ollama / LM Studio / vLLM / llama.cpp (localhost:11434 or similar)
```

### Setup Steps

#### Step 1: Install LiteLLM

```bash
pip install litellm[proxy]
```

#### Step 2: Create LiteLLM config

Create `litellm_config.yaml`:

```yaml
model_list:
  # Map DeepSeek models → local Ollama models
  - model_name: deepseek-v4-pro[1m]
    litellm_params:
      model: ollama/llama3.1:8b        # or any local model
      api_base: http://localhost:11434
      temperature: 0.7
      max_tokens: 8192

  - model_name: deepseek-v4-flash
    litellm_params:
      model: ollama/llama3.1:8b        # same or smaller model
      api_base: http://localhost:11434
      temperature: 0.3
      max_tokens: 4096

  - model_name: claude-sonnet-4-20250514
    litellm_params:
      model: ollama/mistral:7b         # alternative local model
      api_base: http://localhost:11434

  - model_name: claude-haiku-4-20250514
    litellm_params:
      model: ollama/phi3:mini          # lightweight model
      api_base: http://localhost:11434

general_settings:
  master_key: sk-local-proxy-key
```

#### Step 3: Start LiteLLM proxy

```bash
litellm --config litellm_config.yaml --port 4000
```

#### Step 4: Configure the app (.env)

```bash
AI_AUTHORING_ENABLED=true
ANTHROPIC_API_KEY=sk-local-proxy-key      # Any value, LiteLLM doesn't validate it
ANTHROPIC_BASE_URL=http://localhost:4000   # Route to LiteLLM
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]      # LiteLLM maps this to your local model
AI_FALLBACK_MODEL=deepseek-v4-flash
AI_GENERATION_PROVIDER=llm
```

#### Step 5: Test

```bash
# Start the app
PYTHONPATH=. uvicorn app.main:app --reload

# Send a test chat
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test", "user_id": "u1", "prompt": "Hello, list my pages"}'
```

---

## 3. Option B: Add OpenAI Provider to LLMClient (Code Change)

### What needs changing

The app currently hardcodes `LLMProvider.ANTHROPIC` at every call site. Adding an OpenAI path requires:

1. **`LLMProvider` enum** — add `OPENAI = "openai"`
2. **`LLMClient`** — add `_openai_chat()` and `_openai_stream()` methods
3. **Provider selection** — detect from env var or model config
4. **Message format conversion** — OpenAI uses different message format

### Files to modify

| File | Change |
|------|--------|
| `app/services/ai/llm_client.py` | Add `LLMProvider.OPENAI`, `_openai_chat()`, `_openai_stream()` |
| `app/services/ai/config.py` | Update `ModelConfig.provider` to allow `"openai"` |
| `app/services/ai/chat_orchestrator.py` | Provider auto-detection |

### Rough implementation sketch

```python
# llm_client.py — add to LLMProvider enum
class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOCK = "mock"

# llm_client.py — add to LLMClient.chat()
async def chat(self, ...):
    if self.provider == LLMProvider.MOCK:
        return await self._mock_chat(...)
    elif self.provider == LLMProvider.OPENAI:
        return await self._openai_chat(...)
    return await self._anthropic_chat(...)

# New method
async def _openai_chat(self, messages, tools, system_prompt, max_tokens, temperature):
    import openai
    base_url = os.getenv("OPENAI_BASE_URL", "")  # e.g. http://localhost:11434/v1
    client = openai.AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "not-needed"),
        base_url=base_url or None,
    )
    # Convert messages to OpenAI format...
```

Then `.env` would look like:

```bash
AI_AUTHORING_ENABLED=true
LLM_PROVIDER=openai                        # New env var (doesn't exist yet)
OPENAI_BASE_URL=http://localhost:11434/v1  # Ollama/LM Studio/LocalAI endpoint
OPENAI_API_KEY=not-needed                  # Local servers usually don't need this
AI_PRIMARY_MODEL=llama3.1:8b               # Model name on your local server
```

---

## 4. Local Model Serving Options

### 4.1 Ollama (Recommended — Easiest)

| Aspect | Detail |
|--------|--------|
| **Install** | `winget install Ollama.Ollama` (Windows) or `brew install ollama` (macOS) |
| **API** | OpenAI-compatible at `http://localhost:11434/v1` |
| **Default port** | 11434 |
| **Model pull** | `ollama pull llama3.1:8b` |
| **Recommended models** | `llama3.1:8b` (balanced), `mistral:7b` (fast), `phi3:mini` (lightweight planner) |
| **Tool calling** | ✅ Supported in recent versions |
| **Structured output** | ⚠️ Limited (JSON mode available) |
| **Windows GPU** | ✅ CUDA/ROCm via WSL2 or native |

### 4.2 LM Studio

| Aspect | Detail |
|--------|--------|
| **Install** | https://lmstudio.ai/ — GUI installer |
| **API** | OpenAI-compatible at `http://localhost:1234/v1` |
| **Advantage** | GUI for model browsing, easy GPU offloading, no CLI needed |
| **Tool calling** | ✅ Supported |
| **Windows** | ✅ Native Windows app |

### 4.3 vLLM (High Performance)

| Aspect | Detail |
|--------|--------|
| **Install** | `pip install vllm` |
| **API** | OpenAI-compatible at `http://localhost:8000/v1` |
| **Advantage** | PagedAttention, continuous batching, production-grade |
| **Requirement** | NVIDIA GPU with CUDA |
| **Windows** | ⚠️ Linux only (use WSL2) |

### 4.4 llama.cpp / Ollama (CPU-only)

| Aspect | Detail |
|--------|--------|
| **Install** | Via Ollama (simplest) or `llama.cpp` directly |
| **API** | OpenAI-compatible via Ollama |
| **Advantage** | Runs on CPU, no GPU needed |
| **Trade-off** | Slower (5-20 tokens/sec on CPU vs 50+ on GPU) |

---

## 5. Local Embedding Options

The app uses OpenAI `text-embedding-ada-002` for embeddings. Local alternatives:

### 5.1 Ollama Embeddings

```bash
ollama pull nomic-embed-text
```

```bash
# .env
EMBEDDING_PROVIDER=openai                           # uses OpenAI API format
OPENAI_BASE_URL=http://localhost:11434/v1           # Ollama
OPENAI_API_KEY=not-needed
EMBEDDING_MODEL=nomic-embed-text                    # or mxbai-embed-large
```

### 5.2 Sentence Transformers (Code Change Required)

Would need a new `SentenceTransformersBackend` in `embedding_provider.py`:

```python
class SentenceTransformersBackend(EmbeddingProvider):
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._dim = 384  # MiniLM dimension

    async def embed(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()
```

---

## 6. Recommended Local Stack

For **development/testing** (no GPU needed):

```
Ollama (CPU mode)
    ├── llama3.1:8b          → GENERATOR tier
    └── phi3:mini            → PLANNER tier
LiteLLM Proxy (port 4000)    → Translates Anthropic ↔ OpenAI
Embeddings: Mock             → No external dependency
```

For **production-like** (GPU recommended):

```
vLLM or Ollama (GPU)
    ├── llama3.1:70b or mixtral:8x7b   → GENERATOR tier
    └── llama3.1:8b                     → PLANNER tier
LiteLLM Proxy (port 4000)
Embeddings: nomic-embed-text via Ollama
```

---

## 7. Quick-Start Script

Save as `scripts/start_local_llm_stack.sh`:

```bash
#!/bin/bash
# Start local LLM stack for e-learning-backend development

# 1. Start Ollama (if not running)
ollama serve &
sleep 2

# 2. Pull models (one-time)
ollama pull llama3.1:8b
ollama pull phi3:mini

# 3. Start LiteLLM proxy
cat > /tmp/litellm_config.yaml << 'EOF'
model_list:
  - model_name: deepseek-v4-pro[1m]
    litellm_params:
      model: ollama/llama3.1:8b
      api_base: http://localhost:11434
  - model_name: deepseek-v4-flash
    litellm_params:
      model: ollama/phi3:mini
      api_base: http://localhost:11434
  - model_name: claude-sonnet-4-20250514
    litellm_params:
      model: ollama/llama3.1:8b
      api_base: http://localhost:11434
  - model_name: claude-haiku-4-20250514
    litellm_params:
      model: ollama/phi3:mini
      api_base: http://localhost:11434
general_settings:
  master_key: sk-local-proxy-key
EOF

litellm --config /tmp/litellm_config.yaml --port 4000 &
sleep 3

echo ""
echo "Local LLM stack is ready!"
echo "  Ollama:    http://localhost:11434"
echo "  LiteLLM:   http://localhost:4000"
echo ""
echo "Set these in your .env:"
echo "  ANTHROPIC_BASE_URL=http://localhost:4000"
echo "  ANTHROPIC_API_KEY=sk-local-proxy-key"
echo "  AI_GENERATION_PROVIDER=llm"
```

---

## 8. Model Recommendations by Tier

| Tier | Cloud Model (current) | Local Equivalent | RAM Required |
|------|-----------------------|------------------|--------------|
| GENERATOR | deepseek-v4-pro[1m] | llama3.1:8b, mistral:7b, qwen2.5:7b | 8-16 GB |
| PLANNER | deepseek-v4-flash | phi3:mini, llama3.2:3b, gemma2:2b | 4-8 GB |
| SAFETY | (regex, no LLM) | N/A | N/A |
| EMBEDDINGS | text-embedding-ada-002 | nomic-embed-text, mxbai-embed-large | 2-4 GB |

---

> **Next:** See [03_Implementation_Roadmap.md](03_Implementation_Roadmap.md) for a phased approach to adding local LLM support.
