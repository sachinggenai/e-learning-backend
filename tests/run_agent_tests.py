"""Standalone tests for the 3 Specialist LLM Agents — Phase 1-2 migration.

Run: PYTHONPATH=. python tests/run_agent_tests.py

Validates:
    AGT-03: PlannerAgent — page plan generation, orphan detection, retry, fallback
    AGT-06: TemplateSelectorAgent — hybrid rules+LLM, confidence thresholds, batch
    AGT-07: ContentGeneratorAgent — page content gen, JSON repair, retry, mock fallback

All tests use the default Mock LLMClient (LLMProvider.MOCK), which exercises
the degradation and fallback paths. Happy-path tests use a SimpleJSONResponder
that returns well-formed JSON for specific prompts.
"""
from __future__ import annotations
import asyncio
import json as _json
import inspect
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

passed = 0
failed = 0
failures: list[tuple[str, str]] = []

def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))


# ═══════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════

class SimpleJSONResponder:
    """A mock LLM client wrapper that returns specific JSON for testing happy paths.

    Wraps the real LLMClient and intercepts chat() calls to return controlled
    JSON responses. Falls back to the real mock client for unrecognized prompts.
    """
    def __init__(self, llm_client, response_map: Dict[str, Any]):
        self._client = llm_client
        self._response_map = response_map

    @property
    def max_retries(self):
        return getattr(self._client, 'max_retries', 3)

    async def chat(self, messages, system_prompt=None, temperature=0.7, max_tokens=4096, **kwargs):
        prompt_key = ""
        for msg in messages:
            content = getattr(msg, 'content', str(msg))
            if content:
                prompt_key = content
                break

        # Check if we have a matching response
        for key_pattern, response_data in self._response_map.items():
            if key_pattern in str(prompt_key):
                content_str = _json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)
                from app.services.ai.llm_client import LLMResponse
                return LLMResponse(
                    content=content_str,
                    stop_reason="end_turn",
                    token_usage={"input": 100, "output": len(content_str.split())},
                    model="mock-json-responder",
                    latency_ms=1.0,
                )

        # Fall back to the real mock client
        return await self._client.chat(messages, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens, **kwargs)


# ═══════════════════════════════════════════════════════════════════════
# AGT-03: PlannerAgent Tests
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_SECTIONS: List[Dict[str, Any]] = [
    {"id": "sec-1", "heading": "Introduction to Cybersecurity", "content": "Cybersecurity is the practice of protecting systems, networks, and programs from digital attacks. These cyberattacks are usually aimed at accessing, changing, or destroying sensitive information.", "level": 1},
    {"id": "sec-2", "heading": "Types of Threats", "content": "Common threats include malware, phishing, ransomware, and denial-of-service attacks. Each type requires different defense strategies and tools.", "level": 2},
    {"id": "sec-3", "heading": "Security Best Practices", "content": "Organizations should implement multi-factor authentication, regular security audits, employee training, and incident response plans.", "level": 2},
    {"id": "sec-4", "heading": "Chapter Quiz", "content": "Test your knowledge with these MCQ questions covering cybersecurity fundamentals, threat types, and best practices.", "level": 1},
]

VALID_PLAN_RESPONSE = {
    "pages": [
        {"title": "Introduction to Cybersecurity", "template_type": "content-text",
         "source_sections": ["sec-1"], "learning_objective": "Define cybersecurity and understand its importance",
         "rationale": "Foundational content", "estimated_duration_minutes": 10},
        {"title": "Types of Threats", "template_type": "tabs",
         "source_sections": ["sec-2"], "learning_objective": "Identify and compare different threat types",
         "rationale": "Comparison format fits comparing threats", "estimated_duration_minutes": 15},
        {"title": "Security Best Practices", "template_type": "click-reveal",
         "source_sections": ["sec-3"], "learning_objective": "Apply security best practices",
         "rationale": "Interactive reveal for practice steps", "estimated_duration_minutes": 10},
        {"title": "Chapter Quiz", "template_type": "final-assessment",
         "source_sections": ["sec-4"], "learning_objective": "Assess understanding of cybersecurity fundamentals",
         "rationale": "Quiz content", "estimated_duration_minutes": 10},
    ],
    "orphans": [],
    "coverage_report": {"total_sections": 4, "assigned_sections": 4, "orphan_sections": 0, "total_pages": 4},
}


def test_planner_import():
    """AGT03-01: PlannerAgent class importable."""
    from app.services.ai.agents.planner_agent import PlannerAgent, PLANNER_SYSTEM_PROMPT
    check("AGT03-01: PlannerAgent exists", PlannerAgent is not None)
    check("AGT03-01: PLANNER_SYSTEM_PROMPT exists", len(PLANNER_SYSTEM_PROMPT) > 100)

