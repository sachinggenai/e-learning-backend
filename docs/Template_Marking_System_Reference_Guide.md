# Template Marking System — Developer Reference Guide

> **Version:** 1.0  
> **Date:** 2026-07-11  
> **Audience:** Content Authors, Instructional Designers, Developers preparing storyboard DOCX files for AI course generation

---

## 1. What Is Template Marking?

Template marking lets you **annotate your storyboard DOCX** with simple text markers that tell the AI exactly how to structure your e-learning course. Instead of letting the AI guess page boundaries, template types, and component hierarchy (which fails ~30-40% of the time for complex documents), you insert markers like `[PAGE: tabs]` and `[COMPONENT: accordion]` directly into your DOCX paragraphs.

**When markers are present:** The AI uses your structure exactly as specified — 100% deterministic, zero guesswork.

**When markers are absent:** The AI falls back to its existing heuristic/LLM pipeline — your existing workflow is completely unaffected.

---

## 2. Quick Start — 5-Minute Template

Copy this template into a new DOCX file, replace the placeholder text with your content, and upload:

```
[PAGE: welcome | title: Course Introduction]
[COMPONENT: content-text]
Welcome to [Your Course Name]. This course covers...

By the end of this course, you will be able to:
- Learning objective 1
- Learning objective 2
- Learning objective 3
[/COMPONENT]
[/PAGE]

[PAGE: content-text | title: Module 1 — Core Concepts]
[COMPONENT: content-text]
[Your main content here — explanations, definitions, examples.]
Aim for 200-2000 characters per content-text component.
[/COMPONENT]
[/PAGE]

[PAGE: accordion | title: Module 2 — Detailed Breakdown]
[COMPONENT: content-text]
Brief introduction to the topics covered in this section.
[/COMPONENT]
[COMPONENT: accordion]
[ITEM: Topic 1 — Key Concept]
Detailed explanation of the first key concept. Include examples and practical applications.
[/ITEM]
[ITEM: Topic 2 — Advanced Details]
Deeper dive into the second topic. Add context, caveats, and real-world scenarios.
[/ITEM]
[ITEM: Topic 3 — Edge Cases]
Cover important edge cases and common pitfalls to avoid.
[/ITEM]
[/COMPONENT]
[/PAGE]

[PAGE: tabs | title: Module 3 — Comparing Approaches]
[COMPONENT: content-text]
Introduction explaining what we are comparing and why it matters.
[/COMPONENT]
[COMPONENT: tabs]
[ITEM: Approach A — Traditional Method]
Description of the traditional approach, its advantages and limitations.
[/ITEM]
[ITEM: Approach B — Modern Method]
Description of the modern approach and how it improves on the traditional method.
[/ITEM]
[ITEM: Approach C — Hybrid Method]
How combining elements of both approaches can yield optimal results.
[/ITEM]
[/COMPONENT]
[/PAGE]

[PAGE: final-assessment | title: Knowledge Check]
[COMPONENT: final-assessment | passing_score: 80]
[QUESTION: mcq | id: q1]
What is the primary benefit of [key concept from Module 1]?
[OPTION: a]Increased speed[/OPTION]
[OPTION: b | correct: true]Improved accuracy and reliability[/OPTION]
[OPTION: c]Reduced cost[/OPTION]
[OPTION: d]Simpler implementation[/OPTION]
[FEEDBACK]The primary benefit is improved accuracy and reliability, as discussed in Module 1.[/FEEDBACK]
[/QUESTION]

[QUESTION: mcq | id: q2]
Which approach combines traditional and modern methods?
[OPTION: a]Approach A[/OPTION]
[OPTION: b]Approach B[/OPTION]
[OPTION: c | correct: true]Approach C — Hybrid Method[/OPTION]
[OPTION: d]None of the above[/OPTION]
[FEEDBACK]Approach C combines elements of both traditional and modern methods for optimal results.[/FEEDBACK]
[/QUESTION]

[QUESTION: mcq | id: q3]
True or False: The modern method completely replaces the traditional method.
[OPTION: a]True[/OPTION]
[OPTION: b | correct: true]False — each method has appropriate use cases[/OPTION]
[FEEDBACK]Each method has its strengths. The hybrid approach often works best.[/FEEDBACK]
[/QUESTION]
[/COMPONENT]
[/PAGE]

[PAGE: summary | title: Key Takeaways]
[COMPONENT: content-text]
## Summary

In this course, you learned:
- Key takeaway 1
- Key takeaway 2
- Key takeaway 3

## Next Steps
Apply these concepts to your daily work. Review the modules as needed.
[/COMPONENT]
[/PAGE]
```

