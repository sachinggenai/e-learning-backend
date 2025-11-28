"""
Seed script for populating default template definitions.
Run this after migrating the database to add default templates.
"""

import asyncio
from datetime import datetime
from app.db.config import get_session
from app.models.persisted_course import TemplateDefinition
from app.repositories.template_definition_repo import (
    TemplateDefinitionRepository
)


# JSON Schema definitions for each template type
MCQ_SCHEMA = {
    "type": "object",
    "required": ["content", "questions"],
    "properties": {
        "content": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "question", "options"],
                "properties": {
                    "id": {"type": "string"},
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "required": ["id", "text", "isCorrect"],
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "isCorrect": {"type": "boolean"}
                            }
                        }
                    }
                }
            }
        }
    }
}

VIDEO_SCHEMA = {
    "type": "object",
    "required": ["content", "videoUrl"],
    "properties": {
        "content": {"type": "string"},
        "videoUrl": {"type": "string", "format": "uri"},
        "subtitle": {"type": "string"}
    }
}

TEXT_SCHEMA = {
    "type": "object",
    "required": ["content"],
    "properties": {
        "content": {"type": "string"},
        "subtitle": {"type": "string"}
    }
}

WELCOME_SCHEMA = {
    "type": "object",
    "required": ["content"],
    "properties": {
        "content": {"type": "string"},
        "subtitle": {"type": "string"}
    }
}

SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["content"],
    "properties": {
        "content": {"type": "string"},
        "subtitle": {"type": "string"}
    }
}

# Jinja2 render templates (simplified for now)
MCQ_RENDER = """<div class="template-mcq">
    <h2>{{ data.title }}</h2>
    <p>{{ data.content }}</p>
    {% for question in data.questions %}
    <div class="question">
        <h3>{{ question.question }}</h3>
        <div class="options">
            {% for option in question.options %}
            <label class="option">
                <input type="radio" name="q_{{ loop.index0 }}" 
                       value="{{ loop.index0 }}"
                       data-correct="{{ option.isCorrect }}">
                <span>{{ option.text }}</span>
            </label>
            {% endfor %}
        </div>
    </div>
    {% endfor %}
</div>"""

VIDEO_RENDER = """<div class="template-video">
    <h2>{{ data.title }}</h2>
    <video controls src="{{ data.videoUrl }}"></video>
    <p>{{ data.content }}</p>
</div>"""

TEXT_RENDER = """<div class="template-text">
    <h2>{{ data.title }}</h2>
    {% if data.subtitle %}<p class="subtitle">{{ data.subtitle }}</p>{% endif %}
    <div class="content">{{ data.content }}</div>
</div>"""

WELCOME_RENDER = """<div class="template-welcome">
    <h1>{{ data.title }}</h1>
    {% if data.subtitle %}<p class="subtitle">{{ data.subtitle }}</p>{% endif %}
    <div class="content">{{ data.content }}</div>
</div>"""

SUMMARY_RENDER = """<div class="template-summary">
    <h2>{{ data.title }}</h2>
    {% if data.subtitle %}<p class="subtitle">{{ data.subtitle }}</p>{% endif %}
    <div class="content">{{ data.content }}</div>
</div>"""


TEMPLATE_DEFINITIONS = [
    {
        "type_id": "mcq",
        "name": "Multiple Choice Question",
        "description": "Interactive quiz with multiple choice questions",
        "schema_definition": MCQ_SCHEMA,
        "render_template": MCQ_RENDER,
        "default_assets": [],
    },
    {
        "type_id": "content-video",
        "name": "Video Content",
        "description": "Video player with accompanying text",
        "schema_definition": VIDEO_SCHEMA,
        "render_template": VIDEO_RENDER,
        "default_assets": [],
    },
    {
        "type_id": "content-text",
        "name": "Text Content",
        "description": "Rich text content display",
        "schema_definition": TEXT_SCHEMA,
        "render_template": TEXT_RENDER,
        "default_assets": [],
    },
    {
        "type_id": "welcome",
        "name": "Welcome Screen",
        "description": "Course introduction and welcome message",
        "schema_definition": WELCOME_SCHEMA,
        "render_template": WELCOME_RENDER,
        "default_assets": [],
    },
    {
        "type_id": "summary",
        "name": "Summary Screen",
        "description": "Course summary and conclusion",
        "schema_definition": SUMMARY_SCHEMA,
        "render_template": SUMMARY_RENDER,
        "default_assets": [],
    },
]


async def seed_template_definitions():
    """Seed the database with default template definitions."""
    print("Starting template definitions seed...")
    
    async for session in get_session():
        repo = TemplateDefinitionRepository(session)
        
        for template_def in TEMPLATE_DEFINITIONS:
            # Check if already exists
            existing = await repo.get_by_type(template_def["type_id"])
            if existing:
                print(
                    f"  - Skipping {template_def['type_id']}: "
                    f"Already exists (version {existing.version})"
                )
                continue
            
            # Create new definition
            definition = TemplateDefinition(
                type_id=template_def["type_id"],
                version=1,
                name=template_def["name"],
                description=template_def["description"],
                schema_definition=template_def["schema_definition"],
                render_template=template_def["render_template"],
                default_assets=template_def["default_assets"],
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            
            await repo.create(definition)
            print(f"  + Created {template_def['type_id']} (version 1)")
        
        break  # Exit after first session
    
    print("Template definitions seed completed!")


if __name__ == "__main__":
    asyncio.run(seed_template_definitions())
