# US-AI-027 — JSON Repair and Structured Output Recovery (Full Epic)

---

## Section 1 — Title and Metadata

| Field | Value |
|---|---|
| **Epic ID** | US-AI-027 |
| **Title** | JSON Repair and Structured Output Recovery |
| **Source Flow** | 16. JSON Repair and Structured Output Recovery |
| **Priority** | SHOULD for MVP, MUST for production quality |
| **Depends On** | US-AI-005 (Tool and template contract registry), US-AI-026 (Multi-provider model routing and fallback) |
| **Unlocks** | Production robustness for all AI tool-calling paths (US-AI-023, US-AI-024, US-AI-014) |
| **Status** | DRAFT |
| **Author** | Technical Product Owner |
| **Audit Reference** | RESEARCH_AUDIT.md GAP entry: "Missing: Repair strategy catalog. Fast model configuration. Repair attempt limits. Common error patterns." |

---

## Section 2 — Business Context and User Story

### User Story (Standard)

> **As an AI Platform Engineer**, I want malformed JSON from the LLM to be automatically repaired before rejection, so that minor formatting errors do not block the user's workflow.

### Enriched Context

In the AI authoring loop (US-AI-023 `POST /api/v1/ai/chat`), the LLM returns structured JSON for tool calls (`propose_create_page`, `propose_update_page`, `apply_page_proposal`, etc.) and for template-specific data payloads (accordion panels, MCQ questions, assessment scoring configs). Production experience across LLM providers (US-AI-026) shows that even the most capable models occasionally emit:

- Trailing commas in arrays/objects
- Unescaped control characters or quotes in string values
- Missing closing braces or brackets
- Truncated output at context-window boundaries
- Floating-point precision edge cases (`00.0` instead of `0`)
- HTML/comment artifacts inside JSON responses
- Duplicate keys in objects (last-value-wins ambiguity)

Without automatic JSON repair, these minor errors cause a `json.JSONDecodeError` that propagates as a failed tool-call round-trip. The orchestrator (US-AI-023) must feed the error back to the LLM for regeneration, costing an additional LLM call (token cost + latency). Under the default max-tool-call-rounds limit of 10, a single corrupt tool output can cascade into multiple retries, consuming the round budget and degrading user experience.

This epic builds a deterministic, zero-LLM-cost repair pipeline that fixes the top 95% of common JSON errors before they ever reach the orchestrator's error handler. Only errors that cannot be repaired deterministically fall through to the fast-model repair fallback (US-AI-026) or, as a last resort, regeneration by the primary model.

### Business Impact

| Metric | Without Repair | With Repair | Source |
|---|---|---|---|
| LLM retries due to JSON parse failure per 1000 turns | ~80 (8%) | ~5 (0.5%) | Estimated from industry benchmarks |
| Average latency added per retry cycle (primary model) | 3-8 s | 0.5-2 ms (deterministic) | Primary model: GPT-4/Claude 3.5 class |
| Fast-model fallback calls per 1000 turns | N/A (no fast model configured) | ~10 (1%) | Fast model: Claude Haiku / GPT-4o-mini class |
| User-visible tool-call failures (shows error to user) | ~15 per 1000 turns | ~1 per 1000 turns | Escalation from max-retries-exhausted |

---

## Section 3 — Functional Requirements

### FR-1: Deterministic Regex-Based Repair Pipeline

The system MUST apply a configurable chain of regex-based repair strategies to every incoming JSON string before attempting `json.loads()`. Each strategy MUST:
- Return the repaired string OR `None` (strategy does not apply)
- Be independently testable with unit fixtures
- Log the strategy name, input snippet, and output snippet on success

**Repair strategies, in application order:**

| Order | Strategy ID | Description | Pattern | Example Fix |
|---|---|---|---|---|
| 1 | `strip_code_fences` | Remove markdown code fences (```json ... ```) | `(?:^|\n)\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$` with re.DOTALL | ```json\n{"a":1}\n``` → `{"a":1}` |
| 2 | `strip_bom_and_whitespace` | Remove BOM, leading/trailing whitespace | `^\xEF\xBB\xBF?[\s\n\r]*` and `[\s\n\r]*$` | `\n  {"a":1}  \n` → `{"a":1}` |
| 3 | `trim_to_first_last_brace` | Extract substring from first `{` to last `}` or `[` to `]` | Brute-force scan for balanced braces | `text {"a":1} text` → `{"a":1}` |
| 4 | `remove_comments` | Strip `//` and `/* */` comments | `//[^\n]*` and `/\*.*?\*/` with re.DOTALL | `{"a":1 /* comment */}` → `{"a":1}` |
| 5 | `remove_trailing_commas` | Remove commas before `]` or `}` | `,\s*([}\]])` → `\1` (repeated until stable) | `[1,2,]` → `[1,2]` |
| 6 | `escape_single_quotes` | Replace unescaped single quotes with double quotes in string values | Complex regex on key-value contexts | `{'a': 'hello'}` → `{"a": "hello"}` |
| 7 | `fix_unescaped_controls` | Escape unescaped control characters (0x00-0x1F except \t, \n, \r) | `[\x00-\x08\x0B\x0C\x0E-\x1F]` | `{"a":"hello\x00world"}` → `{"a":"hello\\u0000world"}` |
| 8 | `fix_nan_infinity` | Replace NaN/Infinity with null | `\bNaN\b` and `\b(Infinity|-Infinity)\b` | `{"a": NaN}` → `{"a": null}` |
| 9 | `fix_leading_zeros` | Fix numbers with leading zeros (e.g., `00.5` → `0.5`) | `(?<!: )\b0+(?!\.|,|\s*[}\]]|\s*$)` | `{"a": 00.5}` → `{"a": 0.5}` |
| 10 | `fix_duplicate_keys` | Keep last occurrence of duplicate keys | JSON parsing with ordered dict, dedupe on write | `{"a":1,"a":2}` → `{"a":2}` |

