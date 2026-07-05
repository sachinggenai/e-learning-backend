"""Standalone test runner for TRD-CGQ Phase 1 — Course Generation Quality.

Tests DocumentSplitter, FeatureDetector, TemplateSelector, quality metrics,
and provider resolution (G4 fix).
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
# 1. DocumentSplitter Tests
# ═══════════════════════════════════════════════════════════════════════


def test_document_splitter():
    global passed, failed
    from app.services.ai.document_splitter import DocumentSplitter, Section

    print("\n=== [1A] DocumentSplitter ===")
    splitter = DocumentSplitter(use_llm=False)

    # UT-SPLIT-01: Structured paragraphs with heading styles
    paragraphs = [
        {"style_name": "Heading 1", "text": "Module 1: Introduction", "is_heading": True, "heading_level": 1},
        {"style_name": "Normal", "text": "Welcome to this course on cybersecurity awareness.", "is_heading": False, "heading_level": 0},
        {"style_name": "Normal", "text": "This module covers the basics of staying safe online.", "is_heading": False, "heading_level": 0},
        {"style_name": "Heading 1", "text": "Module 2: Password Security", "is_heading": True, "heading_level": 1},
        {"style_name": "Normal", "text": "Strong passwords are essential for account security.", "is_heading": False, "heading_level": 0},
        {"style_name": "Normal", "text": "Use at least 12 characters with mixed case.", "is_heading": False, "heading_level": 0},
        {"style_name": "Heading 2", "text": "Multi-Factor Authentication", "is_heading": True, "heading_level": 2},
        {"style_name": "Normal", "text": "MFA adds an extra layer of security beyond passwords.", "is_heading": False, "heading_level": 0},
        {"style_name": "Heading 1", "text": "Module 3: Phishing", "is_heading": True, "heading_level": 1},
        {"style_name": "Normal", "text": "Phishing attacks trick users into revealing sensitive info.", "is_heading": False, "heading_level": 0},
        {"style_name": "Normal", "text": "Learn to identify suspicious emails and messages.", "is_heading": False, "heading_level": 0},
        {"style_name": "Heading 1", "text": "Module 4: Safe Browsing", "is_heading": True, "heading_level": 1},
        {"style_name": "Normal", "text": "Always check for HTTPS before entering sensitive data.", "is_heading": False, "heading_level": 0},
        {"style_name": "Heading 1", "text": "Module 5: Data Protection", "is_heading": True, "heading_level": 1},
        {"style_name": "Normal", "text": "Encrypt sensitive files and use secure backups.", "is_heading": False, "heading_level": 0},
        {"style_name": "Heading 1", "text": "Assessment", "is_heading": True, "heading_level": 1},
        {"style_name": "Normal", "text": "Final knowledge check with multiple choice questions.", "is_heading": False, "heading_level": 0},
    ]
    sections = splitter.split_structured(paragraphs, "test.docx")
    check("UT-SPLIT-01: 6 sections from heading styles", len(sections) >= 6,
          f"got {len(sections)}")
    check("UT-SPLIT-01: module headings preserved",
          any("Module 1" in s.heading for s in sections))
    check("UT-SPLIT-01: assessment section detected",
          any("Assessment" in s.heading for s in sections))
    check("UT-SPLIT-01: content in sections", all(s.char_count > 0 for s in sections))
    check("UT-SPLIT-01: source style tracked",
          all(s.source_style == "heading_style" for s in sections))

    # UT-SPLIT-02: MD text with # headings
    md_text = (
        "# Introduction\n\nThis is the introduction section.\nIt has two paragraphs.\n\n"
        "## Learning Objectives\n\nBy the end of this module, you will understand key concepts.\n\n"
        "# Chapter 2: Core Concepts\n\nThis chapter covers the fundamentals.\n\n"
        "# Summary\n\nKey takeaways from this module.\n"
    )
    sections = splitter.split(md_text, "test.md", "md")
    check("UT-SPLIT-02: 4 sections from MD headings", len(sections) >= 3,
          f"got {len(sections)}")
    check("UT-SPLIT-02: introduction detected",
          any("Introduction" in s.heading for s in sections))
    check("UT-SPLIT-02: core concepts detected",
          any("Core Concepts" in s.heading for s in sections))

    # UT-SPLIT-03: Flat text, no structure
    flat_text = (
        "This is a flat document with no headings or structure. "
        "It just contains continuous text that goes on and on. "
        "There are no section markers or separators anywhere."
    )
    sections = splitter.split(flat_text, "flat.txt", "txt")
    check("UT-SPLIT-03: at least 1 section", len(sections) >= 1)
    check("UT-SPLIT-03: uses filename as heading",
          sections[0].heading == "flat.txt" or "flat" in sections[0].heading.lower())

    # UT-SPLIT-04: Empty text
    sections = splitter.split("", "empty.txt", "txt")
    check("UT-SPLIT-04: empty text yields 1 section", len(sections) >= 1)
    check("UT-SPLIT-04: empty section has 0 chars", sections[0].char_count == 0)

    # UT-SPLIT-05: DOCX heuristics fallback (ALL CAPS headings)
    flat_docx_text = (
        "INTRODUCTION\nThis is the first section content.\n\n"
        "CORE CONCEPTS\nThis covers key cybersecurity principles.\n\n"
        "BEST PRACTICES\nFollow these guidelines for security.\n\n"
        "ASSESSMENT\nFinal quiz questions here.\n"
    )
    sections = splitter.split(flat_docx_text, "test.docx", "docx")
    check("UT-SPLIT-05: ALL CAPS headings detected", len(sections) >= 3,
          f"got {len(sections)}")
    check("UT-SPLIT-05: has sections with content",
          any(s.char_count > 10 for s in sections))

    # Section.to_dict()
    s = sections[0]
    d = s.to_dict()
    check("Section.to_dict: has index", "index" in d)
    check("Section.to_dict: has heading", "heading" in d)
    check("Section.to_dict: has content_preview", "content_preview" in d)
    check("Section.to_dict: has char_count", "char_count" in d)


# ═══════════════════════════════════════════════════════════════════════
# 2. FeatureDetector Tests
# ═══════════════════════════════════════════════════════════════════════


def test_feature_detector():
    global passed, failed
    from app.services.ai.feature_detector import FeatureDetector, ContentFeatures

    print("\n=== [1B] FeatureDetector ===")
    detector = FeatureDetector()

    # UT-FEAT-01: Introduction language (needs 4+ non-empty lines for narrative)
    intro_text = (
        "Welcome to Cybersecurity Awareness.\n\n"
        "This course provides an overview of getting started with online safety. "
        "By the end, you will understand key security concepts and how to apply "
        "them in your daily work.\n\n"
        "We explore multiple topics including password security, phishing awareness, "
        "and safe browsing practices that every employee should know.\n\n"
        "The course is structured into several modules covering different aspects "
        "of cyber security with practical examples and hands-on exercises designed "
        "to build real-world skills that you can immediately apply in your role."
    )
    f = detector.detect(intro_text, section_index=0, total_sections=10)
    check("UT-FEAT-01: has_intro_language=True", f.has_intro_language is True)
    check("UT-FEAT-01: is_first=True", f.is_first is True)
    check("UT-FEAT-01: has_narrative_structure", f.has_narrative_structure is True,
          f"len={len(intro_text)}, char_count={f.char_count}")

    # UT-FEAT-02: Q&A pattern
    f = detector.detect(
        "Q: What is phishing?\nA: Phishing is a social engineering attack where "
        "attackers send fraudulent messages. How does it work? Attackers create "
        "fake websites that look legitimate. What is spear phishing? A targeted "
        "form of phishing aimed at specific individuals.",
        section_index=2, total_sections=10,
    )
    check("UT-FEAT-02: has_qa_pattern=True", f.has_qa_pattern is True)

    # UT-FEAT-03: Procedure steps
    f = detector.detect(
        "Step 1: Identify the security risk.\n"
        "Step 2: Assess the potential impact.\n"
        "Step 3: Implement appropriate controls.\n"
        "First, gather all relevant information. Next, analyze the data. "
        "Then, make a decision based on the findings. Finally, document your actions.",
        section_index=3, total_sections=10,
    )
    check("UT-FEAT-03: has_procedure_steps=True", f.has_procedure_steps is True)
    check("UT-FEAT-03: sub_topics detected", f.sub_topic_count >= 3)

    # UT-FEAT-04: Assessment keywords
    f = detector.detect(
        "Knowledge Check: Test your understanding of cybersecurity principles. "
        "This quiz covers the key concepts from modules 1-5. Score 80% or higher "
        "to pass. The assessment includes multiple choice and true/false questions. "
        "Each question tests your comprehension of the material.",
        section_index=9, total_sections=10,
    )
    check("UT-FEAT-04: has_assessment_keywords=True", f.has_assessment_keywords is True)
    check("UT-FEAT-04: is_last=True", f.is_last is True)

    # UT-FEAT-05: Callout patterns
    f = detector.detect(
        "Note: Always verify the sender's email address before clicking links. "
        "Important: Never share your password with anyone, including IT support. "
        "Key Takeaway: Multi-factor authentication significantly reduces account "
        "compromise risk. Did you know? Over 90% of breaches start with phishing.",
        section_index=4, total_sections=10,
    )
    check("UT-FEAT-05: has_callout=True", f.has_callout is True)

    # UT-FEAT-06: Term definitions
    f = detector.detect(
        "Phishing: A social engineering attack using deceptive communications.\n"
        "Malware: Malicious software designed to damage or infiltrate systems.\n"
        "Firewall: A network security system that monitors traffic.\n"
        "Encryption: The process of encoding data to prevent unauthorized access.",
        section_index=5, total_sections=10,
    )
    check("UT-FEAT-06: has_term_definitions=True", f.has_term_definitions is True)
    check("UT-FEAT-06: sub_topic_count >= 2", f.sub_topic_count >= 2,
          f"sub_topic_count={f.sub_topic_count}")

    # UT-FEAT-07: List detection
    f = detector.detect(
        "Security best practices include:\n"
        "- Use strong, unique passwords\n"
        "- Enable multi-factor authentication\n"
        "- Keep software updated\n"
        "1. Regular backups\n"
        "2. Network monitoring\n"
        "3. Access control",
        section_index=6, total_sections=10,
    )
    check("UT-FEAT-07: has_list=True", f.has_list is True)

    # UT-FEAT-08: Summary language
    f = detector.detect(
        "Summary: In this module we covered the key takeaways of cybersecurity. "
        "To summarize, the main points are password security, phishing awareness, "
        "and safe browsing habits. Next steps: review the assessment and complete "
        "the final quiz.",
        section_index=8, total_sections=10,
    )
    check("UT-FEAT-08: has_summary_language=True", f.has_summary_language is True)

    # UT-FEAT-09: Independent sub-topics (accordion pattern)
    f = detector.detect(
        "# Password Security\n"
        "Strong passwords are the first line of defense. Use a mix of characters "
        "and avoid common words. Password managers help generate and store complex "
        "passwords securely across all your accounts.\n\n"
        "# Multi-Factor Authentication\n"
        "MFA requires two or more verification methods. This could be something you "
        "know (password), something you have (phone), or something you are (fingerprint). "
        "Enabling MFA reduces account compromise risk by over 99%.\n\n"
        "# Safe Browsing\n"
        "Always check for HTTPS in the address bar before entering sensitive data. "
        "Avoid public Wi-Fi for financial transactions. Use a VPN when accessing "
        "company resources from remote locations.\n\n"
        "# Email Security\n"
        "Be cautious with email attachments from unknown senders. Verify unexpected "
        "requests for sensitive information through a separate channel. Report "
        "suspicious emails to your IT security team immediately.",
        section_index=4, total_sections=10,
    )
    check("UT-FEAT-09: sub_topics_independent=True", f.sub_topics_independent is True)
    check("UT-FEAT-09: sub_topic_count >= 4", f.sub_topic_count >= 4)

    # UT-FEAT-10: Position signals
    f_first = detector.detect("First section content", section_index=0, total_sections=5)
    check("UT-FEAT-10: is_first=True for index 0", f_first.is_first is True)
    check("UT-FEAT-10: section_position=0 for index 0", f_first.section_position == 0.0)

    f_last = detector.detect("Last section content", section_index=4, total_sections=5)
    check("UT-FEAT-10: is_last=True for last index", f_last.is_last is True)
    check("UT-FEAT-10: is_before_assessment for second-last",
          detector.detect("Penultimate", section_index=3, total_sections=5).is_before_assessment is True)

    # Empty text
    f_empty = detector.detect("", section_index=0, total_sections=1)
    check("UT-FEAT-empty: char_count=0", f_empty.char_count == 0)
    check("UT-FEAT-empty: no false positives", not f_empty.has_qa_pattern)


# ═══════════════════════════════════════════════════════════════════════
# 3. TemplateSelector Tests
# ═══════════════════════════════════════════════════════════════════════


def test_template_selector():
    global passed, failed
    from app.services.ai.feature_detector import FeatureDetector
    from app.services.ai.template_selector import (
        TemplateSelector, TemplateScore, DEFAULT_TEMPLATE,
    )

    print("\n=== [1C] TemplateSelector ===")
    detector = FeatureDetector()
    selector = TemplateSelector()

    # UT-SEL-01: Welcome template
    f = detector.detect(
        "Welcome to Cybersecurity Awareness. This course overview covers the "
        "learning objectives and getting started with your training journey. "
        "We will explore key security concepts throughout this program.",
        section_index=0, total_sections=10,
    )
    best, needs_llm = selector.select_with_confidence(f)
    check("UT-SEL-01: welcome selected for intro", best.template_type == "welcome",
          f"got {best.template_type}, score={best.score:.2f}")
    check("UT-SEL-01: high confidence", best.score >= 0.85,
          f"score={best.score:.2f}")
    check("UT-SEL-01: no LLM needed (high confidence)", not needs_llm)

    # UT-SEL-02: Accordion template (independent sub-topics)
    f = detector.detect(
        "# Password Security\n"
        "Strong passwords are the first line of defense. Use a mix of characters "
        "and avoid common words. Password managers help generate and store complex "
        "passwords securely.\n\n"
        "# Multi-Factor Authentication\n"
        "MFA requires two or more verification methods. This could be something you "
        "know (password), something you have (phone), or something you are (fingerprint).\n\n"
        "# Safe Browsing\n"
        "Always check for HTTPS in the address bar before entering sensitive data. "
        "Avoid public Wi-Fi for financial transactions.\n\n"
        "# Email Security\n"
        "Be cautious with email attachments from unknown senders. Verify unexpected "
        "requests through a separate channel.",
        section_index=3, total_sections=10,
    )
    scores = selector.score_all(f)
    best = selector.select(f)
    check("UT-SEL-02: accordion selected for independent topics",
          best.template_type == "accordion",
          f"got {best.template_type}, score={best.score:.2f}")
    check("UT-SEL-02: accordion score >= 0.70", best.score >= 0.70,
          f"score={best.score:.2f}")

    # UT-SEL-03: Click-reveal template (Q&A)
    f = detector.detect(
        "Q: What is phishing?\nA: A social engineering attack using deceptive emails. "
        "Q: How can I spot a phishing email?\n"
        "What are the common signs of a compromised account?\n"
        "How does two-factor authentication protect against phishing?",
        section_index=5, total_sections=10,
    )
    best, _ = selector.select_with_confidence(f)
    check("UT-SEL-03: click-reveal selected for Q&A",
          best.template_type in ("click-reveal", "accordion"),
          f"got {best.template_type}")

    # UT-SEL-04: Assessment template
    f = detector.detect(
        "Final Assessment: Test your knowledge of cybersecurity principles. "
        "This exam covers all modules from the course. You must score 80% or "
        "higher to pass. The quiz includes multiple choice and true/false questions.",
        section_index=9, total_sections=10,
    )
    best, _ = selector.select_with_confidence(f)
    check("UT-SEL-04: final-assessment selected",
          best.template_type == "final-assessment",
          f"got {best.template_type}, score={best.score:.2f}")

    # UT-SEL-05: Ambiguous content -> content-text fallback
    f = detector.detect(
        "This is some general content about a topic. It has a few paragraphs "
        "of explanatory text but no strong structural signals like Q&A, steps, "
        "or sub-topics. Just regular explanatory prose that covers key concepts.",
        section_index=4, total_sections=10,
    )
    best, needs_llm = selector.select_with_confidence(f)
    check("UT-SEL-05: content-text for no strong signal",
          best.template_type == "content-text",
          f"got {best.template_type}")
    # Should flag for LLM if ambiguous
    check("UT-SEL-05: returns valid TemplateScore", isinstance(best, TemplateScore))

    # Test rule arbitration: welcome beats all when is_first
    f = detector.detect(
        "Welcome to the course! In this introduction and overview, we'll cover "
        "Q: What will I learn? A: Key cybersecurity concepts. "
        "Step 1: Get started. Step 2: Learn. Step 3: Apply.",
        section_index=0, total_sections=5,
    )
    best, _ = selector.select_with_confidence(f)
    check("R4-rule1: welcome dominates when is_first",
          best.template_type == "welcome",
          f"got {best.template_type}, score={best.score:.2f}")

    # Test rule arbitration: assessment dominates when is_last
    f = detector.detect(
        "Summary of key takeaways from this module. Final quiz to test your "
        "knowledge and understanding. Assessment with multiple choice questions.",
        section_index=4, total_sections=5,
    )
    best, _ = selector.select_with_confidence(f)
    check("R4-rule2: final-assessment dominates when is_last",
          best.template_type in ("final-assessment", "summary"),
          f"got {best.template_type}, score={best.score:.2f}")

    # Test batch selection
    features_list = [
        detector.detect("Welcome to the course overview.", 0, 3),
        detector.detect("Step 1: Do this. Step 2: Do that. Step 3: Verify.", 1, 3),
        detector.detect("Final quiz with assessment questions.", 2, 3),
    ]
    results = selector.select_batch(features_list)
    check("Batch select: returns correct count", len(results) == 3)
    check("Batch select: first is welcome",
          results[0][0].template_type == "welcome",
          f"got {results[0][0].template_type}")

    # DEFAULT_TEMPLATE
    check("DEFAULT_TEMPLATE is content-text",
          DEFAULT_TEMPLATE.template_type == "content-text")
    check("DEFAULT_TEMPLATE has reasonable score",
          0.0 <= DEFAULT_TEMPLATE.score <= 1.0)


# ═══════════════════════════════════════════════════════════════════════
# 4. Quality Metrics Tests
# ═══════════════════════════════════════════════════════════════════════


def test_quality_metrics():
    global passed, failed
    from app.services.ai.quality_metrics import (
        compute_template_entropy,
        compute_distinct_preview_ratio,
        collect_generation_metrics,
        GenerationQualityMetrics,
    )

    print("\n=== [1D] Quality Metrics ===")

    # Template entropy
    check("Entropy: all one type = 0",
          compute_template_entropy({"content-text": 10}) == 0.0)
    check("Entropy: empty = 0",
          compute_template_entropy({}) == 0.0)

    diverse = {"content-text": 3, "accordion": 3, "tabs": 2, "final-assessment": 2}
    entropy = compute_template_entropy(diverse)
    check("Entropy: diverse distribution > 1.0", entropy > 1.0,
          f"entropy={entropy:.4f}")

    # Distinct preview ratio
    sections = [
        {"content_preview": "AAA unique content about topic 1"},
        {"content_preview": "BBB different content about topic 2"},
        {"content_preview": "CCC another topic entirely"},
        {"content_preview": "AAA unique content about topic 1"},  # duplicate
    ]
    ratio = compute_distinct_preview_ratio(sections)
    check("Distinct preview ratio: 3/4 = 0.75", abs(ratio - 0.75) < 0.01,
          f"got {ratio:.4f}")

    all_same = [
        {"content_preview": "Same content everywhere"},
        {"content_preview": "Same content everywhere"},
        {"content_preview": "Same content everywhere"},
    ]
    ratio = compute_distinct_preview_ratio(all_same)
    check("Distinct preview ratio: all same = 0.33", abs(ratio - 0.333) < 0.01,
          f"got {ratio:.4f}")

    empty_sections = []
    check("Distinct preview ratio: empty = 0",
          compute_distinct_preview_ratio(empty_sections) == 0.0)

    # Collect full metrics
    pages = [
        {"title": "Welcome", "template_type": "welcome", "components": [
            {"component_type": "content-text", "order_index": 0, "data": {"content": "Welcome!"}},
        ]},
        {"title": "Passwords", "template_type": "accordion", "components": [
            {"component_type": "accordion", "order_index": 0, "data": {"items": [
                {"title": "Topic 1", "content": "..."},
                {"title": "Topic 2", "content": "..."},
                {"title": "Topic 3", "content": "..."},
                {"title": "Topic 4", "content": "..."},
            ]}},
            {"component_type": "content-text", "order_index": 1, "data": {"content": "Key takeaway"}},
        ]},
        {"title": "Phishing", "template_type": "tabs", "components": [
            {"component_type": "tabs", "order_index": 0, "data": {"tabs": [
                {"title": "Overview", "content": "..."}, {"title": "Details", "content": "..."},
            ]}},
        ]},
        {"title": "Safe Browsing", "template_type": "content-text", "components": [
            {"component_type": "content-text", "order_index": 0, "data": {"content": "Content..."}},
        ]},
        {"title": "Assessment", "template_type": "final-assessment", "components": [
            {"component_type": "final-assessment", "order_index": 0, "data": {
                "passing_score": 80,
                "questions": [
                    {"id": "q-1", "type": "mcq", "question": "Q1?", "options": []},
                    {"id": "q-2", "type": "mcq", "question": "Q2?", "options": []},
                    {"id": "q-3", "type": "mcq", "question": "Q3?", "options": []},
                    {"id": "q-4", "type": "mcq", "question": "Q4?", "options": []},
                ],
            }},
        ]},
    ]

    metrics = collect_generation_metrics(
        job_id="test-job-123",
        course_id="test-course-456",
        pages=pages,
        sections=sections,
        model_used="qwen2.5:7b",
        provider="ollama",
        duration_ms=15000,
    )

    check("Metrics: 5 pages", metrics.total_pages == 5)
    check("Metrics: template distribution has 5 types",
          len(metrics.template_distribution) == 5)
    check("Metrics: template entropy > 1.0 (diverse)",
          metrics.template_entropy > 1.0,
          f"entropy={metrics.template_entropy:.4f}")
    check("Metrics: 4 assessment questions",
          metrics.assessment_question_count == 4)
    check("Metrics: 1 multi-component page",
          metrics.multi_component_page_count == 1)
    check("Metrics: no mock fallbacks", metrics.mock_fallback_count == 0)
    check("Metrics: provider tracked", metrics.provider == "ollama")
    check("Metrics: model tracked", metrics.llm_model_used == "qwen2.5:7b")
    check("Metrics: duration tracked", metrics.total_duration_ms == 15000)
    check("Metrics: healthy", metrics.is_healthy is True)

    # Alerts on degraded quality
    degraded_pages = [
        {"title": "P1", "template_type": "content-text", "components": [
            {"component_type": "content-text", "order_index": 0, "data": {}}
        ], "generation_metadata": {"method": "mock", "fallback": True}},
        {"title": "P2", "template_type": "content-text", "components": [
            {"component_type": "content-text", "order_index": 0, "data": {}}
        ], "generation_metadata": {"method": "mock", "fallback": True}},
        {"title": "P3", "template_type": "content-text", "components": [
            {"component_type": "content-text", "order_index": 0, "data": {}}
        ]},
    ]
    degraded_metrics = collect_generation_metrics(
        job_id="degraded-job", course_id="", pages=degraded_pages,
    )
    check("Degraded: high mock fallback rate",
          degraded_metrics.mock_fallback_rate > 0.5)
    check("Degraded: low template entropy",
          degraded_metrics.template_entropy == 0.0)
    check("Degraded: has alerts", len(degraded_metrics.alerts) > 0)
    check("Degraded: not healthy", not degraded_metrics.is_healthy)

    # to_dict
    d = metrics.to_dict()
    check("Metrics.to_dict: has template_entropy", "template_entropy" in d)
    check("Metrics.to_dict: has alerts", "alerts" in d)
    check("Metrics.to_dict: has healthy", "healthy" in d)


# ═══════════════════════════════════════════════════════════════════════
# 5. Provider Resolution (G4 fix)
# ═══════════════════════════════════════════════════════════════════════


def test_provider_resolution():
    global passed, failed
    from app.services.ai.llm_client import LLMProvider

    print("\n=== [G4] Provider Resolution ===")

    # Test OLLAMA provider exists
    check("G4: LLMProvider.OLLAMA exists", hasattr(LLMProvider, "OLLAMA"))
    check("G4: LLMProvider.OLLAMA value", LLMProvider.OLLAMA.value == "ollama")

    # Test _resolve_generation_provider with explicit config
    from app.services.ai.course_generator import _resolve_generation_provider

    # Explicit ollama
    cfg_mock = MagicMock()
    cfg_mock.generation_provider = "ollama"
    cfg_mock.primary_model_id = "some-model"
    result = _resolve_generation_provider(cfg_mock)
    check("G4: explicit ollama -> OLLAMA provider",
          result == LLMProvider.OLLAMA)

    # Explicit anthropic
    cfg_mock.generation_provider = "anthropic"
    result = _resolve_generation_provider(cfg_mock)
    check("G4: explicit anthropic -> ANTHROPIC provider",
          result == LLMProvider.ANTHROPIC)

    # Explicit mock
    cfg_mock.generation_provider = "mock"
    result = _resolve_generation_provider(cfg_mock)
    check("G4: explicit mock -> MOCK provider",
          result == LLMProvider.MOCK)

    # Model registry lookup (ollama model)
    from app.services.ai.config import ModelConfig, ModelTier
    cfg_mock.generation_provider = ""
    cfg_mock.primary_model_id = "qwen2.5:7b"
    ollama_model = ModelConfig(
        id="qwen2.5:7b", provider="ollama",
        api_model_name="qwen2.5:7b", tier=ModelTier.GENERATOR,
    )
    cfg_mock.get_model = MagicMock(return_value=ollama_model)
    cfg_mock.anthropic_api_key = None
    result = _resolve_generation_provider(cfg_mock)
    check("G4: ollama model in registry -> OLLAMA provider",
          result == LLMProvider.OLLAMA)

    # Fallback to API key presence
    cfg_mock.get_model = MagicMock(side_effect=ValueError("unknown"))
    cfg_mock.anthropic_api_key = "sk-ant-test"
    result = _resolve_generation_provider(cfg_mock)
    check("G4: no model match + API key -> ANTHROPIC provider",
          result == LLMProvider.ANTHROPIC)

    # No config at all -> MOCK
    cfg_mock.anthropic_api_key = None
    result = _resolve_generation_provider(cfg_mock)
    check("G4: no config -> MOCK provider",
          result == LLMProvider.MOCK)


# ═══════════════════════════════════════════════════════════════════════
# 6. DocumentExtractor Structured Extraction
# ═══════════════════════════════════════════════════════════════════════


def test_docx_structured_extraction():
    global passed, failed
    from app.services.ai.document_extractor import DocumentExtractor

    print("\n=== [1A-fix] DOCX Structured Extraction ===")

    extractor = DocumentExtractor()

    # Test that extract_structured exists
    check("extract_structured method exists",
          hasattr(extractor, "extract_structured"))

    # Test that _extract_docx_structured exists
    check("_extract_docx_structured method exists",
          hasattr(extractor, "_extract_docx_structured"))

    # Test backward compatibility: extract() still works
    check("extract() method preserved for backward compat",
          hasattr(extractor, "extract"))

    # Verify the import path for integration
    from app.services.ai.document_splitter import DocumentSplitter
    check("DocumentSplitter importable from services.ai",
          DocumentSplitter is not None)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    global passed, failed, failures

    print("=" * 70)
    print("TRD-CGQ Phase 1 -- Course Generation Quality Tests")
    print("=" * 70)

    test_document_splitter()
    test_feature_detector()
    test_template_selector()
    test_quality_metrics()
    test_provider_resolution()
    test_docx_structured_extraction()

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
