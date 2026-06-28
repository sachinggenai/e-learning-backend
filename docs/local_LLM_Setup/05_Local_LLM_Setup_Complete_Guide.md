# Local LLM Setup — Complete Guide

> **Machine:** DESKTOP-G1OBP59  
> **Date:** 2026-06-28  
> **Ollama Version:** 0.30.11  
> **Date Completed:** 2026-06-29  
> **Status:** Ollama installed ✅ | Models: 3/3 pulled ✅ | LiteLLM: pending ⏳

---

## 1. System Profile (Verified)

| Component | Detail | Verdict |
|-----------|--------|---------|
| **OS** | Windows 11 Pro (10.0.26100) | ✅ |
| **CPU** | AMD Ryzen 5 3500 — 6 cores / 6 threads @ 3.6 GHz | ✅ Adequate |
| **RAM** | 32 GB DDR4 @ 2133 MHz (2 × 16 GB) | ✅ Good for 7B-8B models |
| **GPU** | NVIDIA GeForce RTX 2060 — **6 GB VRAM** | ⚠️ Tight for 8B |
| **GPU Driver** | 581.57 (NVIDIA) | ✅ CUDA 13.0 compatible |
| **VRAM Free (idle)** | ~5.1 GB of 6.0 GB | ✅ Enough for Q4 7B |
| **D: Drive Free** | ~214 GB | ✅ Models stored here |
| **C: Drive Free** | ~2.3 GB | 🔴 Do NOT store models here |
| **Python** | 3.11.9, pip 26.0.1 (venv: `.venv-1`) | ✅ |

---

## 2. Recommended Models

### Why These Three?

Your RTX 2060 has **6 GB VRAM**. Only **one model is loaded at a time** (Ollama auto-unloads idle models), so peak VRAM is ~5 GB. This means you're limited to 7B-8B parameter models at 4-bit quantization.

| Tier | Model | VRAM | Speed (t/s) | Role |
|------|-------|------|-------------|------|
| **GENERATOR** | `qwen2.5:7b` (Q4_K_M) | ~4.7 GB | 35-50 | Tool calling, JSON output, instructional design reasoning |
| **PLANNER** | `phi3:mini` (3.8B) | ~2.8 GB | 60-90 | Fast classification, triage, intent parsing |
| **EMBEDDINGS** | `nomic-embed-text` (v1.5) | ~0.3 GB | CPU | RAG similarity search, 768-dim vectors |

### Why `qwen2.5:7b` as GENERATOR?

- **Best JSON output** in the ≤8B class — critical for your app's structured responses
- **VRAM fit**: 4.7 GB leaves ~0.4 GB headroom on your 6 GB card
- **Strong tool-calling** via Ollama's OpenAI-compatible API
- **Alternative**: `llama3.1:8b` (5.0 GB — tighter fit) or `mistral:7b` (4.1 GB — more headroom)

### Why `phi3:mini` as PLANNER?

- **Fast inference** (60-90 t/s) — good for classification/routing
- **Small footprint** (2.8 GB) — can run even when the GENERATOR is in VRAM
- **Sufficient** for intent parsing, safety classification, simple decisions

### Why `nomic-embed-text` for Embeddings?

- **Tiny** (274 MB) — runs entirely on CPU, doesn't touch VRAM
- **768-dim vectors** — compatible with pgvector extension
- **No API costs** — true local embeddings, unlimited calls

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ E-Learning Backend (FastAPI :8000)                       │
│   ANTHROPIC_BASE_URL=http://localhost:4000               │
│   AI_GENERATION_PROVIDER=anthropic                       │
│   AI_PRIMARY_MODEL=deepseek-v4-pro[1m]                   │
│   AI_FALLBACK_MODEL=deepseek-v4-flash                    │
└───────────────┬─────────────────────────────────────────┘
                │ Anthropic Messages API
                ▼
┌─────────────────────────────────────────────────────────┐
│ LiteLLM Proxy (localhost:4000)                           │
│   Translates: Anthropic Messages API → Ollama API        │
│   deepseek-v4-pro[1m]  → ollama/qwen2.5:7b              │
│   deepseek-v4-flash     → ollama/phi3:mini               │
└───────────────┬─────────────────────────────────────────┘
                │ OpenAI-compatible API
                ▼