---

## 3. Complete Marker Reference

### 3.1 Marker Syntax Rules

**Every marker follows these rules:**

1. **Each marker occupies its own DOCX paragraph** — a paragraph is a single line of text in Word (created by pressing Enter)
2. **Opening markers:** `[TYPE: value | attribute: value]`
3. **Closing markers:** `[/TYPE]`
4. **All marker keywords are UPPERCASE and case-sensitive** — `[PAGE:]` works, `[page:]` does NOT
5. **Template/component type values are lowercase** — `[PAGE: content-text]` works, `[PAGE: Content-Text]` does NOT
6. **Pipe character `|` separates attributes** — `| title: My Title | order: 2`
7. **Content goes between open and close markers** — on separate paragraphs

### 3.2 Opening and Closing

```
[PAGE: content-text | title: Page Title]    ← Opening marker (one paragraph)
This is the content text.                    ← Content (one or more paragraphs)
More content here.                           ← More content
[/PAGE]                                      ← Closing marker (one paragraph)
```

### 3.3 Inline Short Form

For simple items, you can put content and close on the same line as the open:

```
[ITEM: Tab Title]The tab content goes here[/ITEM]
```

This is equivalent to:

```
[ITEM: Tab Title]
The tab content goes here
[/ITEM]
```

### 3.4 Escaping Literal Brackets

If your content contains text that looks like a marker, escape it with a backslash:

```
\ [PAGE: this is not a marker — it's literal text]
```

---

## 4. Marker Types — Complete Catalog

### 4.1 PAGE Marker

Defines a single page in your course. Every marked document must have at least one PAGE.

```
[PAGE: <template_type> | title: <page_title> | order: <n>]
    ...components and content...
[/PAGE]
```

| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `template_type` | **YES** | — | Positional (first value). See §5 for allowed types. |
| `title` | No | `"Page N"` | Display title for the page. Must be unique across the course. |
| `order` | No | Sequential | Page ordering (0, 1, 2...). Lower numbers appear first. |

**Example:**
```
[PAGE: tabs | title: Comparing Security Models | order: 3]
```

### 4.2 COMPONENT Marker

Defines a structural component within a page. Pages can have multiple components.

```
[COMPONENT: <component_type> | order: <n> | passing_score: <0-100>]
    ...items and content...
[/COMPONENT]
```

| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `component_type` | **YES** | — | Positional. See §6 for allowed types. |
| `order` | No | Sequential | Order within the page. |
| `passing_score` | No | `80` | Only for `final-assessment`. Score 0-100. |
| `visibility` | No | `visible` | `visible` or `hidden`. |

**Example:**
```
[COMPONENT: accordion]
[ITEM: First Item]Content for first item[/ITEM]
[ITEM: Second Item]Content for second item[/ITEM]
[/COMPONENT]
```

### 4.3 ITEM Marker

Defines an item within a component (tabs, accordion panels, click-reveal items).

```
[ITEM: <item_title> | order: <n>]
    ...item content...
[/ITEM]
```

| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `item_title` | **YES** | — | Positional. Display title for this item. |
| `order` | No | Sequential | Order within the parent component. |

**Allowed counts by parent component:**

| Parent Component | Min Items | Max Items |
|-----------------|-----------|-----------|
| `tabs` | 2 | 6 |
| `accordion` | 2 | 20 |
| `click-reveal` | 2 | 10 |

**Example:**
```
[ITEM: Spear Phishing]
Spear phishing is a targeted attack directed at specific individuals or organizations.
Attackers research their victims and craft personalized messages.
[/ITEM]
```

### 4.4 QUESTION Marker

Defines an assessment question within a `final-assessment` component.

```
[QUESTION: <question_type> | id: <question_id>]
    ...question text...
    [OPTION: <id> | correct: true]
        ...option text...
    [/OPTION]
    [FEEDBACK]
        ...feedback text...
    [/FEEDBACK]
[/QUESTION]
```

| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `question_type` | **YES** | — | Positional. `mcq`, `true-false`, or `multi-select`. |
| `id` | No | `q-N` | Unique question identifier. |

**Allowed question types:**

| Type | Options Required | Correct Answers |
|------|-----------------|-----------------|
| `mcq` | 2-10 | Exactly 1 |
| `true-false` | Exactly 2 | Exactly 1 |
| `multi-select` | 2-10 | At least 1 |

