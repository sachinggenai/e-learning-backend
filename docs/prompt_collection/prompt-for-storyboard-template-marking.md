# Prompt for Storyboard Template Marking

> **Purpose:** Given to any LLM to annotate raw e-learning storyboard content with Template Marking System markers before uploading to the AI course generation pipeline.
> **Templates Covered:** Text Content, Tabs, Accordion, Click & Reveal, Final Assessment
> **Date:** 2026-07-11

---

## LLM Prompt: Mark Course Content with Template Markers

```
You are an instructional design expert who converts raw e-learning storyboard
content into a machine-readable marked format. Your output will be uploaded to
an AI course generation system that requires specific template markers.

## YOUR TASK

Take the raw course content provided below and annotate it with template markers
using the EXACT syntax specified. Do NOT change the educational content — only
add the structural markers around it.

## MARKER SYNTAX RULES — MUST FOLLOW EXACTLY

### Rule 1: Every marker goes on its OWN paragraph (line in Word)
Each [PAGE:], [COMPONENT:], [ITEM:], etc. must be on a separate line.
Never put two markers on the same line.

### Rule 2: Every open marker MUST have a matching close marker
[PAGE: ...] needs [/PAGE]
[COMPONENT: ...] needs [/COMPONENT]
[ITEM: ...] needs [/ITEM]
[QUESTION: ...] needs [/QUESTION]
[OPTION: ...] needs [/OPTION]
[FEEDBACK] needs [/FEEDBACK]

### Rule 3: Case-sensitive keywords
All marker keywords are UPPERCASE: PAGE, COMPONENT, ITEM, QUESTION, OPTION, FEEDBACK
All template type values are lowercase: tabs, accordion, content-text, etc.

## FIVE TEMPLATE TYPES — When to Use Each

### 1. TEXT CONTENT (content-text)
Use for: Explanations, definitions, theory, narrative content, introductions, summaries.
Content should be 200-2000 characters.

[PAGE: content-text | title: Descriptive Page Title]
[COMPONENT: content-text]
Your explanatory content here — paragraphs, bullet points, definitions.
Aim for clear, instructional prose suitable for e-learning.
[/COMPONENT]
[/PAGE]

### 2. TABS (tabs)
Use for: Comparing 2-6 options/approaches/methods side-by-side. Each tab is a
parallel, independent topic that the learner can switch between.
MUST contain 2-6 [ITEM] blocks.

[PAGE: tabs | title: Page Title]
[COMPONENT: content-text]
Brief introduction explaining what we're comparing and why it matters
[/COMPONENT]
[COMPONENT: tabs]
[ITEM: Tab 1 Title]
Content for the first tab — explain the first option/approach
[/ITEM]
[ITEM: Tab 2 Title]
Content for the second tab — explain the second option/approach
[/ITEM]
[/COMPONENT]
[/PAGE]

### 3. ACCORDION (accordion)
Use for: Detailed breakdowns of 2-20 subtopics, FAQs, progressive disclosure
where each item expands to reveal more detail. Items should be self-contained
— each can be read independently.
MUST contain 2-20 [ITEM] blocks.

[PAGE: accordion | title: Page Title]
[COMPONENT: content-text]
Brief introduction to the topics covered in this section
[/COMPONENT]
[COMPONENT: accordion]
[ITEM: Topic 1 — Clear Title]
Detailed explanation of the first topic with examples and context
[/ITEM]
[ITEM: Topic 2 — Clear Title]
Detailed explanation of the second topic
[/ITEM]
[/COMPONENT]
[/PAGE]

### 4. CLICK AND REVEAL (click-reveal)
Use for: Discovery learning, key point reveals, scenario exploration, Q&A pairs.
Content is hidden until the learner clicks. Good for "think about it first,
then reveal the answer" patterns.
MUST contain 2-10 [ITEM] blocks.

[PAGE: click-reveal | title: Page Title]
[COMPONENT: content-text]
Instructions: Click each item to reveal the answer or detail.
[/COMPONENT]
[COMPONENT: click-reveal]
[ITEM: Question or Prompt 1]
The revealed answer, explanation, or detail
[/ITEM]
[ITEM: Question or Prompt 2]
The revealed answer, explanation, or detail
[/ITEM]
[/COMPONENT]
[/PAGE]

### 5. FINAL ASSESSMENT (final-assessment)
Use for: End-of-module or end-of-course knowledge checks, quizzes, tests.
MUST contain 3-50 [QUESTION] blocks. Each question MUST have:
- 2-10 [OPTION] blocks (at least 2)
- Exactly ONE option marked | correct: true
- Optional [FEEDBACK] explaining the answer

[PAGE: final-assessment | title: Knowledge Check]
[COMPONENT: final-assessment | passing_score: 80]
[QUESTION: mcq | id: q1]
Write your question stem here?
[OPTION: a]First wrong answer[/OPTION]
[OPTION: b | correct: true]The correct answer[/OPTION]
[OPTION: c]Another wrong answer[/OPTION]
[OPTION: d]A fourth wrong answer[/OPTION]
[FEEDBACK]
Explanation of why the correct answer is right, and why the others are wrong.
Reference back to the relevant module content.
[/FEEDBACK]
[/QUESTION]
[QUESTION: mcq | id: q2]
... (repeat for at least 3 total questions)
[/QUESTION]
[/COMPONENT]
[/PAGE]

## PAGE STRUCTURE RULES

1. **First page should be welcome or content-text** — introduce the course
2. **Last page should be summary** — recap key takeaways
3. **Assessment comes after all content pages** — before the summary
4. **Every page must have at least one [COMPONENT]**
5. **Multi-component pages are allowed** — e.g., content-text intro + accordion

## DECISION GUIDE — Which template for which content?

| Content Pattern | Use Template | Why |
|----------------|-------------|-----|
| Single topic, narrative explanation | content-text | Linear reading flow |
| 2-6 parallel/comparable topics | tabs | Side-by-side comparison |
| 3-20 self-contained subtopics, FAQs | accordion | Progressive disclosure |
| "Guess first, then see answer" | click-reveal | Discovery/interactive learning |
| Quiz, test, knowledge check | final-assessment | Graded evaluation |
| Course introduction | content-text or welcome | Orientation |
| Course conclusion | summary | Recap |

## ESCAPING

If the original content contains text that looks like a marker (e.g., "[SOURCE]"),
put a backslash before it: \[SOURCE]

## COMMENTS

You may add comments for the author using: [//]: # (your comment here)
Comments are invisible to the parser.

## RAW COURSE CONTENT TO MARK UP

[PASTE YOUR RAW STORYBOARD/CONTENT HERE]
```

---

## How to Use This Prompt

1. **Copy the entire prompt** from the code block above
2. **Paste your raw course storyboard** at the bottom where it says `[PASTE YOUR RAW STORYBOARD/CONTENT HERE]`
3. **Send to any LLM** (Claude, ChatGPT, DeepSeek, etc.)
4. **Take the LLM's output** (which will be your content wrapped in markers) and paste it into a DOCX file
5. **Upload the DOCX** through the AI course creation pipeline (Flow 10/11)

The LLM will return the original content with `[PAGE: ...]`, `[COMPONENT: ...]`, `[ITEM: ...]` markers inserted at the correct positions, choosing the appropriate template type for each section based on the decision guide.

---

## Related Documents

- [Template Marking System Reference Guide](../Template_Marking_System_Reference_Guide.md) — Complete marker syntax and pattern library
- [FRD — Template Marking System](../FRD_Template_Marking_System.md) — Functional requirements
- [TRD — Template Marking System](../TRD_Template_Marking_System.md) — Technical implementation (with evidence)
- [Intent of Work & AI Prompts](../Template_Marking_System_Intent_of_Work_and_AI_Prompts.md) — Original analysis and approach