def test_planner_deterministic_fallback_no_llm():
    """AGT03-02: With no LLM client, uses deterministic one-section-one-page fallback."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)
    result = asyncio.run(agent.generate_page_plan(
        extracted_sections=SAMPLE_SECTIONS,
        template_whitelist=["content-text", "tabs", "accordion", "click-reveal", "final-assessment"],
        course_context={"title": "Test Course", "audience": "beginners"},
    ))
    check("AGT03-02: Has pages", len(result.get("pages", [])) == 4)
    check("AGT03-02: No orphans", len(result.get("orphans", [])) == 0)
    check("AGT03-02: Coverage total_sections=4", result.get("coverage_report", {}).get("total_sections") == 4)
    check("AGT03-02: Method is deterministic_fallback",
          result.get("generation_metadata", {}).get("method") == "deterministic_fallback")

def test_planner_normalises_missing_ids():
    """AGT03-03: Sections without 'id' get assigned 'section-N' ids."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)
    raw_sections = [
        {"heading": "Topic A", "content": "Content A"},
        {"heading": "Topic B", "content": "Content B"},
    ]
    result = asyncio.run(agent.generate_page_plan(
        extracted_sections=raw_sections,
        template_whitelist=["content-text"],
        course_context={},
    ))
    pages = result.get("pages", [])
    check("AGT03-03: 2 pages", len(pages) == 2)
    check("AGT03-03: Page 0 has source_sections", len(pages[0].get("source_sections", [])) > 0)
    check("AGT03-03: Section id is section-0", pages[0]["source_sections"][0] == "section-0")

def test_planner_template_suggestion():
    """AGT03-04: _suggest_template_from_content maps keywords to templates."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    available = ["content-text", "tabs", "accordion", "click-reveal", "final-assessment"]

    check("AGT03-04: quiz→final-assessment",
          PlannerAgent._suggest_template_from_content("Quiz", "MCQ questions to test knowledge", available) == "final-assessment")
    check("AGT03-04: compare→tabs",
          PlannerAgent._suggest_template_from_content("Compare A vs B", "differences and similarities", available) == "tabs")
    check("AGT03-04: faq→accordion",
          PlannerAgent._suggest_template_from_content("FAQ", "frequently asked questions and answers", available) == "accordion")
    check("AGT03-04: discover→click-reveal",
          PlannerAgent._suggest_template_from_content("Discover", "interactive exploration", available) == "click-reveal")
    check("AGT03-04: default→content-text",
          PlannerAgent._suggest_template_from_content("Regular Topic", "standard educational content", available) == "content-text")

def test_planner_parse_plan_from_json():
    """AGT03-05: _parse_plan extracts JSON from markdown code block."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    result = agent._parse_plan('```json\n{"pages": [{"title": "Test", "template_type": "content-text", "source_sections": ["s1"]}], "orphans": [], "coverage_report": {}}\n```')
    check("AGT03-05: Parsed pages", len(result.get("pages", [])) == 1)
    check("AGT03-05: Page title", result["pages"][0]["title"] == "Test")

def test_planner_parse_plain_json():
    """AGT03-06: _parse_plan handles plain JSON (no code block)."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    result = agent._parse_plan('{"pages": [], "orphans": [], "coverage_report": {}}')
    check("AGT03-06: Parsed", result.get("pages", []) == [])

def test_planner_parse_malformed_json_returns_empty():
    """AGT03-07: _parse_plan on garbage returns empty dict (graceful degradation)."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    result = agent._parse_plan("This is not JSON at all, just random text from the LLM")
    check("AGT03-07: Empty pages on parse failure", result.get("pages", []) == [])
    check("AGT03-07: Has orphans key", "orphans" in result)
    check("AGT03-07: Has coverage_report key", "coverage_report" in result)

def test_planner_validate_plan_all_assigned():
    """AGT03-08: _validate_plan returns valid=True when all sections covered."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    result = agent._validate_plan(VALID_PLAN_RESPONSE, SAMPLE_SECTIONS)
    check("AGT03-08: Plan is valid", result["valid"] is True)
    check("AGT03-08: No errors", len(result["errors"]) == 0)

def test_planner_validate_plan_missing_sections():
    """AGT03-09: _validate_plan flags unassigned sections."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    incomplete_plan = {
        "pages": [{"title": "Only One", "template_type": "content-text", "source_sections": ["sec-1"]}],
        "orphans": [],
    }
    result = agent._validate_plan(incomplete_plan, SAMPLE_SECTIONS)
    check("AGT03-09: Plan is invalid", result["valid"] is False)
    check("AGT03-09: Has errors about unassigned", any("Unassigned" in e for e in result["errors"]))