┌─────────────────────────────────────────────────────────┐
│ Ollama Server (localhost:11434)                          │
│   OLLAMA_MODELS=D:\ollama_models                        │
│   ┌─────────────────────────────────────────┐           │
│   │ GPU: RTX 2060 (6 GB VRAM)               │           │
│   │   qwen2.5:7b (Q4_K_M)  — 4.7 GB         │           │
│   │   phi3:mini (3.8B)     — 2.8 GB          │           │
│   │   nomic-embed-text     — runs on CPU     │           │
│   └─────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Installation Status

| Step | Status | Details |
|------|--------|---------|
| Ollama installed | ✅ | v0.30.11 at `C:\Users\ADMIN\AppData\Local\Programs\Ollama\` |
| OLLAMA_MODELS set | ✅ | `D:\ollama_models` (user-level env var) |
| GPU detected | ✅ | RTX 2060, 6 GB VRAM, CUDA 13.0 |
| nomic-embed-text | ✅ | 274 MB — pulled 2026-06-29 |
| phi3:mini | ✅ | 2.2 GB — pulled 2026-06-29 |
| qwen2.5:7b | ✅ | 4.7 GB — pulled 2026-06-29 |
| LiteLLM | ⏳ | Not yet installed |
| .env updated | ⏳ | Still pointing to DeepSeek cloud |

### 4.1 Ollama Installation Details

### 4.1 What Was Done

```powershell
# Environment variable set BEFORE install
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\ollama_models", "User")

# Install via winget (silent)
winget install --id Ollama.Ollama --silent --accept-package-agreements
```

### 4.2 Installed Location

| Item | Path |
|------|------|
| **Binary** | `C:\Users\ADMIN\AppData\Local\Programs\Ollama\ollama.exe` |
| **Models** | `D:\ollama_models\blobs\` |
| **Manifests** | `D:\ollama_models\manifests\registry.ollama.ai\library\` |
| **Runtime data** | `%LOCALAPPDATA%\Ollama\` (logs, DB, PID) |

### 4.3 Verified

- ✅ Ollama v0.30.11 installed
- ✅ GPU detected: NVIDIA GeForce RTX 2060 (6 GB, CUDA 13.0)
- ✅ Models stored on D: drive (214 GB free)
- ✅ Ollama server runs automatically (system tray)

---

## 5. Model Downloads (PENDING ⏳)

Run these commands **one at a time** in PowerShell. Each model is downloaded once and cached on D:.

### 5.1 Pull Commands

```powershell
# Set env var so models go to D: drive
$env:OLLAMA_MODELS = "D:\ollama_models"

# Use full path to ollama.exe
$ollamaExe = "C:\Users\ADMIN\AppData\Local\Programs\Ollama\ollama.exe"

# 1. EMBEDDINGS — smallest, pull first (~274 MB)
& $ollamaExe pull nomic-embed-text

# 2. PLANNER — fast classifier (~2.5 GB)
& $ollamaExe pull phi3:mini

# 3. GENERATOR — main workhorse (~4.7 GB)
& $ollamaExe pull qwen2.5:7b

# Verify all loaded
& $ollamaExe list
```

### 5.2 Expected Output

```
NAME                   ID              SIZE      MODIFIED
qwen2.5:7b             <hash>          4.7 GB    2026-06-28
phi3:mini              <hash>          2.5 GB    2026-06-28
nomic-embed-text:latest <hash>         274 MB    2026-06-28
```

### 5.3 Download Time Estimates

| Model | Size | Fast connection (50 Mbps) | Slow connection (5 Mbps) |
|-------|------|--------------------------|--------------------------|
| nomic-embed-text | 274 MB | ~1 min | ~8 min |
| phi3:mini | ~2.5 GB | ~7 min | ~70 min |
| qwen2.5:7b | ~4.7 GB | ~13 min | ~130 min |

---

## 6. LiteLLM Proxy Setup (PENDING ⏳)

### 6.1 Install

```powershell
# Activate venv first!
cd C:\Users\ADMIN\e-learning-backend
.\.venv-1\Scripts\Activate.ps1

# Install LiteLLM proxy
python -m pip install "litellm[proxy]"

