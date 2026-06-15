"""Policy Engine for Auto-Apply Decisions - US-BKND-AI-032.

Evaluates configurable rules to determine whether an AI proposal can be
auto-applied or requires human review. Rules consider operation type,
template type, validation status, dependency risk, and user role.

Architecture:
    Proposal -> PolicyEngine.evaluate() -> auto_apply | requires_review | blocked
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PolicyDecision(str, Enum):
    AUTO_APPLY = "auto_apply"
    REQUIRES_REVIEW = "requires_review"
    BLOCKED = "blocked"


class PolicyEngine:
    """Evaluates auto-apply policies for AI proposals.

    Rules are evaluated in priority order. First matching rule wins.
    Default policy: requires_review for all proposals.

    Usage:
        engine = PolicyEngine()
        decision = engine.evaluate(proposal_context)
    """

    # Default rule set (configurable)
    DEFAULT_RULES: List[Dict[str, Any]] = [
        # BLOCK rules (highest priority)
        {"name": "block_final_assessment_delete", "priority": 100,
         "condition": {"operation": "delete_page", "has_final_assessment": True},
         "decision": PolicyDecision.BLOCKED.value,
         "reason": "Cannot auto-delete pages containing final assessments."},
        {"name": "block_course_delete", "priority": 99,
         "condition": {"operation": "delete_course"},
         "decision": PolicyDecision.BLOCKED.value,
         "reason": "Course deletion always requires explicit confirmation."},

        # AUTO_APPLY rules
        {"name": "auto_create_text_content", "priority": 50,
         "condition": {"operation": "create_page", "template_type": "text-content",
                       "validation_status": "valid", "has_warnings": False},
         "decision": PolicyDecision.AUTO_APPLY.value,
         "reason": "Simple text-content pages can be auto-applied."},
        {"name": "auto_update_minor", "priority": 40,
         "condition": {"operation": "update_page", "change_scope": "minor",
                       "validation_status": "valid"},
         "decision": PolicyDecision.AUTO_APPLY.value,
         "reason": "Minor updates with valid results auto-apply."},

        # REQUIRES_REVIEW rules
        {"name": "review_assessment_pages", "priority": 30,
         "condition": {"template_type": "final-assessment"},
         "decision": PolicyDecision.REQUIRES_REVIEW.value,
         "reason": "Assessment pages require human review."},
        {"name": "review_complex_templates", "priority": 20,
         "condition": {"template_type__in": ["tabs", "accordion", "click-reveal"]},
         "decision": PolicyDecision.REQUIRES_REVIEW.value,
         "reason": "Complex template types require review."},
    ]

    def __init__(self, rules: Optional[List[Dict]] = None):
        self.rules = sorted(rules or self.DEFAULT_RULES,
                            key=lambda r: -r["priority"])

    def evaluate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate auto-apply policies for a proposal context.

        Args:
            context: Dict with operation, template_type, validation_status,
                     has_warnings, has_final_assessment, change_scope, etc.

        Returns:
            Dict with decision, reason, matched_rule, all_evaluations.
        """
        evaluations = []

        for rule in self.rules:
            match = self._match_condition(rule["condition"], context)
            evaluations.append({
                "rule": rule["name"],
                "priority": rule["priority"],
                "matched": match,
                "decision": rule["decision"] if match else "skipped",
            })
            if match:
                logger.debug("Policy match: %s -> %s", rule["name"], rule["decision"])
                return {
                    "decision": rule["decision"],
                    "reason": rule["reason"],
                    "matched_rule": rule["name"],
                    "evaluations": evaluations,
                }

        # Default: requires review
        return {
            "decision": PolicyDecision.REQUIRES_REVIEW.value,
            "reason": "No auto-apply policy matched. Defaulting to human review.",
            "matched_rule": "default",
            "evaluations": evaluations,
        }

    def add_rule(self, name: str, priority: int, condition: Dict,
                 decision: str, reason: str) -> None:
        """Add a custom policy rule."""
        self.rules.append({
            "name": name, "priority": priority,
            "condition": condition, "decision": decision, "reason": reason,
        })
        self.rules.sort(key=lambda r: -r["priority"])

    @staticmethod
    def _match_condition(condition: Dict, context: Dict) -> bool:
        """Check if a context matches a policy condition.

        Supports exact match, __in for list membership, and boolean fields.
        """
        for key, expected in condition.items():
            if key.endswith("__in"):
                actual_key = key[:-4]
                actual = context.get(actual_key)
                if actual not in expected:
                    return False
            else:
                actual = context.get(key)
                if actual != expected:
                    return False
        return True
