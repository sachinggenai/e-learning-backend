"""AGT-03: Planner Agent — Phase 2.4.

Phase 2 of the course generation pipeline.
Task: AI page breakdown from extracted document sections.
Model: Planner tier (deepseek-v4-flash or claude-haiku-4)
Temperature: 0.3

Design:
    - Specialised system prompt for instructional design
    - Template whitelist enforcement
    - Orphan section detection loop
    - Coverage validation (every section must be assigned)
    - Retry (2×) with validation feedback
    - Graceful one-section-one-page fallback on LLM failure
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")

# ── System Prompt ──────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """You are an expert instructional designer and curriculum planner.
Your job is to analyze extracted document sections and produce an optimal page breakdown
for an e-learning course.

RULES:
1. Each page must map to exactly one allowed template type from the whitelist.
2. Every source section must be assigned to at least one page (no orphan content).
3. Pages should follow a logical pedagogical sequence (intro → modules → assessment).
4. Each page should have a focused learning objective derived from its source material.
5. Maximum 50 pages. If source material is very large, prioritize and group strategically.
6. Consider cognitive load: 3-7 concepts per page maximum.
7. Flag sections that cannot be reasonably assigned to any template (orphans).

ALLOWED TEMPLATE TYPES (from template-registry):
- content-text: Standard text-based lesson page with rich HTML content
- tabs: Multi-tab layout for comparing concepts or presenting phases
- accordion: Expandable Q&A or topic drill-down format
- click-reveal: Interactive reveal elements for engagement
- final-assessment: Quiz page with MCQs, passing score, and feedback