**Minimums per assessment:** 3 questions per `final-assessment` component, maximum 50.

**Example:**
```
[QUESTION: mcq | id: phishing_q1]
Which of the following is NOT a type of phishing attack?
[OPTION: a]Spear Phishing[/OPTION]
[OPTION: b]Whaling[/OPTION]
[OPTION: c | correct: true]Firewalling[/OPTION]
[OPTION: d]Clone Phishing[/OPTION]
[FEEDBACK]Firewalling is a network security measure, not a phishing technique.[/FEEDBACK]
[/QUESTION]
```

### 4.5 OPTION Marker

Defines an answer option within a question. Must appear inside a `[QUESTION]` block.

```
[OPTION: <id> | correct: <true|false>]
    ...option text...
[/OPTION]
```

| Attribute | Required | Default | Description |
|-----------|----------|---------|-------------|
| `id` | **YES** | — | Positional. Short identifier (`a`, `b`, `c`... or `1`, `2`, `3`...). |
| `correct` | No | `false` | `true` for the correct answer, `false` otherwise. |

**Example:**
```
[OPTION: b | correct: true]Paris is the capital of France.[/OPTION]
```

### 4.6 FEEDBACK Marker

Provides explanation text shown after a learner answers a question. Optional.

```
[FEEDBACK]
    ...explanation text...
[/FEEDBACK]
```

**No attributes.** Must appear inside a `[QUESTION]` block.

**Example:**
```
[FEEDBACK]
Paris has been the capital of France since the 10th century.
It is the most populous city in France.
[/FEEDBACK]
```

### 4.7 Comment Marker

Add notes to yourself that the parser ignores. Useful for tracking TODOs, version info, or author notes.

```
[//]: # (This is a comment — it will not appear in the course)
```

---

## 5. Allowed Template Types (for PAGE)

| Template Type | Description | Use When |
|--------------|-------------|----------|
| `content-text` | Rich text page with headings, paragraphs, lists | Explanatory content, definitions, theory |
| `tabs` | Tabbed layout, 2-6 tabs | Comparing options, organizing subtopics |
| `accordion` | Expandable panels, 2-20 items | FAQs, detailed breakdowns, progressive disclosure |
| `click-reveal` | Interactive reveal elements, 2-10 items | Discovery learning, key points, scenario exploration |
| `final-assessment` | Graded quiz, 3-50 questions | End-of-course tests, knowledge checks |
| `welcome` | Course introduction page | First page of the course |
| `summary` | Section or course summary | Last page of a section or course |

---

## 6. Allowed Component Types (for COMPONENT)

| Component Type | Requires | Description |
|---------------|----------|-------------|
| `content-text` | Text content between markers or inline | Body text |
| `tabs` | 2-6 `[ITEM]` children | Tabbed interface |
| `accordion` | 2-20 `[ITEM]` children | Expandable sections |
| `click-reveal` | 2-10 `[ITEM]` children | Click-to-reveal |
| `final-assessment` | 3-50 `[QUESTION]` children | Quiz/assessment |

---

## 7. Common Course Patterns

### Pattern A: Simple Explanatory Course

```
[PAGE: welcome | title: Welcome]
  [COMPONENT: content-text]...[/COMPONENT]
[/PAGE]
[PAGE: content-text | title: Topic 1]
  [COMPONENT: content-text]...[/COMPONENT]
[/PAGE]
[PAGE: content-text | title: Topic 2]
  [COMPONENT: content-text]...[/COMPONENT]
[/PAGE]
[PAGE: summary | title: Summary]
  [COMPONENT: content-text]...[/COMPONENT]
[/PAGE]
```

### Pattern B: Detailed Breakdown Course

Each module has an intro paragraph + accordion with subtopics:

```
[PAGE: accordion | title: Module 1 — Core Topics]
[COMPONENT: content-text]
Brief module introduction.
[/COMPONENT]
[COMPONENT: accordion]
[ITEM: Subtopic 1]Detailed explanation...[/ITEM]
[ITEM: Subtopic 2]Detailed explanation...[/ITEM]
[ITEM: Subtopic 3]Detailed explanation...[/ITEM]
[/COMPONENT]
[/PAGE]
```

### Pattern C: Comparison Course

Use tabs to compare approaches side-by-side:

