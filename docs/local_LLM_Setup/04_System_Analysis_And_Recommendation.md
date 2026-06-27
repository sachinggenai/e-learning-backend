# System Analysis & Local LLM Recommendation

> **Role:** Agentic AI Architect
> **Date:** 2026-06-27
> **Machine:** DESKTOP-G1OBP59

---

## 1. System Profile

| Component | Detail | Verdict |
|-----------|--------|---------|
| **OS** | Windows 11 Pro (10.0.26100) | ✅ Supported |
| **CPU** | AMD Ryzen 5 3500 — 6 cores / 6 threads @ 3.6 GHz | ⚠️ No iGPU, adequate for CPU fallback |
| **RAM** | 32 GB DDR4 @ 2133 MHz (2 × 16 GB) | ✅ Good for 7B-8B models |
| **GPU** | NVIDIA GeForce RTX 2060 — **6 GB VRAM** (6144 MiB) | ⚠️ Tight for 7B; can't fit 13B+ |
| **GPU Driver** | 581.57 (NVIDIA) | ✅ Recent, CUDA 12.x compatible |
| **CUDA Toolkit** | NOT installed | ⚠️ Ollama bundles its own, fine |
| **C: Drive** | 214 GB total, **2.3 GB free** | 🔴 CRITICAL — no room for models |
| **D: Drive** | 250 GB total, **223.7 GB free** | ✅ Models go here |
| **Python** | 3.11.9, pip 24.0 | ✅ |
| **PyTorch** | NOT installed | ⚠️ Will install via Ollama |
| **Ollama** | NOT installed | — |
| **LiteLLM** | NOT installed | — |

---

## 2. VRAM Budget Analysis (RTX 2060 6 GB)

### What Fits

```
Total VRAM:                       6144 MiB
Reserved for CUDA context:        ~400 MiB
Available for model weights:      ~5744 MiB
```

| Model | Size (Q4_K_M) | VRAM Used | Fits? | Speed (t/s) |
|-------|---------------|-----------|-------|-------------|
| `phi3:mini` (3.8B) | 2.5 GB | 2.8 GB | ✅ Easy | 60-90 |
| `llama3.2:3b` | 2.0 GB | 2.3 GB | ✅ Easy | 70-100 |
| `gemma2:2b` | 1.6 GB | 1.9 GB | ✅ Easy | 80-120 |
| `qwen2.5:7b` (Q4_K_M) | 4.7 GB | 5.0 GB | ✅ Good | 35-50 |
| `mistral:7b` (Q4_K_M) | 4.1 GB | 4.4 GB | ✅ Good | 40-55 |
| `llama3.1:8b` (Q4_K_M) | 5.0 GB | 5.3 GB | ✅ Tight | 30-45 |
| `llama3.1:8b` (Q8_0) | 8.5 GB | 8.8 GB | ❌ No | — |
| `mixtral:8x7b` (Q4) | 26 GB | 26+ GB | ❌ No | — |
| `llama3.1:70b` | 40+ GB | 40+ GB | ❌ No | — |

### The 6 GB Ceiling

**You cannot fit any model larger than ~8B parameters at 4-bit quantization.** This rules out:
- Mixtral 8×7B (MoE, 26 GB)
- Llama 3.1 70B
- Command R / R+
- Any unquantized model > 2B

**What matters for this app:** The app needs tool calling, structured JSON output, and instructional design reasoning. Modern 7-8B models handle this well.

---

## 3. Recommended Stack

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│ E-Learning Backend (app/main.py)                        │
│   ANTHROPIC_BASE_URL=http://localhost:4000              │
│   AI_GENERATION_PROVIDER=llm                            │
└───────────────┬─────────────────────────────────────────┘
                │ Anthropic Messages API
                ▼
┌─────────────────────────────────────────────────────────┐
│ LiteLLM Proxy (localhost:4000)                          │
│   Translates: Anthropic API → OpenAI API                │
│   Config maps model names → Ollama models               │
└───────────────┬─────────────────────────────────────────┘
                │ OpenAI-compatible API
                ▼