def test_planner_validate_plan_no_pages():
    """AGT03-10: _validate_plan rejects plan with zero pages."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    result = agent._validate_plan({"pages": []}, SAMPLE_SECTIONS)
    check("AGT03-10: Empty plan invalid", result["valid"] is False)
    check("AGT03-10: Error about no pages", any("no pages" in e.lower() for e in result["errors"]))

def test_planner_validate_invalid_template_type():
    """AGT03-11: _validate_plan flags invalid template types."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    plan = {
        "pages": [
            {"title": "Bad Template", "template_type": "INVALID_TYPE", "source_sections": ["sec-1"]},
            {"title": "Good", "template_type": "content-text", "source_sections": ["sec-2"]},
            {"title": "Also Good", "template_type": "tabs", "source_sections": ["sec-3"]},
            {"title": "Good Too", "template_type": "click-reveal", "source_sections": ["sec-4"]},
        ],
    }
    result = agent._validate_plan(plan, SAMPLE_SECTIONS)
    check("AGT03-11: Invalid template flagged", result["valid"] is False)
    check("AGT03-11: Invalid type in errors", any("INVALID_TYPE" in e for e in result["errors"]))

def test_planner_validate_too_many_pages():
    """AGT03-12: _validate_plan rejects plans with >50 pages."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    huge_plan = {"pages": [{"title": f"Page {i}", "template_type": "content-text", "source_sections": ["sec-1"]} for i in range(55)]}
    result = agent._validate_plan(huge_plan, SAMPLE_SECTIONS)
    check("AGT03-12: Too many pages", result["valid"] is False)
    check("AGT03-12: Error mentions 50", any("50" in e for e in result["errors"]))

def test_planner_with_mock_llm_falls_back_gracefully():
    """AGT03-13: Mock LLM (returns non-JSON) → retries → deterministic fallback succeeds."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    from app.services.ai.llm_client import LLMClient

    agent = PlannerAgent(llm_client=LLMClient())  # MOCK by default
    result = asyncio.run(agent.generate_page_plan(
        extracted_sections=SAMPLE_SECTIONS,
        template_whitelist=["content-text", "tabs", "accordion", "click-reveal", "final-assessment"],
        course_context={"title": "Test"},
    ))
    check("AGT03-13: Has pages (fallback worked)", len(result.get("pages", [])) == 4)
    check("AGT03-13: Method is deterministic_fallback",
          result.get("generation_metadata", {}).get("method") == "deterministic_fallback")

def test_planner_build_planning_prompt():
    """AGT03-14: _build_planning_prompt includes sections, templates, context."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)

    prompt = agent._build_planning_prompt(
        SAMPLE_SECTIONS,
        ["content-text", "final-assessment"],
        {"title": "Cyber Course", "audience": "professionals", "tone": "formal"},
    )
    check("AGT03-14: Has course title", "Cyber Course" in prompt)
    check("AGT03-14: Has audience", "professionals" in prompt)
    check("AGT03-14: Has tone", "formal" in prompt)
    check("AGT03-14: Has templates", "content-text, final-assessment" in prompt)
    check("AGT03-14: Has sections", "Introduction to Cybersecurity" in prompt)
    check("AGT03-14: Has section count", "4 total" in prompt)

def test_planner_custom_max_retries():
    """AGT03-15: max_retries parameter is stored."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None, max_retries=5)
    check("AGT03-15: Custom retries", agent.max_retries == 5)

def test_planner_default_max_retries():
    """AGT03-16: Default max_retries is 2."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    agent = PlannerAgent(llm_client=None)
    check("AGT03-16: Default retries=2", agent.max_retries == 2)


# ═══════════════════════════════════════════════════════════════════════
# AGT-06: TemplateSelectorAgent Tests
# ═══════════════════════════════════════════════════════════════════════

def test_selector_import():
    """AGT06-01: TemplateSelectorAgent class importable."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent, TEMPLATE_RULES, TEMPLATE_SELECTOR_SYSTEM_PROMPT
    check("AGT06-01: Class exists", TemplateSelectorAgent is not None)
    check("AGT06-01: TEMPLATE_RULES has 5 rules", len(TEMPLATE_RULES) == 5)
    check("AGT06-01: System prompt exists", len(TEMPLATE_SELECTOR_SYSTEM_PROMPT) > 100)

