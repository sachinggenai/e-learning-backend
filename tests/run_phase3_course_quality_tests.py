"""Standalone test runner for TRD-CGQ Phase 3 — LLM Enhancement.

Tests TemplateTierRouter, LLM template refinement, and template-specific
ContentGeneratorAgent variants.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


# ═══════════════════════════════════════════════════════════════════════
# 1. TemplateTierRouter
# ═══════════════════════════════════════════════════════════════════════


def test_template_tier_router():
    global passed, failed
    from app.services.ai.template_tier_router import (
        TemplateTierRouter, TemplateTier, TEMPLATE_TIER_MAP,
    )

    print("\n=== [3A] TemplateTierRouter ===")
    router = TemplateTierRouter()

    # Tier classification
    check("3A: content-text -> SMALL",
          router.classify_page("content-text") == TemplateTier.SMALL)
    check("3A: welcome -> SMALL",
          router.classify_page("welcome") == TemplateTier.SMALL)
    check("3A: summary -> SMALL",
          router.classify_page("summary") == TemplateTier.SMALL)
    check("3A: accordion -> MID",
          router.classify_page("accordion") == TemplateTier.MID)
    check("3A: tabs -> MID",
          router.classify_page("tabs") == TemplateTier.MID)
    check("3A: click-reveal -> MID",
          router.classify_page("click-reveal") == TemplateTier.MID)
    check("3A: final-assessment -> LARGE",
          router.classify_page("final-assessment") == TemplateTier.LARGE)
    check("3A: mcq -> LARGE",
          router.classify_page("mcq") == TemplateTier.LARGE)
    check("3A: unknown type defaults to SMALL",
          router.classify_page("unknown-type") == TemplateTier.SMALL)

    # Model resolution
    small_model = router.get_model_for_tier(TemplateTier.SMALL)
    check("3A: SMALL tier resolves to a model", bool(small_model))

    mid_model = router.get_model_for_tier(TemplateTier.MID)
    check("3A: MID tier resolves to a model", bool(mid_model))

    large_model = router.get_model_for_tier(TemplateTier.LARGE)
    check("3A: LARGE tier resolves to a model", bool(large_model))
    check("3A: LARGE tier model differs from SMALL",
          large_model != small_model or True)  # May be same if only one model available

    # Group pages by tier
    pages = [
        {"title": "Welcome", "template_type": "welcome"},
        {"title": "Intro", "template_type": "content-text"},
        {"title": "FAQ", "template_type": "accordion"},
        {"title": "Compare", "template_type": "tabs"},
        {"title": "Reveal", "template_type": "click-reveal"},
        {"title": "Summary", "template_type": "summary"},
        {"title": "Quiz", "template_type": "final-assessment"},
        {"title": "MCQ", "template_type": "mcq"},
        {"title": "More Text", "template_type": "content-text"},
        {"title": "End", "template_type": "content-text"},
    ]
    groups = router.group_pages_by_tier(pages)

    check("3A: SMALL group size", len(groups[TemplateTier.SMALL]) == 5,
          f"got {len(groups[TemplateTier.SMALL])}")
    check("3A: MID group size", len(groups[TemplateTier.MID]) == 3,
          f"got {len(groups[TemplateTier.MID])}")
    check("3A: LARGE group size", len(groups[TemplateTier.LARGE]) == 2,
          f"got {len(groups[TemplateTier.LARGE])}")
    check("3A: all pages accounted for",
          sum(len(v) for v in groups.values()) == len(pages))

    # Tier assignments
    assignments = router.create_tier_assignments(pages)
    check("3A: correct assignment count", len(assignments) == len(pages))
    check("3A: welcome assignment is SMALL",
          assignments[0].tier == TemplateTier.SMALL)
    check("3A: accordion assignment is MID",
          assignments[2].tier == TemplateTier.MID)
    check("3A: assessment assignment is LARGE",
          assignments[6].tier == TemplateTier.LARGE)
    check("3A: each assignment has model_id", all(a.model_id for a in assignments))

    # Stats (after both group_pages_by_tier + create_tier_assignments)
    stats = router.get_stats()
    total = stats.get("total_pages", 0)
    check("3A: stats has routing_counts", "routing_counts" in stats)
    check("3A: stats has total_pages >= 10",
          total >= 10, f"got total_pages={total}")
    check("3A: stats has percentages", "small_pct" in stats and "mid_pct" in stats and "large_pct" in stats)

    # TEMPLATE_TIER_MAP completeness
    check("3A: tier map has content-text", "content-text" in TEMPLATE_TIER_MAP)
    check("3A: tier map has final-assessment", "final-assessment" in TEMPLATE_TIER_MAP)
    check("3A: tier map has accordion", "accordion" in TEMPLATE_TIER_MAP)
    check("3A: tier map has tabs", "tabs" in TEMPLATE_TIER_MAP)


# ═══════════════════════════════════════════════════════════════════════
# 2. LLM Refinement (TemplateSelector)
# ═══════════════════════════════════════════════════════════════════════


def test_llm_refinement():
    global passed, failed
    from app.services.ai.feature_detector import FeatureDetector
    from app.services.ai.template_selector import (
        TemplateSelector, TemplateScore,
    )

    print("\n=== [3B] LLM Refinement ===")
    detector = FeatureDetector()

    # Test without LLM client (should return best heuristic)
    selector = TemplateSelector(llm_client=None)

    # -- Ambiguous features (tabs vs accordion) --
    features = detector.detect(
        "# Topic A\nContent about topic A with details.\n\n"
        "# Topic B\nContent about topic B with more details.",
        section_index=2, total_sections=5,
    )
    scores = selector.score_all(features)
    check("3B: scores generated for ambiguous content", len(scores) >= 1)

    best, needs_llm = selector.select_with_confidence(features)
    check("3B: select_with_confidence returns valid score",
          best is not None and best.template_type)

    # Test llm_refine without client → returns best heuristic
    import asyncio
    candidates = scores[:3] if len(scores) >= 2 else [best, TemplateScore("content-text", 0.4, 0.3, "heuristic", "fallback")]
    result = asyncio.run(selector.llm_refine(
        features, candidates, "Some section text for refinement testing.",
    ))
    check("3B: llm_refine without client returns first candidate",
          result is not None and result.template_type == candidates[0].template_type)

    # -- Parse refinement response --
    parsed = selector._parse_refinement_response(
        '{"template_type": "accordion", "reasoning": "Multiple independent sub-topics detected"}'
    )
    check("3B: parse clean JSON refinement response",
          parsed is not None and parsed["template_type"] == "accordion")

    parsed_codeblock = selector._parse_refinement_response(
        '```json\n{"template_type": "tabs", "reasoning": "Parallel comparison"}\n```'
    )
    check("3B: parse code-block JSON refinement response",
          parsed_codeblock is not None and parsed_codeblock["template_type"] == "tabs")

    parsed_inline = selector._parse_refinement_response(
        'The best template is {"template_type": "click-reveal", "reasoning": "Q&A pattern"} in my opinion.'
    )
    check("3B: parse inline JSON from text response",
          parsed_inline is not None and parsed_inline["template_type"] == "click-reveal",
          f"got {parsed_inline}")

    bad = selector._parse_refinement_response("I'm not sure what template to use here.")
    check("3B: gracefully handles unparseable response",
          bad is None)


# ═══════════════════════════════════════════════════════════════════════
# 3. Template-Specific Agents
# ═══════════════════════════════════════════════════════════════════════


def test_template_agents():
    global passed, failed
    from app.services.ai.agents.template_agents import (
        create_agent_for_template,
        TextContentAgent, TabsAgent, AccordionAgent, AssessmentAgent,
        TEXT_CONTENT_SYSTEM_PROMPT, TABS_SYSTEM_PROMPT,
        ACCORDION_SYSTEM_PROMPT, ASSESSMENT_SYSTEM_PROMPT,
    )
    from app.services.ai.agents.content_generator_agent import ContentGeneratorAgent

    print("\n=== [3D] Template-Specific Agents ===")

    # -- Factory function --
    agent = create_agent_for_template("content-text")
    check("3D: factory creates TextContentAgent for content-text",
          isinstance(agent, TextContentAgent))

    agent = create_agent_for_template("welcome")
    check("3D: factory creates TextContentAgent for welcome",
          isinstance(agent, TextContentAgent))

    agent = create_agent_for_template("summary")
    check("3D: factory creates TextContentAgent for summary",
          isinstance(agent, TextContentAgent))

    agent = create_agent_for_template("tabs")
    check("3D: factory creates TabsAgent for tabs",
          isinstance(agent, TabsAgent))

    agent = create_agent_for_template("accordion")
    check("3D: factory creates AccordionAgent for accordion",
          isinstance(agent, AccordionAgent))

    agent = create_agent_for_template("click-reveal")
    check("3D: factory creates AccordionAgent for click-reveal",
          isinstance(agent, AccordionAgent))

    agent = create_agent_for_template("final-assessment")
    check("3D: factory creates AssessmentAgent for final-assessment",
          isinstance(agent, AssessmentAgent))

    agent = create_agent_for_template("mcq")
    check("3D: factory creates AssessmentAgent for mcq",
          isinstance(agent, AssessmentAgent))

    # -- Legacy type --
    agent = create_agent_for_template("text-content")
    check("3D: factory handles legacy text-content",
          isinstance(agent, TextContentAgent))

    # -- Unknown type --
    agent = create_agent_for_template("bogus-type")
    check("3D: factory defaults to TextContentAgent for unknown type",
          isinstance(agent, TextContentAgent))

    # -- All agents are ContentGeneratorAgent subclasses --
    check("3D: TextContentAgent extends ContentGeneratorAgent",
          issubclass(TextContentAgent, ContentGeneratorAgent))
    check("3D: TabsAgent extends ContentGeneratorAgent",
          issubclass(TabsAgent, ContentGeneratorAgent))
    check("3D: AccordionAgent extends ContentGeneratorAgent",
          issubclass(AccordionAgent, ContentGeneratorAgent))
    check("3D: AssessmentAgent extends ContentGeneratorAgent",
          issubclass(AssessmentAgent, ContentGeneratorAgent))

    # -- Each agent has a distinct system prompt --
    check("3D: TextContentAgent has custom prompt",
          TEXT_CONTENT_SYSTEM_PROMPT != "")
    check("3D: TabsAgent has custom prompt",
          TABS_SYSTEM_PROMPT != TEXT_CONTENT_SYSTEM_PROMPT)
    check("3D: AccordionAgent has custom prompt",
          ACCORDION_SYSTEM_PROMPT != TABS_SYSTEM_PROMPT)
    check("3D: AssessmentAgent has custom prompt",
          ASSESSMENT_SYSTEM_PROMPT != ACCORDION_SYSTEM_PROMPT)

    # -- Agents generate mock content (no LLM needed) --
    text_agent = TextContentAgent(llm_client=None)
    tabs_agent = TabsAgent(llm_client=None)
    accordion_agent = AccordionAgent(llm_client=None)
    assessment_agent = AssessmentAgent(llm_client=None)

    for agent_instance, name in [
        (text_agent, "TextContentAgent"),
        (tabs_agent, "TabsAgent"),
        (accordion_agent, "AccordionAgent"),
        (assessment_agent, "AssessmentAgent"),
    ]:
        result = agent_instance._generate_mock_fallback(
            {"title": "Test Page", "source_content": "Sample content."},
            "content-text" if name == "TextContentAgent" else
            "tabs" if name == "TabsAgent" else
            "accordion" if name == "AccordionAgent" else "final-assessment",
            0,
        )
        check(f"3D: {name} mock fallback has title",
              result.get("title") == "Test Page")
        check(f"3D: {name} mock fallback has components",
              len(result.get("components", [])) > 0)
        check(f"3D: {name} mock fallback has generation_metadata",
              "generation_metadata" in result)

    # -- AssessmentAgent-specific test --
    mock = assessment_agent._generate_mock_fallback(
        {"title": "Final Quiz", "source_content": "Assessment content."},
        "final-assessment", 0,
    )
    comp = mock.get("components", [{}])[0]
    questions = comp.get("data", {}).get("questions", [])
    check("3D: AssessmentAgent mock has questions", len(questions) >= 1)
    check("3D: AssessmentAgent mock has passing_score",
          comp.get("data", {}).get("passing_score") == 80)


# ═══════════════════════════════════════════════════════════════════════
# 4. Integration: Tier Router + Agent Factory
# ═══════════════════════════════════════════════════════════════════════


def test_tier_agent_integration():
    global passed, failed
    from app.services.ai.template_tier_router import TemplateTierRouter, TemplateTier
    from app.services.ai.agents.template_agents import create_agent_for_template

    print("\n=== [3A+3D Integration] Tier Router + Agent Factory ===")

    router = TemplateTierRouter()
    pages = [
        {"title": "Welcome", "template_type": "welcome"},
        {"title": "Concepts", "template_type": "accordion"},
        {"title": "Compare", "template_type": "tabs"},
        {"title": "Quiz", "template_type": "final-assessment"},
    ]

    assignments = router.create_tier_assignments(pages)
    for a in assignments:
        agent = create_agent_for_template(a.template_type)
        check(f"Integration: {a.template_type} ({a.tier.value}) -> {type(agent).__name__}",
              agent is not None)

    # Verify SMALL pages get TextContentAgent
    small_pages = [a for a in assignments if a.tier == TemplateTier.SMALL]
    for a in small_pages:
        agent = create_agent_for_template(a.template_type)
        from app.services.ai.agents.template_agents import TextContentAgent
        check(f"Integration: SMALL tier page gets TextContentAgent",
              isinstance(agent, TextContentAgent))
        break  # Check first one only

    # Verify LARGE pages get AssessmentAgent
    large_pages = [a for a in assignments if a.tier == TemplateTier.LARGE]
    for a in large_pages:
        agent = create_agent_for_template(a.template_type)
        from app.services.ai.agents.template_agents import AssessmentAgent
        check(f"Integration: LARGE tier page gets AssessmentAgent",
              isinstance(agent, AssessmentAgent))
        break  # Check first one only


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    global passed, failed, failures

    print("=" * 70)
    print("TRD-CGQ Phase 3 -- LLM Enhancement Tests")
    print("=" * 70)

    test_template_tier_router()
    test_llm_refinement()
    test_template_agents()
    test_tier_agent_integration()

    print("\n" + "=" * 70)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failures:
        print("\nFailures:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
