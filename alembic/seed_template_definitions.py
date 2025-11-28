"""
Helper functions for template definition seed data.
"""
import json
import hashlib


def compute_schema_signature(fields):
    """Compute deterministic SHA-256 hash of field schema."""
    field_data = [{"name": f["name"], "type": f["type"]} for f in fields]
    canonical = json.dumps(field_data, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_mcq_definition():
    """Get MCQ template definition."""
    fields = [
        {
            "name": "questions",
            "type": "list",
            "sanitize_strategy": "preserve_structure",
            "required": True
        },
        {
            "name": "content",
            "type": "text",
            "sanitize_strategy": "text",
            "required": False
        }
    ]
    
    return {
        "id": "mcq",
        "type_key": "mcq",
        "schema_signature": compute_schema_signature(fields),
        "field_schema_json": json.dumps(fields),
        "render_config_json": json.dumps({
            "component_type": "mcq",
            "nested_fields": {
                "questions": {
                    "type": "list",
                    "item_schema": {
                        "question": {"type": "text", "sanitize": "text"},
                        "options": {
                            "type": "list",
                            "item_schema": {
                                "text": {"type": "text", "sanitize": "text"},
                                "isCorrect": {
                                    "type": "boolean",
                                    "sanitize": "none"
                                }
                            }
                        }
                    }
                }
            }
        }),
        "sanitize_rules_json": json.dumps({
            "questions": "preserve_structure",
            "content": "text"
        }),
        "scorm_behavior_json": json.dumps({
            "interaction_type": "choice",
            "reports_score": True,
            "objective_per_question": True
        }),
        "renderer_class": "app.services.scorm.renderers.mcq.MCQRenderer",
        "layout_version": 1
    }


def get_content_text_definition():
    """Get Content-Text template definition."""
    fields = [
        {
            "name": "content",
            "type": "html",
            "sanitize_strategy": "html",
            "required": True
        },
        {
            "name": "subtitle",
            "type": "text",
            "sanitize_strategy": "text",
            "required": False
        }
    ]
    
    return {
        "id": "content-text",
        "type_key": "content-text",
        "schema_signature": compute_schema_signature(fields),
        "field_schema_json": json.dumps(fields),
        "render_config_json": json.dumps({
            "component_type": "html",
            "html_template": "<div class='content-body'>{{{content}}}</div>"
        }),
        "sanitize_rules_json": json.dumps({
            "content": "html",
            "subtitle": "text"
        }),
        "scorm_behavior_json": json.dumps({
            "interaction_type": "none",
            "reports_score": False
        }),
        "renderer_class": "app.services.scorm.renderers.content.ContentRenderer",
            # noqa: E501,
        "layout_version": 1
    }


def get_content_video_definition():
    """Get Content-Video template definition."""
    fields = [
        {
            "name": "content",
            "type": "text",
            "sanitize_strategy": "text",
            "required": False
        },
        {
            "name": "videoUrl",
            "type": "text",
            "sanitize_strategy": "text",
            "required": True
        },
        {
            "name": "subtitle",
            "type": "text",
            "sanitize_strategy": "text",
            "required": False
        }
    ]
    
    return {
        "id": "content-video",
        "type_key": "content-video",
        "schema_signature": compute_schema_signature(fields),
        "field_schema_json": json.dumps(fields),
        "render_config_json": json.dumps({
            "component_type": "video",
            "html_template": (
                "<div class='video-container'>"
                "<video controls><source src='{{{videoUrl}}}'></video>"
                "</div>"
            )
        }),
        "sanitize_rules_json": json.dumps({
            "content": "text",
            "videoUrl": "text",
            "subtitle": "text"
        }),
        "scorm_behavior_json": json.dumps({
            "interaction_type": "none",
            "reports_score": False
        }),
        "renderer_class": "app.services.scorm.renderers.content.ContentRenderer",
            # noqa: E501,
        "layout_version": 1
    }


def get_welcome_definition():
    """Get Welcome template definition."""
    fields = [
        {
            "name": "content",
            "type": "html",
            "sanitize_strategy": "html",
            "required": True
        },
        {
            "name": "subtitle",
            "type": "text",
            "sanitize_strategy": "text",
            "required": False
        }
    ]
    
    return {
        "id": "welcome",
        "type_key": "welcome",
        "schema_signature": compute_schema_signature(fields),
        "field_schema_json": json.dumps(fields),
        "render_config_json": json.dumps({
            "component_type": "html",
            "html_template": (
                "<div class='welcome-screen'>{{{content}}}</div>"
            )
        }),
        "sanitize_rules_json": json.dumps({
            "content": "html",
            "subtitle": "text"
        }),
        "scorm_behavior_json": json.dumps({
            "interaction_type": "none",
            "reports_score": False
        }),
        "renderer_class": "app.services.scorm.renderers.content.ContentRenderer",
            # noqa: E501,
        "layout_version": 1
    }


def get_summary_definition():
    """Get Summary template definition."""
    fields = [
        {
            "name": "content",
            "type": "html",
            "sanitize_strategy": "html",
            "required": True
        },
        {
            "name": "subtitle",
            "type": "text",
            "sanitize_strategy": "text",
            "required": False
        }
    ]
    
    return {
        "id": "summary",
        "type_key": "summary",
        "schema_signature": compute_schema_signature(fields),
        "field_schema_json": json.dumps(fields),
        "render_config_json": json.dumps({
            "component_type": "html",
            "html_template": (
                "<div class='summary-screen'>{{{content}}}</div>"
            )
        }),
        "sanitize_rules_json": json.dumps({
            "content": "html",
            "subtitle": "text"
        }),
        "scorm_behavior_json": json.dumps({
            "interaction_type": "none",
            "reports_score": False
        }),
        "renderer_class": "app.services.scorm.renderers.content.ContentRenderer",
            # noqa: E501,
        "layout_version": 1
    }


def get_all_definitions():
    """Get all built-in template definitions."""
    return [
        get_mcq_definition(),
        get_content_text_definition(),
        get_content_video_definition(),
        get_welcome_definition(),
        get_summary_definition()
    ]
