"""Tests for US-BKND-AI-020 - Admin Audit Views."""
from app.services.ai.audit_query_service import AuditQueryService

passed = 0; failed = 0; failures = []
def check(n, c, d=""):
    global passed, failed
    if c: passed += 1; print(f"  PASS: {n}")
    else: failed += 1; failures.append((n, d)); print(f"  FAIL: {n} -- {d}")

def main():
    global passed, failed
    svc = AuditQueryService()

    # Seed data
    for i in range(15):
        svc.record({"user_id": f"user_{i%3}", "course_id": f"course_{i%2}", "operation": ["create_page","update_page","delete_page"][i%3], "outcome": "success" if i%5 else "failed", "session_id": f"sess_{i%4}", "summary": f"Audit entry {i}", "proposal_id": f"prop_{i}"})

    print("=== Query ===")
    r = svc.query(page_size=10)
    check("has items", len(r["items"]) > 0)
    check("has total", r["total"] == 15)
    check("pagination", r["page"] == 1 and r["total_pages"] == 2)

    r = svc.query(user_id="user_0")
    check("user filter", all(e["user_id"]=="user_0" for e in r["items"]))

    r = svc.query(operation="create_page")
    check("operation filter", all(e["operation"]=="create_page" for e in r["items"]))

    r = svc.query(outcome="failed")
    check("outcome filter", all(e["outcome"]=="failed" for e in r["items"]))

    r = svc.query(search="entry 5")
    check("search", len(r["items"]) >= 1)

    print("\n=== Operations Summary ===")
    s = svc.get_operations_summary(days=30)
    check("has total", "total_operations" in s)
    check("has by_operation", "by_operation" in s)
    check("has by_outcome", "by_outcome" in s)
    check("has by_user", "by_user" in s)
    check("has by_course", "by_course" in s)
    check("counts correct", sum(s["by_operation"].values()) == 15)

    print("\n=== Course History ===")
    h = svc.get_course_history("course_0")
    check("has history", len(h["history"]) > 0)
    check("has total_mutations", h["total_mutations"] > 0)

    print("\n=== Empty Query ===")
    r = svc.query(user_id="nonexistent")
    check("empty filter", r["total"] == 0 and len(r["items"]) == 0)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    exit(0 if main() else 1)
