"""Stale Detection and Merge Resolution - US-BKND-AI-050.

Detects when AI proposals are based on stale page content, classifies
staleness severity, performs three-way auto-merge for non-conflicting
changes, and produces structured conflict reports for human review.

Architecture:
    Fetch page -> get version_hash
    Propose changes -> compare version_hash -> classify staleness
    STALE_COMPATIBLE -> auto-merge
    STALE_CONFLICT -> return conflict report
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class StalenessLevel(str, Enum):
    CURRENT = "current"            # No staleness
    STALE_NO_CHANGE = "no_change"  # Metadata-only changes
    STALE_COMPATIBLE = "compatible"  # Non-overlapping changes
    STALE_CONFLICT = "conflict"      # Overlapping changes


class StaleDetector:
    """Detects stale proposals and performs auto-merge or conflict reporting.

    Usage:
        detector = StaleDetector()
        hash = detector.compute_hash(page_data)
        result = detector.check_staleness(base_state, current_state, proposed)
    """

    @staticmethod
    def compute_hash(data: Dict[str, Any]) -> str:
        """Compute a deterministic SHA-256 hash of page state.

        Uses sorted JSON serialization for determinism. Includes
        page metadata and component data.
        """
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def check_staleness(
        self,
        base_state: Dict[str, Any],
        current_state: Dict[str, Any],
        proposed_changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check if a proposal is stale and classify severity.

        Args:
            base_state: Page state when the AI last fetched it.
            current_state: Current page state in the database.
            proposed_changes: The AI's proposed changes (patch).

        Returns:
            Dict with:
                - level: StalenessLevel
                - can_auto_merge: bool
                - merged_state: Dict (if auto-merge possible)
                - conflicts: List of conflict details (if any)
        """
        # Fast check: if identical, no staleness
        base_hash = self.compute_hash(base_state)
        current_hash = self.compute_hash(current_state)

        if base_hash == current_hash:
            return {
                "level": StalenessLevel.CURRENT.value,
                "can_auto_merge": True,
                "merged_state": self._apply_changes(current_state, proposed_changes),
                "conflicts": [],
                "base_hash": base_hash,
                "current_hash": current_hash,
            }

        # Find what changed between BASE and CURRENT
        local_changes = self._diff_states(base_state, current_state)

        # Find what the AI wants to change (REMOTE)
        remote_changes = self._diff_states(base_state, self._apply_changes(base_state, proposed_changes))

        # Find conflicts: fields changed in BOTH local and remote
        local_keys = set(local_changes.keys())
        remote_keys = set(remote_changes.keys())
        conflicting_keys = local_keys & remote_keys

        if not conflicting_keys:
            # STALE_COMPATIBLE: changes don't overlap
            # Apply BOTH local and remote changes to base
            merged = deepcopy(base_state)
            merged.update(local_changes)
            merged.update(self._apply_changes(merged, proposed_changes))
            # Actually merge correctly: take current + apply remote
            merged = self._apply_changes(deepcopy(current_state), proposed_changes)

            return {
                "level": StalenessLevel.STALE_COMPATIBLE.value,
                "can_auto_merge": True,
                "merged_state": merged,
                "conflicts": [],
                "local_changes": {k: str(v)[:100] for k, v in local_changes.items()},
                "remote_changes": {k: str(v)[:100] for k, v in remote_changes.items()},
                "base_hash": base_hash,
                "current_hash": current_hash,
            }

        # Build conflict report for STALE_CONFLICT
        conflicts = []
        for key in conflicting_keys:
            conflicts.append({
                "field": f"/{key}",
                "conflict_type": "field_level",
                "base_value": str(base_state.get(key, ""))[:200],
                "local_value": str(current_state.get(key, ""))[:200],
                "remote_value": str(remote_changes.get(key, ""))[:200],
            })

        return {
            "level": StalenessLevel.STALE_CONFLICT.value,
            "can_auto_merge": False,
            "merged_state": None,
            "conflicts": conflicts,
            "local_changes": {k: str(v)[:100] for k, v in local_changes.items()},
            "remote_changes": {k: str(v)[:100] for k, v in remote_changes.items()},
            "base_hash": base_hash,
            "current_hash": current_hash,
        }

    def auto_merge(
        self,
        base_state: Dict[str, Any],
        current_state: Dict[str, Any],
        proposed_changes: Dict[str, Any],
    ) -> Tuple[bool, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """Attempt to auto-merge proposed changes with current state.

        Returns (success, merged_state, conflicts).
        """
        result = self.check_staleness(base_state, current_state, proposed_changes)
        if result["can_auto_merge"]:
            return True, result.get("merged_state"), []
        return False, None, result.get("conflicts", [])

    def force_overwrite_state(
        self,
        current_state: Dict[str, Any],
        proposed_changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Force-apply proposed changes, discarding intervening modifications.

        Preserves the current state's version hash for audit trail.
        Use only with explicit user confirmation.
        """
        return self._apply_changes(deepcopy(current_state), proposed_changes)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_states(
        base: Dict[str, Any], modified: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute the difference between two state dicts.

        Returns a dict of fields that differ (key -> modified_value).
        """
        diffs = {}
        all_keys = set(base.keys()) | set(modified.keys())
        for key in all_keys:
            base_val = base.get(key)
            mod_val = modified.get(key)
            if json.dumps(base_val, sort_keys=True) != json.dumps(mod_val, sort_keys=True):
                diffs[key] = mod_val
        return diffs

    @staticmethod
    def _apply_changes(
        state: Dict[str, Any], changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply proposed changes to a state dict.

        Only overwrites fields that exist in changes.
        Does NOT add new top-level keys from changes.
        """
        result = deepcopy(state)
        for key, value in changes.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = {**result[key], **value}
                else:
                    result[key] = value
        return result