### FR-2: Fast-Model Repair Fallback

When deterministic repair fails (all strategies return `None` or the final `json.loads()` still raises), the system MUST invoke a fast, cheap model (configured via `AI_REPAIR_MODEL`) with a dedicated repair system prompt to fix the JSON.

**Contract:**
- The fast model receives: the original malformed JSON string, the error message from `json.loads()`, and the strategies that were attempted.
- The fast model MUST return ONLY valid JSON in its response (deterministic prompt engineering with strict instructions).
- The fast model response is validated: fed through `json.loads()`. If valid, it replaces the original. If invalid, the repair is counted as a failed attempt.

### FR-3: Repair Attempt Budget and Escalation

- **Max deterministic repair passes:** 1 (all strategies applied once in order, no looping).
- **Max fast-model repair attempts per original output:** Configured via `AI_REPAIR_MAX_ATTEMPTS` (default 2).
- **Escalation:** If all attempts (deterministic + fast-model) fail:
  - The original `JSONDecodeError` (with original malformed string and repair trace) is returned to the orchestrator's error handler.
  - The orchestrator feeds the error message back to the PRIMARY model for regeneration (existing US-AI-023 behavior).
  - The repair trace is logged for offline analysis.

### FR-4: Structured Output Recovery (Non-Tool-Call JSON)

In addition to tool-call JSON, the system MUST repair JSON embedded in:
- Template data payloads returned by the LLM via the chat endpoint.
- Course validation responses.
- Batch proposal payloads (US-AI-029).
- File ingestion analysis results (US-AI-017).

The same `JsonRepairService` is invoked for ALL JSON parsing in the AI module, not just tool calls. A centralized `safe_json_loads()` function replaces all bare `json.loads()` calls in `app/services/ai/`.

### FR-5: Repair Telemetry and Monitoring

Every repair attempt MUST produce a structured log entry (and optionally emit a metric) with:

```json
{
  "timestamp": "2026-06-14T10:30:00Z",
  "trace_id": "abc-123-def",
  "chat_turn_id": "turn-456",
  "tool_name": "propose_create_page",
  "input_length": 2345,
  "error_type": "trailing_comma",
  "deterministic_strategies_applied": ["strip_code_fences", "remove_trailing_commas"],
  "deterministic_success": true,
  "fast_model_called": false,
  "fast_model_attempts": 0,
  "fast_model_success": null,
  "final_success": true,
  "latency_ms": 1.2
}
```

**Aggregate metrics to expose (via GET /api/v1/ai/metrics or logs dashboard):**
- Repair success rate by strategy (deterministic vs fast-model)
- Repair failure rate by template type (to identify schema documentation gaps)
- Fast-model repair latency p50/p95/p99
- Repair frequency by error type

---

## Section 4 — Non-Functional Requirements

### NFR-1: Latency Budget
- Deterministic repair MUST complete in <10 ms for a 50 KB JSON payload on average hardware.
- Fast-model repair MUST use a model with p50 latency <500 ms (e.g., Claude Haiku, GPT-4o-mini).
- Total repair pipeline (deterministic + up to 2 fast-model calls) MUST NOT exceed 3 seconds wall-clock time.

### NFR-2: Accuracy
- Deterministic repair MUST successfully fix >=95% of all JSON errors encountered in production.
- Fast-model repair MUST successfully fix >=80% of the remaining 5% (i.e., fix >=99% of all errors overall).
- Registry of error patterns (seeded initially and growing via telemetry) MUST be maintained in `app/services/ai/json_error_patterns.py`.

### NFR-3: Safety
- Repair MUST NOT alter the semantic content of the JSON (e.g., changing `"a":1` to `"a":2`).
- Duplicate key resolution MUST use last-value-wins semantics (Python `json.loads` default behavior).
- The repair service MUST be idempotent: applying it twice to the same string yields the same result.
- Fast-model repair prompt MUST instruct the model to "only fix syntax, never change data values."

### NFR-4: Observability
- Every repair event MUST be logged at INFO level with the telemetry payload (FR-5).
- A Prometheus counter metric `ai_json_repair_total{strategy, success}` MUST be emitted.
- A Prometheus histogram metric `ai_json_repair_duration_ms{strategy}` MUST be emitted.
- The `/health` endpoint MUST include a repair service health check.

### NFR-5: Rate Limiting Exemption
- Repair operations MUST NOT count toward the user's tool-call rate limit (US-AI-021) or token budget (US-AI-036).
- Fast-model repair calls MUST count toward the tenant's repair-model budget, not the primary-model budget.

