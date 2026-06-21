# US-PEND-032: Investigate and Resolve pytest Segfault — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | ⚪ LOW |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | Environment access for debugging |
| **Estimated Effort** | TBD (4-8 hours typical for C extension conflicts) |
| **Target** | pytest test runner + all `test_*.py` files |

---

## User Story

**As a** developer running the test suite,
**I want** `pytest` to work without segfaulting,
**So that** I can use standard pytest tooling (parametrize, fixtures, coverage) instead of only standalone runners.

---

## Current State (Code Verified 2026-06-21)

- `pytest` segfaults with exit code 139 in the Windows development environment
- 30+ `test_*.py` files cannot be run via pytest
- Only 20 standalone `run_*.py` runners work (834 tests)
- Workaround documented in `CLAUDE.md`: "use the standalone runners"
- Root cause: unknown (likely C extension conflict in `pydantic-core`, `sqlalchemy`, or `uvicorn`)
- `requirements.txt` has `pytest` and `pytest-asyncio` listed

---

## 🔧 Investigation Methodology

### Step 1: Isolate the segfault trigger

```bash
# Create minimal reproduction
echo "def test_nothing(): assert True" > tests/test_minimal.py

# Test with bare pytest
python -m pytest tests/test_minimal.py -v

# If this segfaults → pytest or its native deps are broken
# If this passes → one of the test files imports a problematic module
```

### Step 2: Binary search dependencies

```bash
# Run a single existing test file to confirm segfault
python -m pytest tests/test_simple.py -v 2>&1
# Expected on Windows: segfault or exit code 139

# Add debug logging to identify which module load triggers it
python -c "
import sys
print('Python:', sys.version)
# Import modules one by one
import pydantic; print('pydantic OK')
import sqlalchemy; print('sqlalchemy OK')
import uvicorn; print('uvicorn OK')
import pytest; print('pytest OK')
"

# Check for known problematic combinations
pip list | grep -E "pydantic|sqlalchemy|uvicorn|pytest|Cython|cffi"
```

### Step 3: Test with clean virtualenv

```bash
# PowerShell (Windows)
python -m venv .venv_test
.venv_test\Scripts\activate
pip install fastapi uvicorn pydantic sqlalchemy alembic pytest pytest-asyncio asyncpg
pip install -r requirements.txt --no-deps
cd .venv_test
pytest --version
python -m pytest ../tests/test_minimal.py -v
```

### Step 4: Check for C extension conflicts

```bash
# Check for multiple C extension versions that could conflict
python -c "
import pydantic
print('pydantic version:', pydantic.__version__)
# pydantic v2 uses pydantic-core (Rust via PyO3)
try:
    import pydantic_core
    print('pydantic-core version:', pydantic_core.__version__)
except ImportError:
    pass
"

python -c "
import sqlalchemy
print('sqlalchemy version:', sqlalchemy.__version__)
# Check for C extension
try:
    import sqlalchemy.cimmutabledict  # C extension
    print('sqlalchemy C extension: LOADED')
except ImportError:
    print('sqlalchemy C extension: NOT FOUND (pure Python)')
"

# Check uvicorn C deps
python -c "
try:
    import httptools; print('httptools: LOADED (C extension)')
except ImportError: print('httptools: not found')
try:
    import uvloop; print('uvloop: LOADED (C extension)')
except ImportError: print('uvloop: not found')
"
```

### Step 5: Known Windows-specific workarounds

```bash
# Workaround 1: Disable uvloop (commonly crashes on Windows)
$env:UVICORN_LOOP = "asyncio"  # Force asyncio loop, not uvloop

# Workaround 2: Use pure Python SQLAlchemy
pip uninstall sqlalchemy -y
pip install sqlalchemy --no-binary sqlalchemy

# Workaround 3: Run pytest with --forked (isolates each test)
pip install pytest-forked
python -m pytest --forked tests/test_minimal.py -v
```

### Step 6: If unresolved — stack trace capture

```bash
# On Windows, enable crash dumps
# Run: werfault.exe (Windows Error Reporting)
# Or use faulthandler:
python -X faulthandler -m pytest tests/test_minimal.py -v 2>&1
# Look for "Fatal Python error: Segmentation fault" line
```

---

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Root cause identified and documented (e.g., "pydantic-core 2.x + uvloop conflict on Windows") |
| AC-2 | Fix applied OR workaround documented if fix is upstream (open GitHub issue) |
| AC-3 | At least 1 `test_*.py` file runs successfully via `pytest` |
| AC-4 | `CLAUDE.md` updated with findings and resolution |

---

## Known Likely Causes (Based on Common Patterns)

| Suspect | Why | Probability |
|---------|-----|------------|
| **pydantic-core** (Rust/PyO3) | Rust extensions on Windows sometimes conflict with debug builds | 🔴 High |
| **uvloop** (Cython) | uvloop doesn't fully support Windows; uvicorn may load it | 🟡 Medium |
| **sqlalchemy C extensions** | `cimmutabledict` C extension can conflict with other C modules | 🟡 Medium |
| **httptools** (C) | C extension loaded by uvicorn on import | 🟢 Low |

---

## Validation

```bash
# Success: pytest runs without segfault
python -m pytest tests/test_minimal.py -v
# Expected: 1 passed in 0.01s

# Success: existing test file runs
python -m pytest tests/run_workflow_engine_tests.py -v
# Expected: 146 passed (or at minimum, no segfault)
```
