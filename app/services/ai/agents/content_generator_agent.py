"""AGT-07: Content Generator Agent — Phase 1.2.

Phase 6 of course generation pipeline.
Task: Generate full educational content for a single page via LLM.
Model: Generator tier (deepseek-v4-pro or claude-sonnet-4)
Temperature: 0.7
Parallel: N instances via Redis Streams consumer group or asyncio.gather
Retry: Per-page retry (3x max) with JSON repair on each attempt

Design:
    - Specialised system prompt with template-specific JSON schemas
    - Source-grounded content (no fabrication)
    - Template-aware output format
    - Graceful mock fallback on LLM failure
    - Integrated JSON repair via existing 12-strategy pipeline
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_authoring")

# ── System Prompt ──────────────────────────────────────────────────

GENERATOR_SYSTEM_PROMPT = """You are an expert instructional designer and e-learning content creator.
Generate high-quality, pedagogically sound educational content in valid JSON format.

CONTENT QUALITY RULES:
1. Write for the target audience — use appropriate language complexity.
2. Ground all facts in the provided source material. Do NOT fabricate information.
3. Use clear headings, short paragraphs, bullet points, and examples.
4. For assessments: plausible distractors, clear correct answers, constructive feedback.
5. For interactive elements: engaging prompts, progressive disclosure, scenario-based.
6. Do NOT include answer keys (isCorrect) in sample/example content.
7. Follow the template schema EXACTLY — every required field must be present.
8. Format output as clean, parseable JSON inside a markdown code block.

