#!/usr/bin/env python3
"""Test regex on the actual content"""

import json
import re

course_data = {
    "courseId": "golf-training-001",
    "title": "Golf Rules & Etiquette Training",
    "description": "Learn the essential rules and etiquette of golf",
    "author": "Golf Coach",
    "version": "1.0",
    "templates": [
        {
            "id": "slide_1",
            "type": "welcome",
            "order": 0,
            "title": "Welcome to Golf Training",
            "data": {
                "content": "Welcome to the Golf Rules and Etiquette Training Course!",
                "imageUrl": "images/golf-course.jpg"
            }
        },
        {
            "id": "slide_2",
            "type": "content-text",
            "order": 1,
            "title": "Rule 1: Basic Etiquette",
            "data": {
                "heading": "Golf Etiquette - The Foundation",
                "content": "<p>Respect other golfers and the course.</p><p>Always be quiet when others are playing.</p>",
                "imageUrl": "images/etiquette.jpg"
            }
        }
    ]
}

# Create the JS string
js_content = f"""var courseData = {json.dumps(course_data, indent=2)};
"""

print("JS Content length:", len(js_content))
print("First 200 chars:")
print(js_content[:200])
print("\nLast 50 chars:")
print(repr(js_content[-50:]))

# Test patterns
pattern1 = r"(?:var|const|let)\s+\w+\s*=\s*(\{[\s\S]*?\})\s*[;,]"
matches = list(re.finditer(pattern1, js_content))
print(f"\n✓ Pattern 1 matches: {len(matches)}")

if matches:
    for m in matches:
        print(f"  Match span: {m.span()}")
        try:
            obj = json.loads(m.group(1))
            print(f"  ✓ Valid JSON: {list(obj.keys())}")
        except Exception as e:
            print(f"  ✗ Invalid JSON: {str(e)[:100]}")
else:
    print("  No matches!")
    print("\nTesting simpler patterns...")
    
    # Test if variable assignment is there
    if "var courseData" in js_content:
        print("  ✓ 'var courseData' found")
    
    # Test if opening brace is there
    if "{" in js_content:
        print("  ✓ Opening brace found")
    
    # Test if semicolon is there
    if ";" in js_content:
        print("  ✓ Semicolon found")
    
    # Try simpler pattern
    pattern_simple = r"var\s+\w+\s*=\s*\{[\s\S]*\};"
    matches_simple = list(re.finditer(pattern_simple, js_content))
    print(f"  Simple pattern matches: {len(matches_simple)}")
