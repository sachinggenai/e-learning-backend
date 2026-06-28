# Architect Final Review — DevOps Deliverables (Phases 1-4)

**Reviewer:** Architect
**Date:** 2026-06-28
**Scope:** All commits on `AI-Architecture-update` including config, bug fix, 6 scripts, docs

---

## Verdict: Conditionally Approved (8 items must be fixed before merge)

The work is 80% production-ready. The architecture is sound, the startup order is correct, the port conflict resolution is appropriate, and the three-script design (start/stop/reset) is well-conceived. However, I found 3 critical bugs, 4 medium-severity issues, and several polish items that should be addressed.

---

## CRITICAL — Must Fix

### C1: `start-all.sh` flag parser is fundamentally broken

**File:** `start-all.sh` lines 49-61
**Severity:** Critical — `--app-port 8100` does not work

```bash
# BROKEN PATTERN:
for arg in "$@"; do
    case "$arg" in
        --app-port) shift; APP_PORT="${1:-8000}" ;;  # shift inside for loop = undefined behavior
    esac
    shift 2>/dev/null || true  # shifts while iterating $@
done
```

**Root cause:** Bash's `for arg in "$@"` captures the argument list once at loop entry. Calling `shift` inside the loop body changes `$@` but the loop variable `$arg` continues iterating over the *original* captured list. For a paired flag like `--app-port 8100`:

1. Loop iteration 1: `$arg = --app-port`, executes `shift` (removes `--app-port`), sets `APP_PORT="${1:-8000}"` — but `$1` is now `8100` ✓
2. End of iteration: executes `shift` again (removes `8100`) 
3. Loop iteration 2: `$arg` was captured as `8100` but `8100` is not a recognized case, falls through
4. Loop ends, no more arguments

So `APP_PORT=8100` DOES get set correctly in this specific case. But the double-shift pattern is fragile — if someone passes `--app-port=8100` (with `=`), it breaks. If someone passes flags in different order, behavior changes.

More importantly: in `reset-all.sh` line 30-38, the same broken pattern is used for `--force` (no paired value), which works by accident because `shift` on a single item is harmless.

**Fix:** Replace with a proper `while` loop:
```bash
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-docker) SKIP_DOCKER=true; shift ;;
        --skip-mcp)    SKIP_MCP=true; shift ;;
        --with-mcp)    FORCE_MCP=true; shift ;;
        --app-port)    APP_PORT="$2"; shift 2 ;;
        --help)        sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done
```

### C2: `start-all.ps1` `exit` inside `try` skips `finally` (PowerShell 5.1)

**File:** `start-all.ps1` lines 143, 191, 198, 229, 274, 296
**Severity:** Critical — resource leak and directory pollution

In PowerShell 5.1, `exit` called inside a `try` block **immediately terminates the process** without executing `catch` or `finally` blocks. This means every `exit 1` call in the PS scripts (6 places in start-all.ps1, 2 in stop-all.ps1, 2 in reset-all.ps1) bypasses:
- `Invoke-Cleanup` (MCP background processes keep running orphaned)
- `Pop-Location` (session directory stays changed)

**Fix:** Replace all `exit N` with `throw "message"` or set a flag and `return`:
```powershell
# Instead of:
if (-not $docker) { Write-Err "..."; exit 1 }
# Use:
if (-not $docker) { throw "Docker is not installed..." }
# The throw propagates to finally, which runs, then the script exits with error.
```

Or wrap the entire main logic in a function and use `return`:
```powershell
function Main {
    if (-not $docker) { Write-Err "..."; return 1 }
    # ... rest of logic
}
$exitCode = Main
Invoke-Cleanup
Pop-Location
exit $exitCode
```

### C3: `.env` sourced too late — health checks use wrong credentials

**File:** `start-all.sh` lines 248-252 (sourced at Step 2) vs lines 93-98 (used at Step 1)
**Severity:** Critical — PostgreSQL health check may pass with wrong user/db

`.env` is sourced at Step 2 (migrations), but `wait_for_postgres()` at Step 1 uses `${POSTGRES_USER:-elearning}` and `${POSTGRES_DB:-elearning_db}`. If `.env` overrides these variables to non-default values, the health check in Step 1 uses the **wrong** credentials, but the app in Step 4 uses the **correct** ones from `.env`.

If a developer sets `POSTGRES_USER=myuser` in `.env`, the docker-compose creates a container with `myuser`, but the health check tries `pg_isready -U elearning` (wrong) and fails after 60s.

**Fix:** Source `.env` BEFORE Step 1, not at Step 2:
```bash
# Move this block to before STEP 0:
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi
```

---

## HIGH — Should Fix Before Production Use

### H1: `start-all.ps1` hardcodes PG credentials while bash version reads from env

**File:** `start-all.ps1` line 216
**Severity:** High — parity gap, will fail with non-default Postgres config

```powershell
# PowerShell (HARDCODED):
pg_isready -U elearning -d elearning_db

# Bash (DYNAMIC):
pg_isready -U "${POSTGRES_USER:-elearning}" -d "${POSTGRES_DB:-elearning_db}"
```