# Install OpenAI client (for embeddings to Ollama)
python -m pip install openai
```

### 6.2 LiteLLM Config

Save as `D:\litellm_config.yaml`:

```yaml
model_list:
  # GENERATOR tier — qwen2.5:7b
  - model_name: deepseek-v4-pro[1m]
    litellm_params:
      model: ollama/qwen2.5:7b
      api_base: http://localhost:11434
      temperature: 0.7
      max_tokens: 4096
      supports_tool_calling: true

  # PLANNER tier — phi3:mini
  - model_name: deepseek-v4-flash
    litellm_params:
      model: ollama/phi3:mini
      api_base: http://localhost:11434
      temperature: 0.3
      max_tokens: 2048
      supports_tool_calling: true

  # Alternative GENERATOR mapping (if using other models)
  - model_name: claude-sonnet-4-20250514
    litellm_params:
      model: ollama/qwen2.5:7b
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

# LiteLLM translates Anthropic Messages API → OpenAI Chat Completions API
# including tool call format conversion
```

### 6.3 Start LiteLLM

```powershell
# Terminal 1: LiteLLM Proxy
litellm --config D:\litellm_config.yaml --port 4000

# Terminal 2: FastAPI App
cd C:\Users\ADMIN\e-learning-backend
.\.venv-1\Scripts\Activate.ps1
PYTHONPATH=. uvicorn app.main:app --reload
```

---

## 7. .env Configuration

### 7.1 Local LLM Configuration (After Setup Complete)

```bash
# ── Master switch ─────────────────────────────────────
AI_AUTHORING_ENABLED=true

# ── Route to local LLMs via LiteLLM ───────────────────
ANTHROPIC_BASE_URL=http://localhost:4000
ANTHROPIC_API_KEY=sk-local-proxy-key
AI_GENERATION_PROVIDER=anthropic

# ── Models (LiteLLM maps these to Ollama models) ──────
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]
AI_FALLBACK_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash

# ── Embeddings (direct to Ollama) ─────────────────────
EMBEDDING_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
EMBEDDING_MODEL=nomic-embed-text

# ── Token budgets (relaxed for local) ────────────────
AI_MAX_INPUT_TOKENS=4096
AI_MAX_OUTPUT_TOKENS=2048
AI_TOTAL_TOKEN_BUDGET=6144

# ── Session limits ────────────────────────────────────
AI_MAX_ACTIVE_SESSIONS=50
```

### 7.2 Current Cloud Config (For Reference)

```bash
# Current production config using DeepSeek API
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=sk-e9de8e41a745480f861f03c97ef5dae7
AI_PRIMARY_MODEL=deepseek-v4-pro[1m]
AI_FALLBACK_MODEL=deepseek-v4-flash
```

### 7.3 Switching Between Local and Cloud

To switch back to cloud, just change:
```bash
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=           # leave empty if using AUTH_TOKEN
ANTHROPIC_AUTH_TOKEN=sk-e9de8e41a745480f861f03c97ef5dae7
```

To switch to local:
```bash
ANTHROPIC_BASE_URL=http://localhost:4000
ANTHROPIC_API_KEY=sk-local-proxy-key
ANTHROPIC_AUTH_TOKEN=        # leave empty
```

---

## 8. Verification

### 8.1 Ollama Health Check

```powershell
$ollamaExe = "C:\Users\ADMIN\AppData\Local\Programs\Ollama\ollama.exe"

# List models
& $ollamaExe list

# Test generation
& $ollamaExe run qwen2.5:7b "What is instructional design? Answer in one sentence."

# Check API
curl http://localhost:11434/api/version
```

### 8.2 LiteLLM Health Check

```powershell
# Test GENERATOR
curl -X POST http://localhost:4000/v1/messages `
  -H "Content-Type: application/json" `
  -H "x-api-key: sk-local-proxy-key" `
  -d '{"model":"deepseek-v4-pro[1m]","max_tokens":100,"messages":[{"role":"user","content":"What is instructional design?"}]}'

# Test PLANNER
curl -X POST http://localhost:4000/v1/messages `
  -H "Content-Type: application/json" `
  -H "x-api-key: sk-local-proxy-key" `
  -d '{"model":"deepseek-v4-flash","max_tokens":50,"messages":[{"role":"user","content":"Classify: list pages"}]}'
