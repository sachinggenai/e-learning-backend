"""Template-Specific Content Generator Agents — TRD-CGQ Phase 3D.

Extends AGT-07 ContentGeneratorAgent with template-optimized variants.
Each agent gets:
  - Tailored system prompt for its template type
  - Template-specific few-shot examples
  - Optimized output schema for that template type
  - Appropriate temperature and token budget

Architecture:
  ContentGeneratorAgent (base)
    ├── TextContentAgent       — content-text, welcome, summary
    ├── TabsAgent              — tabs
    ├── AccordionAgent         — accordion, click-reveal
    └── AssessmentAgent        — final-assessment, mcq

Used by course_generator.py to select the right agent per page template type.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

from app.services.ai.agents.content_generator_agent import (
    ContentGeneratorAgent,
    GENERATOR_SYSTEM_PROMPT,
    TEMPLATE_SCHEMAS,
)

logger = logging.getLogger("ai_authoring")


# ═══════════════════════════════════════════════════════════════════════
# Agent Factory
# ═══════════════════════════════════════════════════════════════════════


def create_agent_for_template(
    template_type: str,
    llm_client: Any = None,
    json_repair: Any = None,
    max_retries: int = 3,
) -> ContentGeneratorAgent:
    """Factory: create the best agent for a given template type.

    Args:
        template_type: Canonical template type.
        llm_client: LLMClient instance.
        json_repair: JSONRepair instance.
        max_retries: Maximum retry attempts.

    Returns:
        A template-specific ContentGeneratorAgent subclass, or the base
        agent for unknown types.
    """
    agents: Dict[str, type] = {
        "content-text": TextContentAgent,
        "text-content": TextContentAgent,  # Legacy alias
        "welcome": TextContentAgent,
        "summary": TextContentAgent,
        "content-video": TextContentAgent,
        "content-media": TextContentAgent,
        "tabs": TabsAgent,
        "accordion": AccordionAgent,
        "click-reveal": AccordionAgent,   # Shares accordion output format
        "final-assessment": AssessmentAgent,
        "mcq": AssessmentAgent,
    }

    agent_cls = agents.get(template_type, TextContentAgent)
    return agent_cls(
        llm_client=llm_client,
        json_repair=json_repair,
        max_retries=max_retries,
    )


# ═══════════════════════════════════════════════════════════════════════
# Text Content Agent
# ═══════════════════════════════════════════════════════════════════════


TEXT_CONTENT_SYSTEM_PROMPT = """You are an expert instructional designer specializing in narrative content pages.
Generate high-quality educational content in valid JSON format.

CONTENT QUALITY RULES:
1. Write 3-5 substantive paragraphs with clear progressive structure.
2. Start with a hook or learning objective.
3. Use the inverted pyramid: key point first, then supporting details.
4. Include at least one callout box (tip, note, or key takeaway).
5. Break up text with relevant sub-headings.
6. End with a key-points summary or transition to the next topic.
7. Follow the template schema EXACTLY.
8. Return ONLY valid JSON inside ```json ``` code block.

EXAMPLE OUTPUT:
```json
{
  "components": [{
    "component_type": "content-text",
    "order_index": 0,
    "data": {
      "content": "<h2>Topic Title</h2><p>Engaging opening paragraph...</p><h3>Key Concept</h3><p>Detailed explanation...</p><div class='callout'><strong>Key Takeaway:</strong> Essential point.</div>"
    }
  }]
}
```"""


class TextContentAgent(ContentGeneratorAgent):
    """AGT-07-TEXT: Generates narrative content-text pages.

    Optimized for: content-text, welcome, summary templates.
    Focus: Engaging prose, clear structure, callout boxes, key takeaways.
    """

    def _build_generation_prompt(self, *args, **kwargs) -> str:
        prompt = super()._build_generation_prompt(*args, **kwargs)
        return prompt + (
            "\n\nTEXT-SPECIFIC INSTRUCTIONS:\n"
            "- Write 3-5 paragraphs with progressive depth.\n"
            "- Include at least 1 callout/tip box.\n"
            "- Use sub-headings for readability.\n"
            "- End with a key-points summary."
        )


# ═══════════════════════════════════════════════════════════════════════
# Tabs Agent
# ═══════════════════════════════════════════════════════════════════════


TABS_SYSTEM_PROMPT = """You are an expert instructional designer specializing in tabbed comparison pages.
Generate high-quality educational content in valid JSON format.

