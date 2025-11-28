"""
Test script for Dynamic Template System
Verifies registry loading and sanitization
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.scorm.registries import registry
from app.services.scorm.sanitizers import DynamicSanitizer


async def test_registry():
    """Test template registry loading."""
    print("\n=== Testing Template Registry ===")
    
    # Preload cache
    await registry.preload_cache()
    
    # Test each template
    templates = ['mcq', 'content-text', 'content-video', 'welcome', 'summary']
    for template_key in templates:
        try:
            definition = await registry.get(template_key)
            print(f"✓ Loaded: {template_key}")
            print(f"  - Renderer: {definition.renderer_class}")
            print(f"  - Fields: {len(definition.field_schema)}")
            print(f"  - SCORM Type: {definition.scorm_behavior.interaction_type}")
        except Exception as e:
            print(f"✗ Failed to load {template_key}: {e}")
            return False
    
    return True


async def test_sanitizer():
    """Test dynamic sanitizer."""
    print("\n=== Testing Dynamic Sanitizer ===")
    
    sanitizer = DynamicSanitizer()
    
    # Test MCQ sanitization
    mcq_data = {
        "content": "Test question",
        "questions": [
            {
                "id": "q1",
                "question": "What is 2+2?",
                "options": [
                    {"id": "a", "text": "3", "isCorrect": False},
                    {"id": "b", "text": "4", "isCorrect": True}
                ]
            }
        ]
    }
    
    try:
        sanitized = await sanitizer.sanitize_template_data('mcq', mcq_data)
        print("✓ MCQ sanitization successful")
        print(f"  - Questions: {len(sanitized['questions'])}")
        print(f"  - Options preserved: {len(sanitized['questions'][0]['options'])}")
        
        # Verify isCorrect is preserved as boolean
        is_correct_value = sanitized['questions'][0]['options'][1]['isCorrect']
        if isinstance(is_correct_value, bool):
            print("  - Boolean preserved: ✓")
        else:
            print(f"  - Boolean lost: ✗ (type: {type(is_correct_value)})")
            return False
            
    except Exception as e:
        print(f"✗ MCQ sanitization failed: {e}")
        return False
    
    # Test content-text sanitization
    content_data = {
        "content": "<p>Hello <script>alert('xss')</script> World</p>",
        "subtitle": "Test subtitle"
    }
    
    try:
        sanitized = await sanitizer.sanitize_template_data(
            'content-text',
            content_data
        )
        print("✓ Content-text sanitization successful")
        if '<script>' not in sanitized['content']:
            print("  - XSS removed: ✓")
        else:
            print("  - XSS NOT removed: ✗")
            return False
            
    except Exception as e:
        print(f"✗ Content-text sanitization failed: {e}")
        return False
    
    return True


async def main():
    """Run all tests."""
    print("Dynamic Template System - Integration Test")
    print("=" * 50)
    
    success = True
    
    # Test registry
    if not await test_registry():
        success = False
    
    # Test sanitizer
    if not await test_sanitizer():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