┌─────────────────────────────────────────────────────────┐
│ Ollama (localhost:11434)                                │
│   OLLAMA_MODELS=D:\ollama_models  ← models on D: drive │
│   ┌───────────────────────────────────────────────────┐ │
│   │ GPU Layer: RTX 2060 (6 GB VRAM)                   │ │
│   │   llama3.1:8b Q4_K_M (~5 GB)  — GENERATOR tier   │ │
│   │   qwen2.5:7b Q4_K_M  (~5 GB)  — alt GENERATOR    │ │
│   │   phi3:mini 3.8B          (~3 GB)  — PLANNER tier │ │
│   └───────────────────────────────────────────────────┘ │
│   ┌───────────────────────────────────────────────────┐ │
│   │ CPU Fallback: AMD Ryzen 5 3500 (32 GB RAM)        │ │
│   │   Any overflow from GPU spills here               │ │
│   │   nomic-embed-text (274 MB) — embeddings          │ │
│   └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Model Assignments

| App Tier | Model | VRAM | Why |
|----------|-------|------|-----|
| **GENERATOR** | `llama3.1:8b` (Q4_K_M) | ~5.3 GB | Best tool-calling 8B model. Strong JSON output. Good instructional design reasoning. |
| **PLANNER** | `phi3:mini` (3.8B) | ~2.8 GB | Fast inference, small footprint. Good enough for classification/triage. |
| **EMBEDDINGS** | `nomic-embed-text` (v1.5) | ~0.3 GB | Tiny, fast, 768-dim vectors. Runs on CPU without taxing GPU. |

**Alternative GENERATOR**: `qwen2.5:7b` (Q4_K_M, ~4.7 GB) — better at structured output than llama3.1, slightly less VRAM. Swap if llama3.1 is too tight.

---

## 4. Setup Instructions

### Step 1: Install Ollama on D: Drive

```powershell
# Download installer
Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile "$env:TEMP\OllamaSetup.exe"

# Set model storage to D: drive BEFORE running installer
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\ollama_models", "User")

# Run installer
Start-Process "$env:TEMP\OllamaSetup.exe" -Wait

# Verify
ollama --version
```

### Step 2: Pull Models

```powershell
# GENERATOR tier — primary
ollama pull llama3.1:8b

# GENERATOR tier — alternative (better JSON, try if llama3.1 doesn't fit)
# ollama pull qwen2.5:7b

# PLANNER tier
ollama pull phi3:mini

# Embeddings
ollama pull nomic-embed-text

# Verify all loaded
ollama list
```

**Expected VRAM usage**: ~5.3 GB (llama3.1:8b) + ~2.8 GB (phi3:mini) = ~8.1 GB total.
But Ollama only loads the model being queried into VRAM — idle models are unloaded.
At runtime, only ONE model is in VRAM at a time. Peak ~5.3 GB.

### Step 3: Install LiteLLM Proxy

```powershell
pip install "litellm[proxy]"
```

### Step 4: Create LiteLLM Config

Save as `D:\litellm_config.yaml`:

```yaml
model_list:
  - model_name: deepseek-v4-pro[1m]
    litellm_params:
      model: ollama/llama3.1:8b
      api_base: http://localhost:11434
      temperature: 0.7
      max_tokens: 4096
      supports_tool_calling: true

  - model_name: deepseek-v4-flash
    litellm_params:
      model: ollama/phi3:mini
      api_base: http://localhost:11434
      temperature: 0.3
      max_tokens: 2048
      supports_tool_calling: true

  - model_name: claude-sonnet-4-20250514
    litellm_params:
      model: ollama/llama3.1:8b
      api_base: http://localhost:11434
      temperature: 0.7
      max_tokens: 4096

  - model_name: claude-haiku-4-20250514
    litellm_params:
      model: ollama/phi3:mini
      api_base: http://localhost:11434
      temperature: 0.3
      max_tokens: 2048

general_settings:
  master_key: sk-local-proxy-key

# LiteLLM will handle Anthropic Messages API → OpenAI Chat Completions translation
# including tool call format conversion
```

### Step 5: Update .env

```bash
# ── Master switch ─────────────────────────────────────
AI_AUTHORING_ENABLED=true

# ── Route to local LLMs ──────────────────────────────
ANTHROPIC_BASE_URL=http://localhost:4000
ANTHROPIC_API_KEY=sk-local-proxy-key
AI_GENERATION_PROVIDER=llm

# ── Models (LiteLLM maps these to local models) ──────
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]
AI_FALLBACK_MODEL=deepseek-v4-flash

# ── Embeddings (local via Ollama) ────────────────────
EMBEDDING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
EMBEDDING_MODEL=nomic-embed-text

# ── Token budgets (relaxed for local) ────────────────
AI_MAX_INPUT_TOKENS=4096
AI_MAX_OUTPUT_TOKENS=2048
AI_TOTAL_TOKEN_BUDGET=6144
```