---

## Section 5 — Technical Design and API Contracts

### 5.1 Service Class Signature

**File:** `app/services/ai/json_repair.py`

```python
"""
JSON Repair and Structured Output Recovery Service.

Provides deterministic regex-based repair and fast-model fallback
for malformed JSON strings from LLM outputs.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Repair Event Telemetry ──────────────────────────────────────────────────


@dataclass
class RepairEvent:
    """Structured telemetry for a single repair attempt."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str = ""
    chat_turn_id: str = ""
    tool_name: str = ""
    input_length: int = 0
    error_type: str = ""
    deterministic_strategies_applied: List[str] = field(default_factory=list)
    deterministic_success: bool = False
    fast_model_called: bool = False
    fast_model_attempts: int = 0
    fast_model_success: Optional[bool] = None
    final_success: bool = False
    latency_ms: float = 0.0
    original_snippet: str = ""
    repaired_snippet: str = ""


# ── Error Types ─────────────────────────────────────────────────────────────


class RepairError(Exception):
    """Raised when all repair strategies (deterministic + fast) fail."""
    pass


class UnrepairableError(RepairError):
    """Raised when the JSON is structurally unrepairable."""
    pass


# ── Strategy Type ───────────────────────────────────────────────────────────

RepairStrategy = Callable[[str], Optional[str]]
"""A repair function receives the raw string and returns repaired string or None."""


# ── Core Service ────────────────────────────────────────────────────────────


class JsonRepairService:
    """Repair malformed JSON strings from LLM outputs.

    Applies a deterministic strategy chain, then optionally invokes a
    fast LLM for fallback repair.

    Usage::

        service = JsonRepairService()
        result, event = await service.repair(
            raw_string='{\n  "title": "Hello, World!",\n}',
            trace_id="abc-123",
            chat_turn_id="turn-456",
            tool_name="propose_create_page",
        )
        if result is not None:
            data = json.loads(result)  # guaranteed valid JSON
    """

    def __init__(
        self,
        fast_model_repair_fn: Optional[Callable[[str, str, List[str]], str]] = None,
        max_fast_attempts: int = 2,
    ):
        self._fast_model_repair_fn = fast_model_repair_fn
        self._max_fast_attempts = max_fast_attempts
        self._strategies: List[Tuple[str, RepairStrategy]] = [
            ("strip_code_fences", _strip_code_fences),
            ("strip_bom_and_whitespace", _strip_bom_and_whitespace),
            ("trim_to_first_last_brace", _trim_to_first_last_brace),
            ("remove_comments", _remove_comments),
            ("remove_trailing_commas", _remove_trailing_commas),
            ("escape_single_quotes", _escape_single_quotes),
            ("fix_unescaped_controls", _fix_unescaped_controls),
            ("fix_nan_infinity", _fix_nan_infinity),
            ("fix_leading_zeros", _fix_leading_zeros),
            ("fix_duplicate_keys", _fix_duplicate_keys),
        ]

    async def repair(
        self,
        raw_string: str,
        trace_id: str = "",
        chat_turn_id: str = "",
        tool_name: str = "",
    ) -> Tuple[Optional[str], RepairEvent]:
        """Attempt to repair the given JSON string.

        Returns:
            Tuple of (repaired_string_or_None, RepairEvent telemetry).

        The returned string, if not None, is guaranteed valid JSON.
        """
        event = RepairEvent(
            trace_id=trace_id,
            chat_turn_id=chat_turn_id,
            tool_name=tool_name,
            input_length=len(raw_string),
        )
        start = datetime.now(timezone.utc)

        # Step 1: Deterministic repair
        repaired, error_type, applied = await self._deterministic_repair(raw_string)
        event.deterministic_strategies_applied = applied
        event.error_type = error_type

        if repaired is not None:
            event.deterministic_success = True
            event.final_success = True
            event.latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            event.repaired_snippet = repaired[:200]
            event.original_snippet = raw_string[:200]
            self._emit_metric(event)
            return repaired, event

        # Step 2: Fast-model repair
        if self._fast_model_repair_fn is not None:
            event.fast_model_called = True
            for attempt in range(self._max_fast_attempts):
                try:
                    fast_repaired = await self._fast_model_repair_fn(
                        original=raw_string,
                        error=error_type or "unknown",
                        attempted_strategies=applied,
                    )
                    # Validate the fast model's output
                    json.loads(fast_repaired)  # throws if invalid
                    event.fast_model_attempts = attempt + 1
                    event.fast_model_success = True
                    event.final_success = True
                    event.latency_ms = (
                        (datetime.now(timezone.utc) - start).total_seconds() * 1000
                    )
                    event.repaired_snippet = fast_repaired[:200]
                    event.original_snippet = raw_string[:200]
                    self._emit_metric(event)
                    return fast_repaired, event
                except (json.JSONDecodeError, ValueError):
                    continue

            event.fast_model_attempts = self._max_fast_attempts
            event.fast_model_success = False

        # Step 3: Failure
        event.final_success = False
        event.latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        event.original_snippet = raw_string[:200]
        self._emit_metric(event)
        return None, event

    async def _deterministic_repair(
        self, raw: str
    ) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Apply the deterministic strategy chain.

        Returns:
            (repaired_string_or_None, detected_error_type, list_of_strategy_names_applied)
        """
        current = raw
        applied: List[str] = []
        detected_type: Optional[str] = None

        for name, strategy in self._strategies:
            try:
                result = strategy(current)
                if result is not None and result != current:
                    if detected_type is None:
                        detected_type = name
                    applied.append(name)
                    current = result
            except Exception:
                logger.debug("Strategy %s failed unexpectedly", name, exc_info=True)

        # Final validation
        try:
            json.loads(current)
            return current, detected_type, applied
        except json.JSONDecodeError as exc:
            return None, f"final:{exc.msg}", applied

    def safe_json_loads(
        self,
        raw_string: str,
        trace_id: str = "",
        chat_turn_id: str = "",
        tool_name: str = "",
    ) -> Any:
        """DEPRECATED — use ``await repair()`` instead.

        Kept for backward compatibility during migration.
        Replaced by the async repair() method above.
        """
        # Fallback: try direct parse first
        try:
            return json.loads(raw_string)
        except json.JSONDecodeError:
            pass

        # If this is called synchronously and no event loop is available,
        # do deterministic only (no fast-model fallback).
        repaired, _ = self._deterministic_repair(raw_string)
        if repaired is not None:
            return json.loads(repaired)
        raise json.JSONDecodeError(
            "Unrepairable JSON (no fast-model available in sync mode)",
            raw_string[:200],
            0,
        )

    def _emit_metric(self, event: RepairEvent) -> None:
        """Emit metrics and structured logs."""
        logger.info(
            "JSON_REPAIR event=%s",
            asdict(event),
        )
        # TODO: emit Prometheus counters + histograms via app/services/ai/metrics.py
```

