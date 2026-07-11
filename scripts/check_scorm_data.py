"""Extract and examine SCORM course_data.js from the exported ZIP."""
import zipfile, json, sys, os, glob

import glob
# Find the latest E2E export
exports = sorted(glob.glob(r"C:\Users\ADMIN\e-learning-backend\exports\E2E-FIX-*.zip"),
                 key=os.path.getmtime, reverse=True)
if not exports:
    print("No E2E exports found!")
    sys.exit(1)
ZIP_PATH = exports[0]
print(f"Reading: {os.path.basename(ZIP_PATH)}")

with zipfile.ZipFile(ZIP_PATH) as z:
    raw = z.read("course_data.js").decode("utf-8")
    # Extract the JSON object from the JS assignment
    prefix = "var courseData = "
    start = raw.index(prefix) + len(prefix)
    # Find the end of the JSON object by matching braces
    depth = 0
    end = start
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    json_str = raw[start:end]
    data = json.loads(json_str)

templates = data.get("templates", [])
print(f"Total templates: {len(templates)}")

for t in templates:
    ttype = t.get("type", "?")
    title = t.get("title", "?")[:60]
    order = t.get("order", -1)
    page_id = t.get("pageId", "?")
    comp_data = t.get("data", {})

    print(f"\n[{order}] {ttype}: {title}")
    print(f"    pageId: {page_id}")

    if ttype == "tabs":
        tabs = comp_data.get("tabs", [])
        print(f"    tabs count: {len(tabs)}")
        for tab in tabs:
            print(f"      - {tab.get('title','?')[:50]}")
            content = tab.get("content", "")
            print(f"        content: {content[:80]}...")

    elif ttype == "accordion":
        panels = comp_data.get("panels") or comp_data.get("items") or []
        print(f"    panels/items: {len(panels)}")
        for p in panels:
            title = p.get('title', '?')[:50]
            content = p.get('content') or p.get('body', '')
            print(f"      - {title}")
            print(f"        content: {content[:120]}...")

    elif ttype == "content-text":
        content = comp_data.get("content", "")
        print(f"    content: {content[:150]}...")

    elif ttype == "final-assessment":
        questions = comp_data.get("questions", [])
        print(f"    questions: {len(questions)}")
        if questions:
            q1 = questions[0]
            print(f"    Q1: {q1.get('question','')[:80]}")
            for o in q1.get("options", []):
                print(f"      [{o.get('id')}] correct={o.get('isCorrect')} text={o.get('text','')[:40]}")
