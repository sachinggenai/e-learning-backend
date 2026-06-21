"""Shared types for the durable workflow engine — US-BKND-AI-034."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    """Return value from a step executor function.

    Args:
        success: True if the step completed successfully.
        checkpoint_data: Dict to merge into the job's checkpoint_data.
        progress: Optional float 0.0-1.0. If None, progress is unchanged.
        error: Optional dict with 'code' and 'message' keys.
        output: Optional dict with step-specific output (stored in checkpoint).
    """
    success: bool
    checkpoint_data: Dict[str, Any] = field(default_factory=dict)
    progress: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