### 5.2 Strategy Implementations (partial, one representative)

**File:** `app/services/ai/json_repair_strategies.py`

```python
"""Deterministic JSON repair strategy functions."""

from __future__ import annotations
import re
import json
from typing import Optional
from collections import OrderedDict


def _strip_code_fences(raw: str) -> Optional[str]:
    """Remove markdown ```json ... ``` fences."""
    m = re.match(
        r"(?:^|\n)\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _strip_bom_and_whitespace(raw: str) -> Optional[str]:
    """Remove BOM and leading/trailing whitespace."""
    cleaned = raw.lstrip("﻿").strip()
    return cleaned if cleaned != raw else None


def _trim_to_first_last_brace(raw: str) -> Optional[str]:
    """Find first { and last } (or [ and ]) and extract substring."""
    # Try object first
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = raw[first : last + 1]
        return candidate if candidate != raw else None
    # Try array
    first = raw.find("[")
    last = raw.rfind("]")
    if first != -1 and last != -1 and last > first:
        candidate = raw[first : last + 1]
        return candidate if candidate != raw else None
    return None


def _remove_comments(raw: str) -> Optional[str]:
    """Remove // and /* */ style comments."""
    # Single-line comments
    cleaned = re.sub(r"//[^\n]*", "", raw)
    # Multi-line comments
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    return cleaned if cleaned != raw else None


def _remove_trailing_commas(raw: str) -> Optional[str]:
    """Remove trailing commas before ] or }."""
    changed = False
    current = raw
    while True:
        new = re.sub(r",\s*([}\]])", r"\1", current)
        if new == current:
            break
        changed = True
        current = new
    return current if changed else None


def _escape_single_quotes(raw: str) -> Optional[str]:
    """Replace single-quoted strings with double-quoted strings.

    This is a simplified approach. Production version should handle
    escaped single quotes and nested quotes.
    """
    changed = False
    # Replace single-quoted keys: {'key': ...} -> {"key": ...}
    current = re.sub(r"'([^']+)':", r'"\1":', raw)
    if current != raw:
        changed = True
    # Replace single-quoted string values: : 'value' -> : "value"
    current = re.sub(r":\s*'([^']*?)'(\s*[,}\]])", r': "\1"\2', current)
    if current != raw:
        changed = True
    return current if changed else None


def _fix_unescaped_controls(raw: str) -> Optional[str]:
    """Escape unescaped control characters."""
    def _escape(m: re.Match) -> str:
        c = m.group(0)
        return f"\\u{ord(c):04x}"

    current = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", _escape, raw)
    return current if current != raw else None


def _fix_nan_infinity(raw: str) -> Optional[str]:
    """Replace NaN and Infinity with null."""
    current = re.sub(r"\bNaN\b", "null", raw)
    current = re.sub(r"\b(?:-)?Infinity\b", "null", current)
    return current if current != raw else None


def _fix_leading_zeros(raw: str) -> Optional[str]:
    """Remove leading zeros from numbers (except 0.x)."""
    # Fix numbers like 00.5 -> 0.5, 01 -> 1 (but not 0, 0.5)
    current = re.sub(
        r'(?<=[:\s\[,(])(0+)(\d+)',
        lambda m: m.group(2),
        raw,
    )
    return current if current != raw else None


def _fix_duplicate_keys(raw: str) -> Optional[str]:
    """Remove duplicate keys, keeping the last occurrence."""
    try:
        data = json.loads(raw, object_pairs_hook=OrderedDict)
        return json.dumps(data)  # re-serialize with dedup
    except json.JSONDecodeError:
        return None
```

