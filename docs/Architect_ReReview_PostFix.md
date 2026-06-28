# Architect Re-Review — Post-Fix Assessment

**Reviewer:** Architect
**Date:** 2026-06-28
**Scope:** All 6 scripts after C1-C3 + H1,H3,H4 remediation (commit `7af5463`)

---

## Verdict: Approved (1 new bug found and fixed, 0 remaining critical issues)

---

## Prior Issues — Fix Verification

### C1: Flag parser — FIXED
`start-all.sh` line 49, `reset-all.sh` line 30: now uses `while [ $# -gt 0 ]; do case "$1" in ... shift ;; shift 2 ;;` pattern. Correctly handles paired flags (`--app-port 8100`), solo flags (`--skip-docker`), and unknown flags (error + exit). Bash syntax check passes.

### C2: `exit` in `try` — FIXED
All 3 PS scripts now use `function Main { ... return N }` pattern with `$exitCode = Main; Invoke-Cleanup; Pop-Location; exit $exitCode`. The `finally` block in `start-all.ps1` provides a belt-and-suspenders guarantee that cleanup always runs.

**However**, a stray brace artifact was introduced in `reset-all.ps1` lines 148-149 (extra `return 1` + `}`). This was caught in re-review and fixed. No other artifacts found in the other 2 PS scripts.

### C3: `.env` sourcing — FIXED
`start-all.sh` line 184-189: `.env` is now sourced before Step 0 (port conflict resolution). `start-all.ps1` line 164: `Load-DotEnv` called before Step 0. Previously at Step 2 in both scripts. Health checks now use correct credentials.

### H1: Hardcoded PG credentials in PS — FIXED
`start-all.ps1` line 225: `pg_isready -U $pgUser -d $pgDb` reads from `$env:POSTGRES_USER` (default `elearning`) and `$env:POSTGRES_DB` (default `elearning_db`). Matches bash behavior.

### H3: Ctrl+C handler — FIXED
`start-all.ps1` lines 362-371: `try/catch [System.Management.Automation.BreakException]` wraps the uvicorn call. Combined with the `finally { Invoke-Cleanup; Pop-Location }` block (line 380-382), Ctrl+C reliably triggers cleanup.

### H4: `--app-port` on stop scripts — FIXED
`stop-all.sh` lines 26-36: `while` flag parser with `--app-port` option. `APP_PORT="${PORT:-8000}"` default overridden by flag. `stop-all.ps1` lines 22-32: `-AppPort` parameter with env var fallback. Both versions stop the correct port.

---

## New Issue Found During Re-Review

### N1: Stray brace artifact in `reset-all.ps1` from C2 fix — FIXED DURING REVIEW

**Severity:** Critical (would cause parse failure at runtime)
**Location:** `reset-all.ps1` lines 148-149
**Symptom:** Two extraneous lines (`return 1` + `}`) between the `if/else` block and the Main function's `return 0`. These were leftover from the old `} finally {` replacement pattern.
**Root cause:** The original C2 edit replaced `} finally { Pop-Location }` with `return 1\n}\nreturn 0\n}`. The first `return 1` was the old `exit 1` replacement inside the `else` block — correct. But the `}` that formerly closed the `else` triggered the extra lines being appended.

Fixed by removing the two extraneous lines. File now parses and executes correctly.

---

## Remaining Low-Severity Items (not part of the 6-item fix scope)

These were noted in the first review as Medium/Low. They do not block approval but should be addressed in the next iteration:

| # | Item | Severity | Effort |
|---|------|----------|--------|
| **L1** | `docker info &>/dev/null 2>&1` double redirect (3 bash scripts) | Low | 5 min |
| **L2** | Log functions use `echo -e` with unsanitized `$1` (all 3 bash scripts) | Low | 10 min |
| **L3** | Color definitions duplicated across 3 bash scripts | Low | 20 min |
| **L4** | `wait_for_redpanda` grep pattern matches "Healthy" anywhere | Low | 5 min |
| **L5** | No `--help` recognized by `stop-all.sh` non-status flow | Low | 5 min |
| **L6** | Docker Compose v2 `version` deprecation warning | Low | 2 min |
| **L7** | No Python version check (requires 3.12+) | Medium | 10 min |
| **L8** | `lsof` dependency not universal | Low | 30 min |

---

## Architecture Assessment (Post-Fix)

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Correctness** | Pass | Flag parsing, env loading, port conflict, health checks all verified correct by code inspection and dry-run execution |
| **Bash/PS Parity** | Pass | Both platforms now have equivalent flag sets, credential handling, and error cleanup behavior |
| **Error Handling** | Pass | Bash: `trap SIGINT` + `set -e`. PS: `Main()` + `finally` + `catch [BreakException]` |
| **Resource Cleanup** | Pass | MCP background processes killed on exit. `Pop-Location` always called. Docker containers stopped not destroyed. |
| **Maintainability** | Conditional Pass | Scripts are clean and well-commented. Duplicated color/log patterns (L2-L3) are the main drag on DRY. |

---

## Summary

The 6 items from the first architect review are satisfactorily resolved. One new bug was introduced by the C2 fix (stray braces in `reset-all.ps1`) and caught/fixed during this re-review.

The scripts are production-ready for developer onboarding. The 8 remaining low-severity items are polish that can be addressed iteratively without blocking usage.

**Decision:** Approved. Merge when ready.
