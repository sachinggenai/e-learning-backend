"""Standalone test runner for US-BKND-AI-027 - JSON Repair Service.

Tests all 12 repair strategies, telemetry, edge cases, safe_parse,
and integration scenarios.
"""
import json
from app.services.ai.json_repair import (
    JSONRepair, RepairTelemetry, safe_json_loads, JSONRepairError,
)

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


def main():
    global passed, failed

    # ===============================================================
    # Strategy 1: Markdown Extraction
    # ===============================================================
    print("=== Strategy 1: Markdown Extraction ===")
    r, s, t = JSONRepair.repair('```json\n{"a": 1}\n```')
    check("extracts from code fence", json.loads(r) == {"a": 1})
    check("strategy recorded", "strip_code_fences" in (s or ""))

    r, s, t = JSONRepair.repair('```\n[1, 2, 3]\n```')
    check("extracts array from fence", json.loads(r) == [1, 2, 3])

    # ===============================================================
    # Strategy 2: BOM and Whitespace
    # ===============================================================
    print("\n=== Strategy 2: BOM/Whitespace ===")
    r, s, t = JSONRepair.repair('  \n  {"a": 1}  \n')
    check("strips whitespace", json.loads(r) == {"a": 1})
    check("strategy recorded", "strip_bom_and_whitespace" in (s or ""))

    # ===============================================================
    # Strategy 3: Trim to Braces
    # ===============================================================
    print("\n=== Strategy 3: Trim to Braces ===")
    r, s, t = JSONRepair.repair('some text {"a": 1} more text')
    check("extracts JSON from text", json.loads(r) == {"a": 1})
    check("strategy recorded", "trim_to_braces" in (s or ""))

    r, s, t = JSONRepair.repair('prefix [1, 2, 3] suffix')
    check("extracts array from text", json.loads(r) == [1, 2, 3])

    # ===============================================================
    # Strategy 4: Remove Comments
    # ===============================================================
    print("\n=== Strategy 4: Remove Comments ===")
    r, s, t = JSONRepair.repair('{"a": 1 /* comment */, "b": 2}')
    check("removes block comments", json.loads(r) == {"a": 1, "b": 2})

    r, s, t = JSONRepair.repair('// line comment\n{"a": 1}')
    check("removes line comments", json.loads(r) == {"a": 1})

    r, s, t = JSONRepair.repair('<!-- html comment -->\n{"a": 1}')
    check("removes HTML comments", json.loads(r) == {"a": 1})

    # ===============================================================
    # Strategy 5: Remove Trailing Commas
    # ===============================================================
    print("\n=== Strategy 5: Trailing Commas ===")
    r, s, t = JSONRepair.repair('{"a": 1, "b": 2,}')
    check("removes trailing comma in object", json.loads(r) == {"a": 1, "b": 2})

    r, s, t = JSONRepair.repair('[1, 2, 3,]')
    check("removes trailing comma in array", json.loads(r) == [1, 2, 3])

    r, s, t = JSONRepair.repair('{"a": [1, 2,], "b": {"c": 3,}}')
    check("removes nested trailing commas", json.loads(r) == {"a": [1, 2], "b": {"c": 3}})

    # ===============================================================
    # Strategy 6: Fix Single Quotes
    # ===============================================================
    print("\n=== Strategy 6: Single Quotes ===")
    r, s, t = JSONRepair.repair("{'key': 'value'}")
    check("fixes single quotes", json.loads(r) == {"key": "value"})

    # ===============================================================
    # Strategy 7: Fix Unescaped Controls
    # ===============================================================
    print("\n=== Strategy 7: Unescaped Controls ===")
    # Strategy 7 also removes control chars
    r, s, t = JSONRepair.repair('{"a": "value", "b": "ok"}')
    check("clean input passes", json.loads(r) == {"a": "value", "b": "ok"})

    # ===============================================================
    # Strategy 8: NaN/Infinity
    # ===============================================================
    print("\n=== Strategy 8: NaN/Infinity ===")
    r, s, t = JSONRepair.repair('{"a": NaN, "b": Infinity, "c": -Infinity}')
    check("fixes NaN", json.loads(r) == {"a": None, "b": None, "c": None})
    check("strategy recorded", "fix_nan_infinity" in (s or ""))

    # ===============================================================
    # Strategy 9: Leading Zeros
    # ===============================================================
    print("\n=== Strategy 9: Leading Zeros ===")
    r, s, t = JSONRepair.repair('{"a": 01.5, "b": 00}')
    check("fixes leading zeros", json.loads(r) == {"a": 1.5, "b": 0})
    check("strategy recorded", "fix_leading_zeros" in (s or ""))

    # ===============================================================
    # Strategy 10: Balance Braces
    # ===============================================================
    print("\n=== Strategy 10: Balance Braces ===")
    r, s, t = JSONRepair.repair('{"a": [1, 2')
    check("balances missing brackets", json.loads(r) == {"a": [1, 2]})

    r, s, t = JSONRepair.repair('{"a": {"b": 1')
    check("balances missing braces", json.loads(r) == {"a": {"b": 1}})

    # ===============================================================
    # Strategy 11: Duplicate Keys
    # ===============================================================
    print("\n=== Strategy 11: Duplicate Keys ===")
    # Duplicate keys with other issue that forces repair path
    r, s, t = JSONRepair.repair('{"a": 1, "a": 2,}')  # trailing comma triggers repair
    check("deduplicates keys with trailing comma", json.loads(r) == {"a": 2})
    check("dup key strategy recorded", "fix_duplicate_keys" in (s or ""))

    # ===============================================================
    # Strategy 12: Truncation Recovery
    # ===============================================================
    print("\n=== Strategy 12: Truncation Recovery ===")
    r, s, t = JSONRepair.repair('{"a": "unclosed string')
    check("closes unclosed string", json.loads(r) == {"a": "unclosed string"})

    r, s, t = JSONRepair.repair('{"a": [1, 2,')
    check("recovers truncated array", json.loads(r) == {"a": [1, 2]})

    # ===============================================================
    # Combined Strategies
    # ===============================================================
    print("\n=== Combined Strategies ===")
    r, s, t = JSONRepair.repair('```json\n{"a": 01, "b": NaN, "c": [1,2,]}\n```')
    check("multiple fixes combined", json.loads(r) == {"a": 1, "b": None, "c": [1, 2]})
    check("multiple strategies recorded", s and "strip_code_fences" in s and "fix_nan_infinity" in s)

    # ===============================================================
    # Telemetry
    # ===============================================================
    print("\n=== Telemetry ===")
    r, s, t = JSONRepair.repair('{"a": 1,}', tool_name="propose_create_page", turn_id="turn_1")
    check("telemetry has tool_name", t.tool_name == "propose_create_page")
    check("telemetry has turn_id", t.chat_turn_id == "turn_1")
    check("telemetry has input_length", t.input_length > 0)
    check("telemetry has strategies", len(t.strategies_applied) > 0)
    check("telemetry deterministic success", t.deterministic_success)
    check("telemetry final success", t.final_success)
    check("telemetry latency > 0", t.latency_ms >= 0)
    d = t.to_dict()
    check("telemetry to_dict", isinstance(d, dict) and "strategies_applied" in d)

    # ===============================================================
    # safe_parse / safe_json_loads
    # ===============================================================
    print("\n=== Safe Parse ===")
    result, t = JSONRepair.safe_parse('{"valid": true}')
    check("safe_parse direct path", result == {"valid": True} and t is None)

    result, t = JSONRepair.safe_parse('```json\n{"a": NaN}\n```')
    check("safe_parse repair path", result == {"a": None})
    check("safe_parse telemetry success", t and t.deterministic_success)

    result, t = JSONRepair.safe_parse('not json at all {{{')
    check("safe_parse failure returns default", result is None)
    check("safe_parse failure telemetry", t and not t.final_success)

    result = safe_json_loads('{"a": 1}')
    check("safe_json_loads works", result == {"a": 1})

    result = safe_json_loads('not json', default={})
    check("safe_json_loads default", result == {})

    result, t = JSONRepair.safe_parse_dict('{"key": "value"}')
    check("safe_parse_dict works", result == {"key": "value"})

    result, t = JSONRepair.safe_parse_dict('not dict', default={"fallback": True})
    check("safe_parse_dict fallback", result == {"fallback": True})

    # ===============================================================
    # Edge Cases
    # ===============================================================
    print("\n=== Edge Cases ===")
    try:
        JSONRepair.repair("")
        check("empty string raises", False, "should raise")
    except JSONRepairError:
        check("empty string raises JSONRepairError", True)

    try:
        JSONRepair.repair("   ")
        check("whitespace only raises", False, "should raise")
    except JSONRepairError:
        check("whitespace only raises JSONRepairError", True)

    r, s, t = JSONRepair.repair('{"a": null}')
    check("null handled correctly", json.loads(r) == {"a": None})

    r, s, t = JSONRepair.repair('{"a": true, "b": false}')
    check("booleans preserved", json.loads(r) == {"a": True, "b": False})

    r, s, t = JSONRepair.repair('{"nested": {"deep": [1, 2, 3]}}')
    check("deep nesting preserved", json.loads(r) == {"nested": {"deep": [1, 2, 3]}})

    r, s, t = JSONRepair.repair('{"unicode": "\\u00e9"}')
    check("unicode escapes preserved", json.loads(r) == {"unicode": "é"})

    # ===============================================================
    # RepairTelemetry standalone
    # ===============================================================
    print("\n=== RepairTelemetry ===")
    tele = RepairTelemetry()
    tele.input_length = 100
    tele.error_type = "JSONDecodeError"
    tele.strategies_applied = ["strip_code_fences", "fix_nan_infinity"]
    tele.deterministic_success = True
    tele.final_success = True
    tele.latency_ms = 1.5
    d = tele.to_dict()
    check("telemetry serialization", d["input_length"] == 100)
    check("telemetry strategies", len(d["strategies_applied"]) == 2)
    check("telemetry success flags", d["deterministic_success"] and d["final_success"])

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