### 5.3 Fast-Model Repair Prompt

**File:** `app/services/ai/prompts/json_repair_prompt.txt`

```
You are a JSON repair assistant. Your ONLY job is to fix syntax errors in
JSON strings. Never change data values — only fix syntax.

The original JSON string had this parse error:
{error_message}

The following deterministic strategies were already attempted and failed:
{attempted_strategies}

Rules:
1. Fix only JSON syntax errors (unquoted keys, missing quotes, trailing
   commas, unescaped characters, missing braces, comment removal).
2. Never change string values, numbers, booleans, or nulls.
3. Output ONLY the repaired JSON — no explanations, no markdown fences.
4. If truly unrepairable, output: {{"repair_failed": true, "reason": "..."}}

Original JSON:
{original_json}

Repaired JSON:
```

### 5.4 Integration with US-AI-023 Chat Orchestrator

**File:** `app/services/ai/chat_orchestrator.py` (modifications)

```python
# At the top of the orchestrator file, add:
from app.services.ai.json_repair import JsonRepairService

# In the orchestrator class __init__:
self.json_repair = JsonRepairService(
    fast_model_repair_fn=self._fast_model_repair,
    max_fast_attempts=int(os.getenv("AI_REPAIR_MAX_ATTEMPTS", "2")),
)

# Wrap all tool-call JSON parsing:
async def _parse_tool_call_response(self, raw: str, tool_name: str) -> dict:
    """Parse tool call JSON with repair fallback."""
    # Try direct parse first (fast path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Repair
    repaired, event = await self.json_repair.repair(
        raw_string=raw,
        trace_id=self.trace_id,
        chat_turn_id=self.current_turn_id,
        tool_name=tool_name,
    )

    if repaired is None:
        raise json.JSONDecodeError(
            f"Unrepairable JSON for tool {tool_name}: {event.error_type}",
            raw[:200],
            0,
        )
    return json.loads(repaired)


async def _fast_model_repair(
    self, original: str, error: str, attempted_strategies: List[str]
) -> str:
    """Call the configured fast repair model."""
    from app.services.ai.prompts import JSON_REPAIR_SYSTEM_PROMPT
    
    response = await self.model_router.call_model(
        model_tier="repair",  # maps to AI_REPAIR_MODEL_US-AI-026
        system_prompt=JSON_REPAIR_SYSTEM_PROMPT.format(
            error_message=error,
            attempted_strategies=", ".join(attempted_strategies),
            original_json=original,
        ),
        user_prompt="Repair the JSON above.",
        max_tokens=4096,
        temperature=0.0,  # deterministic
    )
    return response.content.strip()
```

### 5.5 Centralized `safe_json_loads` Wrapper

**File:** `app/services/ai/json_utils.py`

```python
"""Central JSON utility functions. All AI services MUST use these instead of bare json.loads()."""

from __future__ import annotations
import json
from typing import Any
from app.services.ai.json_repair import JsonRepairService


# Singleton instance — initialized with fast model when router is available.
# Until then, runs in deterministic-only mode.
_repair_service: JsonRepairService = JsonRepairService()


def configure_repair_service(fast_model_fn, max_attempts: int = 2) -> None:
    """Call once at app startup to wire in the fast model."""
    global _repair_service
    _repair_service = JsonRepairService(
        fast_model_repair_fn=fast_model_fn,
        max_fast_attempts=max_attempts,
    )


def safe_json_loads(raw: str, **kwargs: Any) -> Any:
    """Parse JSON with automatic repair.

    This is a synchronous convenience wrapper. For async contexts with
    full telemetry, use ``await JsonRepairService.repair()`` directly.
    """
    return _repair_service.safe_json_loads(raw, **kwargs)
```

### 5.6 Web UI Notification on Repair

The chat endpoint response (US-AI-023) MUST include repair telemetry so the frontend can optionally show "JSON was auto-repaired" info badges.

**Addition to chat response DTO:**

```python
class ChatResponse(BaseModel):
    # ... existing fields ...
    json_repair_info: Optional[JsonRepairInfo] = None

class JsonRepairInfo(BaseModel):
    repaired: bool = False
    strategy: Optional[str] = None  # e.g., "remove_trailing_commas"
```

---

## Section 6 — Database Design (DDL)

### 6.1 New Table: `ai_repair_events`

Migration file: `alembic/versions/XXXX_add_ai_repair_events.py`

