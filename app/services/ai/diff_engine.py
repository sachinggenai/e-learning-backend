"""Diff Engine — US-BKND-AI-009.

Computes field-level structural diffs between resource states for
proposal previews, audit trails, and optimistic concurrency checks.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any


class DiffEngine:
    """Computes before/after diffs for proposal operations."""

    def compute(
        self,
        operation: str,
        before: Optional[Dict[str, Any]],
        after: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compute a structured diff based on the operation type.

        Args:
            operation: create_page, update_page, delete_page
            before: Current DB state (None for creates)
            after: Proposed state (None for deletes)

        Returns:
            Dict with before, after, and changed_fields.
        """
        if operation in ("create_page", "create_course"):
            return {
                "before": None,
                "after": after,
                "changed_fields": sorted(after.keys()) if after else [],
            }

        elif operation in ("update_page", "update_course"):
            before_keys = set(before.keys()) if before else set()
            after_keys = set(after.keys()) if after else set()
            # Fields that were added, removed, or changed
            changed = sorted(
                before_keys.symmetric_difference(after_keys)
                | {
                    k for k in before_keys & after_keys
                    if before.get(k) != after.get(k)
                }
            )
            return {
                "before": before,
                "after": after,
                "changed_fields": changed,
            }

        elif operation == "delete_page":
            return {
                "before": before,
                "after": None,
                "changed_fields": sorted(before.keys()) if before else [],
            }

        else:
            return {
                "before": before,
                "after": after,
                "changed_fields": [],
            }