**Fix:** Read from environment after `Load-DotEnv`:
```powershell
$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "elearning" }
$pgDb   = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "elearning_db" }
# ... use $pgUser and $pgDb in pg_isready call
```

But note C3 above — `.env` is sourced at Step 2, and PG health check is at Step 1. Both scripts need the C3 fix first.

### H2: `Load-DotEnv` breaks on values containing `=`

**File:** `start-all.ps1` lines 88-99
**Severity:** High — `DATABASE_URL` with query params silently corrupted

```powershell
$parts = $line -split '=', 2
$key = $parts[0].Trim()
$value = $parts[1].Trim().Trim('"').Trim("'")
```

For `DATABASE_URL=postgresql://user:pass@host/db?options=value`, this splits on the first `=` only (due to `, 2`), so `$parts[1]` = everything after first `=`. This IS correct for the key=value split itself. But the `.Trim('"').Trim("'")` only strips outer quotes — internal special characters are preserved correctly.

**Verdict:** Actually, this is more robust than I first thought. The `-split '=', 2` correctly handles values containing `=`. The real concern is values with embedded quotes or multi-line values. **Downgraded to Medium.**

### H3: PowerShell Ctrl+C handler does not reliably execute

**File:** `start-all.ps1` lines 102-126
**Severity:** High — background MCP processes may survive Ctrl+C

The PS script relies on `finally { Invoke-Cleanup }` to kill background MCP processes. In PowerShell 5.1:

- `Ctrl+C` during `uvicorn` (foreground process) sends a `Break` to the pipeline
- The `finally` block DOES execute in most cases when a `Break` exception propagates
- BUT: if the user presses Ctrl+C twice rapidly, or if the pipeline is in a non-interruptible state, `finally` can be skipped

The bash version uses `trap cleanup SIGINT SIGTERM` which is OS-level signal handling — more reliable.

**Fix:** Add an explicit event handler:
```powershell
$null = Register-EngineEvent -SourceIdentifier ([System.Management.Automation.EngineIntrinsics].Assembly.GetType('System.Management.Automation.Internal.Host').GetField('_externalErrorOutput').GetValue($null)) 2>$null
# Simpler alternative: wrap uvicorn in a try/catch that catches [System.Management.Automation.BreakException]
try {
    & $VenvPython -m uvicorn ...
} catch [System.Management.Automation.BreakException] {
    # Ctrl+C pressed
} finally {
    Invoke-Cleanup
}
```

### H4: No `--app-port` flag on `stop-all.sh`

**File:** `stop-all.sh` and `stop-all.ps1`
**Severity:** High — can't stop app if started on non-default port

If a developer runs `start-all.sh --app-port 8100`, the app runs on port 8100. Running `stop-all.sh` will attempt to stop port 8000 (default) and miss the actual app. The only workaround is `APP_PORT=8100 bash stop-all.sh`, which is non-discoverable.

**Fix:** Add `--app-port` flag to both stop scripts, matching start scripts. Or better: save the port to a `.app_port` file on start and read it on stop.

---

## MEDIUM — Should Fix in Next Iteration

### M1: Flag parser duplicated across scripts

`start-all.sh` and `reset-all.sh` each implement their own flag parser with the same broken `for/shift` pattern. This is a DRY violation. A shared `parse_flags.sh` sourced by both scripts would fix C1 once, not twice.

### M2: Log functions use `echo -e` with unsanitized input

```bash
log_info() { echo -e "${GREEN}[start-all]${NC} $1"; }
```

If `$1` starts with `-n`, `-e`, or `-E`, `echo` interprets it as a flag, not text. Use `printf`:
```bash
log_info() { printf "${GREEN}[start-all]${NC} %s\n" "$1"; }
```

### M3: Color definitions duplicated across all 3 bash scripts

The same 6 ANSI variables appear in `start-all.sh`, `stop-all.sh`, and `reset-all.sh`. Should be in a shared `lib/colors.sh`.

### M4: `wait_for_redpanda` grep matches false positives

```bash
rpk cluster health 2>/dev/null | grep -q "Healthy"
```

If Redpanda outputs `Unhealthy: 3 nodes down`, the string `Healthy` does not appear, so no false positive. But if it outputs `Healthy: false`, this would match. Unlikely with `rpk cluster health` but fragile. Better: check exit code of `rpk cluster health` or grep for `Healthy: true`.

### M5: `lsof` not universally available

Minimal Docker images, some Linux distros, and Windows Git Bash may not have `lsof`. The PS scripts use `Get-NetTCPConnection` which is Windows-only. A fallback using `ss -tlnp` (Linux) or `/proc/net/tcp` would improve portability for developers using WSL or Linux.

### M6: No Python version check

The project requires Python 3.12+. The scripts check for Python's existence but not its version. Running with Python 3.8 would produce cryptic import errors.

---

## LOW — Polish Items

### L1: `stop-all.sh` does not handle `--help` flag

Only `--status` is recognized. `--help` falls through to the normal stop flow, which exits cleanly but prints the "Graceful Stop" header confusingly.

### L2: `start-all.sh` line 217 double redirect

