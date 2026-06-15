"""Job Status & Course-Level Operations - US-BKND-AI-045/046.

Real-time job status tracking for async AI operations and
course-level operation support (create, delete, archive courses).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

class JobState(str, Enum):
    QUEUED="queued"; RUNNING="running"; COMPLETED="completed"
    FAILED="failed"; CANCELLED="cancelled"

class JobStatusTracker:
    """Tracks async AI job status with real-time progress."""

    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def create(self, job_id: str, job_type: str, user_id: str) -> Dict:
        job = {"job_id":job_id, "job_type":job_type, "user_id":user_id,
               "status":JobState.QUEUED.value, "progress":0.0, "message":"Queued",
               "created_at":datetime.now(timezone.utc).isoformat(),
               "completed_at":None, "result":None, "error":None}
        self._jobs[job_id] = job; return job

    def update(self, job_id: str, status: str = "", progress: float = -1, message: str = "", result: Any = None, error: str = ""):
        j = self._jobs.get(job_id)
        if not j: return None
        if status: j["status"] = status
        if progress >= 0: j["progress"] = min(100.0, progress)
        if message: j["message"] = message
        if result is not None: j["result"] = result
        if error: j["error"] = error
        if status in (JobState.COMPLETED.value, JobState.FAILED.value, JobState.CANCELLED.value):
            j["completed_at"] = datetime.now(timezone.utc).isoformat()
        return j

    def get(self, job_id: str) -> Optional[Dict]: return self._jobs.get(job_id)

    def list_by_user(self, user_id: str) -> List[Dict]:
        return sorted([j for j in self._jobs.values() if j["user_id"]==user_id],
                      key=lambda j: j["created_at"], reverse=True)

    def get_stats(self) -> Dict:
        jobs = list(self._jobs.values())
        by_status = {}; by_type = {}
        for j in jobs:
            by_status[j["status"]] = by_status.get(j["status"], 0) + 1
            by_type[j["job_type"]] = by_type.get(j["job_type"], 0) + 1
        return {"total": len(jobs), "by_status": by_status, "by_type": by_type}


class CourseOperation(str, Enum):
    CREATE_COURSE = "create_course"
    DELETE_COURSE = "delete_course"
    ARCHIVE_COURSE = "archive_course"
    DUPLICATE_COURSE = "duplicate_course"

class CourseOpsService:
    """Course-level AI-assisted operations with validation."""

    VALID_OPS = {op.value for op in CourseOperation}

    def __init__(self):
        self._ops_log: List[Dict] = []

    def validate_operation(self, operation: str, course_id: str) -> Dict[str, Any]:
        """Validate a course-level operation before execution."""
        issues = []
        if operation not in self.VALID_OPS:
            issues.append({"field":"operation","message":f"Invalid operation: {operation}","severity":"error"})
        if not course_id:
            issues.append({"field":"course_id","message":"Course ID required","severity":"error"})
        return {"valid": len(issues) == 0, "issues": issues}

    def log_operation(self, operation: str, course_id: str, user_id: str, result: str) -> Dict:
        entry = {"operation": operation, "course_id": course_id, "user_id": user_id,
                 "result": result, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._ops_log.append(entry); return entry

    def get_course_operations(self, course_id: str) -> List[Dict]:
        return [o for o in self._ops_log if o["course_id"] == course_id]
