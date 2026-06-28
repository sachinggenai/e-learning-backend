"""CSA Full Pipeline — upload, LLM breakdown, generate, apply, export."""
import httpx, json, time, os

BASE = 'http://localhost:8000'
AUTH = {'Authorization': 'Bearer test-user-001'}
DOC = r'c:/Users/ADMIN/Downloads/SB2-Cybersecurity Awareness for the Modern Workplace.docx'

def check(step, ok, detail=''):
    print(f'  {"PASS" if ok else "FAIL"} | {step} {detail}')

print('='*65)
print('  CSA FULL PIPELINE - LLM Breakdown + Assessment Detection')
print('='*65)

# Step 1: Session
r = httpx.post(f'{BASE}/api/v1/ai/sessions', headers=AUTH, json={'course_id': 'COURSE-DEMO-001'})
sid = r.json().get('session',{}).get('sessionId','')
check('Session', r.status_code==201, sid[:20])

# Step 2: Upload
with open(DOC, 'rb') as f:
    r = httpx.post(f'{BASE}/api/v1/ai/ingestions', headers=AUTH, files={'file': f}, data={'session_id': sid}, timeout=60)
jid = r.json().get('job_id','')
secs = len(r.json().get('extracted_sections', r.json().get('extracted_sections',{}).get('plan',[])))
check('Upload', r.status_code==200, f'{jid[:20]}... {secs} sections')
time.sleep(2)

# Step 3: LLM-driven Breakdown
print()
print('--- LLM Breakdown (phi3:mini via MCP Gateway) ---')
r = httpx.post(f'{BASE}/api/v1/ai/ingestions/{jid}/propose-breakdown',
    headers=AUTH, json={'session_id': sid, 'body': '', 'max_pages': 20}, timeout=300)
plan = r.json().get('plan',[])
print(f'  Pages proposed: {len(plan)}')
templates = {}
for p in plan:
    t = p.get('suggested_template_type','?')
    title = p.get('proposed_title','?')[:60]
    rationale = p.get('rationale','')[:100]
    templates[t] = templates.get(t,0) + 1
    flag = '(LLM)' if t != '?' and 'mapped to' not in rationale else '(rule)'
    print(f'  [{t:18}] {title} {flag}')
    print(f'    {rationale}')

print(f'\n  Template distribution: {templates}')
check('Assessment detected', 'final-assessment' in templates, 'LLM found quiz/test content')

# Step 4: Review Plan
r = httpx.post(f'{BASE}/api/v1/ai/ingestions/{jid}/review-plan',
    headers=AUTH, json={'session_id': sid, 'action': 'approve'})
check('Review Plan', r.status_code==200, r.json().get('plan_status','?'))

# Step 5: Generate Course (REAL LLM via MCP)
print()
print('--- Generate Course (qwen2.5:7b via MCP Gateway) ---')
t0 = time.time()
r = httpx.post(f'{BASE}/api/v1/ai/generate-course',
    headers=AUTH, json={'import_job_id': jid, 'session_id': sid, 'use_llm': True}, timeout=600)
gen_time = time.time() - t0
gen = r.json()
pages = gen.get('generated_pages', gen.get('total_pages', 0))
check('Generate', r.status_code==200, f'{pages} pages in {gen_time:.0f}s')
for p in gen.get('pages',[]):
    print(f'    [{p.get("template_type","?")}] {p.get("title","?")[:60]} valid={p.get("validation_status","?")}')

# Check provenance
prov = gen.get('provenance', {})
if not prov:
    meta = gen.get('source_metadata',{}).get('generated_course',{}).get('provenance',{})
    prov = meta
if prov:
    print(f'\n  Provenance: model={prov.get("model","?")} provider={prov.get("provider","?")}')

# Step 6: Apply
r = httpx.post(f'{BASE}/api/v1/ai/generate-course/{jid}/apply',
    headers=AUTH, json={'session_id': sid})
c_id = r.json().get('course_id','?')
p_created = r.json().get('pages_created',0)
check('Apply', r.status_code==200, f'{c_id} {p_created} pages')
for p in r.json().get('pages',[]):
    print(f'    {p["page_id"][:20]}... [{p.get("template_type","?")}] {p["title"][:50]}')

# Step 7: Export
r = httpx.post(f'{BASE}/api/v1/export/scorm/{c_id}?format=scorm_1_2', headers=AUTH)
out = 'csa_course_v2.zip'
with open(out, 'wb') as f:
    f.write(r.content)
check('Export SCORM', r.status_code==200, f'{out} ({len(r.content)} bytes)')

print(f'\n{"="*65}')
print(f'  COMPLETE: {c_id} | {p_created} pages | {out}')
print(f'  Assessment: {"final-assessment" in templates} | Templates: {templates}')
print(f'  Generation: {pages} pages in {gen_time:.0f}s')
print(f'{"="*65}')
