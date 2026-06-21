"""Central registry mapping (workflow_type, state_name) -> step functions.

SINGLETON PATTERN: get_default_registry() returns the shared instance.
Step modules register via decorators on the shared instance.
The orchestrator looks up steps from the SAME shared instance.

This fixes the B1 bug identified in the developer review:
    - Was: step modules create StepRegistry() instances, orchestrator creates another
    - Now: single shared instance via get_default_registry()
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

StepKey = Tuple[str, str]  # (workflow_type, state_name)


class StepRegistry:
    """Maps (workflow_type, state_name) to async step executor functions."""

    def __init__(self):
        self._steps: Dict[StepKey, Callable] = {}

    def register(self, workflow_type: str, state_name: str):
        """Decorator: @registry.register('course_generation', 'validate_input')"""
        def decorator(func: Callable):
            self._steps[(workflow_type, state_name)] = func
            return func
        return decorator

    def get(self, workflow_type: str, state_name: str) -> Callable | None:
        """Look up a step function. Returns None if not registered."""
        return self._steps.get((workflow_type, state_name))

    def unregister(self, workflow_type: str, state_name: str) -> None:
        """Remove a step registration (useful in tests)."""
        self._steps.pop((workflow_type, state_name), None)

    @property
    def registered_steps(self) -> Dict[StepKey, Callable]:
        """Return {key: func} — the actual registered callables."""
        return dict(self._steps)

    @property
    def registered_step_names(self) -> Dict[StepKey, str]:
        """Return {key: func_name} for debugging."""
        return {k: f.__name__ for k, f in self._steps.items()}


# ═══════════════════════════════════════════════════════════════════
# Shared singleton — ALL modules use this same instance
# ═══════════════════════════════════════════════════════════════════

_default_registry: StepRegistry | None = None


def get_default_registry() -> StepRegistry:
    """Get or create the shared StepRegistry singleton.

    Step modules call this to get the registry they decorate.
    The orchestrator calls this to look up steps.
    Tests can reset it via reset_default_registry().
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = StepRegistry()
    return _default_registry


def reset_default_registry() -> None:
    """Reset the singleton (for tests that need a clean registry)."""
    global _default_registry
    _default_registry = StepRegistry()
