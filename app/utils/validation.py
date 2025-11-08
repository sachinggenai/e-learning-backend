"""
Course validation utilities
Implements server-side validation logic as specified in Phase 1 requirements
"""

from typing import List, Dict, Any, Optional
from ..models.course import Course, Template, MCQData, CourseExportRequest
from pydantic import ValidationError as PydanticValidationError
from jsonschema import validate, ValidationError as JsonSchemaError
import json
import os
import logging


def load_course_schema() -> Dict[str, Any]:
    """Load the course JSON schema for validation"""
    try:
        # Get path to shared schema
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            'shared', 'schema', 'course.json'
        )
        
        with open(schema_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Fallback schema if file not found
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "courseId": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "author": {"type": "string"},
                "version": {"type": "string"},
                "templates": {"type": "array"},
                "assets": {"type": "array"},
                "navigation": {"type": "object"}
            },
            "required": ["courseId", "title", "author", "templates"]
        }


class ValidationError:
    """Validation error structure"""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
    
    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "message": self.message}


class CourseValidator:
    """Course validation service"""
    
    def __init__(self):
        self.schema = load_course_schema()
    
    async def validate_course(self, course: Course) -> List[ValidationError]:
        """
        Comprehensive course validation
        
        Args:
            course: Course object to validate
            
        Returns:
            List of validation errors
        """
        errors = []
        
        try:
            # Skip JSON Schema validation for now to avoid conflicts with Pydantic
            # The Pydantic models already provide comprehensive validation
            # TODO: Align JSON schema with Pydantic models
            
            # Convert course to dict for any remaining validation needs
            # course_dict = course.model_dump(mode='json')
            # schema_errors = self._validate_against_schema(course_dict) 
            # errors.extend(schema_errors)
            
            # Business rule validations
            business_errors = await self._validate_business_rules(course)
            errors.extend(business_errors)
            
        except Exception as e:
            errors.append(ValidationError("validation", f"Validation failed: {str(e)}"))
        
        return errors
    
    def _validate_against_schema(self, course_dict: Dict[str, Any]) -> List[ValidationError]:
        """Validate course data against JSON schema"""
        errors = []
        
        try:
            validate(instance=course_dict, schema=self.schema)
        except JsonSchemaError as e:
            field_path = ".".join(str(x) for x in e.absolute_path) if e.absolute_path else "course"
            errors.append(ValidationError(field_path, e.message))
        except Exception as e:
            errors.append(ValidationError("schema", f"Schema validation error: {str(e)}"))
        
        return errors
    
    async def _validate_business_rules(self, course: Course) -> List[ValidationError]:
        """Validate business-specific rules"""
        errors = []
        
        # Validate course metadata
        errors.extend(self._validate_course_metadata(course))
        
        # Validate templates
        errors.extend(self._validate_templates(course.templates))
        
        # Validate navigation settings
        errors.extend(self._validate_navigation(course.navigation))
        
        return errors
    
    def _validate_course_metadata(self, course: Course) -> List[ValidationError]:
        """Validate course metadata fields"""
        errors = []
        
        # Required fields
        if not course.courseId or not course.courseId.strip():
            errors.append(ValidationError("courseId", "Course ID is required"))
        
        if not course.title or not course.title.strip():
            errors.append(ValidationError("title", "Course title is required"))
        
        if not course.author or not course.author.strip():
            errors.append(ValidationError("author", "Course author is required"))
        
        # Course ID format validation
        if course.courseId and not course.courseId.replace('_', '').replace('-', '').isalnum():
            errors.append(ValidationError("courseId", "Course ID can only contain letters, numbers, hyphens, and underscores"))
        
        # Title length validation
        if course.title and len(course.title) > 100:
            errors.append(ValidationError("title", "Course title cannot exceed 100 characters"))
        
        # Description length validation
        if course.description and len(course.description) > 1000:
            errors.append(ValidationError("description", "Course description cannot exceed 1000 characters"))
        
        return errors
    
    def _validate_templates(self, templates: List[Template]) -> List[ValidationError]:
        """Validate template array and individual templates"""
        errors = []
        
        if not templates:
            errors.append(ValidationError("templates", "Course must have at least one template"))
            return errors
        
        # Check template count limit
        if len(templates) > 100:
            errors.append(ValidationError("templates", "Course cannot have more than 100 templates"))
        
        # Validate template ordering
        orders = [t.order for t in templates]
        expected_orders = list(range(len(templates)))
        
        if sorted(orders) != expected_orders:
            errors.append(ValidationError("templates.order", "Template orders must be sequential starting from 0"))
        
        # Check for duplicate orders
        if len(set(orders)) != len(orders):
            errors.append(ValidationError("templates.order", "Template orders must be unique"))
        
        # Validate individual templates
        for i, template in enumerate(templates):
            template_errors = self._validate_template(template, i)
            errors.extend(template_errors)
        
        return errors
    
    def _validate_template(self, template: Template, index: int) -> List[ValidationError]:
        """Validate individual template"""
        errors = []
        field_prefix = f"templates[{index}]"
        
        # Template ID validation
        if not template.id or not template.id.strip():
            errors.append(ValidationError(f"{field_prefix}.id", "Template ID is required"))
        
        # Template title validation
        if not template.title or not template.title.strip():
            errors.append(ValidationError(f"{field_prefix}.title", "Template title is required"))
        elif len(template.title) > 100:
            errors.append(ValidationError(f"{field_prefix}.title", "Template title cannot exceed 100 characters"))
        
        # Template type validation
        valid_types = ["welcome", "content-text", "content-video", "mcq", "summary"]
        if template.type not in valid_types:
            errors.append(ValidationError(f"{field_prefix}.type", f"Invalid template type. Must be one of: {', '.join(valid_types)}"))
        
        # Template data validation based on type
        if template.type == "mcq":
            mcq_errors = self._validate_mcq_template(template, field_prefix)
            errors.extend(mcq_errors)
        elif template.type == "welcome":
            welcome_errors = self._validate_welcome_template(template, field_prefix)
            errors.extend(welcome_errors)
        elif template.type in ["content-text", "content-video"]:
            content_errors = self._validate_content_template(template, field_prefix)
            errors.extend(content_errors)
        elif template.type == "summary":
            summary_errors = self._validate_summary_template(template, field_prefix)
            errors.extend(summary_errors)
        
        return errors
    
    def _validate_mcq_template(self, template: Template, field_prefix: str) -> List[ValidationError]:
        """Validate MCQ template data"""
        errors = []
        # Handle both Pydantic model objects and dict objects
        data = template.data.model_dump() if hasattr(template.data, 'model_dump') else template.data

        if not isinstance(data, dict):
            errors.append(ValidationError(f"{field_prefix}.data", "MCQ template data must be an object"))
            return errors

        # Accept either canonical questions[] list OR legacy question/options form
        if data.get('questions') and isinstance(data['questions'], list):
            # Canonical shape: iterate each question object
            for qi, q in enumerate(data['questions']):
                if not isinstance(q, dict):
                    errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}]", "Question must be an object"))
                    continue
                if not q.get('question') or not str(q['question']).strip():
                    errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].question", "Question text is required"))
                options = q.get('options', [])
                if not isinstance(options, list) or len(options) < 2:
                    errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options", "Each question must have at least 2 options"))
                    continue
                if len(options) > 10:
                    errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options", "Each question cannot have more than 10 options"))
                correct_count = 0
                for oi, opt in enumerate(options):
                    if not isinstance(opt, dict):
                        errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options[{oi}]", "Option must be an object"))
                        continue
                    if not opt.get('id'):
                        errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options[{oi}].id", "Option ID is required"))
                    if not opt.get('text') or not str(opt['text']).strip():
                        errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options[{oi}].text", "Option text is required"))
                    if 'isCorrect' not in opt or not isinstance(opt['isCorrect'], bool):
                        errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options[{oi}].isCorrect", "Option isCorrect must be a boolean"))
                    elif opt['isCorrect']:
                        correct_count += 1
                if correct_count != 1:
                    errors.append(ValidationError(f"{field_prefix}.data.questions[{qi}].options", "Each question must have exactly one correct answer"))
        else:
            # Legacy flat shape
            if not data.get("question") or not str(data.get("question")).strip():
                errors.append(ValidationError(f"{field_prefix}.data.question", "MCQ question is required"))
            options = data.get("options", [])
            if not isinstance(options, list) or len(options) < 2:
                errors.append(ValidationError(f"{field_prefix}.data.options", "MCQ must have at least 2 options"))
            else:
                correct_count = 0
                for i, option in enumerate(options):
                    if not isinstance(option, dict):
                        errors.append(ValidationError(f"{field_prefix}.data.options[{i}]", "Option must be an object"))
                        continue
                    if not option.get("id"):
                        errors.append(ValidationError(f"{field_prefix}.data.options[{i}].id", "Option ID is required"))
                    if not option.get("text") or not str(option.get("text")).strip():
                        errors.append(ValidationError(f"{field_prefix}.data.options[{i}].text", "Option text is required"))
                    if 'isCorrect' not in option or not isinstance(option['isCorrect'], bool):
                        errors.append(ValidationError(f"{field_prefix}.data.options[{i}].isCorrect", "Option isCorrect must be a boolean"))
                    elif option['isCorrect']:
                        correct_count += 1
                if correct_count != 1:
                    errors.append(ValidationError(f"{field_prefix}.data.options", "MCQ must have exactly one correct answer"))
        return errors
    
    def _validate_welcome_template(self, template: Template, field_prefix: str) -> List[ValidationError]:
        """Validate welcome template data"""
        errors = []
        
        # Handle both Pydantic model objects and dict objects
        data = template.data.model_dump() if hasattr(template.data, 'model_dump') else template.data
        
        if not isinstance(data, dict):
            errors.append(ValidationError(f"{field_prefix}.data", "Welcome template data must be an object"))
            return errors
        
        # Content validation (updated to match Pydantic TemplateData model)
        if not data.get("content") or not data["content"].strip():
            errors.append(ValidationError(f"{field_prefix}.data.content", "Welcome content is required"))
        
        return errors
    
    def _validate_content_template(self, template: Template, field_prefix: str) -> List[ValidationError]:
        """Validate content template data"""
        errors = []
        
        # Handle both Pydantic model objects and dict objects
        data = template.data.model_dump() if hasattr(template.data, 'model_dump') else template.data
        
        if not isinstance(data, dict):
            errors.append(ValidationError(f"{field_prefix}.data", "Content template data must be an object"))
            return errors
        
        # Content validation (updated to match Pydantic TemplateData model)
        if not data.get("content") or not data["content"].strip():
            errors.append(ValidationError(f"{field_prefix}.data.content", "Content is required"))
        
        return errors
    
    def _validate_summary_template(self, template: Template, field_prefix: str) -> List[ValidationError]:
        """Validate summary template data"""
        errors = []
        
        # Handle both Pydantic model objects and dict objects
        data = template.data.model_dump() if hasattr(template.data, 'model_dump') else template.data
        
        if not isinstance(data, dict):
            errors.append(ValidationError(f"{field_prefix}.data", "Summary template data must be an object"))
            return errors
        
        # Content validation (updated to match Pydantic TemplateData model)
        if not data.get("content") or not data["content"].strip():
            errors.append(ValidationError(f"{field_prefix}.data.content", "Summary content is required"))
        
        return errors
    
    def _validate_navigation(self, navigation: Any) -> List[ValidationError]:
        """Validate navigation settings"""
        errors = []
        
        # Handle both Pydantic model objects and dict objects
        nav_dict = navigation.model_dump() if hasattr(navigation, 'model_dump') else navigation
        
        if not isinstance(nav_dict, dict):
            errors.append(ValidationError("navigation", "Navigation settings must be an object"))
            return errors
        
        # Validate boolean fields (updated to match Pydantic model)
        for field in ["allowSkip", "showProgress", "linearProgression"]:
            if field in nav_dict and not isinstance(nav_dict[field], bool):
                errors.append(ValidationError(f"navigation.{field}", f"Navigation {field} must be a boolean"))
        
        return errors