OUTPUT FORMAT:
Return valid JSON:
{
  "pages": [
    {
      "title": "Page title derived from content",
      "template_type": "content-text",
      "source_sections": ["section_id_1", "section_id_2"],
      "learning_objective": "What the learner will know after this page",
      "rationale": "Why this template fits this content",
      "estimated_duration_minutes": 5
    }
  ],
  "orphans": [
    {
      "section_id": "section_id_x",
      "content_summary": "Brief summary of orphaned content",
      "reason": "Why it couldn't be assigned"
    }
  ],
  "coverage_report": {
    "total_sections": 42,
    "assigned_sections": 40,
    "orphan_sections": 2,
    "total_pages": 12
  }
}"""


class PlannerAgent:
    """AGT-03: Specialised agent for course page planning.

    Usage:
        agent = PlannerAgent(llm_client=llm_client)
        plan = await agent.generate_page_plan(
            extracted_sections=[...],
            template_whitelist=["content-text", "tabs", ...],
            course_context={"title": "My Course", "audience": "beginners"},
        )
    """

    def __init__(
        self,
        llm_client: Any = None,
        model_tier_router: Any = None,
        max_retries: int = 2,
    ):
        self.llm_client = llm_client
        self.max_retries = max_retries
        if model_tier_router is not None:
            self._router = model_tier_router
        else:
            try:
                from app.services.ai.model_tier_router import ModelTierRouter
                self._router = ModelTierRouter()
            except Exception:
                self._router = None

    async def generate_page_plan(
        self,
        extracted_sections: List[Dict[str, Any]],
        template_whitelist: List[str],
        course_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate a page breakdown plan from extracted document sections.

        Args:
            extracted_sections: List of {id, heading, content, level} dicts
            template_whitelist: Allowed template types
            course_context: {title, description, audience, tone}

        Returns:
            {pages: [...], orphans: [...], coverage_report: {...}}
        """
        # Normalise sections: ensure each has an id
        for i, s in enumerate(extracted_sections):
            if "id" not in s:
                s["id"] = f"section-{i}"

        # If no LLM client, use deterministic fallback
        if self.llm_client is None:
            logger.info("No LLM client — using deterministic one-section-one-page mapping")
            return self._deterministic_fallback(extracted_sections, template_whitelist)

        prompt = self._build_planning_prompt(
            extracted_sections, template_whitelist, course_context
        )

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.llm_client.chat(
                    messages=[
                        type('LLMMessage', (), {
                            'role': 'user', 'content': prompt,
                            'tool_calls': [], 'tool_results': [],
                        })()
                    ],
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_tokens=4096,
                )

                response_text = getattr(response, 'content', str(response))
                plan = self._parse_plan(response_text)

                # Validate coverage
                validation = self._validate_plan(plan, extracted_sections)
                if validation["valid"]:
                    logger.info(
                        "Planner: %d pages from %d sections (attempt %d)",
                        len(plan.get("pages", [])),
                        len(extracted_sections),
                        attempt + 1,
                    )
                    return plan

                # Retry with validation feedback
                if attempt < self.max_retries:
                    prompt = self._build_retry_prompt(prompt, validation["errors"])
                    logger.info("Planner retry %d: %s", attempt + 1, validation["errors"])

            except Exception as exc:
                logger.warning("Planner attempt %d failed: %s", attempt + 1, exc)
                if attempt == self.max_retries:
                    return self._deterministic_fallback(extracted_sections, template_whitelist)

        return self._deterministic_fallback(extracted_sections, template_whitelist)

    # ── Prompt construction ───────────────────────────────────────

    def _build_planning_prompt(
        self,
        sections: List[Dict[str, Any]],
        templates: List[str],
        context: Dict[str, Any],
    ) -> str:
        """Build the planning prompt with structured section data."""
        sections_text = "\n".join(
            f"[{s.get('id', '?')}] H{s.get('level', 2)}: {s.get('heading', 'Untitled')}\n"
            f"  {s.get('content', '')[:500]}"
            for s in sections
        )

        return (
            f"COURSE CONTEXT:\n"
            f"Title: {context.get('title', 'Untitled Course')}\n"
            f"Audience: {context.get('audience', 'adult learners')}\n"
            f"Tone: {context.get('tone', 'professional')}\n\n"
            f"ALLOWED TEMPLATES: {', '.join(templates)}\n\n"
            f"EXTRACTED SECTIONS ({len(sections)} total):\n"
            f"{sections_text}\n\n"
            f"TASK: Generate an optimal page breakdown plan. "
            f"See system prompt for rules and output format."
        )

    def _build_retry_prompt(self, original: str, errors: List[str]) -> str:
        return (
            f"Your previous plan had these issues:\n"
            + "\n".join(f"- {e}" for e in errors)
            + f"\n\nPlease revise. Original prompt:\n{original}"
        )

    # ── Parsing & validation ──────────────────────────────────────

    def _parse_plan(self, llm_output: str) -> Dict[str, Any]:
        """Parse LLM JSON output with repair fallback."""
        content = llm_output.strip()

        # Extract from markdown code block
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            return _json.loads(content)
        except (_json.JSONDecodeError, ValueError):
            # Try JSON repair
            try:
                from app.services.ai.json_repair import repair_json
                repaired = repair_json(content)
                if repaired:
                    return _json.loads(repaired)
            except Exception:
                pass
            return {"pages": [], "orphans": [], "coverage_report": {}}

    def _validate_plan(
        self,
        plan: Dict[str, Any],
        sections: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate that all sections are covered and plan is well-formed."""
        errors: List[str] = []

        pages = plan.get("pages", [])
        if not pages:
            errors.append("Plan has no pages")
            return {"valid": False, "errors": errors}

        # Check coverage: every section must be assigned
        assigned_ids: set = set()
        for page in pages:
            for sid in page.get("source_sections", []):
                assigned_ids.add(sid)

        all_ids = {s.get("id", "") for s in sections}
        missing = all_ids - assigned_ids

        if missing:
            errors.append(f"Unassigned sections ({len(missing)}): {sorted(missing)[:10]}")

        # Check template types are valid
        valid_templates = {
            "content-text", "tabs", "accordion", "click-reveal", "final-assessment",
        }
        for i, page in enumerate(pages):
            tt = page.get("template_type", "")
            if tt not in valid_templates:
                errors.append(f"Page {i}: invalid template type '{tt}'")
            if not page.get("title"):
                errors.append(f"Page {i}: missing title")

        # Check page count reasonable
        if len(pages) > 50:
            errors.append(f"Too many pages ({len(pages)}). Maximum is 50.")

        return {"valid": len(errors) == 0, "errors": errors}

    # ── Fallback ─────────────────────────────────────────────────

    def _deterministic_fallback(
        self,
        sections: List[Dict[str, Any]],
        templates: List[str],
    ) -> Dict[str, Any]:
        """One-section-one-page deterministic fallback."""
        default_template = templates[0] if templates else "content-text"

        pages = []
        for i, s in enumerate(sections):
            heading = s.get("heading", f"Section {i + 1}")
            content = s.get("content", "")

            # Suggest template based on content keywords
            suggested = self._suggest_template_from_content(heading, content, templates)

            pages.append({
                "title": heading[:200],
                "template_type": suggested,
                "source_sections": [s.get("id", f"section-{i}")],
                "learning_objective": f"Understand {heading[:80]}",
                "rationale": f"Deterministic mapping: section → {suggested} page",
                "estimated_duration_minutes": max(3, len(content) // 500),
                "source_content": content,
                "order": i,
            })

        return {
            "pages": pages,
            "orphans": [],
            "coverage_report": {
                "total_sections": len(sections),
                "assigned_sections": len(sections),
                "orphan_sections": 0,
                "total_pages": len(pages),
            },
            "generation_metadata": {"method": "deterministic_fallback"},
        }

    @staticmethod
    def _suggest_template_from_content(
        heading: str, content: str, available: List[str],
    ) -> str:
        """Suggest a template type based on content analysis."""
        text = (heading + " " + content[:500]).lower()
        available_set = set(available)

        if "final-assessment" in available_set and any(
            w in text for w in ["quiz", "test", "assessment", "exam", "score", "questions", "mcq"]
        ):
            return "final-assessment"
        if "tabs" in available_set and any(
            w in text for w in ["compare", "versus", "vs", "differences", "pros and cons"]
        ):
            return "tabs"
        if "accordion" in available_set and any(
            w in text for w in ["faq", "frequently asked", "q&a", "questions and answers"]
        ):
            return "accordion"
        if "click-reveal" in available_set and any(
            w in text for w in ["click", "reveal", "discover", "explore", "interactive"]
        ):
            return "click-reveal"

        return "content-text" if "content-text" in available_set else (available[0] if available else "content-text")