```sql
CREATE TABLE IF NOT EXISTS ai_repair_events (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        VARCHAR(64) NOT NULL,
    chat_turn_id    VARCHAR(64),
    tool_name       VARCHAR(128),
    input_length    INTEGER NOT NULL DEFAULT 0,
    error_type      VARCHAR(64),
    
    -- Repair path
    deterministic_strategies_applied TEXT[] DEFAULT '{}',
    deterministic_success            BOOLEAN NOT NULL DEFAULT FALSE,
    fast_model_called                BOOLEAN NOT NULL DEFAULT FALSE,
    fast_model_attempts              SMALLINT NOT NULL DEFAULT 0,
    fast_model_success               BOOLEAN,
    final_success                    BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Performance
    latency_ms      NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    
    -- References
    session_id      VARCHAR(64),
    proposal_id     VARCHAR(64),
    
    -- Content snippets (truncated to 500 chars for PII safety)
    original_snippet  VARCHAR(500),
    repaired_snippet  VARCHAR(500),
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for queries
CREATE INDEX idx_repair_events_created_at ON ai_repair_events (created_at DESC);
CREATE INDEX idx_repair_events_trace_id ON ai_repair_events (trace_id);
CREATE INDEX idx_repair_events_error_type ON ai_repair_events (error_type);
CREATE INDEX idx_repair_events_tool_name ON ai_repair_events (tool_name);
CREATE INDEX idx_repair_events_final_success ON ai_repair_events (final_success);

-- Partition by month for large-scale deployments
-- CREATE TABLE ai_repair_events_y2026m06 PARTITION OF ai_repair_events
--     FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

### 6.2 SQLAlchemy ORM Model

**File:** `app/models/ai_repair.py`

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, BigInteger, Boolean, SmallInteger, Numeric, DateTime, ARRAY, Text

from app.models.base import Base


class AiRepairEvent(Base):
    __tablename__ = "ai_repair_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    input_length: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    deterministic_strategies_applied: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String(64)), default=list
    )
    deterministic_success: Mapped[bool] = mapped_column(Boolean, default=False)
    fast_model_called: Mapped[bool] = mapped_column(Boolean, default=False)
    fast_model_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    fast_model_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    final_success: Mapped[bool] = mapped_column(Boolean, default=False)

    latency_ms: Mapped[float] = mapped_column(Numeric(10, 2), default=0.00)

    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    original_snippet: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    repaired_snippet: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
```

### 6.3 Existing Table Modification

Add `repair_count` and `last_repair_event_id` to the `ai_sessions` table (US-AI-004) for session-level repair tracking:

```sql
ALTER TABLE ai_sessions
    ADD COLUMN IF NOT EXISTS repair_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_repair_event_id BIGINT;
```

---

## Section 7 — Configuration and Environment Variables

### 7.1 New Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_REPAIR_MAX_ATTEMPTS` | int | `2` | Max fast-model repair attempts per original output |
| `AI_REPAIR_MODEL` | str | `"claude-3-haiku-20240307"` | Model ID for fast-model repair (must be US-AI-026 routable) |
| `AI_REPAIR_MODEL_TEMPERATURE` | float | `0.0` | Temperature for fast-model repair calls |
| `AI_REPAIR_ENABLE_DETERMINISTIC` | bool | `true` | Enable the deterministic regex strategy chain |
| `AI_REPAIR_ENABLE_FAST_MODEL` | bool | `true` | Enable the fast-model fallback repair |
| `AI_REPAIR_SNIPPET_LENGTH` | int | `200` | Max length of original/repaired snippet in log/DB (for PII safety) |
| `AI_REPAIR_METRICS_ENABLED` | bool | `true` | Emit Prometheus metrics for repair events |

### 7.2 Feature Flag

Add to `app/utils/feature_flags.py`:

```python
'json_repair': FeatureFlag(
    name='json_repair',
    enabled=True,
    description='Enable automatic JSON repair and structured output recovery',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
```

### 7.3 App Lifecycle Wiring

**File:** `app/main.py` or `app/services/ai/__init__.py`

```python
async def setup_json_repair():
    """Wire JsonRepairService into the app on startup."""
    from app.services.ai.json_utils import configure_repair_service
    from app.services.ai.model_router import get_model_router  # US-AI-026

    router = get_model_router()
    max_attempts = int(os.getenv("AI_REPAIR_MAX_ATTEMPTS", "2"))

    configure_repair_service(
        fast_model_fn=router.call_repair_model,
        max_attempts=max_attempts,
    )
    logger.info("JsonRepairService initialized (max_fast_attempts=%s)", max_attempts)
```

---

## Section 8 — Test Scenarios and Task Breakdown

### 8.1 Unit Test Scenarios

**File:** `tests/ai/test_json_repair.py`

