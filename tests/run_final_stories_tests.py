"""Tests for US-BKND-AI-032/034/041 - Final 3 stories."""
from app.services.ai.policy_engine import PolicyEngine, PolicyDecision
from app.services.ai.durable_workflow import DurableWorkflow, WorkflowState, AsyncPreviewJob

passed = 0; failed = 0; failures = []
def check(n, c, d=""):
    global passed, failed
    if c: passed += 1; print(f"  PASS: {n}")
    else: failed += 1; failures.append((n, d)); print(f"  FAIL: {n} -- {d}")

def main():
    global passed, failed

    print("=== Policy Engine ===")
    pe = PolicyEngine()
    # Auto-apply: simple text-content create
    r = pe.evaluate({"operation":"create_page","template_type":"text-content","validation_status":"valid","has_warnings":False})
    check("auto-apply text-content", r["decision"]==PolicyDecision.AUTO_APPLY.value)

    # Blocked: delete with final assessment
    r = pe.evaluate({"operation":"delete_page","has_final_assessment":True})
    check("block final assessment delete", r["decision"]==PolicyDecision.BLOCKED.value)

    # Blocked: course delete
    r = pe.evaluate({"operation":"delete_course"})
    check("block course delete", r["decision"]==PolicyDecision.BLOCKED.value)

    # Requires review: assessment template
    r = pe.evaluate({"operation":"create_page","template_type":"final-assessment","validation_status":"valid"})
    check("review assessment", r["decision"]==PolicyDecision.REQUIRES_REVIEW.value)

    # Requires review: complex template
    r = pe.evaluate({"operation":"create_page","template_type":"accordion","validation_status":"valid"})
    check("review accordion", r["decision"]==PolicyDecision.REQUIRES_REVIEW.value)

    # Default: unknown context
    r = pe.evaluate({"operation":"unknown_op"})
    check("default to review", r["decision"]==PolicyDecision.REQUIRES_REVIEW.value)

    # Custom rule
    pe.add_rule("my_custom", 200, {"operation":"custom_op"}, "auto_apply", "Custom auto-apply")
    r = pe.evaluate({"operation":"custom_op"})
    check("custom rule works", r["decision"]=="auto_apply" and r["matched_rule"]=="my_custom")

    # __in operator
    r = pe.evaluate({"operation":"create_page","template_type":"tabs","validation_status":"valid"})
    check("__in matches tabs", r["decision"]==PolicyDecision.REQUIRES_REVIEW.value)

    # has_warnings=True should not auto-apply
    r = pe.evaluate({"operation":"create_page","template_type":"text-content","validation_status":"valid","has_warnings":True})
    check("warnings prevent auto-apply", r["decision"]!=PolicyDecision.AUTO_APPLY.value)

    print("\n=== Durable Workflow ===")
    wf = DurableWorkflow("wf1", "course_generation", "u1")
    check("initial state pending", wf.state==WorkflowState.PENDING)
    wf.add_step("extract_document", "extract", {"file":"doc.pdf"})
    wf.add_step("generate_pages", "generate", {"count":5})
    wf.add_step("validate_course", "validate", {})
    check("has 3 steps", len(wf.steps)==3)
    r = wf.advance({"pages":5})
    check("advances step 1", wf.current_step==1)
    wf.advance({"course_id":"c1"})
    wf.advance({"valid":True})
    check("completes workflow", wf.state==WorkflowState.COMPLETED)
    d = wf.to_dict()
    check("serializes", d["state"]=="completed")

    wf2 = DurableWorkflow("wf2","test","u1")
    wf2.add_step("step1","fn1",{})
    wf2.fail_current("timeout")
    check("fails workflow", wf2.state==WorkflowState.FAILED)

    print("\n=== Async Preview ===")
    preview = AsyncPreviewJob("j1", "page", "p1", "u1")
    check("initial pending", preview.status=="pending" and preview.progress==0)
    preview.mark_complete("https://cdn.example.com/previews/p1.html")
    check("complete with url", preview.status=="completed" and preview.preview_url is not None)
    check("has completed_at", preview.completed_at is not None)

    preview2 = AsyncPreviewJob("j2","course","c1","u1")
    preview2.mark_failed("Generation timeout")
    check("failed with error", preview2.status=="failed" and preview2.error is not None)

    print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    exit(0 if main() else 1)
