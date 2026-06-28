"""Debug LLM breakdown JSON field names."""
import httpx, json

prompt = """You are an instructional design expert. Create page breakdown. Return ONLY JSON array with fields: title, template_type, rationale, source_section_ids, order.

Available templates: content-text, tabs, accordion, click-reveal, final-assessment.

SECTIONS:
[{
  "heading": "Welcome to Cybersecurity",
  "content": "Introduction to cybersecurity awareness course."
},{
  "heading": "Phishing Attacks",
  "content": "How phishing works and how to prevent it."
},{
  "heading": "Final Assessment",
  "content": "Test your knowledge. 10 multiple choice questions about phishing, malware, and password security."
}]

Return ONLY: [{"title": "...", "template_type": "...", "rationale": "...", "source_section_ids": [0], "order": 0}]"""

r = httpx.post('http://localhost:8004/v1/chat/completions',
    json={'model': 'phi3:mini', 'messages': [{'role': 'user', 'content': prompt}],
          'max_tokens': 1000, 'temperature': 0.3}, timeout=60)

content = r.json()['choices'][0]['message']['content']
print("=== RAW LLM ===")
print(content[:800])

# Parse
if '```json' in content:
    content = content.split('```json')[1].split('```')[0]
elif '```' in content:
    content = content.split('```')[1].split('```')[0]
if '[' in content:
    content = content[content.index('['):content.rindex(']') + 1]

plan = json.loads(content)
print(f"\n=== PARSED: {len(plan)} pages ===")
for p in plan:
    print(f"  Keys: {list(p.keys())}")
    print(f"  Title: {p.get('title', p.get('proposed_title', 'MISSING'))}")
    print(f"  Template: {p.get('template_type', p.get('suggested_template_type', 'MISSING'))}")
    print(f"  Rationale: {str(p.get('rationale', p.get('reason', 'MISSING')))[:80]}")
    print()