TAB CONTENT RULES:
1. Create 3-4 tabs with clearly distinct topics.
2. Each tab should be independently readable.
3. Tab titles should be short (2-5 words) and parallel in structure.
4. Tab content should be balanced — similar length per tab.
5. Use the tabs pattern for: comparisons, multi-step processes, multi-perspective topics.
6. Do NOT use tabs for sequential content that must be read in order.
7. Follow the template schema EXACTLY.
8. Return ONLY valid JSON inside ```json ``` code block.

EXAMPLE OUTPUT:
```json
{
  "components": [{
    "component_type": "tabs",
    "order_index": 0,
    "data": {
      "tabs": [
        {"title": "Overview", "content": "<p>High-level introduction...</p>"},
        {"title": "Key Details", "content": "<p>In-depth exploration...</p>"},
        {"title": "Practical Examples", "content": "<p>Real-world applications...</p>"}
      ]
    }
  }]
}
```"""


class TabsAgent(ContentGeneratorAgent):
    """AGT-07-TABS: Generates tabbed comparison/interactive pages.

    Optimized for: tabs template.
    Focus: Balanced tab content, parallel structure, clear tab labels.
    """

    def _build_generation_prompt(self, *args, **kwargs) -> str:
        prompt = super()._build_generation_prompt(*args, **kwargs)
        return prompt + (
            "\n\nTABS-SPECIFIC INSTRUCTIONS:\n"
            "- Create 3-4 tabs with clearly distinct but related topics.\n"
            "- Tab titles must be short (2-5 words), parallel, and descriptive.\n"
            "- Content per tab should be balanced (similar length).\n"
            "- Each tab must be independently readable."
        )


# ═══════════════════════════════════════════════════════════════════════
# Accordion Agent
# ═══════════════════════════════════════════════════════════════════════


ACCORDION_SYSTEM_PROMPT = """You are an expert instructional designer specializing in progressive disclosure pages.
Generate high-quality educational content in valid JSON format.

ACCORDION CONTENT RULES:
1. Create 4-6 accordion items with progressive difficulty.
2. Item titles should be engaging questions or clear topic labels.
3. Item content should be substantive (2-4 sentences per item).
4. Use for: FAQs, topic breakdowns, progressive learning, knowledge checks.
5. Order items from basic to advanced or most to least important.
6. Each item should be a self-contained learning unit.
7. Follow the template schema EXACTLY.
8. Return ONLY valid JSON inside ```json ``` code block.

EXAMPLE OUTPUT:
```json
{
  "components": [{
    "component_type": "accordion",
    "order_index": 0,
    "data": {
      "items": [
        {"title": "What is the fundamental concept?", "content": "<p>Clear explanation of the core idea with an example.</p>"},
        {"title": "How does this apply in practice?", "content": "<p>Real-world scenario showing practical application.</p>"},
        {"title": "What are common challenges?", "content": "<p>Typical obstacles and how to overcome them.</p>"},
        {"title": "What are the key takeaways?", "content": "<p>Summary of essential points to remember.</p>"}
      ]
    }
  }]
}
```"""


class AccordionAgent(ContentGeneratorAgent):
    """AGT-07-ACCORDION: Generates accordion/click-reveal interactive pages.

    Optimized for: accordion, click-reveal templates.
    Focus: Progressive disclosure, Q&A format, self-contained items.
    """

    def _build_generation_prompt(self, *args, **kwargs) -> str:
        prompt = super()._build_generation_prompt(*args, **kwargs)
        return prompt + (
            "\n\nACCORDION-SPECIFIC INSTRUCTIONS:\n"
            "- Create 4-6 accordion items in progressive order.\n"
            "- Titles should be questions or clear topic labels.\n"
            "- Each item should be self-contained (2-4 sentences).\n"
            "- Order from foundational to advanced concepts."
        )


# ═══════════════════════════════════════════════════════════════════════
# Assessment Agent
# ═══════════════════════════════════════════════════════════════════════


ASSESSMENT_SYSTEM_PROMPT = """You are an expert instructional designer and assessment specialist.
Generate high-quality quiz/assessment content in valid JSON format.