### Step 6: Start the Stack

```powershell
# Terminal 1: Start LiteLLM proxy
litellm --config D:\litellm_config.yaml --port 4000

# Terminal 2: Start the app
cd C:\Users\ADMIN\e-learning-backend
PYTHONPATH=. uvicorn app.main:app --reload
```

---

## 5. What Won't Work (And Mitigations)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Tool calling quality** | 7B models have imperfect tool call adherence | LiteLLM translates Anthropic tool format → OpenAI function calling. Test with simple tools first. |
| **Structured JSON output** | 7B models may drift from JSON schema | Use phi3:mini for planning (simpler output). llama3.1:8b handles JSON well. |
| **VRAM pressure** | If llama3.1:8b Q4 doesn't fit cleanly | Fall back to `qwen2.5:7b` (4.7 GB) or `mistral:7b` (4.1 GB). |
| **Latency** | 30-45 t/s on RTX 2060 vs 100+ on cloud | Acceptable for dev/testing. Not production latency. |
| **32K context window** | llama3.1:8b default is 8K context in Ollama | Set `num_ctx=8192` in Ollama or reduce `AI_MAX_INPUT_TOKENS`. |
| **DeepSeek model ID** | `deepseek-v4-pro[1m]` has brackets in name | LiteLLM handles this in the config mapping. Test the model name passes through correctly. |

---

## 6. Quick Validation

After setup, test each tier:

```powershell
# Test GENERATOR (llama3.1:8b through LiteLLM)
curl -X POST http://localhost:4000/v1/messages `
  -H "Content-Type: application/json" `
  -H "x-api-key: sk-local-proxy-key" `
  -d '{"model":"deepseek-v4-pro[1m]","max_tokens":100,"messages":[{"role":"user","content":"What is instructional design?"}]}'

# Test PLANNER (phi3:mini through LiteLLM)
curl -X POST http://localhost:4000/v1/messages `
  -H "Content-Type: application/json" `
  -H "x-api-key: sk-local-proxy-key" `
  -d '{"model":"deepseek-v4-flash","max_tokens":50,"messages":[{"role":"user","content":"Classify: list pages"}]}'

# Test embeddings (direct to Ollama)
curl http://localhost:11434/v1/embeddings `
  -H "Content-Type: application/json" `
  -d '{"model":"nomic-embed-text","input":"test text"}'
```

---

## 7. Alternative: Skip LiteLLM (Moderate Code Change)

If the proxy adds unacceptable latency or breaks tool calling, implement `LLMProvider.OPENAI` directly in `llm_client.py` (see [03_Implementation_Roadmap.md](03_Implementation_Roadmap.md), Phase 1). Then:

```bash
# .env — no proxy needed
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
AI_PRIMARY_MODEL=llama3.1:8b
AI_FALLBACK_MODEL=phi3:mini
```

The Ollama OpenAI-compatible endpoint is at `http://localhost:11434/v1`.

---

## 8. Cost Comparison

| Setup | Monthly Cost | Latency | Quality |
|-------|-------------|---------|---------|
| **DeepSeek v4 Pro (cloud)** | ~$50-200/mo | 2-8s | Excellent |
| **Claude Sonnet 4 (cloud)** | ~$100-500/mo | 1-3s | Best |
| **Local RTX 2060 (this setup)** | **$0** (electricity only) | 5-15s | Good (7B) |
| **Local + cloud fallback** | ~$10-50/mo | 1-15s | Good-Excellent |

**For testing/development, the local setup is ideal — $0 marginal cost, unlimited calls.**

---

## Summary

**Best setup for your system: Ollama + LiteLLM proxy on D: drive.**

| Component | Choice | Why |
|-----------|--------|-----|
| Model server | **Ollama** (native Windows) | No CUDA toolkit needed, easy model management, OpenAI-compatible API |
| Protocol bridge | **LiteLLM** proxy | Translates Anthropic → OpenAI, zero app changes |
| GENERATOR model | **llama3.1:8b Q4_K_M** | Best tool-calling 8B model, fits 6 GB VRAM |
| PLANNER model | **phi3:mini 3.8B** | Fast, lightweight, sufficient for classification |
| Embeddings | **nomic-embed-text** | Tiny (274 MB), runs on CPU, 768-dim vectors |
| Model storage | **D:\ollama_models** | C: drive has only 2.3 GB free |
| App changes | **Zero** | `ANTHROPIC_BASE_URL=http://localhost:4000` is all you need |