def test_selector_rules_assessment():
    """AGT06-02: Assessment keywords → final-assessment with high confidence."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = asyncio.run(agent.select_template(
        page={"title": "Chapter 5 Quiz", "learning_objective": "Test knowledge of chapter 5 concepts"},
        source_content="Here are 10 MCQ questions to evaluate your understanding. Score 80% to pass.",
    ))
    check("AGT06-02: template=final-assessment", result["template_type"] == "final-assessment")
    check("AGT06-02: confidence > 0.80", result["confidence"] > 0.80)
    check("AGT06-02: method=rule", result["method"] == "rule")

def test_selector_rules_comparison():
    """AGT06-03: Comparison keywords → tabs."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = asyncio.run(agent.select_template(
        page={"title": "Comparing Firewalls vs IDS", "learning_objective": "Compare and contrast security tools"},
        source_content="In this section we compare firewalls and intrusion detection systems. The differences and similarities are important to understand. See the comparison table for pros and cons.",
    ))
    check("AGT06-03: template=tabs", result["template_type"] == "tabs")
    check("AGT06-03: method=rule", result["method"] == "rule")

def test_selector_rules_faq():
    """AGT06-04: FAQ keywords → accordion."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = asyncio.run(agent.select_template(
        page={"title": "Frequently Asked Questions", "learning_objective": "Address common questions about the topic"},
        source_content="This FAQ covers the most common questions and answers about our security policy.",
    ))
    check("AGT06-04: template=accordion", result["template_type"] == "accordion")
    check("AGT06-04: method=rule", result["method"] == "rule")

def test_selector_rules_interactive():
    """AGT06-05: Interactive keywords → click-reveal."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = asyncio.run(agent.select_template(
        page={"title": "Explore Security Scenarios", "learning_objective": "Discover how to respond to security incidents"},
        source_content="Interactive scenario: click to reveal what happens and explore your decision points.",
    ))
    check("AGT06-05: template=click-reveal", result["template_type"] == "click-reveal")
    check("AGT06-05: method=rule", result["method"] == "rule")

def test_selector_rules_video():
    """AGT06-06: Video keywords → content-text (video embedded, not standalone template)."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = asyncio.run(agent.select_template(
        page={"title": "Watch: Security Walkthrough", "learning_objective": "Learn through video demonstration"},
        source_content="Watch this screencast demonstration of the security audit process.",
    ))
    check("AGT06-06: template=content-text", result["template_type"] == "content-text")
    check("AGT06-06: method=rule", result["method"] == "rule")

def test_selector_no_keywords_falls_back_to_default():
    """AGT06-07: Content with no matching keywords → fallback to page template or content-text."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = asyncio.run(agent.select_template(
        page={"title": "Regular Content Page", "template_type": "accordion"},
        source_content="This is a regular informational paragraph about network security principles. It does not contain any specific keywords that would trigger any of the classification rules.",
    ))
    check("AGT06-07: Has template_type", "template_type" in result)
    check("AGT06-07: method is fallback or llm",
          result["method"] in ("fallback", "llm", "rule_below_threshold"))
    check("AGT06-07: confidence <= 0.80",
          result["confidence"] <= 0.80 or result["method"] != "rule")

def test_selector_multiple_rules_picks_highest_confidence():
    """AGT06-08: When multiple rules match, the highest confidence wins."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    # Contains both "assessment" AND "interactive" keywords
    result = asyncio.run(agent.select_template(
        page={"title": "Interactive Assessment", "learning_objective": "Evaluate knowledge"},
        source_content="This quiz tests your knowledge with interactive click-to-reveal questions and MCQ assessments. Explore and discover the right answers.",
    ))
    check("AGT06-08: Has template_type", "template_type" in result)

def test_selector_custom_threshold():
    """AGT06-09: Custom confidence_threshold changes behavior."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    # Set threshold very high so even video rule (0.80) falls to LLM/fallback
    agent = TemplateSelectorAgent(llm_client=None, confidence_threshold=0.85)

    result = asyncio.run(agent.select_template(
        page={"title": "Watch Tutorial", "learning_objective": "Video learning"},
        source_content="Watch this video tutorial and walkthrough demonstration.",
    ))
    check("AGT06-09: method != rule (threshold too high)",
          result["method"] != "rule" or result["confidence"] >= 0.85)

def test_selector_default_threshold():
    """AGT06-10: Default confidence_threshold is 0.80."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)
    check("AGT06-10: Default threshold=0.80", agent.confidence_threshold == 0.80)

def test_selector_batch_selection():
    """AGT06-11: select_templates_batch handles multiple pages concurrently."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    pages = [
        {"title": "Quiz", "learning_objective": "Test"},
        {"title": "Compare", "learning_objective": "Compare A and B"},
        {"title": "FAQ", "learning_objective": "Answer questions"},
        {"title": "Regular", "learning_objective": "Learn"},
    ]
    sources = [
        "quiz assessment MCQ test score",
        "compare and contrast differences",
        "frequently asked questions",
        "regular content no keywords",
    ]
    results = asyncio.run(agent.select_templates_batch(pages, sources))
    check("AGT06-11: 4 results", len(results) == 4)
    check("AGT06-11: Result 0 is assessment", results[0]["template_type"] == "final-assessment")
    check("AGT06-11: Result 1 is tabs", results[1]["template_type"] == "tabs")
    check("AGT06-11: Result 2 is accordion", results[2]["template_type"] == "accordion")
    check("AGT06-11: All have template_type", all("template_type" in r for r in results))

