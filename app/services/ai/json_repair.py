"""JSON Repair Service - US-BKND-AI-027.

Repairs common LLM JSON formatting errors before they become parse failures.
Handles: trailing commas, missing braces, unescaped quotes, truncation,
HTML artifacts, duplicate keys, numeric edge cases, NaN/Infinity,
leading zeros, BOM, single quotes, and code fence extraction.

12-strategy deterministic pipeline plus telemetry. Reduces LLM retry
rounds by recovering from minor formatting errors without requiring
an additional model call.
"""

from __future__ import annotations

import re
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple, List

logger = logging.getLogger("ai_authoring")


class RepairTelemetry:
    """Structured telemetry for JSON repair operations."""

    def __init__(self):
        self.input_length: int = 0
        self.error_type: str = ""
        self.strategies_applied: List[str] = []
        self.deterministic_success: bool = False
        self.fast_model_called: bool = False
        self.fast_model_attempts: int = 0
        self.fast_model_success: Optional[bool] = None
        self.final_success: bool = False
        self.latency_ms: float = 0.0
        self.tool_name: str = ""
        self.chat_turn_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_length": self.input_length,
            "error_type": self.error_type,
            "strategies_applied": self.strategies_applied,
            "deterministic_success": self.deterministic_success,
            "fast_model_called": self.fast_model_called,
            "fast_model_attempts": self.fast_model_attempts,
            "fast_model_success": self.fast_model_success,
            "final_success": self.final_success,
            "latency_ms": self.latency_ms,
            "tool_name": self.tool_name,
            "chat_turn_id": self.chat_turn_id,
        }


class JSONRepairError(Exception):
    """JSON could not be repaired after all strategies."""
    def __init__(self, original: str, attempts: list):
        self.original = original
        self.attempts = attempts
        super().__init__("JSON repair failed after all strategies")


