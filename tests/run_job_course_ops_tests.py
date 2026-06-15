"""Tests for US-BKND-AI-045/046."""
from app.services.ai.job_status_service import JobStatusTracker, CourseOpsService, JobState, CourseOperation
passed = 0; failed = 0; failures = []
def check(n, c, d=""):
    global passed, failed
    if c: passed += 1; print(f"  PASS: {n}")
    else: failed += 1; failures.append((n, d)); print(f"  FAIL: {n} -- {d}")
def main():
    global passed, failed
    tracker = JobStatusTracker()
    j = tracker.create("j1", "course_generation", "u1")
    check("creates queued job", j["status"]=="queued" and j["progress"]==0)
    tracker.update("j1", status="running", progress=50, message="Generating page 3/6")
    j = tracker.get("j1")
    check("updates progress", j["progress"]==50)
    tracker.update("j1", status="completed", progress=100, result={"course_id":"c1"})
    j = tracker.get("j1")
    check("completes with result", j["status"]=="completed" and j["result"])
    check("has completed_at", j["completed_at"] is not None)
    jobs = tracker.list_by_user("u1")
    check("lists by user", len(jobs)==1)
    stats = tracker.get_stats()
    check("has stats", stats["total"]==1)

    print("\n=== Course Ops ===")
    ops = CourseOpsService()
    v = ops.validate_operation("create_course", "c1")
    check("valid op passes", v["valid"])
    v = ops.validate_operation("invalid_op", "c1")
    check("invalid op rejected", not v["valid"])
    ops.log_operation("create_course", "c1", "u1", "success")
    ops.log_operation("archive_course", "c2", "u1", "success")
    history = ops.get_course_operations("c1")
    check("course history", len(history)==1)
    check("valid ops set", len(CourseOpsService.VALID_OPS)==4)

    print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed")
    return failed == 0
if __name__ == "__main__":
    exit(0 if main() else 1)