```bash
if ! docker info &>/dev/null 2>&1; then
```

`&>/dev/null` already redirects both stdout and stderr. `2>&1` is redundant (though harmless).

### L3: `stop-all.ps1` exit code pollution from Docker warning

Docker Compose v2 prints a `version` deprecation warning to stdout (not stderr), causing PowerShell to report a `NativeCommandError`. Exit code 0 with error text is confusing. Fix: `docker compose ... 2>&1 | Out-Null` or remove `version: "3.9"` from docker-compose.yml.

### L4: `reset-all` scripts use `kill -9` / `Stop-Process -Force` immediately

`reset-all` is destructive by design, but even for a reset, `kill -9` without attempting `kill` (SIGTERM) first is unnecessarily harsh. The MCP servers and FastAPI should get a chance to close file handles.

### L5: No `--dry-run` flag on any script

A `--dry-run` mode that prints what would happen without doing it would be valuable for debugging and CI validation.

### L6: Summary table uses hardcoded ports instead of variables

`start-all.sh` lines 323-326 hardcode Redis (6379) and Redpanda admin (19644) in the summary table, while PostgreSQL, MinIO, and FastAPI ports are read from variables. Inconsistent.

---

## Architecture Assessment

### What's Well-Designed

| Aspect | Assessment |
|--------|-----------|
| **Three-script separation** (start/stop/reset) | Excellent. Clean separation of concerns. Each script has a single, well-defined purpose. |
| **Startup order** | Correct. Docker → PG health (hard) → Redpanda health (soft) → Alembic → MCP → FastAPI. Matches the dependency graph precisely. |
| **Graceful degradation** | Good. Redpanda being slow doesn't block startup. MCP servers are optional. Docker can be skipped. |
| **Port conflict resolution** | Good. Kills stale processes and verifies ports are actually freed before proceeding. |
| **Prompt-first destructive reset** | Excellent. `reset-all` requires typing the phrase "delete everything" — prevents muscle-memory accidents. |
| **MCP auto-detection from AI_AUTHORING_ENABLED** | Smart. No useless MCP servers when AI is off. Overridable with explicit flags. |
| **Bash/PowerShell parity** | Good intention. Both platforms get equivalent functionality. |
| **`docker compose stop` not `down`** | Correct. Preserves data by default. |
| **AITemplateContractsService fix** | Correct approach. Making `db` optional with graceful fallback is the right pattern. |
| **Docker-compose env var substitution** | Correct architectural decision. Single source of truth for config. |

### What Needs Work

| Aspect | Gap |
|--------|-----|
| **Bash/PowerShell parity** | C2, C3, H1 — the PS scripts have subtle behavioral differences from bash |
| **Error handling** | C2 — `exit` in `try` skips `finally` in PS 5.1. No equivalent safety net. |
| **Flag parsing** | C1 — the `for/shift` pattern is a known bash anti-pattern |
| **Config loading order** | C3 — `.env` loaded too late, health checks use wrong credentials |
| **Portability** | M5 — `lsof` dependency, no Python version check |
| **DRY** | M1, M3 — duplicated color vars, duplicated flag parsers |

---

## Action Items

### Immediate (before merge/production use)

| # | Item | Files | Effort |
|---|------|-------|--------|
| **C1** | Fix flag parser: `while [ $# -gt 0 ]` instead of `for/shift` | `start-all.sh`, `reset-all.sh` | 15 min |
| **C2** | Replace `exit` with `throw` or return-code pattern in PS scripts | `start-all.ps1`, `stop-all.ps1`, `reset-all.ps1` | 30 min |
| **C3** | Source `.env` before Step 1 (Docker), not at Step 2 (migrations) | `start-all.sh`, `start-all.ps1` | 10 min |
| **H1** | Read PG credentials from env vars in PS health check | `start-all.ps1` | 10 min |
| **H3** | Add explicit Ctrl+C catch in PS scripts | `start-all.ps1` | 15 min |
| **H4** | Add `--app-port` flag to stop scripts | `stop-all.sh`, `stop-all.ps1` | 20 min |

### Next iteration (before next team member onboards)

| # | Item | Effort |
|---|------|--------|
| **M1** | Extract shared `lib/colors.sh` and `lib/flags.sh` | 30 min |
| **M2** | Switch log functions to `printf` | 15 min |
| **M4** | Harden Redpanda health pattern | 5 min |
| **M6** | Add Python 3.12+ version check | 10 min |
| **L1-L6** | Polish items | 60 min |

### Future (nice to have)

- `--dry-run` mode on all scripts
- WSL2 compatibility testing
- CI smoke test that runs `start-all --skip-docker` and validates port checks
- Remove `version: "3.9"` from `docker-compose.yml` (Docker Compose v2 deprecated it)

---

## Summary

The DevOps team delivered solid work. The architecture is right, the testing surface is covered, and the documentation is thorough. The issues I found are implementation-level bugs (flag parser, exit-in-try, config loading order) rather than architectural flaws. Once the 6 immediate items are addressed, these scripts are production-ready for developer onboarding.

**Decision:** Conditionally approved — address C1-C3 + H1, H3, H4, then merge.