TEMPLATE-SPECIFIC GUIDANCE:
- content-text: 3-5 substantive paragraphs, relevant headings, 1-2 callout boxes
- tabs: 3-4 tabs with balanced content, clear tab labels
- accordion: 4-6 items, progressive difficulty, clear trigger text
- click-reveal: 3-5 reveal cards, engaging prompts, valuable revealed content
- final-assessment: 5-10 MCQs covering key learning objectives, plausible distractors, passing_score: 80"""


# ── Template JSON Schemas ──────────────────────────────────────────

TEMPLATE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "content-text": {
        "components": [{
            "component_type": "content-text",
            "order_index": 0,
            "data": {
                "content": "<h2>Title</h2><p>Body with educational content including definitions, examples, and key takeaways.</p>"
            }
        }]
    },
    "tabs": {
        "components": [{
            "component_type": "tabs",
            "order_index": 0,
            "data": {
                "tabs": [
                    {"title": "Tab 1", "content": "Content for first tab..."},
                    {"title": "Tab 2", "content": "Content for second tab..."},
                ]
            }
        }]
    },
    "accordion": {
        "components": [{
            "component_type": "accordion",
            "order_index": 0,
            "data": {
                "items": [
                    {"title": "Question or topic 1", "content": "Expanded answer or detail..."},
                ]
            }
        }]
    },
    "click-reveal": {
        "components": [{
            "component_type": "accordion",
            "order_index": 0,
            "data": {
                "items": [
                    {"title": "Click to reveal...", "content": "Revealed content with key insight..."},
                ]
            }
        }]
    },
    "final-assessment": {
        "components": [{
            "component_type": "final-assessment",
            "order_index": 0,
            "data": {
                "passing_score": 80,
                "questions": [{
                    "id": "q-1",
                    "type": "mcq",
                    "question": "Question text based on learning objectives?",
                    "options": [
                        {"id": "a", "text": "Correct answer", "isCorrect": True},
                        {"id": "b", "text": "Plausible distractor 1", "isCorrect": False},
                        {"id": "c", "text": "Plausible distractor 2", "isCorrect": False},
                        {"id": "d", "text": "Plausible distractor 3", "isCorrect": False},
                    ],
                    "feedback": "Explanation of why the correct answer is right."
                }]
            }
        }]
    },
}


class ContentGeneratorAgent:
    """AGT-07: Generates full page content via LLM.

    Designed for parallel execution: one instance per page, coordinated via
    StreamManager (Redis Streams or asyncio.gather fallback).

    Usage:
        agent = ContentGeneratorAgent(llm_client, json_repair)
        page = await agent.generate_page(
            page_plan={"title": "Intro", "source_content": "...", "learning_objective": "..."},
            template_assignment={"template_type": "content-text"},
            rag_context=[],
            course_context={"title": "My Course", "audience": "beginners", "tone": "friendly"},
            page_index=0,
            total_pages=10,
        )
    """

    def __init__(
        self,
        llm_client: Any = None,
        json_repair: Any = None,
        max_retries: int = 3,
    ):
        self.llm_client = llm_client  # LLMClient instance
        self.json_repair = json_repair  # JSONRepair instance
        self.max_retries = max_retries

    # ── Main generation method ────────────────────────────────────

    async def generate_page(
        self,
        page_plan: Dict[str, Any],
        template_assignment: Dict[str, Any],
        rag_context: List[Dict[str, Any]],
        course_context: Dict[str, Any],
        page_index: int,
        total_pages: int,
    ) -> Dict[str, Any]:
        """Generate full educational content for a single page.

        Args:
            page_plan: {title, learning_objective, source_content, ...}
            template_assignment: {template_type, confidence, reasoning, method}
            rag_context: Similar courses/examples for tone/style reference
            course_context: {title, description, audience, tone}
            page_index: Zero-based page index
            total_pages: Total pages in course

        Returns:
            {title, template_type, order, components: [...],
             source_excerpt, learning_objective, generation_metadata}
        """
        template_type = template_assignment.get("template_type", "content-text")

        # If no LLM client is available, use mock generation
        if self.llm_client is None:
            logger.info("No LLM client — using mock generation for page %d", page_index)
            return self._generate_mock_fallback(page_plan, template_type, page_index)

        prompt = self._build_generation_prompt(
            page_plan, template_type, rag_context, course_context,
            page_index, total_pages,
        )

        for attempt in range(self.max_retries):
            try:
                response = await self.llm_client.chat(
                    messages=[
                        type('LLMMessage', (), {
                            'role': 'user',
                            'content': prompt,
                            'tool_calls': [],
                            'tool_results': [],
                        })()
                    ],
                    system_prompt=GENERATOR_SYSTEM_PROMPT,
                    temperature=0.7,
                    max_tokens=4096,
                )

                parsed = self._parse_and_repair(
                    getattr(response, 'content', str(response)),
                    template_type,
                )

                if self._quick_validate(parsed, template_type):
                    return {
                        "title": page_plan.get("title", f"Page {page_index + 1}"),
                        "template_type": template_type,
                        "order": page_plan.get("order", page_index),
                        "components": parsed.get("components", []),
                        "source_excerpt": page_plan.get("source_content", "")[:500],
                        "learning_objective": page_plan.get("learning_objective", ""),
                        "generation_metadata": {
                            "attempt": attempt + 1,
                            "method": "llm",
                            "template_type": template_type,
                        },
                    }

                # Retry with validation feedback
                prompt = self._build_retry_prompt(
                    prompt,
                    f"Invalid structure for template '{template_type}': missing required fields or malformed JSON",
                )

            except Exception as exc:
                logger.error(
                    "Generator attempt %d for page %d failed: %s",
                    attempt + 1, page_index, exc,
                )
                if attempt == self.max_retries - 1:
                    return self._generate_mock_fallback(
                        page_plan, template_type, page_index, str(exc)
                    )

        return self._generate_mock_fallback(page_plan, template_type, page_index)

    # ── Prompt construction ───────────────────────────────────────

    def _build_generation_prompt(
        self,
        page_plan: Dict[str, Any],
        template_type: str,
        rag_context: List[Dict[str, Any]],
        course_context: Dict[str, Any],
        page_index: int,
        total_pages: int,
    ) -> str:
        """Build a template-specific generation prompt."""
        schema = TEMPLATE_SCHEMAS.get(template_type, TEMPLATE_SCHEMAS["content-text"])
        schema_json = _json.dumps(schema, indent=2)

        # RAG context (top 2 examples)
        rag_block = ""
        if rag_context:
            examples = rag_context[:2]
            rag_block = "\nSIMILAR COURSE EXAMPLES (for style/tone reference only):\n"
            for ex in examples:
                rag_block += f"- {ex.get('title', '')}: {ex.get('excerpt', str(ex)[:200])}\n"

        return (
            f"COURSE: {course_context.get('title', 'Untitled')} "
            f"(Page {page_index + 1} of {total_pages})\n"
            f"PAGE TITLE: {page_plan.get('title', '')}\n"
            f"LEARNING OBJECTIVE: {page_plan.get('learning_objective', '')}\n"
            f"TEMPLATE TYPE: {template_type}\n"
            f"AUDIENCE: {course_context.get('audience', 'adult learners')}\n"
            f"TONE: {course_context.get('tone', 'professional')}\n\n"
            f"SOURCE MATERIAL:\n{page_plan.get('source_content', '')[:2000]}\n\n"
            f"{rag_block}\n"
            f"REQUIRED OUTPUT SCHEMA:\n```json\n{schema_json}\n```\n\n"
            f"IMPORTANT:\n"
            f"- Generate 3-5 substantive educational paragraphs/items per component.\n"
            f"- Do NOT use placeholder text like 'lorem ipsum'.\n"
            f"- Content must be factually grounded in the source material above.\n"
            f"- For assessments: provide plausible distractor options.\n"
            f"- Return ONLY the JSON inside ```json ``` code block."
        )

    def _build_retry_prompt(self, original: str, error: str) -> str:
        return (
            f"Your previous output had this issue: {error}\n\n"
            f"Please fix and regenerate.\n\n{original}"
        )

    # ── Parsing & validation ──────────────────────────────────────

    def _parse_and_repair(self, llm_output: str, template_type: str) -> Dict[str, Any]:
        """Extract JSON from LLM output, repair if needed using the 12-strategy pipeline."""
        content = llm_output.strip()

        # Extract from markdown code block
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            return _json.loads(content)
        except (_json.JSONDecodeError, ValueError):
            # Run through the 12-strategy JSON repair pipeline
            if self.json_repair is not None:
                try:
                    from app.services.ai.json_repair import repair_json
                    repaired = repair_json(content)
                    if repaired:
                        return _json.loads(repaired)
                except Exception:
                    pass

            # Last resort: return empty components
            return {"components": []}

    def _quick_validate(self, parsed: Dict[str, Any], template_type: str) -> bool:
        """Fast pre-validation — checks structure, not full schema."""
        if not isinstance(parsed, dict):
            return False
        if "components" not in parsed or not isinstance(parsed["components"], list):
            return False
        if len(parsed["components"]) == 0:
            return False
        comp = parsed["components"][0]
        if not isinstance(comp, dict):
            return False
        if "component_type" not in comp or "data" not in comp:
            return False
        return True

    # ── Mock fallback ─────────────────────────────────────────────

    @staticmethod
    def _build_mock_components(template_type: str, title: str) -> list:
        """Build deterministic mock components based on template type.

        Uses the TEMPLATE_SCHEMAS definitions to produce structurally valid
        mock output for each supported template type. Self-contained — no
        external dependencies.
        """
        if template_type == "final-assessment":
            return [{
                "component_type": "final-assessment",
                "order_index": 0,
                "data": {
                    "passing_score": 80,
                    "questions": [{
                        "id": "q-1",
                        "type": "mcq",
                        "question": f"Key concept from: {title}",
                        "options": [
                            {"id": "a", "text": "Correct understanding of the concept", "isCorrect": True},
                            {"id": "b", "text": "Common misconception A", "isCorrect": False},
                            {"id": "c", "text": "Common misconception B", "isCorrect": False},
                            {"id": "d", "text": "Common misconception C", "isCorrect": False},
                        ],
                        "feedback": "Review the core material on this topic.",
                    }],
                },
            }]
        elif template_type == "tabs":
            return [{
                "component_type": "tabs",
                "order_index": 0,
                "data": {
                    "tabs": [
                        {"title": f"{title} — Overview", "content": "<p>Key concepts and introduction to the topic.</p>"},
                        {"title": "Details", "content": "<p>In-depth exploration of the core material.</p>"},
                        {"title": "Examples", "content": "<p>Practical applications and case studies.</p>"},
                    ],
                },
            }]
        elif template_type == "accordion":
            return [{
                "component_type": "accordion",
                "order_index": 0,
                "data": {
                    "items": [
                        {"title": "What is the core concept?", "content": "<p>Answer explaining the fundamental idea.</p>"},
                        {"title": "How does it apply in practice?", "content": "<p>Practical application explanation.</p>"},
                        {"title": "What are the key takeaways?", "content": "<p>Summary of most important points.</p>"},
                    ],
                },
            }]
        elif template_type == "click-reveal":
            return [{
                "component_type": "click-reveal",
                "order_index": 0,
                "data": {
                    "cards": [
                        {"prompt": "Click to explore: Core Concept", "content": "<p>Revealed insight about the topic.</p>"},
                        {"prompt": "Click to explore: Real-World Example", "content": "<p>Practical scenario demonstrating the concept.</p>"},
                        {"prompt": "Click to explore: Key Takeaway", "content": "<p>Essential point to remember.</p>"},
                    ],
                },
            }]
        else:  # content-text (default)
            return [{
                "component_type": "content-text",
                "order_index": 0,
                "data": {
                    "content": f"<h2>{title}</h2>"
                              f"<p>This section covers the key concepts related to {title.lower()}. "
                              f"Learners will explore the fundamental principles and practical applications.</p>"
                              f"<h3>Key Points</h3>"
                              f"<ul><li>Primary concept definition and context</li>"
                              f"<li>Practical application in real-world scenarios</li>"
                              f"<li>Common challenges and how to address them</li></ul>"
                              f"<p>Review the material above and complete the associated activities to reinforce your understanding.</p>",
                },
            }]

    def _generate_mock_fallback(
        self,
        page_plan: Dict[str, Any],
        template_type: str,
        page_index: int,
        error: str = "",
    ) -> Dict[str, Any]:
        """Deterministic mock fallback when LLM generation fails.

        Self-contained — builds structurally valid mock output for each
        supported template type without any external dependencies.
        """
        title = page_plan.get("title", f"Page {page_index + 1}")
        components = self._build_mock_components(template_type, title)

        return {
            "title": title,
            "template_type": template_type,
            "order": page_plan.get("order", page_index),
            "components": components,
            "source_excerpt": page_plan.get("source_content", "")[:500],
            "learning_objective": page_plan.get("learning_objective", ""),
            "generation_metadata": {
                "fallback": True,
                "reason": error or "LLM generation unavailable",
                "method": "inline_mock",
                "template_type": template_type,
            },
        }
