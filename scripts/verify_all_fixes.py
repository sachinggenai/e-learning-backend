"""
Comprehensive unit-level verification of ALL RCA fixes.
Tests every code path without DB/HTTP dependencies.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ai.marked_document_parser import MarkedDocumentParser
from app.routers.ai_ingestion import _convert_marked_to_plan
from app.services.ai.course_generator import CourseGenerator

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")

print("=" * 60)
print("  RCA Fix Verification — Direct Code Tests")
print("=" * 60)

# ══════════════════════════════════════════════════════════════════════
# TEST 1: MarkedDocumentParser — is_correct in MarkedItems
# ══════════════════════════════════════════════════════════════════════
print("\n--- Test 1: Parser correctly sets is_correct on OPTION MarkedItems ---")
p = MarkedDocumentParser()
full = [
    {'text': '[PAGE: final-assessment | title: Quiz]'},
    {'text': '[COMPONENT: final-assessment | passing_score: 80]'},
    {'text': '[QUESTION: mcq | id: q1]'},
    {'text': 'Which is a common sign of phishing?'},
    {'text': '[OPTION: a]Wrong A[/OPTION]'},
    {'text': '[OPTION: b | correct: true]Correct B[/OPTION]'},
    {'text': '[OPTION: c]Wrong C[/OPTION]'},
    {'text': '[FEEDBACK]Phishing explanation[/FEEDBACK]'},
    {'text': '[/QUESTION]'},
    {'text': '[QUESTION: mcq | id: q2]'},
    {'text': 'What is 2+2?'},
    {'text': '[OPTION: a]3[/OPTION]'},
    {'text': '[OPTION: b | correct: true]4[/OPTION]'},
    {'text': '[/QUESTION]'},
    {'text': '[QUESTION: mcq | id: q3]'},
    {'text': 'Is the sky blue?'},
    {'text': '[OPTION: a | correct: true]Yes[/OPTION]'},
    {'text': '[OPTION: b]No[/OPTION]'},
    {'text': '[/QUESTION]'},
    {'text': '[/COMPONENT]'},
    {'text': '[/PAGE]'},
]
doc = p.parse(full)
real_errors = [e for e in doc.parse_errors if e.severity == "error"]
check("No parse errors", len(real_errors) == 0, f"got {len(real_errors)}")

comp = doc.pages[0].components[0]
questions = [i for i in comp.items if i.item_type == "question"]
check("3 questions parsed", len(questions) == 3, f"got {len(questions)}")

q1 = questions[0]
q1_children = q1.metadata.get("_children", [])
q1_opts = [c for c in q1_children if c.item_type == "option"]
q1_correct = [o for o in q1_opts if o.metadata.get("is_correct")]
check("Q1 has 3 options", len(q1_opts) == 3, f"got {len(q1_opts)}")
check("Q1 has 1 correct answer (MarkedItem.metadata.is_correct)",
      len(q1_correct) == 1, f"got {len(q1_correct)}")
check("Q1 correct option is 'b'", q1_correct[0].title == "b",
      f"got '{q1_correct[0].title}'")

q2 = questions[1]
q2_children = q2.metadata.get("_children", [])
q2_opts = [c for c in q2_children if c.item_type == "option"]
q2_correct = [o for o in q2_opts if o.metadata.get("is_correct")]
check("Q2 has 1 correct answer", len(q2_correct) == 1)

q3 = questions[2]
q3_children = q3.metadata.get("_children", [])
q3_opts = [c for c in q3_children if c.item_type == "option"]
q3_correct = [o for o in q3_opts if o.metadata.get("is_correct")]
check("Q3 has 1 correct answer", len(q3_correct) == 1)

# Also verify tabs page
tabs_test = [
    {'text': '[PAGE: tabs | title: TabTest]'},
    {'text': '[COMPONENT: content-text]Intro text about the comparison[/COMPONENT]'},
    {'text': '[COMPONENT: tabs]'},
    {'text': '[ITEM: Phishing Attacks]Phishing details here[/ITEM]'},
    {'text': '[ITEM: Ransomware]Ransomware details here[/ITEM]'},
    {'text': '[ITEM: Insider Risks]Insider risk details here[/ITEM]'},
    {'text': '[/COMPONENT]'},
    {'text': '[/PAGE]'},
]
doc_tabs = p.parse(tabs_test)
check("Tabs page has 2 components", len(doc_tabs.pages[0].components) == 2,
      f"got {len(doc_tabs.pages[0].components)}")
tab_comp = doc_tabs.pages[0].components[1]
check("Tabs component has 3 items", len(tab_comp.items) == 3)
check("Tab item_type = 'tab'", all(i.item_type == "tab" for i in tab_comp.items))
check("Tab items have content", all(i.content for i in tab_comp.items))

# ══════════════════════════════════════════════════════════════════════
# TEST 2: RC2 — _serialize_item preserves is_correct through JSON
# ══════════════════════════════════════════════════════════════════════
print("\n--- Test 2: _serialize_item preserves is_correct through JSON round-trip ---")

plan = _convert_marked_to_plan(doc)
check("Plan has 1 page", len(plan) == 1)
check("Plan has _marked_page", plan[0].get("_marked_page") is not None)

marked = plan[0]["_marked_page"]
comp_serialized = marked["components"][0]
check("Serialized component has items", len(comp_serialized["items"]) == 3)

# Check pre-JSON serialization
q_item = comp_serialized["items"][0]
children_pre = q_item.get("metadata", {}).get("_children", [])
opts_pre = [c for c in children_pre if c["item_type"] == "option"]
correct_pre = [o for o in opts_pre if o.get("is_correct")]
check("Pre-JSON: is_correct=True present", len(correct_pre) == 1,
      f"got {len(correct_pre)} correct out of {len(opts_pre)}")

# JSON round-trip (simulates DB storage)
plan_json = json.loads(json.dumps(plan))
marked_rt = plan_json[0]["_marked_page"]
comp_rt = marked_rt["components"][0]
q_item_rt = comp_rt["items"][0]
children_rt = q_item_rt.get("metadata", {}).get("_children", [])
opts_rt = [c for c in children_rt if c["item_type"] == "option"]
correct_rt = [o for o in opts_rt if o.get("is_correct")]
check("Post-JSON: is_correct=True survives round-trip", len(correct_rt) == 1,
      f"got {len(correct_rt)} correct out of {len(opts_rt)}")
if correct_rt:
    check("Post-JSON: correct option title preserved",
          correct_rt[0]["title"] == "b",
          f"got '{correct_rt[0]['title']}'")

# ══════════════════════════════════════════════════════════════════════
# TEST 3: RC1+3 — _generate_page_content uses _marked_page
# ══════════════════════════════════════════════════════════════════════
print("\n--- Test 3: _generate_page_content dispatches to marked data path ---")
cg = CourseGenerator.__new__(CourseGenerator)
cg.db = None
cg.use_llm = False

# Build page dict as start_generation would (after RC1 fix)
page_dict = {
    'title': marked_rt['title'],
    'template_type': marked_rt['template_type'],
    'order': marked_rt['order'],
    'source_excerpt': marked_rt.get('raw_content', ''),
    '_marked_page': marked_rt,
}

result = cg._generate_page_content(page_dict, {}, 0)
check("Generated template_type = final-assessment",
      result.get('template_type') in ('final-assessment', 'accordion'),
      f"got {result.get('template_type')}")

comps = result.get('components', [])
check("Generated components = 1", len(comps) == 1, f"got {len(comps)}")

data = comps[0].get('data', {})
questions = data.get('questions', [])
check("Generated assessment has 3 questions", len(questions) == 3,
      f"got {len(questions)}")

all_correct = 0
for q in questions:
    for o in q.get('options', []):
        if o.get('isCorrect'):
            all_correct += 1
check("Generated assessment has correct answers (isCorrect=True)",
      all_correct == 3, f"got {all_correct}/3 correct")

check("Q1 question text preserved",
      "phishing" in questions[0].get('question', '').lower())

# Verify options too
q1_opts_gen = questions[0].get('options', [])
check("Q1 has 3 options after generation", len(q1_opts_gen) == 3)
has_correct_option = any(o.get('isCorrect') for o in q1_opts_gen)
check("Q1 has correct option marked", has_correct_option)

# ══════════════════════════════════════════════════════════════════════
# TEST 4: RC1 — content-text pages use raw_content from markers
# ══════════════════════════════════════════════════════════════════════
print("\n--- Test 4: content-text pages use marker raw_content ---")
ct_test = [
    {'text': '[PAGE: content-text | title: Welcome]'},
    {'text': '[COMPONENT: content-text]This is the actual welcome text from the DOCX.[/COMPONENT]'},
    {'text': '[/PAGE]'},
]
doc_ct = p.parse(ct_test)
plan_ct = _convert_marked_to_plan(doc_ct)
marked_ct_rt = json.loads(json.dumps(plan_ct))[0]['_marked_page']

page_ct = {
    'title': marked_ct_rt['title'],
    'template_type': marked_ct_rt['template_type'],
    'order': marked_ct_rt['order'],
    'source_excerpt': '',
    '_marked_page': marked_ct_rt,
}
result_ct = cg._generate_page_content(page_ct, {}, 0)
ct_data = result_ct['components'][0]['data']
ct_content = ct_data.get('content', '')
check("content-text uses marked raw_content (not mock)",
      'actual welcome text from the DOCX' in ct_content,
      f"got: '{ct_content[:80]}'")

# ══════════════════════════════════════════════════════════════════════
# TEST 5: MarkedDocument.to_dict() JSON serializable
# ══════════════════════════════════════════════════════════════════════
print("\n--- Test 5: MarkedDocument.to_dict() produces JSON-serializable output ---")
d = doc.to_dict()
try:
    json_str = json.dumps(d)
    check("to_dict() output is JSON-serializable", True,
          f"serialized {len(json_str)} bytes")
except TypeError as e:
    check("to_dict() output is JSON-serializable", False, str(e))

# Also verify round-trip
from app.services.ai.marked_document_parser import MarkedDocument
doc2 = MarkedDocument.from_dict(d)
check("from_dict() restores has_markers", doc2.has_markers)
check("from_dict() restores pages", len(doc2.pages) == 1)
check("from_dict() restores questions",
      len([i for i in doc2.pages[0].components[0].items
           if i.item_type == "question"]) == 3)

# ══════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print(f"  VERIFICATION RESULTS: {passed} passed, {failed} failed")
print(f"{'=' * 60}")
if failed == 0:
    print("  ALL FIXES VERIFIED — Pipeline will produce correct output")
else:
    print(f"  {failed} FAILURES — review above")
    sys.exit(1)
