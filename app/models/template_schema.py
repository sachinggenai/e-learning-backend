"""
Pydantic Models for Template Definition Validation

Data models for template definitions with validation rules.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Any, Optional, Literal
from datetime import datetime


class FieldSchema(BaseModel):
    """Schema for a single template field."""
    
    name: str = Field(..., description="Field name in template data")
    type: Literal[
        "text", "html", "boolean", "number", "list", "object"
    ] = Field(..., description="Data type of field")
    sanitize_strategy: Literal[
        "none", "text", "html", "preserve_structure"
    ] = Field(
        default="text", description="How to sanitize this field"
    )
    required: bool = Field(
        default=True, description="Whether field is required"
    )
    nested_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Schema for nested structures (lists/objects)"
    )


class ScormBehavior(BaseModel):
    """SCORM interaction configuration."""
    
    interaction_type: Literal[
        "none", "choice", "fill-in", "true-false", "matching"
    ] = "none"
    reports_score: bool = False
    objective_per_question: bool = False
    completion_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Score required for completion (0-1)"
    )


class RenderConfig(BaseModel):
    """Client-side rendering configuration."""
    
    component_type: Literal["html", "mcq", "video", "custom"] = Field(
        ..., description="Type of renderer to use"
    )
    html_template: Optional[str] = Field(
        default=None,
        description="Mustache/Handlebars template for HTML rendering"
    )
    nested_fields: Optional[Dict[str, Any]] = Field(
        default=None, description="Schema for nested field structures"
    )
    validation_rules: Optional[Dict[str, Any]] = Field(
        default=None, description="Client-side validation config"
    )
    
    @field_validator('html_template')
    @classmethod
    def no_script_tags(cls, v):
        """Security: Prevent script injection in templates."""
        if v and '<script' in v.lower():
            raise ValueError("Script tags not allowed in render templates")
        return v


class TemplateDefinition(BaseModel):
    """Complete template definition."""
    
    type_key: str = Field(..., min_length=1, max_length=50)
    schema_signature: str = Field(..., pattern=r'^[a-f0-9]{64}$')  # SHA-256
    field_schema: List[FieldSchema]
    render_config: RenderConfig
    sanitize_rules: Dict[str, str]
    scorm_behavior: ScormBehavior
    renderer_class: str = Field(
        ..., pattern=r'^app\.services\.scorm\.renderers\.\w+\.\w+$'
    )
    layout_version: int = Field(default=1, ge=1)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "type_key": "mcq",
                "schema_signature": "abc123" + "0" * 58,
                "field_schema": [
                    {
                        "name": "questions",
                        "type": "list",
                        "sanitize_strategy": "preserve_structure"
                    }
                ],
                "render_config": {
                    "component_type": "mcq",
                    "nested_fields": {"questions": {"type": "list"}}
                },
                "sanitize_rules": {"questions": "preserve_structure"},
                "scorm_behavior": {
                    "interaction_type": "choice",
                    "reports_score": True
                },
                "renderer_class": (
                    "app.services.scorm.renderers.mcq.MCQRenderer"
                ),
                "layout_version": 1
            }
        }
    }