class JSONRepair:
    """Attempts to repair malformed JSON from LLM outputs.

    12-strategy pipeline applied in order. Each strategy is independently
    testable and logs its contribution to repair. Telemetry is captured
    for monitoring and offline analysis.
    """

    MAX_ATTEMPTS = 5

    @classmethod
    def repair(cls, text: str, tool_name: str = "", turn_id: str = "") -> Tuple[str, Optional[str], RepairTelemetry]:
        """Attempt to repair malformed JSON.

        Returns (repaired_text, strategy_chain, telemetry).
        Raises JSONRepairError if all strategies fail.
        """
        telemetry = RepairTelemetry()
        telemetry.tool_name = tool_name
        telemetry.chat_turn_id = turn_id
        telemetry.input_length = len(text)

        start = time.time()

        if not text or not text.strip():
            telemetry.latency_ms = (time.time() - start) * 1000
            raise JSONRepairError(text, ["empty_input"])

        original = text
        attempts: List[str] = []

        strategies = [
            ("strip_code_fences", cls._extract_from_markdown),
            ("strip_bom_and_whitespace", cls._strip_bom_whitespace),
            ("trim_to_braces", cls._trim_to_braces),
            ("remove_comments", cls._remove_artifacts),
            ("remove_trailing_commas", cls._remove_trailing_commas),
            ("escape_single_quotes", cls._fix_single_quotes),
            ("fix_unescaped_controls", cls._fix_unescaped_chars),
            ("fix_nan_infinity", cls._fix_nan_infinity),
            ("fix_leading_zeros", cls._fix_leading_zeros),
            ("recover_truncation", cls._recover_truncation),  # Before balance_braces
            ("balance_braces", cls._balance_braces),
            ("fix_duplicate_keys", cls._fix_duplicate_keys),
        ]

        for strategy_name, strategy_fn in strategies:
            try:
                repaired = strategy_fn(text)
                if repaired != text:
                    attempts.append(strategy_name)
                    text = repaired
            except Exception:
                pass

        try:
            json.loads(text)
            strategy_chain = " -> ".join(attempts) if attempts else None
            telemetry.strategies_applied = attempts
            telemetry.deterministic_success = True
            telemetry.final_success = True
            telemetry.latency_ms = (time.time() - start) * 1000
            logger.debug("JSON repaired: strategies=%s, latency=%.2fms", strategy_chain, telemetry.latency_ms)
            return text, strategy_chain, telemetry
        except json.JSONDecodeError as e:
            telemetry.strategies_applied = attempts
            telemetry.error_type = type(e).__name__
            telemetry.latency_ms = (time.time() - start) * 1000
            raise JSONRepairError(original, attempts)

    # Strategy 1: Extract from markdown code blocks
    @staticmethod
    def _extract_from_markdown(text: str) -> str:
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r'`(\{.*?\}|\[.*?\])`', text, re.DOTALL)
        if m and len(m.group(1)) > 10:
            return m.group(1).strip()
        return text

    # Strategy 2: Strip BOM and whitespace
    @staticmethod
    def _strip_bom_whitespace(text: str) -> str:
        if text.startswith('﻿'):
            text = text[1:]
        return text.strip()

    # Strategy 3: Trim to first/last brace
    @staticmethod
    def _trim_to_braces(text: str) -> str:
        text = text.strip()
        if not text:
            return text
        first_brace = -1
        target_open = None
        target_close = None
        for i, ch in enumerate(text):
            if ch in ('{', '[') and target_open is None:
                target_open = ch
                target_close = '}' if ch == '{' else ']'
                first_brace = i
                break
        if first_brace == -1:
            return text
        depth = 0
        last_brace = -1
        for i in range(first_brace, len(text)):
            if text[i] == target_open:
                depth += 1
            elif text[i] == target_close:
                depth -= 1
                if depth == 0:
                    last_brace = i
                    break
        if last_brace > first_brace:
            return text[first_brace:last_brace + 1].strip()
        return text

    # Strategy 4: Remove trailing commas
    @staticmethod
    def _remove_trailing_commas(text: str) -> str:
        text = re.sub(r',\s*\]', ']', text)
        text = re.sub(r',\s*\}', '}', text)
        text = re.sub(r',\s*$', '', text.strip()).strip()
        return text

    # Strategy 5: Fix single quotes
    @staticmethod
    def _fix_single_quotes(text: str) -> str:
        if "'" not in text:
            return text
        if '"' in text:
            return text
        text = re.sub(r"'([^']+)'\s*:", r'"\1":', text)
        text = re.sub(r":\s*'([^']*)'", r':"\1"', text)
        return text

    # Strategy 6: Fix unescaped characters
    @staticmethod
    def _fix_unescaped_chars(text: str) -> str:
        text = text.replace('“', '"').replace('”', '"')
        text = text.replace('‘', "'").replace('’', "'")
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        return text

    # Strategy 7: Fix NaN/Infinity
    @staticmethod
    def _fix_nan_infinity(text: str) -> str:
        # Use lookbehind for -Infinity (no word boundary before -)
        text = re.sub(r'(?<![a-zA-Z0-9])-Infinity\b', 'null', text)
        text = re.sub(r'\bInfinity\b', 'null', text)
        text = re.sub(r'\bNaN\b', 'null', text)
        return text

    # Strategy 8: Fix leading zeros
    @staticmethod
    def _fix_leading_zeros(text: str) -> str:
        result = []
        i = 0
        in_string = False
        while i < len(text):
            if text[i] == '"' and (i == 0 or text[i-1] != '\\'):
                in_string = not in_string
                result.append(text[i])
                i += 1
                continue
            if not in_string:
                m = re.match(r'\b0(\d+\.?\d*)\b', text[i:])
                if m:
                    result.append(m.group(1))
                    i += m.end()
                    continue
            result.append(text[i])
            i += 1
        return ''.join(result)

    # Strategy 9: Balance braces and brackets (string-aware)
    @staticmethod
    def _balance_braces(text: str) -> str:
        # Count braces only outside strings
        open_braces = 0
        close_braces = 0
        open_brackets = 0
        close_brackets = 0
        in_string = False
        escape_next = False
        for ch in text:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == '{':
                    open_braces += 1
                elif ch == '}':
                    close_braces += 1
                elif ch == '[':
                    open_brackets += 1
                elif ch == ']':
                    close_brackets += 1

        result = text.rstrip()
        # Close brackets before braces (correct nesting)
        if open_brackets > close_brackets:
            result += ']' * (open_brackets - close_brackets)
        if open_braces > close_braces:
            result += '}' * (open_braces - close_braces)
        return result

    # Strategy 10: Remove comments/HTML artifacts
    @staticmethod
    def _remove_artifacts(text: str) -> str:
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        lines = []
        in_string = False
        for line in text.split('\n'):
            stripped = line.strip()
            if not in_string and (stripped.startswith('//') or stripped.startswith('#')):
                continue
            lines.append(line)
        return '\n'.join(lines)

    # Strategy 11: Fix duplicate keys
    @staticmethod
    def _fix_duplicate_keys(text: str) -> str:
        try:
            data = json.loads(text)
            return json.dumps(data)
        except (json.JSONDecodeError, ValueError):
            return text

    # Strategy 12: Truncation recovery
    @staticmethod
    def _recover_truncation(text: str) -> str:
        if not text:
            return text
        text = text.strip()
        in_string = False
        escape_next = False
        for ch in text:
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
            elif ch == '"':
                in_string = not in_string
        if in_string:
            text += '"'
        text = JSONRepair._balance_braces(text)
        text = JSONRepair._remove_trailing_commas(text)
        return text

    # Convenience methods
    @classmethod
    def safe_parse(cls, text: str, default: Any = None,
                   tool_name: str = "", turn_id: str = "") -> Tuple[Any, Optional[RepairTelemetry]]:
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            pass
        try:
            repaired, strategy, telemetry = cls.repair(text, tool_name, turn_id)
            result = json.loads(repaired)
            return result, telemetry
        except (JSONRepairError, json.JSONDecodeError) as e:
            telemetry = RepairTelemetry()
            telemetry.input_length = len(text)
            telemetry.error_type = type(e).__name__
            telemetry.final_success = False
            telemetry.tool_name = tool_name
            telemetry.chat_turn_id = turn_id
            logger.debug("JSON repair failed: %s...", text[:80])
            return default, telemetry

    @classmethod
    def safe_parse_dict(cls, text: str, default: Optional[Dict] = None,
                        tool_name: str = "", turn_id: str = "") -> Tuple[Dict[str, Any], Optional[RepairTelemetry]]:
        result, telemetry = cls.safe_parse(text, default, tool_name, turn_id)
        if isinstance(result, dict):
            return result, telemetry
        return default or {}, telemetry


def safe_json_loads(text: str, default: Any = None) -> Any:
    """Centralized safe JSON loading for all AI module paths.

    Use this instead of bare json.loads() throughout app/services/ai/.
    """
    result, _ = JSONRepair.safe_parse(text, default)
    return result