```
[PAGE: tabs | title: Comparing Solutions]
[COMPONENT: content-text]
Introduction to the comparison.
[/COMPONENT]
[COMPONENT: tabs]
[ITEM: Solution A — Overview]Details about Solution A...[/ITEM]
[ITEM: Solution B — Overview]Details about Solution B...[/ITEM]
[ITEM: Solution C — Overview]Details about Solution C...[/ITEM]
[/COMPONENT]
[/PAGE]
```

### Pattern D: Full Course With Assessment

```
[PAGE: welcome | title: Welcome]...[/PAGE]
[PAGE: content-text | title: Introduction]...[/PAGE]
[PAGE: accordion | title: Core Concepts]...[/PAGE]
[PAGE: tabs | title: Practical Applications]...[/PAGE]
[PAGE: final-assessment | title: Knowledge Check]...[/PAGE]
[PAGE: summary | title: Key Takeaways]...[/PAGE]
```

### Pattern E: Multi-Component Page

A single page with intro text + accordion + key takeaway:

```
[PAGE: accordion | title: Cybersecurity Threats]
[COMPONENT: content-text]
This module covers the most common cybersecurity threats facing modern organizations.
Understanding these threats is the first step toward effective defense.
[/COMPONENT]
[COMPONENT: accordion]
[ITEM: Phishing Attacks]Social engineering attacks that trick users...[/ITEM]
[ITEM: Ransomware]Malware that encrypts data and demands payment...[/ITEM]
[ITEM: DDoS Attacks]Overwhelming servers with traffic to cause outages...[/ITEM]
[ITEM: Insider Threats]Security risks originating from within the organization...[/ITEM]
[/COMPONENT]
[/PAGE]
```

---

## 8. Error Codes Quick Reference

If your markers have issues, the system returns an error with a code. Here's what each means:

| Code | Severity | What Went Wrong | How To Fix |
|------|----------|-----------------|------------|
| `UNCLOSED_MARKER` | Error | You opened a `[PAGE:]` or `[COMPONENT:]` but forgot to close it | Add the matching `[/TYPE]` at the end of the block |
| `INVALID_TEMPLATE_TYPE` | Error | You used a template type that doesn't exist | Use one of: `content-text`, `tabs`, `accordion`, `click-reveal`, `final-assessment`, `welcome`, `summary` |
| `INVALID_COMPONENT_TYPE` | Error | You used a component type that doesn't exist | Use one of: `content-text`, `tabs`, `accordion`, `click-reveal`, `final-assessment` |
| `INVALID_QUESTION_TYPE` | Error | Question type not recognized | Use `mcq`, `true-false`, or `multi-select` |
| `NESTING_VIOLATION` | Error | A marker is inside the wrong parent | Check §4 — e.g., `[ITEM]` must be inside `[COMPONENT]` |
| `MISSING_CORRECT_ANSWER` | Error | A question has no option marked `correct: true` | Add `correct: true` to exactly one option per question |
| `MISMATCHED_CLOSE` | Error | Close marker doesn't match open marker | `[PAGE: ...]` must close with `[/PAGE]`, not `[/COMPONENT]` |
| `UNEXPECTED_CLOSE` | Error | A close marker with no matching open | Remove the stray `[/TYPE]` |
| `MAX_NESTING_EXCEEDED` | Error | Too many levels of nesting | Maximum 4 levels: PAGE > COMPONENT > QUESTION > OPTION |
| `DUPLICATE_PAGE_TITLE` | Warning | Two pages have the same title | Give each page a unique title |
| `EMPTY_COMPONENT` | Warning | A component has no content | Add text or items, or remove the empty component |
| `EMPTY_PAGE` | Warning | A page has no components | Add at least one `[COMPONENT]` to the page |
| `TOO_FEW_QUESTIONS` | Warning | Assessment has < 3 questions | Add more questions (minimum 3) |
| `TOO_FEW_OPTIONS` | Warning | Question has < 2 options | Add more options (minimum 2) |
| `TOO_MANY_ITEMS` | Warning | Too many items in a component | Reduce tabs to ≤6, accordion to ≤20, click-reveal to ≤10 |

---

## 9. Best Practices

### DO

- **Place each marker on its own DOCX paragraph** — one line in Word = one paragraph
- **Use descriptive page titles** — they appear in the course navigation
- **Keep content-text between 200-2000 characters** — short enough to read, long enough to be meaningful
- **Include at least 3 questions per assessment** — fewer triggers a warning
- **Always mark exactly one correct answer per question** — use `| correct: true`
- **Add FEEDBACK to each question** — it helps learners understand why answers are right or wrong
- **Use comments for TODOs** — `[//]: # (TODO: add 2 more questions)`
- **Test your marked DOCX on a small course first** — upload a 2-3 page test before marking a 50-page course

