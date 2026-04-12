"""Builtin template definitions used when the template store is unavailable."""
from __future__ import annotations

from typing import Optional


_BUILTIN_TEMPLATES = [
    {
        "id": "builtin-template-intro",
        "templateId": "template_intro_001",
        "type": "introduction",
        "title": "Course Introduction",
        "rating": 4.7,
        "usage_count": 156,
        "data": {
            "content": [
                {
                    "id": "course_title",
                    "name": "courseTitle",
                    "type": "text",
                    "label": "Course Title",
                    "required": True,
                    "placeholder": "Enter course title",
                }
            ],
            "description": "Welcome page with course overview and objectives",
        },
    },
    {
        "id": "builtin-template-lab",
        "templateId": "template_lab_001",
        "type": "lab",
        "title": "Virtual Lab Setup",
        "rating": 4.5,
        "usage_count": 89,
        "data": {
            "content": [
                {
                    "id": "lab_name",
                    "name": "labName",
                    "type": "text",
                    "label": "Lab Name",
                    "required": True,
                }
            ],
            "description": "Interactive lab setup with equipment selection",
        },
    },
    {
        "id": "builtin-template-assessment",
        "templateId": "template_assessment_001",
        "type": "assessment",
        "title": "Quiz Assessment",
        "rating": 4.3,
        "usage_count": 234,
        "data": {
            "content": [
                {
                    "id": "quiz_title",
                    "name": "quizTitle",
                    "type": "text",
                    "label": "Quiz Title",
                    "required": True,
                }
            ],
            "description": "Multiple choice quiz with automatic grading",
        },
    },
]


def build_builtin_template_picker_payload(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "rating",
) -> dict:
    """Return builtin template data in the API's frontend format."""
    templates = list(_BUILTIN_TEMPLATES)

    normalized_category = category if category and category != "all" else None
    if normalized_category:
        templates = [
            template
            for template in templates
            if template["type"] == normalized_category
        ]

    if search:
        search_lower = search.lower()
        templates = [
            template
            for template in templates
            if search_lower in template["title"].lower()
            or search_lower in template["data"]["description"].lower()
        ]

    if sort_by == "usage":
        templates.sort(
            key=lambda template: template["usage_count"],
            reverse=True,
        )
    else:
        templates.sort(key=lambda template: template["rating"], reverse=True)

    categories = sorted({template["type"] for template in _BUILTIN_TEMPLATES})
    frontend_templates = []
    for index, template in enumerate(templates):
        frontend_templates.append(
            {
                "id": template["id"],
                "templateId": template["templateId"],
                "type": template["type"],
                "title": template["title"],
                "order": index,
                "data": template["data"],
            }
        )

    return {
        "templates": frontend_templates,
        "categories": categories,
        "total_count": len(frontend_templates),
    }