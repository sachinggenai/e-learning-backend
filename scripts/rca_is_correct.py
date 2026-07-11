"""
RCA: Why isCorrect is always False in the assessment despite code fixes.

This script tests each layer independently to identify exactly where
the is_correct value is lost.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ai.marked_document_parser import (
    MarkedDocumentParser, MarkedDocument, MarkedPage,
    MarkedComponent, MarkedItem, ParseError,
    _item_to_dict, _item_metadata_to_dict, _component_to_dict, _component_from_dict,
)

print("=" * 70)
print("RCA: isCorrect propagation through the full pipeline")
print("=" * 70)

# ── Test data: minimal assessment with one correct option ──────────
TEST_PARAS = [
    {'text': '[PAGE: final-assessment | title: Quiz]'},
    {'text': '[COMPONENT: final-assessment | passing_score: 80]'},
    {'text': '[QUESTION: mcq | id: q1]'},
    {'text': 'Question text'},
    {'text': '[OPTION: a]Wrong A[/OPTION]'},
    {'text': '[OPTION: b | correct: true]Right B[/OPTION]'},
    {'text': '[OPTION: c]Wrong C[/OPTION]'},
    {'text': '[/QUESTION]'},
    {'text': '[/COMPONENT]'},
    {'text': '[/PAGE]'},
]

p = MarkedDocumentParser()

# ═══════════════════════════════════════════════════════════════════
# LAYER 1: Parser -&gt; MarkedItem.metadata.is_correct
# ═══════════════════════════════════════════════════════════════════
print("\n--- LAYER 1: Parser -&gt; MarkedItem.metadata ---")
doc = p.parse(TEST_PARAS)
q1 = [i for i in doc.pages[0].components[0].items if i.item_type == "question"][0]
children = q1.metadata.get("_children", [])
opts = [c for c in children if c.item_type == "option"]

print(f"  Question q1 has {len(opts)} options in _children")
for o in opts:
    ic = o.metadata.get("is_correct", "KEY MISSING")
    print(f"    [{o.title}] MarkedItem.metadata.is_correct = {ic}")

layer1_ok = any(o.metadata.get("is_correct") for o in opts)
print(f"  LAYER 1 RESULT: {'PASS' if layer1_ok else 'FAIL'}")

# ═══════════════════════════════════════════════════════════════════
# LAYER 2: to_dict() -&gt; serialized dict
# ═══════════════════════════════════════════════════════════════════
print("\n--- LAYER 2: MarkedDocument.to_dict() ---")
d = doc.to_dict()
q1_serialized = d["pages"][0]["components"][0]["items"][0]
children2 = q1_serialized.get("metadata", {}).get("_children", [])
opts2 = [c for c in children2 if c.get("item_type") == "option"]

print(f"  Serialized question has {len(opts2)} options in _children")
for o in opts2:
    ic = o.get("is_correct", "KEY MISSING")
    print(f"    [{o.get('title')}] serialized is_correct = {ic}")

layer2_ok = any(o.get("is_correct") for o in opts2)
print(f"  LAYER 2 RESULT: {'PASS' if layer2_ok else 'FAIL'}")

# Also check if is_correct is at top level vs nested
sample = opts2[0]
toplevel = "is_correct" in sample
nested = "is_correct" in sample.get("metadata", {})
print(f"  is_correct at TOP level: {toplevel}")
print(f"  is_correct in metadata: {nested}")

# ═══════════════════════════════════════════════════════════════════
# LAYER 3: JSON serialize -&gt; JSON deserialize
# ═══════════════════════════════════════════════════════════════════
print("\n--- LAYER 3: JSON round-trip ---")
json_str = json.dumps(d)
d3 = json.loads(json_str)
q1_json = d3["pages"][0]["components"][0]["items"][0]
children3 = q1_json.get("metadata", {}).get("_children", [])
opts3 = [c for c in children3 if c.get("item_type") == "option"]

print(f"  After JSON round-trip: {len(opts3)} options")
for o in opts3:
    ic = o.get("is_correct", "KEY MISSING")
    print(f"    [{o.get('title')}] is_correct = {ic}")

layer3_ok = any(o.get("is_correct") for o in opts3)
print(f"  LAYER 3 RESULT: {'PASS' if layer3_ok else 'FAIL'}")

# ═══════════════════════════════════════════════════════════════════
# LAYER 4: from_dict() -&gt; reconstructed MarkedItem
# ═══════════════════════════════════════════════════════════════════
print("\n--- LAYER 4: MarkedDocument.from_dict() ---")
doc4 = MarkedDocument.from_dict(d3)
q1_recon = [i for i in doc4.pages[0].components[0].items if i.item_type == "question"][0]
children4 = q1_recon.metadata.get("_children", [])
opts4 = [c for c in children4 if c.item_type == "option"]

print(f"  Reconstructed question has {len(opts4)} options")
for o in opts4:
    ic = o.metadata.get("is_correct", "KEY MISSING")
    print(f"    [{o.title}] MarkedItem.metadata.is_correct = {ic}")

layer4_ok = any(o.metadata.get("is_correct") for o in opts4)
print(f"  LAYER 4 RESULT: {'PASS' if layer4_ok else 'FAIL'}")

# ═══════════════════════════════════════════════════════════════════
# LAYER 5: _serialize_item -&gt; second serialization (as in propose_breakdown)
# ═══════════════════════════════════════════════════════════════════
print("\n--- LAYER 5: _serialize_item (from _convert_marked_to_plan) ---")
from app.routers.ai_ingestion import _convert_marked_to_plan
plan = _convert_marked_to_plan(doc4)
mp = plan[0].get("_marked_page", {})
comp_s = mp.get("components", [{}])[0]
q_s = comp_s.get("items", [{}])[0]
children5 = q_s.get("metadata", {}).get("_children", [])
opts5 = [c for c in children5 if c.get("item_type") == "option"]

print(f"  _serialize_item produced {len(opts5)} options")
for o in opts5:
    ic = o.get("is_correct", "KEY MISSING")
    print(f"    [{o.get('title')}] is_correct = {ic}")

layer5_ok = any(o.get("is_correct") for o in opts5)
print(f"  LAYER 5 RESULT: {'PASS' if layer5_ok else 'FAIL'}")

# ═══════════════════════════════════════════════════════════════════
# LAYER 6: _generate_from_marked_data -&gt; final component output
# ═══════════════════════════════════════════════════════════════════
print("\n--- LAYER 6: CourseGenerator._generate_from_marked_data ---")
from app.services.ai.course_generator import CourseGenerator
cg = CourseGenerator.__new__(CourseGenerator)
cg.db = None
cg.use_llm = False

# Simulate what start_generation does (after RC1 fix)
page_dict = {
    'title': mp['title'],
    'template_type': mp['template_type'],
    'order': mp['order'],
    'source_excerpt': mp.get('raw_content', ''),
    '_marked_page': mp,
}
result = cg._generate_page_content(page_dict, {}, 0)
data6 = result.get('components', [{}])[0].get('data', {})
questions6 = data6.get('questions', [])

print(f"  Generator produced {len(questions6)} questions")
for q in questions6:
    for o in q.get('options', []):
        print(f"    [{o.get('id')}] isCorrect = {o.get('isCorrect')}")

layer6_ok = any(o.get('isCorrect') for q in questions6 for o in q.get('options', []))
print(f"  LAYER 6 RESULT: {'PASS' if layer6_ok else 'FAIL'}")

# ═══════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
results = [layer1_ok, layer2_ok, layer3_ok, layer4_ok, layer5_ok, layer6_ok]
all_ok = all(results)
print(f"  Layer 1 (Parser):              {'PASS' if results[0] else 'FAIL'}")
print(f"  Layer 2 (to_dict):             {'PASS' if results[1] else 'FAIL'}")
print(f"  Layer 3 (JSON round-trip):     {'PASS' if results[2] else 'FAIL'}")
print(f"  Layer 4 (from_dict):           {'PASS' if results[3] else 'FAIL'}")
print(f"  Layer 5 (_serialize_item):     {'PASS' if results[4] else 'FAIL'}")
print(f"  Layer 6 (generator output):    {'PASS' if results[5] else 'FAIL'}")
print(f"  OVERALL: {'ALL LAYERS PASS' if all_ok else 'FAILURES DETECTED'}")
print(f"{'='*70}")