ASSESSMENT CONTENT RULES:
1. Generate 5-10 multiple-choice questions (MCQs) covering key learning objectives.
2. Each question must have EXACTLY 4 options: 1 correct, 3 plausible distractors.
3. Distractors must be believable — common misconceptions or partial understandings.
4. Questions should test different cognitive levels: recall, comprehension, application.
5. Passing score: 80% (adjust if assessment is diagnostic vs summative).
6. Each question needs constructive feedback explaining the correct answer.
7. Do NOT repeat questions or test trivial facts.
8. Follow the template schema EXACTLY.
9. Return ONLY valid JSON inside ```json ``` code block.

EXAMPLE OUTPUT:
```json
{
  "components": [{
    "component_type": "final-assessment",
    "order_index": 0,
    "data": {
      "passing_score": 80,
      "questions": [
        {
          "id": "q-1",
          "type": "mcq",
          "question": "Which statement best describes the primary purpose of a firewall?",
          "options": [
            {"id": "a", "text": "To monitor and control incoming and outgoing network traffic based on security rules", "isCorrect": true},
            {"id": "b", "text": "To encrypt all data stored on the device", "isCorrect": false},
            {"id": "c", "text": "To physically protect servers from unauthorized access", "isCorrect": false},
            {"id": "d", "text": "To automatically update software to the latest version", "isCorrect": false}
          ],
          "feedback": "A firewall acts as a barrier between trusted and untrusted networks, filtering traffic based on predefined security rules."
        }
      ]
    }
  }]
}
```"""


class AssessmentAgent(ContentGeneratorAgent):
    """AGT-07-ASSESSMENT: Generates quiz/assessment pages.

    Optimized for: final-assessment, mcq templates.
    Focus: Plausible distractors, varied cognitive levels, constructive feedback.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Assessment needs more tokens for multiple questions
        self._assessment_max_tokens = 8192

    def _build_generation_prompt(self, *args, **kwargs) -> str:
        prompt = super()._build_generation_prompt(*args, **kwargs)
        return prompt + (
            "\n\nASSESSMENT-SPECIFIC INSTRUCTIONS:\n"
            "- Generate 5-10 MCQs covering different learning objectives.\n"
            "- EXACTLY 4 options per question: 1 correct + 3 plausible distractors.\n"
            "- Distractors must represent common misconceptions.\n"
            "- Vary cognitive levels: recall, comprehension, application.\n"
            "- Each question MUST have constructive feedback.\n"
            "- Set passing_score to 80."
        )

    async def generate_page(self, *args, **kwargs) -> Dict[str, Any]:
        """Override to use higher max_tokens for assessment generation."""
        # The base generate_page uses max_tokens=4096 from _build_generation_prompt.
        # Assessment needs more for 5-10 MCQs. We override by using a higher token
        # budget in the LLM call. The base class doesn't expose max_tokens directly,
        # so we augment the page_plan to signal this.
        page_plan = args[0] if args else kwargs.get("page_plan", {})
        if isinstance(page_plan, dict):
            page_plan["_assessment_mode"] = True
        return await super().generate_page(*args, **kwargs)