```

### 8.3 Embeddings Check

```powershell
curl http://localhost:11434/v1/embeddings `
  -H "Content-Type: application/json" `
  -d '{"model":"nomic-embed-text","input":"test text"}'
```

### 8.4 App Integration Test

```powershell
# Start the app with local config
cd C:\Users\ADMIN\e-learning-backend
.\.venv-1\Scripts\Activate.ps1
PYTHONPATH=. uvicorn app.main:app --reload

# Test a chat request
curl -X POST http://localhost:8000/api/v1/chat `
  -H "Content-Type: application/json" `
  -d '{"message":"Hello, what can you help me with?","session_id":"test-local-1"}'
```

---

## 9. Troubleshooting

### 9.1 "ollama: command not found"

```powershell
# Use full path
$ollamaExe = "C:\Users\ADMIN\AppData\Local\Programs\Ollama\ollama.exe"
& $ollamaExe list
```

Or add to PATH permanently:
```powershell
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$userPath;C:\Users\ADMIN\AppData\Local\Programs\Ollama", "User")
# Restart terminal afterward
```

### 9.2 Models Not Listed After Pull

```powershell
# Check models dir
Get-ChildItem D:\ollama_models\blobs

# Check server log
Get-Content "$env:LOCALAPPDATA\Ollama\server.log" -Tail 20

# Restart Ollama server
Get-Process ollama* | Stop-Process -Force
# Ollama auto-restarts via system tray, or run:
& $ollamaExe serve
```

### 9.3 "CUDA out of memory"

```powershell
# Check VRAM usage
nvidia-smi

# Model too large — use a smaller one
& $ollamaExe pull qwen2.5:7b     # 4.7 GB (recommended)
# OR
& $ollamaExe pull mistral:7b      # 4.1 GB (if qwen2.5 is too tight)
```

### 9.4 LiteLLM Not Translating Tool Calls

- Check `supports_tool_calling: true` is in the LiteLLM config for the model
- Test with simple no-tool requests first
- Check LiteLLM logs for translation errors
- Alternative: skip LiteLLM entirely (see Section 11)

### 9.5 Slow Responses

Local LLM on RTX 2060: expect 30-50 tokens/second. This is normal.
- **PLANNER** calls (phi3:mini): < 3 seconds
- **GENERATOR** calls (qwen2.5:7b): 5-15 seconds for typical responses
- **Embeddings** (nomic): < 1 second

### 9.6 pip Blocked by Application Control

```powershell
# Use python -m pip instead of pip directly
python -m pip install "litellm[proxy]"
python -m pip install openai
```

### 9.7 Ollama Not Detecting GPU

```powershell
# Verify CUDA is available
nvidia-smi

# Check Ollama server log for GPU discovery
Get-Content "$env:LOCALAPPDATA\Ollama\server.log" | Select-String "GPU\|CUDA\|compute"

# Expected log line:
# "inference compute" ... name=CUDA0 description="NVIDIA GeForce RTX 2060" ... total="6.0 GiB"
```

---

## 10. Model Inventory

### 10.1 Recommended Models (This Setup)

