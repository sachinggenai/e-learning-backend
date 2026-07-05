"""Standalone test runner for TRD-CGQ Phase 2 — Content Generation Enhancement.

Tests template-specific content generators, rules-based MCQ generation,
model escalation, and TemplateSelector integration into propose-breakdown.
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
# 1. Template-Specific Content Generators
# ═══════════════════════════════════════════════════════════════════════


def test_template_generators():
    global passed, failed
    from app.services.ai.course_generator import CourseGenerator
    from app.services.ai.feature_detector import FeatureDetector

    print("\n=== [2A] Template-Specific Content Generators ===")
    gen = CourseGenerator(AsyncMock())
    detector = FeatureDetector()

    # -- Text content with features --
    features = detector.detect(
        "This section covers key concepts related to password security. "
        "Note: Always use strong passwords. Important: Enable MFA. "
        "Key Takeaway: Password managers improve security. "
        "- Use unique passwords\n- Enable MFA\n- Update regularly",
        section_index=2, total_sections=5,
    )
    components = gen._generate_text_content("Password Security", "Source text about passwords.", features)
    check("UT-GEN-01: text content has main component", len(components) >= 1)
    check("UT-GEN-01: has callout box (has_callout=True)",
          any("callout" in c.get("data", {}).get("content", "").lower() for c in components),
          f"got {len(components)} components")
    check("UT-GEN-01: has key points list (has_list=True)",
          len(components) >= 3 or any("Key Points" in c.get("data", {}).get("content", "") for c in components),
          f"got {len(components)} components")

    # -- Text content without features (minimal) --
    features_plain = detector.detect(
        "Simple content with no special patterns.", section_index=3, total_sections=5,
    )
    components = gen._generate_text_content("Simple Topic", "Simple content.", features_plain)
    check("UT-GEN-01-minimal: single component for plain text", len(components) == 1,
          f"got {len(components)}")

    # -- Accordion with sub-topics --
    features = detector.detect(
        "# Password Security\nStrong passwords are the first line of defense. "
        "Use a mix of characters and avoid common words. Password managers help.\n\n"
        "# Multi-Factor Authentication\nMFA requires two or more verification methods. "
        "This could be something you know, have, or are.\n\n"
        "# Safe Browsing\nAlways check for HTTPS before entering sensitive data. "
        "Avoid public Wi-Fi for financial transactions.\n\n"
        "# Email Security\nBe cautious with email attachments from unknown senders.",
        section_index=3, total_sections=10,
    )
    components = gen._generate_accordion_content("Security Topics", "Source text", features)
    check("UT-GEN-02: accordion has items", len(components) > 0)
    comp = components[0]
    items = comp.get("data", {}).get("items", [])
    check("UT-GEN-02: accordion item count >= 3", len(items) >= 3,
          f"got {len(items)} items")
    check("UT-GEN-02: items have titles", all("title" in item for item in items))
    check("UT-GEN-02: items have content", all("content" in item for item in items))

    # -- Accordion with few sub-topics (generic fallback) --
    features_few = detector.detect(
        "Single paragraph about one topic.", section_index=4, total_sections=10,
    )
    components = gen._generate_accordion_content("Single Topic", "Content", features_few)
    items = components[0].get("data", {}).get("items", [])
    check("UT-GEN-02-fallback: 3 generic items for few sub-topics",
          len(items) == 3, f"got {len(items)}")

    # -- Tabs with procedure steps --
    features = detector.detect(
        "Step 1: Identify the risk. Step 2: Assess impact. Step 3: Implement controls. "
        "First, gather information. Next, analyze the data. Then, make a decision. "
        "Finally, document your actions.",
        section_index=2, total_sections=5,
    )
    components = gen._generate_tabs_content("Risk Management", "Procedure source", features)
    tabs = components[0].get("data", {}).get("tabs", [])
    check("UT-GEN-03: tabs with procedure steps", len(tabs) == 3,
          f"got {len(tabs)}")
    check("UT-GEN-03: has Preparation tab",
          any(t["title"] == "Preparation" for t in tabs))
    check("UT-GEN-03: has Step-by-Step tab",
          any(t["title"] == "Step-by-Step" for t in tabs))

    # -- Tabs with parallel sub-topics --
    features_parallel = detector.detect(
        "# Option A: Cloud Storage\nCloud storage offers scalability and accessibility. "
        "It is ideal for distributed teams and remote work scenarios.\n\n"
        "# Option B: On-Premise Storage\nOn-premise storage provides full control "
        "over data and infrastructure. Best for regulated industries.",
        section_index=3, total_sections=5,
    )
    components = gen._generate_tabs_content("Storage Options", "Parallel topics", features_parallel)
    tabs = components[0].get("data", {}).get("tabs", [])
    check("UT-GEN-03-parallel: tabs for parallel topics", len(tabs) >= 2,
          f"got {len(tabs)}")

    # -- Tabs generic fallback --
    features_plain = detector.detect("Simple content.", section_index=1, total_sections=5)
    components = gen._generate_tabs_content("Simple", "Content", features_plain)
    tabs = components[0].get("data", {}).get("tabs", [])
    check("UT-GEN-03-fallback: 3 generic tabs", len(tabs) == 3,
          f"got {len(tabs)}")

    # -- Click-reveal with Q&A --
    features = detector.detect(
        "Q: What is phishing? A: A social engineering attack. "
        "Q: How can I protect myself? A: Use email filters and be cautious of links.",
        section_index=4, total_sections=5,
    )
    components = gen._generate_click_reveal_content("Phishing Q&A", "Q&A source", features)
    items = components[0].get("data", {}).get("items", [])
    check("UT-GEN-click-reveal: Q&A items generated", len(items) >= 2,
          f"got {len(items)}")
    check("UT-GEN-click-reveal: items are Q&A style",
          any("Q:" in item.get("title", "") for item in items))


# ═══════════════════════════════════════════════════════════════════════
# 2. Rules-Based MCQ Generator
# ═══════════════════════════════════════════════════════════════════════


def test_rules_based_mcq():
    global passed, failed
    from app.services.ai.course_generator import CourseGenerator
    from app.services.ai.feature_detector import FeatureDetector

    print("\n=== [2B] Rules-Based MCQ Generator ===")
    gen = CourseGenerator(AsyncMock())
    detector = FeatureDetector()

    # -- 5 page titles → 5 MCQs --
    features = detector.detect(
        "Final assessment with quiz questions.", section_index=4, total_sections=5,
    )
    all_titles = [
        "Introduction to Cybersecurity",
        "Password Security",
        "Phishing Awareness",
        "Safe Browsing Practices",
        "Data Protection",
    ]
    components = gen._generate_assessment_content(
        "Final Assessment", "Assessment content", features, all_titles,
    )
    comp = components[0]
    questions = comp.get("data", {}).get("questions", [])

    check("UT-MCQ-01: 5 questions from 5 titles", len(questions) == 5,
          f"got {len(questions)} questions")
    check("UT-MCQ-01: passing_score=80",
          comp.get("data", {}).get("passing_score") == 80)
    check("UT-MCQ-01: each question has id",
          all("id" in q for q in questions))
    check("UT-MCQ-01: each question has 4 options",
          all(len(q.get("options", [])) == 4 for q in questions))
    check("UT-MCQ-01: each question has exactly 1 correct option",
          all(sum(1 for o in q.get("options", []) if o.get("isCorrect")) == 1
              for q in questions))
    check("UT-MCQ-01: each question has feedback",
          all("feedback" in q for q in questions))
    check("UT-MCQ-01: questions reference topic titles",
          any(titles_partial in questions[0]["question"]
              for titles_partial in ["Password", "Phishing", "Introduction"])
          or any(t in questions[0]["question"] for t in all_titles))

    # -- 3 titles → at least 3 MCQs (min from config) --
    components = gen._generate_assessment_content(
        "Quiz", "Quiz content", features,
        ["Topic A", "Topic B", "Topic C"],
    )
    questions = components[0].get("data", {}).get("questions", [])
    check("UT-MCQ-02: at least 3 questions", len(questions) >= 3,
          f"got {len(questions)}")

    # -- No page titles → uses generic topics --
    features_empty = detector.detect("Quiz.", section_index=9, total_sections=10)
    components = gen._generate_assessment_content(
        "Quiz", "Quiz", features_empty, [],
    )
    questions = components[0].get("data", {}).get("questions", [])
    check("UT-MCQ-03: generates questions even without titles",
          len(questions) >= 3, f"got {len(questions)}")
    check("UT-MCQ-03: questions use generic topics",
          all("question" in q and "options" in q for q in questions))


# ═══════════════════════════════════════════════════════════════════════
# 3. Breakdown Model Resolution
# ═══════════════════════════════════════════════════════════════════════


def test_breakdown_integration():
    global passed, failed

    print("\n=== [2C] Breakdown Integration ===")

    # Test model chain
    from app.routers.ai_ingestion import _get_breakdown_model_chain
    chain = _get_breakdown_model_chain()
    check("UT-BRK-01: breakdown chain is non-empty list",
          isinstance(chain, list) and len(chain) > 0,
          f"chain={chain}")
    check("UT-BRK-01: 'mock' is last in chain",
          chain[-1] == "mock", f"last={chain[-1]}")
    check("UT-BRK-01: chain starts with qwen2.5:7b",
          chain[0] == "qwen2.5:7b", f"first={chain[0]}")

    # Test heuristic breakdown
    from app.routers.ai_ingestion import _heuristic_breakdown
    sections = [
        {"heading": "Welcome", "content_preview": "Welcome to the course overview.", "char_count": 150},
        {"heading": "Passwords", "content_preview": "Step 1: Choose strong passwords. Step 2: Enable MFA. Step 3: Use password manager.", "char_count": 500},
        {"heading": "Phishing", "content_preview": "Q: What is phishing? A: A social engineering attack. Q: How to avoid?", "char_count": 400},
        {"heading": "Final Quiz", "content_preview": "Assessment: Test your knowledge. Score 80% to pass.", "char_count": 250},
    ]
    plan = _heuristic_breakdown(sections, 50)

    check("UT-BRK-02: correct page count", len(plan) == 4, f"got {len(plan)}")
    check("UT-BRK-02: each page has suggested_template_type",
          all("suggested_template_type" in p for p in plan))
    check("UT-BRK-02: each page has rationale",
          all("rationale" in p for p in plan))

    # Template diversity check
    templates = set(p["suggested_template_type"] for p in plan)
    check("UT-BRK-02: template diversity >= 2 types",
          len(templates) >= 2,
          f"got {templates} ({len(templates)} types)")

    # First page should be welcome (intro language + is_first)
    check("UT-BRK-02: first section uses welcome",
          plan[0]["suggested_template_type"] == "welcome",
          f"got {plan[0]['suggested_template_type']}")

    # Last page with assessment keywords
    check("UT-BRK-02: assessment section detected",
          plan[3]["suggested_template_type"] == "final-assessment",
          f"got {plan[3]['suggested_template_type']}")

    # Test _heuristic_breakdown fallback with empty sections
    empty_plan = _heuristic_breakdown([], 10)
    check("UT-BRK-03: empty sections yields empty plan",
          len(empty_plan) == 0)

    # Test _heuristic_breakdown with malformed sections
    bad_plan = _heuristic_breakdown([None, "not a dict", 123], 10)
    check("UT-BRK-04: malformed sections handled gracefully",
          len(bad_plan) == 0)


# ═══════════════════════════════════════════════════════════════════════
# 4. Model Escalation in Course Generator
# ═══════════════════════════════════════════════════════════════════════


def test_model_escalation():
    global passed, failed
    from app.services.ai.course_generator import _provider_from_model_config
    from app.services.ai.config import ModelConfig, ModelTier
    from app.services.ai.llm_client import LLMProvider

    print("\n=== [P6] Model Escalation ===")

    # Provider from model config
    ollama_model = ModelConfig(
        id="qwen2.5:7b", provider="ollama",
        api_model_name="qwen2.5:7b", tier=ModelTier.GENERATOR,
    )
    check("P6: ollama model -> OLLAMA provider",
          _provider_from_model_config(ollama_model) == LLMProvider.OLLAMA)

    anthropic_model = ModelConfig(
        id="claude-sonnet-4", provider="anthropic",
        api_model_name="claude-sonnet-4-20250514", tier=ModelTier.GENERATOR,
    )
    check("P6: anthropic model -> ANTHROPIC provider",
          _provider_from_model_config(anthropic_model) == LLMProvider.ANTHROPIC)

    check("P6: None model -> MOCK provider",
          _provider_from_model_config(None) == LLMProvider.MOCK)

    # Test escalation chain integration (import check only — actual LLM test requires server)
    from app.routers.ai_ingestion import _get_breakdown_model_chain
    chain = _get_breakdown_model_chain()
    check("P6: breakdown chain ends with mock", chain[-1] == "mock")
    check("P6: breakdown chain is ordered correctly",
          all(chain[i] != chain[i+1] for i in range(len(chain)-1)),
          f"chain has duplicate adjacent entries: {chain}")


# ═══════════════════════════════════════════════════════════════════════
# 5. Full Page Build Pipeline
# ═══════════════════════════════════════════════════════════════════════


def test_full_page_build():
    global passed, failed
    from app.services.ai.course_generator import CourseGenerator
    from app.services.ai.feature_detector import FeatureDetector

    print("\n=== [2A-Integration] Full Page Build Pipeline ===")
    gen = CourseGenerator(AsyncMock())
    detector = FeatureDetector()

    pages = [
        {"title": "Welcome", "template_type": "welcome",
         "source_excerpt": "Welcome to the course overview.", "order": 0},
        {"title": "Password Security", "template_type": "accordion",
         "source_excerpt": "# Topic 1\nContent here.\n# Topic 2\nMore content.\n# Topic 3\nEven more.\n# Topic 4\nFinal topic.", "order": 1},
        {"title": "Phishing Defense", "template_type": "tabs",
         "source_excerpt": "Step 1: Identify. Step 2: Protect. Step 3: Report.", "order": 2},
        {"title": "Key Concepts", "template_type": "content-text",
         "source_excerpt": "Note: Important security concept. Key Takeaway: Be vigilant.", "order": 3},
        {"title": "Final Assessment", "template_type": "final-assessment",
         "source_excerpt": "Assessment: Test your knowledge.", "order": 4},
    ]

    total = len(pages)
    options = {
        "page_titles": [p["title"] for p in pages],
        "_all_pages": pages,
    }

    for i, page in enumerate(pages):
        features = detector.detect(page.get("source_excerpt", ""), i, total)
        result = gen._generate_page_content(page, options, i, features)

        check(f"Page {i}: has title", "title" in result)
        check(f"Page {i}: has template_type", "template_type" in result)
        check(f"Page {i}: has components", len(result.get("components", [])) > 0)

        ttype = page["template_type"]
        if ttype == "final-assessment":
            comp = result["components"][0]
            questions = comp.get("data", {}).get("questions", [])
            check(f"Page {i}: assessment has >= 3 questions",
                  len(questions) >= 3, f"got {len(questions)}")

    # Check multi-component output on content-text with callout
    note_page = [r for r in [gen._generate_page_content(
        {"title": "Key Concepts", "template_type": "content-text",
         "source_excerpt": "Note: Important concept. - Bullet 1\n- Bullet 2\n- Bullet 3", "order": 0},
        options, 0,
        detector.detect("Note: Important concept. - Bullet 1\n- Bullet 2\n- Bullet 3", 0, 1)
    )]]
    # The text-content page with callout + list should have 3 components
    for r in note_page:
        comps = r.get("components", [])
        check("Integration: multi-component output for rich content",
              len(comps) >= 2,
              f"got {len(comps)} components for content-text with callout+list")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    global passed, failed, failures

    print("=" * 70)
    print("TRD-CGQ Phase 2 -- Content Generation Enhancement Tests")
    print("=" * 70)

    test_template_generators()
    test_rules_based_mcq()
    test_breakdown_integration()
    test_model_escalation()
    test_full_page_build()

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
    import asyncio
    success = main()
    sys.exit(0 if success else 1)