| Test Case | Input | Expected Output | Strategy |
|---|---|---|---|
| TR-01: Valid JSON passes through unchanged | `{"a": 1, "b": "hello"}` | Same | direct parse |
| TR-02: Code fences stripped | `` ```json\n{"a":1}\n``` `` | `{"a":1}` | strip_code_fences |
| TR-03: Trailing commas removed | `[1, 2, 3,]` | `[1, 2, 3]` | remove_trailing_commas |
| TR-04: Trailing comma in object | `{"a": 1, "b": 2,}` | `{"a": 1, "b": 2}` | remove_trailing_commas |
| TR-05: Single-line comments removed | `{"a": 1 // comment\n}` | `{"a: 1\n}` | remove_comments |
| TR-06: Multi-line comments removed | `{"a": 1 /* comment */}` | `{"a": 1}` | remove_comments |
| TR-07: Single-quoted keys | `{'key': 'value'}` | `{"key": "value"}` | escape_single_quotes |
| TR-08: Single-quoted string values | `{"a": 'hello'}` | `{"a": "hello"}` | escape_single_quotes |
| TR-09: NaN replaced with null | `{"a": NaN}` | `{"a": null}` | fix_nan_infinity |
| TR-10: Infinity replaced with null | `{"a": Infinity}` | `{"a": null}` | fix_nan_infinity |
| TR-11: Leading zeros fixed | `{"a": 00.5}` | `{"a": 0.5}` | fix_leading_zeros |
| TR-12: Duplicate keys deduplicated | `{"a": 1, "a": 2}` | `{"a": 2}` | fix_duplicate_keys |
| TR-13: Leading/trailing whitespace stripped | `\n {"a":1}\n` | `{"a":1}` | strip_bom_and_whitespace |
| TR-14: BOM removed | `\xEF\xBB\xBF{"a":1}` | `{"a":1}` | strip_bom_and_whitespace |
| TR-15: Mixed errors | `{'a': NaN,,}` then `{"a": NaN}` then `{"a": null}` | `{"a": null}` | chain (escape_single_quotes, fix_nan_infinity, remove_trailing_commas) |
| TR-16: Truncated JSON | `{"a": 1, "b":` | Repair fails → returns None | trim_to_first_last_brace fails |
| TR-17: Already valid JSON | `{"valid": true}` | Returns same without logging repair | N/A |
| TR-18: HTML entity in string | `{"a": "hello & world"}` | `{"a": "hello & world"}` (unchanged — not a JSON syntax error) | N/A |
| TR-19: Unescaped newline in string | `{"a": "line1\nline2"}` | `{"a": "line1\\nline2"}` | fix_unescaped_controls |
| TR-20: Text before JSON | `text before {"a":1}` | `{"a":1}` | trim_to_first_last_brace |

### 8.2 Fast-Model Mock Test Scenarios

**File:** `tests/ai/test_json_repair_fast_model.py`

| Test Case | Input | Mock Response | Expected |
|---|---|---|---|
| FM-01: Fast model returns valid JSON | `{bad json}` | `{"fixed": true}` | Returns `{"fixed": true}`, success=True |
| FM-02: Fast model returns invalid JSON (1st attempt) | `{bad}` | `{bad again}` | Retries up to max_attempts |
| FM-03: Fast model always fails | `{bad}` | `{still bad}` | Returns None, success=False |
| FM-04: Fast model timeout | `{bad}` | raises TimeoutError | Logs error, retries |
| FM-05: Fast model returns repair_failed signal | `{bad}` | `{"repair_failed": true, "reason": "..."}` | Recognizes signal, does NOT attempt json.loads |
| FM-06: Fast model adds extra text | `{bad}` | `Here is the fixed JSON: {"fixed": true}` | Strips extra text, parses successfully |

### 8.3 Integration Test Scenarios

**File:** `tests/ai/test_chat_orchestrator_repair.py`

| Test Case | Description |
|---|---|
| IT-01: Chat orchestrator feeds malformed tool-call JSON through repair | Mock LLM returns tool call with trailing commas; orchestrator successfully parses and executes tool |
| IT-02: Chat orchestrator regenerates on unrepairable JSON | Mock LLM returns truncated JSON; deterministic + fast-model repair fails; orchestrator sends error back to LLM for regeneration |
| IT-03: Repair telemetry in chat response | Chat response includes `json_repair_info` when repair was applied |
| IT-04: Repair does not fire for valid JSON | Direct parse succeeds; repair service is not called; telemetry shows no event |
| IT-05: Repair event written to DB | After a repair event, `ai_repair_events` table has a matching row with correct `trace_id` and `final_success=True` |
| IT-06: Session repair count incremented | After repair, `ai_sessions.repair_count` incremented by 1 |
| IT-07: Fast-model repair disabled via feature flag | When `json_repair` flag is OFF, deterministic strategies still run but fast model is never called |
| IT-08: Fast-model repair disabled via env var | When `AI_REPAIR_ENABLE_FAST_MODEL=false`, only deterministic strategies run |
| IT-09: Safe_json_loads used everywhere | Grep for `json.loads` in `app/services/ai/` returns no results (all replaced with `safe_json_loads`) |
| IT-10: Repair on batch proposal payload (US-AI-029) | Batch proposal JSON with trailing commas is repaired before validation |

### 8.4 Security Test Scenarios

| Test Case | Description |
|---|---|
| ST-01: No SQL injection via repair snippets | Truncated snippets (500 chars) prevent injection; verify parameterized insert |
| ST-02: No PII leakage in repair logs | Snippet length respects `AI_REPAIR_SNIPPET_LENGTH`; verify no full JSON in logs |
| ST-03: Fast-model repair prompt injection | Verify prompt boundaries prevent injection from malformed JSON content |
| ST-04: Repair service is not a DOS vector | Verify that extremely long (10 MB+) JSON strings are rejected before repair |

### 8.5 Task Breakdown

#### Task 1: Build Deterministic Repair Strategies (3 days)

- Implement `app/services/ai/json_repair.py` with all 10 strategies.
- Implement `app/services/ai/json_repair_strategies.py` with strategy functions.
- Implement `JsonRepairService.repair()` with configurable strategy chain.
- Write unit tests TR-01 through TR-20.
- Verify all strategies are independently testable.