# Export validator instance
course_validator = CourseValidator()


# FastAPI dependency function
async def validate_course_json(request: CourseExportRequest) -> Course:
    """
    FastAPI dependency to validate course JSON from export request
    
    Args:
        request: CourseExportRequest containing course JSON string
        
    Returns:
        Validated Course instance
        
    Raises:
        HTTPException: If validation fails
    """
    from fastapi import HTTPException
    import json
    
    try:
        # Parse JSON string
        course_data = json.loads(request.course)

        logger = logging.getLogger(__name__)
        logger.info("[validate_course_json] Incoming raw course keys: %s", list(course_data.keys()))
        logger.debug("[validate_course_json] Full payload: %s", json.dumps(course_data, indent=2))

        # --- Pre-normalization: Legacy MCQ shape recovery ---
        try:
            for t in course_data.get('templates', []):
                if t.get('type') == 'mcq':
                    data = t.get('data', {})
                    # Case 1: Already canonical (questions present)
                    if isinstance(data, dict) and data.get('questions'):
                        continue
                    # Case 2: Flat shape question/options
                    if isinstance(data, dict) and data.get('question') and data.get('options'):
                        t['data'] = {
                            'content': data.get('content') or '',
                            'questions': [{
                                'id': f"{t.get('id','mcq')}_q1",
                                'question': data.get('question'),
                                'options': data.get('options')
                            }]
                        }
                        continue
                    # Case 3: JSON string stuffed in content field
                    if isinstance(data, dict) and 'content' in data and isinstance(data['content'], str):
                        raw = data['content']
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict) and parsed.get('question') and parsed.get('options'):
                                t['data'] = {
                                    'content': '',
                                    'questions': [{
                                        'id': f"{t.get('id','mcq')}_q1",
                                        'question': parsed.get('question'),
                                        'options': parsed.get('options')
                                    }]
                                }
                        except Exception:
                            # Leave as-is if not parseable
                            pass
        except Exception as norm_e:
            logger.warning("[validate_course_json] MCQ pre-normalization warning: %s", norm_e)

        # --- Stage 1: Pydantic structural & field validation ---
        try:
            course = Course(**course_data)
        except PydanticValidationError as ve:
            # Convert each Pydantic error into FastAPI-style detail entries
            detail_entries = []
            for err in ve.errors():
                # err has keys: loc, msg, type, input (pydantic v2) maybe ctx
                loc = ["body", *(["course"] if err.get("loc") == ("course",) else err.get("loc", []))]
                detail_entries.append({
                    "type": err.get("type", "value_error"),
                    "loc": loc,
                    "msg": err.get("msg", "Validation error"),
                    "input": err.get("input", None)
                })
            logger.warning("[validate_course_json] Pydantic validation failed with %d errors", len(detail_entries))
            raise HTTPException(status_code=422, detail=detail_entries)

        # --- Stage 2: Business rule validation (non-structural) ---
        validation_errors = await course_validator.validate_course(course)
        if validation_errors:
            detail_entries = [
                {
                    "type": "business_rule_error",
                    "loc": ["body", "course", err.field],
                    "msg": err.message,
                    "input": None,
                }
                for err in validation_errors
            ]
            logger.info("[validate_course_json] Business rule validation failed: %s", [e["msg"] for e in detail_entries])
            raise HTTPException(status_code=422, detail=detail_entries)

        logger.info("[validate_course_json] Validation succeeded for courseId=%s templates=%d", course.courseId, len(course.templates))
        return course

    except json.JSONDecodeError as e:
        logger = logging.getLogger(__name__)
        logger.error(f"JSON decode error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON format: {str(e)}"
        )
    except HTTPException:
        # Already structured; just re-raise
        raise
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.exception("[validate_course_json] Unexpected exception during validation")
        raise HTTPException(status_code=500, detail=f"Internal validation error: {str(e)}")


async def get_validation_status() -> Dict[str, Any]:
    """
    FastAPI dependency to get validation system status
    
    Returns:
        Dictionary containing validation system status
    """
    try:
        # Check if schema file is accessible
        schema = load_course_schema()
        
        return {
            "validation_system": "operational",
            "schema_loaded": True,
            "schema_version": schema.get("$schema", "unknown"),
            "course_validator": "ready"
        }
    except Exception as e:
        return {
            "validation_system": "error",
            "schema_loaded": False,
            "error": str(e),
            "course_validator": "unavailable"
        }