"""Standalone test runner for US-BKND-AI-050 - Stale Detection.

Tests StaleDetector: hash computation, staleness classification,
three-way auto-merge, conflict reporting, force overwrite.
"""
from app.services.ai.stale_detector import (
    StaleDetector, StalenessLevel,
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
    detector = StaleDetector()

    # ===============================================================
    # Hash Computation
    # ===============================================================
    print("=== Hash Computation ===")
    h1 = detector.compute_hash({"title": "Test", "order": 1, "components": []})
    h2 = detector.compute_hash({"title": "Test", "order": 1, "components": []})
    check("deterministic hash", h1 == h2)
    check("hash is 64 chars", len(h1) == 64)
    h3 = detector.compute_hash({"title": "Different", "order": 1})
    check("different data = different hash", h1 != h3)

    # ===============================================================
    # Current (No Staleness)
    # ===============================================================
    print("\n=== Current (No Staleness) ===")
    base = {"title": "Intro", "body": "Hello", "order": 1}
    current = {"title": "Intro", "body": "Hello", "order": 1}
    proposed = {"title": "New Title"}

    result = detector.check_staleness(base, current, proposed)
    check("current state detected", result["level"] == StalenessLevel.CURRENT.value)
    check("can auto merge", result["can_auto_merge"])
    check("merged has new title", result["merged_state"]["title"] == "New Title")

    # ===============================================================
    # STALE_COMPATIBLE (Non-overlapping changes)
    # ===============================================================
    print("\n=== STALE_COMPATIBLE ===")
    base2 = {"title": "Intro", "body": "Hello", "order": 1}
    current2 = {"title": "Intro", "body": "Hello", "order": 2}  # order changed
    proposed2 = {"title": "New Title"}  # AI changes title

    result = detector.check_staleness(base2, current2, proposed2)
    check("compatible staleness detected", result["level"] == StalenessLevel.STALE_COMPATIBLE.value)
    check("can auto merge", result["can_auto_merge"])
    merged = result["merged_state"]
    check("merged keeps local order change", merged["order"] == 2)
    check("merged applies remote title change", merged["title"] == "New Title")
    check("merged preserves body", merged["body"] == "Hello")

    # ===============================================================
    # STALE_CONFLICT (Overlapping changes)
    # ===============================================================
    print("\n=== STALE_CONFLICT ===")
    base3 = {"title": "Intro", "body": "Hello", "order": 1}
    current3 = {"title": "Intro", "body": "Bob's edit", "order": 1}  # Bob changed body
    proposed3 = {"body": "AI's edit"}  # AI also changed body

    result = detector.check_staleness(base3, current3, proposed3)
    check("conflict detected", result["level"] == StalenessLevel.STALE_CONFLICT.value)
    check("cannot auto merge", not result["can_auto_merge"])
    check("has conflicts", len(result["conflicts"]) > 0)
    conflict = result["conflicts"][0]
    check("conflict has field path", "/body" in conflict["field"])
    check("conflict has base value", conflict["base_value"] == "Hello")
    check("conflict has local value", "Bob's edit" in conflict["local_value"])
    check("conflict has remote value", "AI's edit" in conflict["remote_value"])

    # ===============================================================
    # Auto-Merge Helper
    # ===============================================================
    print("\n=== Auto-Merge Helper ===")
    success, merged, conflicts = detector.auto_merge(base2, current2, proposed2)
    check("auto_merge succeeds for compatible", success)
    check("auto_merge returns state", merged is not None)
    check("auto_merge no conflicts", len(conflicts) == 0)

    success, merged, conflicts = detector.auto_merge(base3, current3, proposed3)
    check("auto_merge fails for conflict", not success)
    check("auto_merge returns conflicts", len(conflicts) > 0)

    # ===============================================================
    # Force Overwrite
    # ===============================================================
    print("\n=== Force Overwrite ===")
    state = {"title": "Current", "body": "Current body", "order": 3}
    changes = {"title": "Overwritten", "body": "New body"}
    result = detector.force_overwrite_state(state, changes)
    check("force overwrites title", result["title"] == "Overwritten")
    check("force overwrites body", result["body"] == "New body")
    check("force preserves order", result["order"] == 3)

    # ===============================================================
    # Edge Cases
    # ===============================================================
    print("\n=== Edge Cases ===")
    # Nested dict changes
    base_nest = {"title": "X", "layout": {"templateType": "text"}}
    current_nest = {"title": "X", "layout": {"templateType": "accordion"}}
    proposed_nest = {"title": "New"}
    result = detector.check_staleness(base_nest, current_nest, proposed_nest)
    check("nested changes detected", result["level"] == StalenessLevel.STALE_COMPATIBLE.value)

    # Identical base and current
    result = detector.check_staleness({"a": 1}, {"a": 1}, {})
    check("identical states are current", result["level"] == StalenessLevel.CURRENT.value)

    # Empty proposed changes
    result = detector.check_staleness({"a": 1}, {"a": 2}, {})
    check("empty proposed with local change", result["level"] == StalenessLevel.STALE_COMPATIBLE.value)

    # ===============================================================
    # Diff Computation
    # ===============================================================
    print("\n=== Diff Computation ===")
    diffs = detector._diff_states({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4})
    check("detects changed field", "b" in diffs)
    check("detects new field", "c" in diffs)
    check("unchanged field not in diffs", "a" not in diffs)

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