**Acceptance criteria:**
- All 20 unit tests pass.
- Each strategy logged with name and success/failure.
- A JSON string with a single trailing comma is repaired in <1 ms.

#### Task 2: Configure Fast-Model Fallback (2 days)

- Implement fast-model repair integration via US-AI-026 `ModelRouter.call_repair_model()`.
- Implement `app/services/ai/prompts/json_repair_prompt.txt`.
- Wire `JsonRepairService` with fast-model function at app startup.
- Write integration tests FM-01 through FM-06.

**Acceptance criteria:**
- Fast-model is called only after deterministic chain fails.
- Max attempts config works (default 2).
- Fast-model response is validated as valid JSON before returning.

#### Task 3: Integrate with Chat Orchestrator (2 days)

- Replace `json.loads()` in `app/services/ai/chat_orchestrator.py` with `safe_json_loads()`.
- Add `_parse_tool_call_response()` method with repair augmentation.
- Add `JsonRepairInfo` to chat response DTO.
- Write integration tests IT-01 through IT-10.

**Acceptance criteria:**
- Chat orchestrator successfully parses malformed tool-call JSON.
- Repair telemetry is in chat response.
- No bare `json.loads()` remains in `app/services/ai/*`.
- Grep for `json.loads` in AI services returns only the `JsonRepairService` itself and `json_utils.py`.

#### Task 4: Implement Repair Telemetry and DB Persistence (2 days)

- Create `ai_repair_events` table via Alembic migration (DDL from Section 6).
- Create `AiRepairEvent` SQLAlchemy model.
- Implement `AiRepairRepository` with async insert + query methods.
- Wire repair event persistence into `JsonRepairService._emit_metric()`.
- Add Prometheus counter and histogram metrics.
- Add `repair_count` and `last_repair_event_id` columns to `ai_sessions`.

**Acceptance criteria:**
- Every repair event is persisted to `ai_repair_events`.
- Repair events queryable by trace_id, error_type, tool_name, final_success.
- Repair event latency <5 ms overhead for deterministic-only path.
- Metrics visible in Prometheus scrape endpoint.

#### Task 5: Configuration, Feature Flag, and Safety (1 day)

- Add all env vars from Section 7 to `.env.example` and app config.
- Add `json_repair` feature flag to `FeatureFlagService`.
- Implement `safe_json_loads` in `app/services/ai/json_utils.py` as the drop-in replacement.
- Add repair service health check to `/health` endpoint.
- Add PII-safe snippet truncation (`AI_REPAIR_SNIPPET_LENGTH`).
- Write security tests ST-01 through ST-04.

**Acceptance criteria:**
- Feature flag controls fast-model repair independently of deterministic repair.
- Health check returns repair_service_ok=true/false.
- No PII leaks in log snippets.

#### Task 6: Documentation and Onboarding (1 day)

- Add design doc section to `docs/AI_Implemenation/01_SystemArchitecture/` explaining the repair pipeline.
- Update `TOOL_SCHEMAS_CLAUDE_NATIVE.md` error response section to mention auto-repair.
- Add note to `US-AI-023` about the repair integration.
- Update `RESEARCH_AUDIT.md` to mark US-AI-027 gaps as "Resolved."

**Total estimated effort: 11 engineering days** (split across 2 engineers for parallel task execution: Tasks 1+4, Tasks 2+5, Task 3, Task 6).

---

## Appendix A: Registry of Common Error Patterns

Maintained in `app/services/ai/json_error_patterns.py`. Seeded initially from industry research and grown via telemetry.

| Pattern ID | Pattern | Strategy | Frequency (est.) |
|---|---|---|---|
| `trailing_comma_array` | `[1, 2,]` | remove_trailing_commas | ~35% |
| `trailing_comma_object` | `{"a": 1,}` | remove_trailing_commas | ~25% |
| `code_fences` | Surrounding ```json...``` | strip_code_fences | ~12% |
| `single_quotes` | `{'key': 'value'}` | escape_single_quotes | ~10% |
| `missing_braces_context` | Text before/after JSON | trim_to_first_last_brace | ~8% |
| `comment_artifacts` | `{"a":1 /* note */}` | remove_comments | ~5% |
| `unescaped_controls` | Embedded \x00 in string | fix_unescaped_controls | ~2% |
| `nan_infinity` | `{"a": NaN}` | fix_nan_infinity | ~1.5% |
| `duplicate_keys` | `{"a":1,"a":2}` | fix_duplicate_keys | ~1% |
| `leading_zeros` | `{"a": 00.5}` | fix_leading_zeros | ~0.5% |

## Appendix B: Dependency Graph

```
US-AI-005 (Tool Schema Registry)
    |
    v
US-AI-027 (JSON Repair) ──────────► US-AI-023 (Chat Orchestrator)
    |                                       |
    v                                       v
US-AI-026 (Model Routing) ──────► US-AI-024 (Frontend Integration)
    |                                       |
    v                                       v
US-AI-021 (Observability) ◄──── US-AI-036 (Cost Tracking)
    |
    v
US-AI-022 (E2E Tests)
```

---

*End of US-AI-027 Epic*