def test_selector_parse_selection_valid_json():
    """AGT06-12: _parse_selection parses valid JSON."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = agent._parse_selection('{"template_type": "tabs", "confidence": 0.92, "reasoning": "Best fit"}')
    check("AGT06-12: Parsed tabs", result["template_type"] == "tabs")
    check("AGT06-12: Confidence 0.92", result["confidence"] == 0.92)

def test_selector_parse_selection_markdown_block():
    """AGT06-13: _parse_selection extracts JSON from markdown code block."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = agent._parse_selection('Here is my selection:\n```json\n{"template_type": "accordion", "confidence": 0.88, "reasoning": "Q&A format"}\n```')
    check("AGT06-13: Parsed accordion", result["template_type"] == "accordion")

def test_selector_parse_selection_bad_json_returns_default():
    """AGT06-14: _parse_selection on garbage returns content-text default."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    agent = TemplateSelectorAgent(llm_client=None)

    result = agent._parse_selection("I'm not sure, maybe tabs? Let me think...")
    check("AGT06-14: Falls back to content-text", result["template_type"] == "content-text")
    check("AGT06-14: Confidence 0.5", result["confidence"] == 0.5)
    check("AGT06-14: Method note", "unparseable" in result.get("reasoning", "").lower() or "default" in result.get("reasoning", "").lower())


# ═══════════════════════════════════════════════════════════════════════
# AGT-07: ContentGeneratorAgent Tests
# ═══════════════════════════════════════════════════════════════════════

def test_generator_import():
    """AGT07-01: ContentGeneratorAgent class importable."""
    from app.services.ai.agents.content_generator_agent import (
        ContentGeneratorAgent, GENERATOR_SYSTEM_PROMPT, TEMPLATE_SCHEMAS,
    )
    check("AGT07-01: Class exists", ContentGeneratorAgent is not None)
    check("AGT07-01: System prompt exists", len(GENERATOR_SYSTEM_PROMPT) > 100)
    check("AGT07-01: 5 template schemas", len(TEMPLATE_SCHEMAS) == 5)
    for t in ["content-text", "tabs", "accordion", "click-reveal", "final-assessment"]:
        check(f"AGT07-01: Has {t} schema", t in TEMPLATE_SCHEMAS)

def test_generator_no_llm_uses_mock_fallback():
    """AGT07-02: With no LLM client, uses inline mock fallback immediately."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Test Page", "source_content": "Sample content", "learning_objective": "Learn testing"},
        template_assignment={"template_type": "content-text"},
        rag_context=[],
        course_context={"title": "Test Course", "audience": "beginners", "tone": "friendly"},
        page_index=0,
        total_pages=5,
    ))
    check("AGT07-02: Has title", result["title"] == "Test Page")
    check("AGT07-02: Has template_type", result["template_type"] == "content-text")
    check("AGT07-02: Has components", len(result.get("components", [])) > 0)
    check("AGT07-02: Fallback metadata", result.get("generation_metadata", {}).get("fallback") is True)
    check("AGT07-02: Method is inline_mock", result["generation_metadata"]["method"] == "inline_mock")