| # | Model | Ollama Tag | Size | Purpose | Ollama Docs |
|---|-------|-----------|------|---------|-------------|
| 1 | Qwen 2.5 7B | `qwen2.5:7b` | 4.7 GB | GENERATOR | [ollama.com/library/qwen2.5](https://ollama.com/library/qwen2.5) |
| 2 | Phi-3 Mini | `phi3:mini` | 2.5 GB | PLANNER | [ollama.com/library/phi3](https://ollama.com/library/phi3) |
| 3 | Nomic Embed Text | `nomic-embed-text` | 274 MB | Embeddings | [ollama.com/library/nomic-embed-text](https://ollama.com/library/nomic-embed-text) |

### 10.2 Alternative/Fallback Models

| Model | Ollama Tag | Size | When to Use |
|-------|-----------|------|-------------|
| Llama 3.1 8B | `llama3.1:8b` | 5.0 GB | Best tool-calling, but tighter VRAM fit |
| Mistral 7B | `mistral:7b` | 4.1 GB | More VRAM headroom than qwen2.5 |
| Gemma 2 2B | `gemma2:2b` | 1.6 GB | Ultra-light PLANNER alternative |
| Llama 3.2 3B | `llama3.2:3b` | 2.0 GB | Another PLANNER option |

---

## 11. Alternative: Skip LiteLLM (Direct Ollama)

If LiteLLM adds too much latency or breaks tool calling, you can modify `app/services/ai/llm_client.py` to support `LLMProvider.OPENAI` directly. Then:

```bash
# .env — no LiteLLM proxy needed
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=not-needed
AI_PRIMARY_MODEL=qwen2.5:7b
AI_FALLBACK_MODEL=phi3:mini
```

This requires a moderate code change in `llm_client.py` (implementing the OpenAI provider path), but eliminates the proxy hop and potential translation issues.

---

## 12. Cost Comparison

| Setup | Monthly Cost | Latency | Quality | Best For |
|-------|-------------|---------|---------|----------|
| **DeepSeek v4 Pro (cloud)** | ~$50-200/mo | 2-8s | Excellent | Production |
| **Claude Sonnet 4 (cloud)** | ~$100-500/mo | 1-3s | Best | Production |
| **Local RTX 2060 (this setup)** | **$0** (electricity only) | 5-15s | Good (7B) | Dev/Testing |
| **Local + cloud fallback** | ~$10-50/mo | 1-15s | Good-Excellent | Hybrid |

**For development and testing, local is ideal — $0 marginal cost, unlimited calls.**

---

## 13. Quick Start Checklist

- [x] **Step 1**: Install Ollama (`winget install Ollama.Ollama`)
- [x] **Step 2**: Set `OLLAMA_MODELS=D:\ollama_models` env var
- [x] **Step 3**: Verify GPU detected (RTX 2060, 6 GB, CUDA)
- [x] **Step 4**: Pull models — `qwen2.5:7b` (4.7 GB), `phi3:mini` (2.2 GB), `nomic-embed-text` (274 MB)
- [ ] **Step 5**: Install LiteLLM (`python -m pip install "litellm[proxy]"`)
- [ ] **Step 6**: Create `D:\litellm_config.yaml`
- [ ] **Step 7**: Update `.env` for local LLM
- [ ] **Step 8**: Start LiteLLM + App, verify integration
- [ ] **Step 9**: Test tool calling and embeddings

---

## 14. Reference Files

| File | Description |
|------|-------------|
| `docs/local_LLM_Setup/01_Current_LLM_Architecture.md` | App's LLM architecture analysis |
| `docs/local_LLM_Setup/02_LLM_Providers_Comparison.md` | Provider comparison |
| `docs/local_LLM_Setup/03_Implementation_Roadmap.md` | Code change roadmap |
| `docs/local_LLM_Setup/04_System_Analysis_And_Recommendation.md` | Original system analysis |
| `docs/local_LLM_Setup/05_Local_LLM_Setup_Complete_Guide.md` | **This file** |
| `ollama-workflow/ollama-profiles.ps1` | PowerShell helpers for interactive use |
| `ollama-workflow/README.md` | Ollama workflow quick start |
| `D:\litellm_config.yaml` | LiteLLM proxy config (after setup) |
| `.env` | App environment variables |

---

## 15. Daily Operations

### Start Everything

```powershell
# Terminal 1: LiteLLM proxy
litellm --config D:\litellm_config.yaml --port 4000

# Terminal 2: FastAPI app
cd C:\Users\ADMIN\e-learning-backend
.\.venv-1\Scripts\Activate.ps1
$env:PYTHONPATH = "."
uvicorn app.main:app --reload
```

### Stop Everything

```powershell
# Ctrl+C in both terminals
# Or via the project scripts:
.\stop-all.ps1
```

### Check GPU Usage

```powershell
# Monitor GPU while generating
nvidia-smi -l 1
```

### Update Models

```powershell
$ollamaExe = "C:\Users\ADMIN\AppData\Local\Programs\Ollama\ollama.exe"
& $ollamaExe pull qwen2.5:7b     # Updates to latest version
```

---

> **TL;DR:** Ollama is installed. Pull 3 models, install LiteLLM, update `.env`, and you have a $0/month local LLM stack for your e-learning app.
