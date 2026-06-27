# C: Drive Cleanup — Safe Actions Only

> **Date:** 2026-06-27
> **Rule:** Nothing below affects any running application, Docker container, or development workflow.

---

## Current State

```
C: Drive — 214 GB total, 2.7 GB free, 211.6 GB used
```

## What's Running (DO NOT TOUCH)

| Container | Image | Status |
|-----------|-------|--------|
| elearning-postgres | pgvector/pgvector:pg16 | Up 5 hours — **active** |
| elearning-redpanda | redpanda:v24.1.1 | Up 5 hours — **active** |
| minio-local | minio/minio | Up 5 hours — **active** |
| elearning-redis | redis:7-alpine | Up 5 hours — **active** |

**Volumes to preserve:** minio_data, redis_data, redpanda_data, 3 PostgreSQL data volumes.

---

## Safe to Delete Immediately (Zero Impact)

### Quick Commands (Run These Now)

```powershell
# 1. Disable hibernation → 12.8 GB
powercfg -h off

# 2. Purge pip cache → 2.7 GB
pip cache purge

# 3. Clean npm cache → 0.7 GB
npm cache clean --force

# 4. Clean Windows temp → 1.1 GB
Get-ChildItem $env:TEMP -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 5. Clean user .cache → 1.4 GB
Remove-Item "$env:USERPROFILE\.cache" -Recurse -Force -ErrorAction SilentlyContinue

# 6. Delete stopped minikube → 0.8 GB + Docker images
minikube delete --all 2>$null
docker system prune -a -f 2>$null
```

### Manual Cleanup

```powershell
# 7. Delete old Downloads — review first, keep what you need
#    Old NVIDIA drivers (5 versions, ~3.9 GB)
#    Ubuntu ISO (4.5 GB)
#    Docker Desktop installers (3 copies, ~1.7 GB)
#    Datasets zips (3 files, ~1.7 GB)
#    Old software installers (~2.7 GB)
# → Up to 14 GB reclaimable
start explorer "$env:USERPROFILE\Downloads"
```

---

## Summary: What You Get

| # | Action | Frees | Risk |
|---|--------|-------|------|
| 1 | Disable hibernation (`powercfg -h off`) | **12.8 GB** | None — Sleep still works |
| 2 | Purge pip cache | **2.7 GB** | None — re-downloads if needed |
| 3 | Clean npm cache | **0.7 GB** | None — re-downloads if needed |
| 4 | Clean Windows temp | **1.1 GB** | None |
| 5 | Clean .cache folder | **1.4 GB** | None |
| 6 | Delete minikube + prune Docker | **~4.5 GB** | None — minikube is stopped |
| 7 | Delete old Downloads | **~10-14 GB** | None — old installers only |
| **TOTAL** | | **~33-37 GB** | |

### After Cleanup

```
Before:  2.7 GB free  (2% of 214 GB)  🔴 Critical
After:  36-40 GB free  (17-19%)        🟢 Safe for development + models
```

---

## What NOT to Delete

| Item | Why |
|------|-----|
| Docker WSL data (44.5 GB) | Contains active container data. Moving it to D: is possible but requires Docker Desktop reconfiguration. Separate task. |
| .ollama models (4.4 GB) | Move to D: after cleanup (set `OLLAMA_MODELS=D:\ollama_models`). Don't delete — you'll want them. |
| Desktop\UTILITY SOFTWARE (9.1 GB) | Move to D: later. Don't delete — it's likely useful software. |
| .vscode (3.0 GB) | VS Code extensions. Needed. |
| Active Docker volumes | PostgreSQL, Redis, Redpanda, MinIO data. YOU WILL LOSE DATA if deleted. |
| Windows folder (31.7 GB) | System. Never touch. |
| Program Files / ProgramData | System + installed apps. Never touch. |

---

## Beyond This — Move to D: Drive (Phase 2)

Once C: has breathing room, move large items to D: (223 GB free):

| Item | Size | Command |
|------|------|---------|
| Ollama models | 4.4 GB | `$env:OLLAMA_MODELS = "D:\ollama_models"` |
| Desktop UTILITY | 9.1 GB | Move folder to `D:\UTILITY_SOFTWARE` |
| Docker WSL disk | 44.5 GB | `wsl --export` → `wsl --import` to D: |

This would free another ~58 GB, bringing C: to ~95 GB free.