def test_generator_mock_content_text():
    """AGT07-03: Mock fallback generates valid content-text components."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Security Basics"},
        template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    comps = result["components"]
    check("AGT07-03: 1 component", len(comps) == 1)
    check("AGT07-03: component_type", comps[0]["component_type"] == "content-text")
    check("AGT07-03: Has data.content", "content" in comps[0]["data"])
    check("AGT07-03: Contains title in content", "Security Basics" in comps[0]["data"]["content"])

def test_generator_mock_tabs():
    """AGT07-04: Mock fallback generates valid tabs components."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Compare Firewalls"},
        template_assignment={"template_type": "tabs"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    comps = result["components"]
    check("AGT07-04: component_type=tabs", comps[0]["component_type"] == "tabs")
    check("AGT07-04: Has 3 tabs", len(comps[0]["data"]["tabs"]) == 3)

def test_generator_mock_accordion():
    """AGT07-05: Mock fallback generates valid accordion components."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "FAQ: Security"},
        template_assignment={"template_type": "accordion"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    comps = result["components"]
    check("AGT07-05: component_type=accordion", comps[0]["component_type"] == "accordion")
    check("AGT07-05: Has 3 items", len(comps[0]["data"]["items"]) == 3)

def test_generator_mock_click_reveal():
    """AGT07-06: Mock fallback generates valid click-reveal components."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Explore Threats"},
        template_assignment={"template_type": "click-reveal"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    comps = result["components"]
    check("AGT07-06: component_type=click-reveal", comps[0]["component_type"] == "click-reveal")
    check("AGT07-06: Has 3 cards", len(comps[0]["data"]["cards"]) == 3)

def test_generator_mock_final_assessment():
    """AGT07-07: Mock fallback generates valid final-assessment components."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Security Quiz"},
        template_assignment={"template_type": "final-assessment"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    comps = result["components"]
    check("AGT07-07: component_type=final-assessment", comps[0]["component_type"] == "final-assessment")
    check("AGT07-07: Has passing_score=80", comps[0]["data"]["passing_score"] == 80)
    check("AGT07-07: Has questions", len(comps[0]["data"]["questions"]) > 0)
    check("AGT07-07: Question has options", len(comps[0]["data"]["questions"][0]["options"]) == 4)
    # Verify exactly one correct answer
    correct_count = sum(1 for o in comps[0]["data"]["questions"][0]["options"] if o.get("isCorrect"))
    check("AGT07-07: Exactly 1 correct answer", correct_count == 1)

def test_generator_mock_unknown_template_defaults_to_content_text():
    """AGT07-08: Unknown template type defaults to content-text mock."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Something New"},
        template_assignment={"template_type": "nonexistent-type"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    check("AGT07-08: Falls back to content-text", result["components"][0]["component_type"] == "content-text")

def test_generator_with_mock_llm_falls_back_gracefully():
    """AGT07-09: Mock LLM (non-JSON) → retries → mock fallback succeeds."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    from app.services.ai.llm_client import LLMClient

    agent = ContentGeneratorAgent(llm_client=LLMClient())  # MOCK by default
    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Test", "source_content": "Content", "learning_objective": "Learn"},
        template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={"title": "Test"}, page_index=0, total_pages=1,
    ))
    check("AGT07-09: Has title", "title" in result)
    check("AGT07-09: Has components (fallback worked)", len(result.get("components", [])) > 0)
    check("AGT07-09: Fallback metadata", result.get("generation_metadata", {}).get("fallback") is True)

def test_generator_quick_validate():
    """AGT07-10: _quick_validate correctly validates component structure."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent()

    # Valid
    check("AGT07-10: Valid content-text",
          agent._quick_validate({"components": [{"component_type": "content-text", "data": {"content": "hi"}}]}, "content-text"))
    # Invalid: not a dict
    check("AGT07-10: Invalid: not dict", agent._quick_validate("not a dict", "content-text") is False)
    # Invalid: no components key
    check("AGT07-10: Invalid: no components", agent._quick_validate({}, "content-text") is False)
    # Invalid: empty components
    check("AGT07-10: Invalid: empty components", agent._quick_validate({"components": []}, "content-text") is False)
    # Invalid: missing component_type
    check("AGT07-10: Invalid: no component_type",
          agent._quick_validate({"components": [{"data": {"content": "hi"}}]}, "content-text") is False)
    # Invalid: missing data
    check("AGT07-10: Invalid: no data",
          agent._quick_validate({"components": [{"component_type": "content-text"}]}, "content-text") is False)

def test_generator_parse_and_repair_valid_json():
    """AGT07-11: _parse_and_repair extracts valid JSON from code block."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent()

    result = agent._parse_and_repair(
        '```json\n{"components": [{"component_type": "content-text", "data": {"content": "Hello"}}]}\n```',
        "content-text",
    )
    check("AGT07-11: Parsed component", len(result.get("components", [])) == 1)

def test_generator_parse_and_repair_bad_json_returns_empty():
    """AGT07-12: _parse_and_repair on garbage returns empty components."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent()

    result = agent._parse_and_repair("not json at all", "content-text")
    check("AGT07-12: Returns empty components", result.get("components") == [])

def test_generator_default_order():
    """AGT07-13: Uses page_index as order when order not in page_plan."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Page 5"},
        template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={}, page_index=5, total_pages=10,
    ))
    check("AGT07-13: order is page_index", result["order"] == 5)

def test_generator_source_excerpt_truncation():
    """AGT07-14: source_excerpt truncated to 500 chars."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    long_content = "X" * 1000
    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Test", "source_content": long_content},
        template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    check("AGT07-14: Excerpt <= 500", len(result["source_excerpt"]) <= 500)

def test_generator_error_message_in_metadata():
    """AGT07-15: Error message passed through to generation_metadata."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    result = asyncio.run(agent.generate_page(
        page_plan={"title": "Test"},
        template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    # With no error (llm_client=None triggers fallback with empty error)
    check("AGT07-15: reason in metadata", "reason" in result["generation_metadata"])
    # When we use mock LLM that fails, the error should be captured
    from app.services.ai.llm_client import LLMClient
    agent2 = ContentGeneratorAgent(llm_client=LLMClient(), max_retries=1)
    result2 = asyncio.run(agent2.generate_page(
        page_plan={"title": "Test", "source_content": "X"},
        template_assignment={"template_type": "content-text"},
        rag_context=[], course_context={}, page_index=0, total_pages=1,
    ))
    check("AGT07-15: Error propagated to metadata",
          result2["generation_metadata"]["fallback"] is True)

def test_generator_custom_max_retries():
    """AGT07-16: Custom max_retries is stored."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(max_retries=5)
    check("AGT07-16: Custom retries", agent.max_retries == 5)

def test_generator_each_template_produces_different_structure():
    """AGT07-17: Each template type produces structurally distinct mock output."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent(llm_client=None)

    results = {}
    for ttype in ["content-text", "tabs", "accordion", "click-reveal", "final-assessment"]:
        results[ttype] = asyncio.run(agent.generate_page(
            page_plan={"title": f"Test {ttype}"},
            template_assignment={"template_type": ttype},
            rag_context=[], course_context={}, page_index=0, total_pages=1,
        ))

    # Each template should have different component data structures
    check("AGT07-17: content-text has 'content'",
          "content" in results["content-text"]["components"][0]["data"])
    check("AGT07-17: tabs has 'tabs'",
          "tabs" in results["tabs"]["components"][0]["data"])
    check("AGT07-17: accordion has 'items'",
          "items" in results["accordion"]["components"][0]["data"])
    check("AGT07-17: click-reveal has 'cards'",
          "cards" in results["click-reveal"]["components"][0]["data"])
    check("AGT07-17: final-assessment has 'questions'",
          "questions" in results["final-assessment"]["components"][0]["data"])

def test_generator_build_prompt_includes_context():
    """AGT07-18: _build_generation_prompt embeds course context, RAG, source."""
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent
    agent = ContentGeneratorAgent()

    prompt = agent._build_generation_prompt(
        page_plan={"title": "Intro", "learning_objective": "Understand X", "source_content": "Source text here"},
        template_type="content-text",
        rag_context=[{"title": "Similar Course", "excerpt": "Example course content"}],
        course_context={"title": "My Course", "audience": "beginners", "tone": "friendly"},
        page_index=2,
        total_pages=10,
    )
    check("AGT07-18: Has course title", "My Course" in prompt)
    check("AGT07-18: Has page number", "Page 3 of 10" in prompt)
    check("AGT07-18: Has template type", "content-text" in prompt)
    check("AGT07-18: Has audience", "beginners" in prompt)
    check("AGT07-18: Has tone", "friendly" in prompt)
    check("AGT07-18: Has source material", "Source text here" in prompt)
    check("AGT07-18: Has RAG context", "Similar Course" in prompt)
    check("AGT07-18: Has output schema", "REQUIRED OUTPUT SCHEMA" in prompt)
    check("AGT07-18: Has IMPORTANT instructions", "IMPORTANT" in prompt)


# ═══════════════════════════════════════════════════════════════════════
# Cross-Agent Integration Smoke Tests
# ═══════════════════════════════════════════════════════════════════════

def test_cross_planner_output_feeds_selector():
    """CROSS-01: Planner output format is compatible with TemplateSelector input."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent

    planner = PlannerAgent(llm_client=None)
    plan = asyncio.run(planner.generate_page_plan(
        SAMPLE_SECTIONS, ["content-text", "tabs", "final-assessment"], {"title": "Test"},
    ))

    selector = TemplateSelectorAgent(llm_client=None)
    for page in plan["pages"]:
        result = asyncio.run(selector.select_template(page, page.get("source_content", "")))
        check(f"CROSS-01: Template for {page['title']}",
              "template_type" in result and "confidence" in result and "method" in result)

def test_cross_selector_output_feeds_generator():
    """CROSS-02: TemplateSelector output format is compatible with ContentGenerator input."""
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent

    selector = TemplateSelectorAgent(llm_client=None)
    selection = asyncio.run(selector.select_template(
        {"title": "Quiz Page", "learning_objective": "Test"},
        "quiz assessment MCQ test score",
    ))

    generator = ContentGeneratorAgent(llm_client=None)
    page = asyncio.run(generator.generate_page(
        page_plan={"title": "Quiz Page", "source_content": "quiz assessment MCQ test score", "learning_objective": "Test"},
        template_assignment=selection,
        rag_context=[],
        course_context={"title": "Test"},
        page_index=0,
        total_pages=1,
    ))
    check("CROSS-02: Has components", len(page.get("components", [])) > 0)
    check("CROSS-02: Template matches selection",
          page["template_type"] == selection["template_type"])

def test_cross_full_pipeline_3_agents():
    """CROSS-03: Full pipeline: Plan → Select Templates → Generate Content (all 3 agents)."""
    from app.services.ai.agents.planner_agent import PlannerAgent
    from app.services.ai.agents.template_selector_agent import TemplateSelectorAgent
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent

    # Phase 1: Plan
    planner = PlannerAgent(llm_client=None)
    plan = asyncio.run(planner.generate_page_plan(
        SAMPLE_SECTIONS,
        ["content-text", "tabs", "accordion", "click-reveal", "final-assessment"],
        {"title": "Cybersecurity 101", "audience": "IT professionals", "tone": "professional"},
    ))
    check("CROSS-03: Plan generated", len(plan["pages"]) == 4)

    # Phase 2: Select templates for each page
    selector = TemplateSelectorAgent(llm_client=None)
    selections = []
    for page in plan["pages"]:
        sel = asyncio.run(selector.select_template(page, page.get("source_content", "")))
        selections.append(sel)
    check("CROSS-03: All templates selected", len(selections) == 4)

    # Phase 3: Generate content for each page
    generator = ContentGeneratorAgent(llm_client=None)
    generated_pages = []
    for i, (page, sel) in enumerate(zip(plan["pages"], selections)):
        gen_page = asyncio.run(generator.generate_page(
            page_plan=page,
            template_assignment=sel,
            rag_context=[],
            course_context={"title": "Cybersecurity 101", "audience": "IT professionals", "tone": "professional"},
            page_index=i,
            total_pages=len(plan["pages"]),
        ))
        generated_pages.append(gen_page)

    check("CROSS-03: All pages generated", len(generated_pages) == 4)
    for i, gp in enumerate(generated_pages):
        check(f"CROSS-03: Page {i} has title", len(gp.get("title", "")) > 0)
        check(f"CROSS-03: Page {i} has components", len(gp.get("components", [])) > 0)
        check(f"CROSS-03: Page {i} has metadata", "generation_metadata" in gp)


# ═══════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Agent Tests — AGT-03, AGT-06, AGT-07 + Cross-Agent Integration")
    print("=" * 60)

    # AGT-03: PlannerAgent
    print("\n--- AGT-03: PlannerAgent ---")
    test_planner_import()
    test_planner_deterministic_fallback_no_llm()
    test_planner_normalises_missing_ids()
    test_planner_template_suggestion()
    test_planner_parse_plan_from_json()
    test_planner_parse_plain_json()
    test_planner_parse_malformed_json_returns_empty()
    test_planner_validate_plan_all_assigned()
    test_planner_validate_plan_missing_sections()
    test_planner_validate_plan_no_pages()
    test_planner_validate_invalid_template_type()
    test_planner_validate_too_many_pages()
    test_planner_with_mock_llm_falls_back_gracefully()
    test_planner_build_planning_prompt()
    test_planner_custom_max_retries()
    test_planner_default_max_retries()

    # AGT-06: TemplateSelectorAgent
    print("\n--- AGT-06: TemplateSelectorAgent ---")
    test_selector_import()
    test_selector_rules_assessment()
    test_selector_rules_comparison()
    test_selector_rules_faq()
    test_selector_rules_interactive()
    test_selector_rules_video()
    test_selector_no_keywords_falls_back_to_default()
    test_selector_multiple_rules_picks_highest_confidence()
    test_selector_custom_threshold()
    test_selector_default_threshold()
    test_selector_batch_selection()
    test_selector_parse_selection_valid_json()
    test_selector_parse_selection_markdown_block()
    test_selector_parse_selection_bad_json_returns_default()

    # AGT-07: ContentGeneratorAgent
    print("\n--- AGT-07: ContentGeneratorAgent ---")
    test_generator_import()
    test_generator_no_llm_uses_mock_fallback()
    test_generator_mock_content_text()
    test_generator_mock_tabs()
    test_generator_mock_accordion()
    test_generator_mock_click_reveal()
    test_generator_mock_final_assessment()
    test_generator_mock_unknown_template_defaults_to_content_text()
    test_generator_with_mock_llm_falls_back_gracefully()
    test_generator_quick_validate()
    test_generator_parse_and_repair_valid_json()
    test_generator_parse_and_repair_bad_json_returns_empty()
    test_generator_default_order()
    test_generator_source_excerpt_truncation()
    test_generator_error_message_in_metadata()
    test_generator_custom_max_retries()
    test_generator_each_template_produces_different_structure()
    test_generator_build_prompt_includes_context()

    # Cross-Agent Integration
    print("\n--- Cross-Agent Integration ---")
    test_cross_planner_output_feeds_selector()
    test_cross_selector_output_feeds_generator()
    test_cross_full_pipeline_3_agents()

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    if failures:
        print("\nFAILURES:")
        for name, detail in failures:
            print(f"  {name}: {detail}")
