"""End-to-end Flow 10/11 + SCORM export test with all RCA fixes."""
import requests, json, os, sys, time

BASE = "http://localhost:8000/api/v1"
H = {"Authorization": "Bearer test-user-001"}
ORIG_FP = r"C:\Users\ADMIN\Downloads\Cybersecurity_Course_Template_Markers.docx"
CID = f"E2E-FIX-{int(time.time())}"
EXPORT_PATH = f"C:/Users/ADMIN/e-learning-backend/exports/{CID}_scorm.zip"

# Create a UNIQUE copy to defeat file-hash dedup
FP = f"C:/Users/ADMIN/Downloads/test_unique_{int(time.time())}.docx"
with open(ORIG_FP, "rb") as src:
    content = src.read()
content += f"\n[//]: # (unique-{time.time()})".encode("utf-8")
with open(FP, "wb") as dst:
    dst.write(content)
print(f"Unique file: {FP}")

PASS = 0
FAIL = 0
def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")

print(f"Course ID: {CID}\n")

# 1. CREATE COURSE
print("1. Create Course")
r = requests.post(f"{BASE}/courses", json={
    "courseId": CID, "title": "Cybersecurity (E2E Fix Test)",
    "description": "End-to-end verification", "status": "draft"
}, headers=H)
check("Course created", r.status_code == 201, f"got {r.status_code}: {r.text[:100]}")
if r.status_code != 201: sys.exit(1)

# 2. CREATE SESSION
print("\n2. Create Session")
r = requests.post(f"{BASE}/ai/sessions", json={"course_id": CID}, headers=H)
check("Session created", r.status_code == 201, f"got {r.status_code}")
sid = r.json()["session"]["sessionId"]

# 3. UPLOAD MARKED DOCX
print("\n3. Upload Marked DOCX")
with open(FP, "rb") as f:
    r = requests.post(f"{BASE}/ai/ingestions", headers=H,
        files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"session_id": sid, "course_id": CID})
check("Upload OK", r.status_code == 200, f"got {r.status_code}")
jd = r.json()
jid = jd["job_id"]
meta = jd.get("source_metadata", {}) or {}
ms = meta.get("marker_status", "?")
check("marker_status=parsed", ms == "parsed", f"got {ms}")
md = meta.get("marked_document", {}) or {}
check("7 marked pages", len(md.get("pages", [])) == 7, f"got {len(md.get('pages', []))}")
check("0 parse errors", md.get("parse_error_count", -1) == 0)

# 4. PROPOSE BREAKDOWN
print("\n4. Propose Breakdown")
r = requests.post(f"{BASE}/ai/ingestions/{jid}/propose-breakdown",
    json={"session_id": sid, "job_id": jid, "max_pages": 50}, headers=H)
check("Breakdown OK", r.status_code == 200)
bd = r.json()
check("marker_mode=True", bd.get("marker_mode") == True, f"got {bd.get('marker_mode')}")

# Verify _marked_page has is_correct
plan = bd.get("plan", [])
for p in plan:
    mp = p.get("_marked_page", {})
    for c in mp.get("components", []):
        if c.get("component_type") == "final-assessment":
            first_q = c.get("items", [{}])[0]
            children = first_q.get("metadata", {}).get("_children", [])
            has_correct = any(ch.get("is_correct") for ch in children)
            check("Plan: assessment has is_correct=True", has_correct,
                  f"got {[ch.get('is_correct') for ch in children[:5]]}")

# 5. REVIEW PLAN
print("\n5. Review Plan")
r = requests.post(f"{BASE}/ai/ingestions/{jid}/review-plan",
    json={"session_id": sid, "job_id": jid, "approved": True, "modifications": []}, headers=H)
check("Plan approved", r.json().get("plan_status") == "approved")

# 6. GENERATE COURSE
print("\n6. Generate Course")
r = requests.post(f"{BASE}/ai/generate-course", json={
    "import_job_id": jid, "course_id": CID,
    "options": {"course_title": "Cybersecurity Awareness for the Modern Workplace"}
}, headers=H)
check("Generate OK", r.status_code == 200)
gen = r.json()
check("7 pages", gen.get("generated_pages") == 7)
check("0 validation errors", gen.get("validation", {}).get("errors", 0) == 0)

# 7. APPLY COURSE
print("\n7. Apply Course")
r = requests.post(f"{BASE}/ai/generate-course/{jid}/apply", headers=H)
check("Apply OK", r.status_code == 200)
ap = r.json()
check("7 pages created", ap.get("pages_created") == 7)

# 8. VERIFY COURSE DATA
print("\n8. Verify Course Data")
r = requests.get(f"{BASE}/courses/{CID}", headers=H)
pages = r.json().get("pages", [])
check("7 pages in DB", len(pages) == 7, f"got {len(pages)}")

for pg in pages:
    ttype = pg.get("layout", {}).get("templateType", "?")
    comps = pg.get("components", [])
    for c in comps:
        data = c.get("data", {})

        # Check assessment
        if ttype == "final-assessment" or c.get("component_type") == "final-assessment":
            questions = data.get("questions", [])
            correct = sum(1 for q in questions for o in q.get("options", []) if o.get("isCorrect"))
            total = sum(len(q.get("options", [])) for q in questions)
            check(f"Assessment: correct answers present ({correct}/{total})",
                  correct > 0, f"got {correct}/{total}")
            if questions:
                print(f"  Q1: {questions[0]['question'][:80]}")
                for o in questions[0].get("options", [])[:4]:
                    print(f"    [{o['id']}] correct={o.get('isCorrect')}")

        # Check tabs
        if ttype == "tabs":
            tabs = data.get("tabs", [])
            if tabs:
                check(f"Tabs: real titles (not mock)",
                      not any(t.get("title") in ("Overview", "Details", "Examples") for t in tabs),
                      f"got {[t.get('title','')[:30] for t in tabs]}")
                print(f"  Tab titles: {[t.get('title','')[:40] for t in tabs]}")

        # Check accordion/click-reveal
        if ttype in ("accordion",):
            items = data.get("items", [])
            if items:
                check(f"Accordion: real items (not mock)",
                      not any(i.get("title") in ("Overview", "Key Details", "Summary") for i in items),
                      f"got {[i.get('title','')[:30] for i in items]}")
                print(f"  Item titles: {[i.get('title','')[:40] for i in items]}")

# 9. SCORM EXPORT
print("\n9. SCORM Export")
r = requests.post(f"{BASE}/export/scorm/{CID}",
    json={"format": "scorm_1_2", "includeMedia": True}, headers=H)
check("SCORM export OK", r.status_code == 200,
      f"got {r.status_code}: {r.text[:200]}")

if r.status_code == 200:
    os.makedirs(os.path.dirname(EXPORT_PATH), exist_ok=True)
    with open(EXPORT_PATH, "wb") as f:
        f.write(r.content)
    print(f"  Saved: {EXPORT_PATH} ({len(r.content)/1024:.1f} KB)")

# SUMMARY
print(f"\n{'='*60}")
print(f"  E2E RESULTS: {PASS} passed, {FAIL} failed")
print(f"  SCORM: {EXPORT_PATH}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