### DON'T

- **Don't put multiple markers on the same paragraph** — `[PAGE: tabs][COMPONENT: tabs]` won't work; use separate paragraphs
- **Don't use unsupported template types** — stick to the 7 allowed types
- **Don't forget closing markers** — every `[PAGE:]` needs `[/PAGE]`, every `[COMPONENT:]` needs `[/COMPONENT]`
- **Don't overlap pages** — close `[/PAGE]` before opening the next `[PAGE:]`
- **Don't nest more than 4 levels deep** — PAGE > COMPONENT > QUESTION > OPTION is the maximum
- **Don't skip the assessment** — courses without assessments generate a warning

---

## 10. Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| "No markers detected" | Template type is misspelled or wrong case | Check exact spelling: `content-text` not `Content-Text` |
| "Unclosed marker" error | Missing `[/PAGE]` or `[/COMPONENT]` | Add the closing marker at the end of the block |
| "Nesting violation" | `[ITEM]` placed directly inside `[PAGE]` | Wrap items in a `[COMPONENT: accordion]` first |
| "Invalid template type" | Used an unsupported type like `video` | Use `content-text` instead |
| "Too few questions" | Assessment has < 3 questions | Add more `[QUESTION]` blocks |
| "Missing correct answer" | No option has `correct: true` | Mark exactly one option as correct |
| Assessment page has no questions | Questions are inside wrong component | Ensure questions are inside `[COMPONENT: final-assessment]` |
| Content appears on wrong page | Page boundaries are misplaced | Check `[/PAGE]` placement |

---

## 11. Configuration

The Template Marking System is controlled by these environment variables (set in `.env`):

```bash
# Enable template marking (default: false)
AI_TEMPLATE_MARKING_ENABLED=true

# Strict mode: reject uploads without markers (default: false)
AI_TEMPLATE_MARKING_STRICT_MODE=false

# Maximum nesting depth (default: 4)
AI_TEMPLATE_MARKING_MAX_NESTING=4

# Maximum pages per marked document (default: 50)
AI_TEMPLATE_MARKING_MAX_PAGES=50
```

**To enable marking:** Ensure `AI_TEMPLATE_MARKING_ENABLED=true` is set in your `.env` file.

**When disabled (default):** Markers in your DOCX are treated as regular text. The existing AI pipeline handles the document normally.

---

## Appendix A: Marker Cheat Sheet

```
┌─────────────────────────────────────────────────────────────┐
│                     MARKER CHEAT SHEET                       │
├─────────────────────────────────────────────────────────────┤
│ PAGE:                                                       │
│   [PAGE: <type> | title: <title> | order: <n>]             │
│   [/PAGE]                                                   │
│                                                             │
│ COMPONENT:                                                  │
│   [COMPONENT: <type> | order: <n>]                         │
│   [/COMPONENT]                                              │
│                                                             │
│ ITEM:                                                       │
│   [ITEM: <title> | order: <n>]...[/ITEM]                   │
│                                                             │
│ QUESTION:                                                   │
│   [QUESTION: <mcq|true-false|multi-select> | id: <id>]     │
│   [/QUESTION]                                               │
│                                                             │
│ OPTION:                                                     │
│   [OPTION: <id> | correct: <true|false>]...[/OPTION]       │
│                                                             │
│ FEEDBACK:                                                   │
│   [FEEDBACK]...[/FEEDBACK]                                  │
│                                                             │
│ COMMENT:                                                    │
│   [//]: # (comment text)                                    │
├─────────────────────────────────────────────────────────────┤
│ TEMPLATE TYPES:                                             │
│   content-text | tabs | accordion | click-reveal           │
│   final-assessment | welcome | summary                      │
├─────────────────────────────────────────────────────────────┤
│ COMPONENT TYPES:                                            │
│   content-text | tabs | accordion | click-reveal           │
│   final-assessment                                          │
├─────────────────────────────────────────────────────────────┤
│ QUESTION TYPES:                                             │
│   mcq | true-false | multi-select                           │
├─────────────────────────────────────────────────────────────┤
│ COUNTS:                                                     │
│   tabs: 2-6 items    accordion: 2-20 items                 │
│   click-reveal: 2-10 items   assessment: 3-50 questions    │
│   mcq options: 2-10   correct answers: exactly 1           │
└─────────────────────────────────────────────────────────────┘
```

---

*Reference Guide — Template Marking System v1.0*
