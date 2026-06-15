"""Durable Workflow Engine - US-BKND-AI-034. Async Preview Gen - US-BKND-AI-041."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

class WorkflowState(str, Enum):
    PENDING="pending"; RUNNING="running"; COMPLETED="completed"
    FAILED="failed"; PAUSED="paused"

class DurableWorkflow:
    """Simple durable workflow with checkpoint/retry support."""
    def __init__(self, wf_id: str, name: str, user_id: str):
        self.wf_id=wf_id; self.name=name; self.user_id=user_id
        self.state=WorkflowState.PENDING; self.steps:List[Dict]=[]
        self.current_step=0; self.created_at=datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    def add_step(self, name: str, fn_name: str, payload: Dict=None) -> None:
        self.steps.append({"name":name,"fn":fn_name,"payload":payload or {},"status":"pending"})

    def advance(self, result: Any = None) -> Dict:
        if self.current_step < len(self.steps):
            self.steps[self.current_step]["status"]="completed"
            self.steps[self.current_step]["result"]=result
            self.current_step+=1
        if self.current_step >= len(self.steps):
            self.state=WorkflowState.COMPLETED; self.completed_at=datetime.now(timezone.utc)
        return self.to_dict()

    def fail_current(self, error: str) -> Dict:
        if self.current_step < len(self.steps):
            self.steps[self.current_step]["status"]="failed"
            self.steps[self.current_step]["error"]=error
        self.state=WorkflowState.FAILED; return self.to_dict()

    def to_dict(self) -> Dict:
        return {"wf_id":self.wf_id,"name":self.name,"state":self.state.value,
                "current_step":self.current_step,"total_steps":len(self.steps),
                "steps":self.steps,"created_at":self.created_at.isoformat(),
                "completed_at":self.completed_at.isoformat() if self.completed_at else None}


class AsyncPreviewJob:
    """Tracks async preview generation for a page or course."""
    def __init__(self, job_id: str, resource_type: str, resource_id: str, user_id: str):
        self.job_id=job_id; self.resource_type=resource_type; self.resource_id=resource_id
        self.user_id=user_id; self.status="pending"; self.progress=0.0
        self.preview_url:Optional[str]=None; self.error:Optional[str]=None
        self.created_at=datetime.now(timezone.utc)
        self.completed_at:Optional[datetime]=None

    def mark_complete(self, preview_url: str):
        self.status="completed"; self.progress=100.0; self.preview_url=preview_url
        self.completed_at=datetime.now(timezone.utc)

    def mark_failed(self, error: str):
        self.status="failed"; self.error=error; self.completed_at=datetime.now(timezone.utc)

    def to_dict(self) -> Dict:
        return {"job_id":self.job_id,"resource_type":self.resource_type,
                "resource_id":self.resource_id,"status":self.status,
                "progress":self.progress,"preview_url":self.preview_url,
                "error":self.error,"created_at":self.created_at.isoformat(),
                "completed_at":self.completed_at.isoformat() if self.completed_at else None}
