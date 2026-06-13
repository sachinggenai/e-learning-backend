# Detailed Task Breakdowns: Chunks 0–2 (Production Grade)

**Date:** 2026-06-13  
**Status:** Production Specification  
**Duration:** 2.5–3 days  
**Team:** Backend (FastAPI) + Frontend (React)  
**Deliverable:** Foundation for all downstream AI chunks  

---

## Overview

**Chunk 0:** Feature flag + environment config + logging scaffolding  
**Chunk 1:** Tool schemas + template registry + validation module  
**Chunk 2:** Session management + state enforcement + permission scoping  

These three chunks establish the **guardrails** that make downstream chunks safe and predictable.

---

## Chunk 0: Foundation & Feature Flag

**Duration:** 0.5–1 day  
**Owner:** Backend Lead + DevOps  
**Deliverable:** Feature flag integrated; all AI UI hidden behind flag  

### 0.1 Add AI Feature Flag

#### Requirement: Add environment variable for feature flag control

**Task:** Backend - Add feature flag configuration

```python
# app/config.py
from pydantic import BaseSettings

class Settings(BaseSettings):
    # AI Feature Flag (default: disabled for safety)
    AI_AUTHORING_ENABLED: bool = False  # Set to true in staging/demo only
    
    # AI Model Configuration
    AI_PRIMARY_MODEL: str = "claude-3-5-sonnet-20241022"
    AI_FALLBACK_MODEL: str = "claude-3-5-haiku-20241022"
    AI_MAX_RETRIES: int = 1
    AI_REQUEST_TIMEOUT_SECONDS: int = 30
    
    # Rate Limiting
    AI_RATE_LIMIT_CALLS_PER_HOUR: int = 100
    AI_RATE_LIMIT_CALLS_PER_DAY: int = 500
    
    # Cost Controls (optional)
    AI_MONTHLY_COST_CAP_USD: float = 500.0
    
    class Config:
        env_file = ".env"

settings = Settings()
```

**Acceptance Criteria:**
- ✅ Feature flag reads from environment variable
- ✅ Default is `False` (AI disabled)
- ✅ All other AI config (model, timeouts, rate limits) also configurable
- ✅ Config is validated on app startup (fail fast if invalid)
- ✅ No hardcoded values in code

**Test:**
```bash
# With flag disabled
export AI_AUTHORING_ENABLED=false
pytest -v tests/test_feature_flag_disabled.py

# With flag enabled
export AI_AUTHORING_ENABLED=true
pytest -v tests/test_feature_flag_enabled.py
```

#### Task: Frontend - Conditionally render AI UI

**File:** `src/components/CourseEditor/CourseMenu.tsx`

```typescript
// Check if AI features are enabled
const [isAIEnabled, setIsAIEnabled] = useState(false);

useEffect(() => {
  // Fetch AI feature status from backend
  fetch('/api/v1/ai/feature-status')
    .then(r => r.json())
    .then(data => setIsAIEnabled(data.aiAuthoringEnabled))
    .catch(() => setIsAIEnabled(false)); // Default off on error
}, []);

// Conditionally show AI button
return (
  <div className="course-menu">
    {/* Existing manual create course button */}
    <button onClick={handleManualCreate}>Create Course</button>
    
    {/* AI button only if enabled */}
    {isAIEnabled && (
      <button onClick={handleAICreate} className="btn-primary-secondary">
        ✨ Build with AI
      </button>
    )}
  </div>
);
```

**Acceptance Criteria:**
- ✅ AI button hidden when feature flag is `false`
- ✅ AI button visible when feature flag is `true`
- ✅ Manual course creation button always visible (no change)
- ✅ No console errors or warnings when AI disabled
- ✅ UI layout unchanged when AI button hidden

**Test:**
```bash
# Test with feature disabled
npx cypress run --spec "cypress/e2e/feature-flag-disabled.cy.ts"

# Test with feature enabled
npx cypress run --spec "cypress/e2e/feature-flag-enabled.cy.ts"
```

---

### 0.2 Add Environment Config for Model Routing

#### Task: Backend - Create AI config module

**File:** `app/services/ai_config.py`

```python
import os
from typing import Literal
from pydantic import BaseModel, Field

class ModelConfig(BaseModel):
    """Model configuration for LLM routing."""
    id: str = Field(..., description="Model identifier")
    api_name: str = Field(..., description="Model name as known by API")
    max_tokens: int = Field(default=4096)
    is_primary: bool = Field(default=False, description="Primary model (tried first)")
    is_fallback: bool = Field(default=False, description="Fallback model (tried second)")
    cost_per_1k_input: float = Field(..., description="Cost per 1k input tokens")
    cost_per_1k_output: float = Field(..., description="Cost per 1k output tokens")
    status: Literal["active", "hidden", "deprecated"] = "active"

class AIConfig:
    """Load and manage AI configuration."""
    
    def __init__(self):
        self.primary_model = os.getenv("AI_PRIMARY_MODEL", "claude-3-5-sonnet-20241022")
        self.fallback_model = os.getenv("AI_FALLBACK_MODEL", "claude-3-5-haiku-20241022")
        
        # Model registry
        self.models = {
            "gpt-4-1": ModelConfig(
                id="gpt-4-1",
                api_name="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                is_primary=True,
                cost_per_1k_input=0.003,
                cost_per_1k_output=0.006,
            ),
            "gpt-4-1-mini": ModelConfig(
                id="gpt-4-1-mini",
                api_name="claude-3-5-haiku-20241022",
                max_tokens=2048,
                is_fallback=True,
                cost_per_1k_input=0.0008,
                cost_per_1k_output=0.0024,
            ),
        }
    
    def get_model(self, model_id: str) -> ModelConfig:
        """Get model config by ID."""
        model = self.models.get(model_id)
        if not model:
            raise ValueError(f"Unknown model: {model_id}")
        return model
    
    def get_primary_model(self) -> ModelConfig:
        return self.get_model(self.primary_model)
    
    def get_fallback_model(self) -> ModelConfig:
        return self.get_model(self.fallback_model)

ai_config = AIConfig()
```

**Acceptance Criteria:**
- ✅ Config loads from environment variables
- ✅ Models have metadata (cost, max tokens, status)
- ✅ Primary and fallback models clearly marked
- ✅ Can query models by ID
- ✅ Invalid model IDs raise clear errors

**Test:**
```python
def test_ai_config_loads():
    assert ai_config.get_primary_model().is_primary
    assert ai_config.get_fallback_model().is_fallback

def test_ai_config_invalid_model():
    with pytest.raises(ValueError):
        ai_config.get_model("invalid-model-xyz")
```

---

### 0.3 Add Logging Scaffolding for AI Requests

#### Task: Backend - Create AI logging module

**File:** `app/services/ai_logging.py`

```python
import logging
import json
from datetime import datetime
from typing import Any, Optional
import hashlib

logger = logging.getLogger("ai_authoring")

class AIRequestLogger:
    """Log AI requests and responses for debugging and compliance."""
    
    @staticmethod
    def log_request(
        session_id: str,
        user_id: str,
        organization_id: str,
        tool_name: str,
        input_hash: str,  # SHA256 of sanitized input
        model_used: str,
    ):
        """Log incoming AI request."""
        logger.info(
            "ai_request_started",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "organization_id": organization_id,
                "tool_name": tool_name,
                "input_hash": input_hash,
                "model": model_used,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
    
    @staticmethod
    def log_response(
        session_id: str,
        tool_name: str,
        status: str,  # "success", "validation_error", "timeout", etc.
        response_time_ms: int,
        tokens_used_input: int,
        tokens_used_output: int,
        cost_usd: float,
    ):
        """Log AI response with metrics."""
        logger.info(
            "ai_response_completed",
            extra={
                "session_id": session_id,
                "tool_name": tool_name,
                "status": status,
                "response_time_ms": response_time_ms,
                "tokens_input": tokens_used_input,
                "tokens_output": tokens_used_output,
                "cost_usd": cost_usd,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
    
    @staticmethod
    def log_error(
        session_id: str,
        tool_name: str,
        error_code: str,
        error_message: str,
        retryable: bool,
    ):
        """Log error for troubleshooting."""
        logger.error(
            "ai_error",
            extra={
                "session_id": session_id,
                "tool_name": tool_name,
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
    
    @staticmethod
    def sanitize_input(input_dict: dict) -> str:
        """Create hash of input for logging (never log actual sensitive data)."""
        # Remove sensitive fields
        sanitized = {k: v for k, v in input_dict.items() 
                     if k not in ["password", "api_key", "token", "secret"]}
        return hashlib.sha256(json.dumps(sanitized, sort_keys=True).encode()).hexdigest()
```

**Acceptance Criteria:**
- ✅ Log all AI requests with context (session, user, tool, model)
- ✅ Log all responses with metrics (time, tokens, cost)
- ✅ Log all errors with classification
- ✅ Never log actual sensitive data (passwords, API keys)
- ✅ Use SHA256 hash of inputs for deduplication/searchability
- ✅ All logs include timestamp in ISO-8601 format

**Test:**
```python
def test_logging_sanitization():
    input_data = {"user_id": "abc123", "api_key": "secret123"}
    hash1 = AIRequestLogger.sanitize_input(input_data)
    hash2 = AIRequestLogger.sanitize_input(input_data)
    assert hash1 == hash2  # Deterministic
    # Verify it doesn't contain actual secret
    assert "secret123" not in hash1
```

---

### 0.4 Verify Manual Flow Unchanged

#### Task: QA - Regression test on manual course creation

**Test File:** `cypress/e2e/manual-course-creation-unchanged.cy.ts`

```typescript
describe("Manual Course Creation (Regression)", () => {
  beforeEach(() => {
    cy.visit("/");
    cy.loginAs("teacher@example.com");
  });

  it("Create course manually - flow unchanged", () => {
    // Click "Create Course" (not AI button)
    cy.contains("button", "Create Course").click();
    
    // Fill course details
    cy.get("input[name='courseTitle']").type("My Course");
    cy.get("textarea[name='courseDescription']").type("Learn the basics");
    
    // Add page
    cy.contains("button", "Add Page").click();
    cy.get("input[name='pageTitle']").type("Page 1");
    cy.contains("button", "text-content").click();  // Select template
    
    // Save
    cy.contains("button", "Save").click();
    
    // Verify course created
    cy.url().should("include", "/courses/");
    cy.contains("My Course").should("be.visible");
  });

  it("Preview course - renders correctly", () => {
    // ... existing preview test ...
  });

  it("Export course - SCORM generated", () => {
    // ... existing export test ...
  });
});
```

**Acceptance Criteria:**
- ✅ All existing manual course tests pass
- ✅ No UI changes to manual flow
- ✅ Manual create button always visible
- ✅ All templates work as before
- ✅ Preview and export unchanged

---

## Chunk 0 Sign-Off Checklist

- [ ] Feature flag implemented and tested (off by default)
- [ ] Environment config for models loaded correctly
- [ ] Logging scaffolding in place (no data logged yet)
- [ ] All manual course creation tests pass (baseline regression)
- [ ] Code reviewed by team lead
- [ ] Deployed to dev environment
- [ ] Manual testing on dev: AI button hidden when flag=false
- [ ] Manual testing on staging: AI button visible when flag=true
- [ ] **Product Owner Sign-Off:** ✅

**Exit Criteria Met:** App behavior identical to baseline when feature flag is off.

---

## Chunk 1: Template Registry & Schemas

**Duration:** 1 day  
**Owner:** Backend (API Design)  
**Deliverable:** Template schemas versioned; registry complete; 5 templates defined  

### 1.1 Define Template Capability Registry

#### Task: Backend - Create template registry module

**File:** `app/services/template_registry.py`

```python
from typing import Dict, List, Any
from pydantic import BaseModel, Field

class TemplateCapability(BaseModel):
    """Describes what a template can do and its constraints."""
    template_id: str = Field(..., description="Unique template type ID")
    display_name: str
    description: str
    category: str  # "content", "interaction", "assessment"
    is_ai_generatable: bool = True
    
    # Schema
    required_fields: List[str]
    optional_fields: List[str]
    json_schema: dict  # Full JSON Schema for validation
    
    # Constraints
    max_items: int = Field(..., description="Max subitems (e.g., max tabs)")
    min_items: int = Field(..., description="Min subitems")
    
    # Metadata
    estimated_duration_minutes: int
    complexity_level: str  # "simple", "medium", "advanced"
    accessibility_score: int  # 0-100, based on WCAG compliance
    
    # Planner hints
    best_for: List[str]  # e.g., ["comparison", "grouped sections"]
    avoid_for: List[str]  # e.g., ["single short paragraph"]

class TemplateRegistry:
    """Central registry of all supported templates."""
    
    def __init__(self):
        self.templates: Dict[str, TemplateCapability] = {
            "text-content": TemplateCapability(
                template_id="text-content",
                display_name="Text Content",
                description="Static text, paragraphs, key points",
                category="content",
                required_fields=["title", "content"],
                optional_fields=["key_points"],
                json_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "maxLength": 200},
                        "content": {"type": "string"},
                        "key_points": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 5
                        }
                    },
                    "required": ["title", "content"]
                },
                max_items=1,
                min_items=1,
                estimated_duration_minutes=5,
                complexity_level="simple",
                accessibility_score=95,
                best_for=["explanation", "introduction", "summary"],
                avoid_for=["highly interactive content"],
            ),
            "tabs": TemplateCapability(
                template_id="tabs",
                display_name="Tabs",
                description="Compare/group 2–6 subtopics side-by-side",
                category="interaction",
                required_fields=["title", "tabs"],
                optional_fields=[],
                json_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "tabs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "icon": {"type": "string"}
                                },
                                "required": ["title", "content"]
                            },
                            "minItems": 2,
                            "maxItems": 6
                        }
                    },
                    "required": ["title", "tabs"]
                },
                max_items=6,
                min_items=2,
                estimated_duration_minutes=8,
                complexity_level="medium",
                accessibility_score=90,
                best_for=["comparison", "grouped sections", "options"],
                avoid_for=["single option"],
            ),
            # ... accordion, click-reveal, final-assessment similarly defined ...
        }
    
    def get_template(self, template_id: str) -> TemplateCapability:
        """Get template by ID."""
        if template_id not in self.templates:
            raise ValueError(f"Unknown template: {template_id}")
        return self.templates[template_id]
    
    def get_allowed_templates(self) -> List[str]:
        """List all allowed (AI-generatable) templates."""
        return [t.template_id for t in self.templates.values() 
                if t.is_ai_generatable]
    
    def get_schema(self, template_id: str) -> dict:
        """Get JSON schema for a template."""
        return self.get_template(template_id).json_schema

template_registry = TemplateRegistry()
```

**Acceptance Criteria:**
- ✅ Registry contains all 5 in-scope templates
- ✅ Each template has complete metadata and schema
- ✅ JSON schemas are valid and enforceable
- ✅ Registry is immutable after initialization
- ✅ Can query templates by ID or filter by properties

**Test:**
```python
def test_registry_all_templates_present():
    templates = template_registry.get_allowed_templates()
    assert len(templates) == 5
    assert "text-content" in templates
    assert "tabs" in templates

def test_registry_get_schema():
    schema = template_registry.get_schema("tabs")
    assert schema["type"] == "object"
    assert "tabs" in schema["properties"]
    assert schema["properties"]["tabs"]["minItems"] == 2
```

---

### 1.2 Implement Validator Module

#### Task: Backend - Create schema + business rules validator

**File:** `app/services/ai_validator.py`

```python
import jsonschema
from typing import List, Tuple, Any
from enum import Enum

class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

class ValidationMessage:
    def __init__(self, severity: ValidationSeverity, field: str, message: str, hint: str = None):
        self.severity = severity
        self.field = field
        self.message = message
        self.hint = hint

class TemplateValidator:
    """Validate template data against schema + business rules."""
    
    @staticmethod
    def validate_page(template_type: str, data: dict) -> Tuple[bool, List[ValidationMessage]]:
        """
        Validate page data.
        Returns: (is_valid, messages)
        """
        messages = []
        
        # 1. Schema validation
        template = template_registry.get_template(template_type)
        schema = template.json_schema
        
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            messages.append(ValidationMessage(
                ValidationSeverity.ERROR,
                str(e.path),
                e.message,
                f"Expected {e.validator} for field '{e.path}'"
            ))
            return False, messages
        
        # 2. Business rules validation
        messages.extend(
            TemplateValidator._validate_business_rules(template_type, data)
        )
        
        # 3. Accessibility validation
        messages.extend(
            TemplateValidator._validate_accessibility(template_type, data)
        )
        
        has_errors = any(m.severity == ValidationSeverity.ERROR for m in messages)
        return not has_errors, messages
    
    @staticmethod
    def _validate_business_rules(template_type: str, data: dict) -> List[ValidationMessage]:
        """Validate template-specific business rules."""
        messages = []
        
        if template_type == "final-assessment":
            # Assessment must have min 3 questions
            questions = data.get("questions", [])
            if len(questions) < 3:
                messages.append(ValidationMessage(
                    ValidationSeverity.ERROR,
                    "questions",
                    f"Assessment must have at least 3 questions (has {len(questions)})"
                ))
            
            # Each question must have correct answer
            for i, q in enumerate(questions):
                if "correct_answer" not in q:
                    messages.append(ValidationMessage(
                        ValidationSeverity.ERROR,
                        f"questions[{i}]",
                        "Question missing 'correct_answer' field"
                    ))
            
            # Passing score must be 0-100
            passing_score = data.get("passing_score", 0)
            if not (0 <= passing_score <= 100):
                messages.append(ValidationMessage(
                    ValidationSeverity.ERROR,
                    "passing_score",
                    f"Passing score must be 0-100 (got {passing_score})"
                ))
        
        elif template_type == "tabs":
            tabs = data.get("tabs", [])
            if len(tabs) < 2 or len(tabs) > 6:
                messages.append(ValidationMessage(
                    ValidationSeverity.ERROR,
                    "tabs",
                    f"Tabs must have 2-6 items (got {len(tabs)})"
                ))
        
        elif template_type == "accordion":
            items = data.get("items", [])
            if len(items) < 2:
                messages.append(ValidationMessage(
                    ValidationSeverity.ERROR,
                    "items",
                    "Accordion must have at least 2 items"
                ))
        
        elif template_type == "click-reveal":
            items = data.get("items", [])
            if len(items) < 2 or len(items) > 10:
                messages.append(ValidationMessage(
                    ValidationSeverity.ERROR,
                    "items",
                    f"Click-reveal must have 2-10 items (got {len(items)})"
                ))
        
        return messages
    
    @staticmethod
    def _validate_accessibility(template_type: str, data: dict) -> List[ValidationMessage]:
        """Validate WCAG accessibility requirements."""
        messages = []
        
        # All templates should have descriptive title
        title = data.get("title", "")
        if not title or len(title.strip()) < 3:
            messages.append(ValidationMessage(
                ValidationSeverity.WARNING,
                "title",
                "Title should be at least 3 characters for accessibility",
                "Add a descriptive title"
            ))
        
        if template_type == "final-assessment":
            # Assessment should have accessible instructions
            if "assessment_metadata" in data:
                meta = data["assessment_metadata"]
                if not meta.get("has_accessible_instructions", False):
                    messages.append(ValidationMessage(
                        ValidationSeverity.WARNING,
                        "assessment_metadata.hasAccessibleInstructions",
                        "Assessment should provide accessible instructions",
                        "Add instructions that work with screen readers"
                    ))
        
        return messages

ai_validator = TemplateValidator()
```

**Acceptance Criteria:**
- ✅ Schema validation works for all 5 templates
- ✅ Business rules enforced (min questions, tab count, etc.)
- ✅ Accessibility warnings included
- ✅ Validation returns structured error messages with hints
- ✅ Errors vs. warnings clearly distinguished

**Test:**
```python
def test_validator_final_assessment():
    # Valid assessment
    valid_data = {
        "title": "Quiz",
        "passing_score": 70,
        "questions": [
            {"question_text": "Q1?", "question_type": "true_false", "correct_answer": "True"},
            {"question_text": "Q2?", "question_type": "true_false", "correct_answer": "False"},
            {"question_text": "Q3?", "question_type": "true_false", "correct_answer": "True"},
        ]
    }
    is_valid, messages = ai_validator.validate_page("final-assessment", valid_data)
    assert is_valid
    
    # Invalid: too few questions
    invalid_data = {"title": "Quiz", "passing_score": 70, "questions": []}
    is_valid, messages = ai_validator.validate_page("final-assessment", invalid_data)
    assert not is_valid
    assert any("at least 3" in m.message for m in messages)
```

---

### 1.3 Add Unit Tests for Schema Validation

**File:** `tests/test_template_schemas.py`

```python
import pytest
from app.services.template_registry import template_registry
from app.services.ai_validator import ai_validator

class TestTemplateSchemas:
    """Test all template schemas are valid."""
    
    def test_all_templates_have_schema(self):
        for template_id in ["text-content", "tabs", "accordion", "click-reveal", "final-assessment"]:
            schema = template_registry.get_schema(template_id)
            assert schema is not None
            assert schema.get("type") == "object"
    
    def test_text_content_schema(self):
        valid = {"title": "Intro", "content": "Learn this..."}
        is_valid, msgs = ai_validator.validate_page("text-content", valid)
        assert is_valid
        
        invalid = {"content": "No title"}  # Missing required field
        is_valid, msgs = ai_validator.validate_page("text-content", invalid)
        assert not is_valid
    
    def test_tabs_min_max_items(self):
        # Min items = 2
        invalid_single = {
            "title": "Tabs",
            "tabs": [{"title": "A", "content": "A content"}]
        }
        is_valid, _ = ai_validator.validate_page("tabs", invalid_single)
        assert not is_valid
        
        # Max items = 6
        valid_six = {
            "title": "Tabs",
            "tabs": [{"title": f"T{i}", "content": f"C{i}"} for i in range(6)]
        }
        is_valid, _ = ai_validator.validate_page("tabs", valid_six)
        assert is_valid
        
        invalid_seven = {
            "title": "Tabs",
            "tabs": [{"title": f"T{i}", "content": f"C{i}"} for i in range(7)]
        }
        is_valid, _ = ai_validator.validate_page("tabs", invalid_seven)
        assert not is_valid
    
    # Similar tests for other templates...
```

**Acceptance Criteria:**
- ✅ All 5 templates have valid JSON schemas
- ✅ Schemas can validate correct data (passes)
- ✅ Schemas reject invalid data (fails)
- ✅ All constraint rules tested (min/max items, required fields, etc.)
- ✅ 100% test coverage for validation logic

---

### 1.4 Expose Template Registry via API

#### Task: Backend - Create template registry endpoint

**File:** `app/routers/ai_templates.py`

```python
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/ai/templates", tags=["AI Templates"])

@router.get("/registry")
def get_template_registry():
    """Get complete template registry."""
    return {
        "templates": {
            t_id: {
                "displayName": t.display_name,
                "description": t.description,
                "category": t.category,
                "requiredFields": t.required_fields,
                "optionalFields": t.optional_fields,
                "schema": t.json_schema,
                "minItems": t.min_items,
                "maxItems": t.max_items,
                "complexity": t.complexity_level,
                "bestFor": t.best_for,
            }
            for t_id, t in template_registry.templates.items()
        }
    }

@router.get("/allowed")
def get_allowed_templates():
    """Get list of templates AI can generate."""
    return {
        "allowed": template_registry.get_allowed_templates()
    }

@router.post("/validate")
def validate_template_data(template_type: str, data: dict):
    """Validate template data."""
    try:
        is_valid, messages = ai_validator.validate_page(template_type, data)
        return {
            "isValid": is_valid,
            "validationStatus": "valid" if is_valid else "error",
            "messages": [
                {
                    "severity": m.severity,
                    "field": m.field,
                    "message": m.message,
                    "hint": m.hint
                }
                for m in messages
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```

**Acceptance Criteria:**
- ✅ `/api/v1/ai/templates/registry` returns complete registry
- ✅ `/api/v1/ai/templates/allowed` lists allowed templates
- ✅ `/api/v1/ai/templates/validate` validates data
- ✅ All endpoints return structured JSON
- ✅ Errors have clear messages

---

## Chunk 1 Sign-Off Checklist

- [ ] Template registry implemented (5 templates, all metadata complete)
- [ ] JSON schemas defined and validated
- [ ] Validator module passes all tests (100 coverage)
- [ ] Template registry API endpoints working
- [ ] AI can only propose allowed templates (whitelist enforced)
- [ ] All schema validation tests pass
- [ ] Code reviewed
- [ ] Deployed to dev environment
- [ ] **Product Owner Sign-Off:** ✅

**Exit Criteria Met:** Validator blocks invalid structures before UI apply.

---

## Chunk 2: Session & State Management

**Duration:** 1–1.5 days  
**Owner:** Backend (API Design) + Frontend (State Management)  
**Deliverable:** Session lifecycle working; re-fetch rule enforced; permission scoping server-side  

### 2.1 Implement Session Management Layer

#### Task: Backend - Create session service

**File:** `app/services/session_manager.py`

```python
from datetime import datetime, timedelta
import uuid
from typing import Dict, Optional
from pydantic import BaseModel

class SessionContext(BaseModel):
    """AI authoring session context."""
    session_id: str
    user_id: str
    organization_id: str
    course_id: str  # Immutable for this session
    created_at: datetime
    expires_at: datetime
    
class SessionManager:
    """Manage AI authoring sessions with scope enforcement."""
    
    def __init__(self):
        # In-memory store (in production, use Redis)
        self._sessions: Dict[str, SessionContext] = {}
    
    def create_session(self, user_id: str, organization_id: str, course_id: str) -> SessionContext:
        """Create a new AI authoring session."""
        # Verify user has access to course (permission check in router)
        
        session = SessionContext(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            organization_id=organization_id,
            course_id=course_id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        
        self._sessions[session.session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Get session by ID."""
        session = self._sessions.get(session_id)
        
        # Check expiry
        if session and session.expires_at < datetime.utcnow():
            del self._sessions[session_id]
            return None
        
        return session
    
    def validate_session_scope(self, session_id: str, course_id: str) -> bool:
        """Verify session has access to course."""
        session = self.get_session(session_id)
        if not session:
            return False
        return session.course_id == course_id
    
    def end_session(self, session_id: str):
        """End a session (cleanup)."""
        if session_id in self._sessions:
            del self._sessions[session_id]

session_manager = SessionManager()
```

**Acceptance Criteria:**
- ✅ Sessions created with immutable course_id
- ✅ Sessions expire after 24 hours
- ✅ get_session returns None for expired sessions
- ✅ validate_session_scope enforces course scoping
- ✅ Can end session explicitly

**Test:**
```python
def test_session_creation_and_expiry():
    session = session_manager.create_session("user1", "org1", "course1")
    assert session.session_id is not None
    assert session.course_id == "course1"
    
    # Should be retrievable
    retrieved = session_manager.get_session(session.session_id)
    assert retrieved is not None
    
    # Manually expire it
    retrieved.expires_at = datetime.utcnow() - timedelta(seconds=1)
    expired = session_manager.get_session(session.session_id)
    assert expired is None  # Auto-cleaned up

def test_session_scope_enforcement():
    session = session_manager.create_session("user1", "org1", "course1")
    
    assert session_manager.validate_session_scope(session.session_id, "course1")
    assert not session_manager.validate_session_scope(session.session_id, "course2")
```

---

### 2.2 Implement Re-Fetch-Before-Edit Rule

#### Task: Backend - Add session middleware to enforce re-fetch

**File:** `app/middleware/session_middleware.py`

```python
from fastapi import Request, HTTPException
from app.services.session_manager import session_manager

class SessionScopeMiddleware:
    """Middleware to enforce session scope on every tool call."""
    
    async def __call__(self, request: Request, call_next):
        # Extract session ID from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Session "):
            return await call_next(request)
        
        session_id = auth_header.replace("Session ", "")
        session = session_manager.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=401, detail="Session invalid or expired")
        
        # Attach to request state
        request.state.session = session
        
        return await call_next(request)
```

**Usage in tool endpoints:**

```python
from fastapi import Depends, HTTPException, Request

async def get_session(request: Request):
    session = getattr(request.state, "session", None)
    if not session:
        raise HTTPException(status_code=401, detail="No session")
    return session

@router.post("/tools/list_pages")
async def list_pages(session=Depends(get_session)):
    """Always fetches fresh data from DB, not from conversation history."""
    # Query DB directly
    pages = db.query(Page).filter(Page.course_id == session.course_id).all()
    return {"pages": [p.to_dict() for p in pages]}
```

**Acceptance Criteria:**
- ✅ Every tool call requires valid session in Authorization header
- ✅ Session scope enforced (can only access own course)
- ✅ Expired sessions rejected
- ✅ Data always fetched from DB (fresh state)
- ✅ Conversation history never used as state source

**Test:**
```python
def test_middleware_requires_session():
    response = client.post("/tools/list_pages", headers={})
    assert response.status_code == 401

def test_middleware_validates_scope():
    session = session_manager.create_session("user1", "org1", "course1")
    headers = {"Authorization": f"Session {session.session_id}"}
    
    # Request should succeed
    response = client.post("/tools/list_pages", headers=headers)
    assert response.status_code == 200
    
    # But data should only be for course1
    data = response.json()
    assert all(p["courseId"] == "course1" for p in data["pages"])
```

---

### 2.3 Add Permission Scoping Enforcement

#### Task: Backend - Enforce course ownership on page operations

**File:** `app/routers/ai_tools.py` (tool endpoint example)

```python
from fastapi import Depends, HTTPException, Request
from app.services.session_manager import session_manager

async def enforce_course_scope(page_id: str, session: SessionContext = Depends(get_session)):
    """Verify page belongs to session's course."""
    page = db.query(Page).filter(Page.id == page_id).first()
    
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    if page.course_id != session.course_id:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this page"
        )
    
    return page

@router.post("/tools/fetch_page")
async def tool_fetch_page(
    page_id: str,
    page: Page = Depends(enforce_course_scope),
    session: SessionContext = Depends(get_session),
):
    """Fetch page (with scope enforcement)."""
    # Log access
    ai_logger.log_request(
        session_id=session.session_id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        tool_name="fetch_page",
        input_hash=AIRequestLogger.sanitize_input({"page_id": page_id}),
        model_used="N/A"  # Not LLM yet
    )
    
    return {
        "page_id": page.id,
        "title": page.title,
        "template_type": page.template_type,
        "data": page.data,
    }
```

**Acceptance Criteria:**
- ✅ Pages from other courses cannot be accessed
- ✅ Permission denied returns 403 (not 404, to avoid info leak)
- ✅ All page operations enforce scope
- ✅ Audit log includes permission denials
- ✅ No data leakage on permission errors

**Test:**
```python
def test_course_scope_enforcement():
    # Create two courses and sessions
    session1 = session_manager.create_session("user1", "org1", "course1")
    session2 = session_manager.create_session("user1", "org1", "course2")
    
    # Create page in course1
    page1 = db.create_page(course_id="course1", title="Page 1", template_type="text-content")
    
    # Try to access page1 from session1 (should work)
    headers1 = {"Authorization": f"Session {session1.session_id}"}
    response = client.post("/tools/fetch_page", json={"page_id": page1.id}, headers=headers1)
    assert response.status_code == 200
    
    # Try to access page1 from session2 (should fail)
    headers2 = {"Authorization": f"Session {session2.session_id}"}
    response = client.post("/tools/fetch_page", json={"page_id": page1.id}, headers=headers2)
    assert response.status_code == 403
```

---

### 2.4 Add Session Endpoint to API

#### Task: Backend - Create session management endpoint

**File:** `app/routers/ai_sessions.py`

```python
from fastapi import APIRouter, HTTPException, Request, Depends
from app.services.session_manager import session_manager
from app.models.course import Course
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ai/sessions", tags=["AI Sessions"])

class CreateSessionRequest(BaseModel):
    user_id: str
    course_id: str
    organization_id: str

@router.post("")
def create_session(request: CreateSessionRequest):
    """Create a new AI authoring session."""
    # TODO: Verify user has permission to course
    # (In real app, check user_course_permissions table)
    
    session = session_manager.create_session(
        user_id=request.user_id,
        course_id=request.course_id,
        organization_id=request.organization_id,
    )
    
    return {
        "sessionId": session.session_id,
        "courseId": session.course_id,
        "userId": session.user_id,
        "organizationId": session.organization_id,
        "createdAt": session.created_at.isoformat(),
        "expiresAt": session.expires_at.isoformat(),
    }

@router.get("/{session_id}")
def get_session(session_id: str):
    """Get session details."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    
    return {
        "sessionId": session.session_id,
        "courseId": session.course_id,
        "userId": session.user_id,
        "expiresAt": session.expires_at.isoformat(),
    }

@router.delete("/{session_id}")
def end_session(session_id: str):
    """End a session."""
    session_manager.end_session(session_id)
    return {"status": "ended"}
```

**Acceptance Criteria:**
- ✅ POST /api/v1/ai/sessions creates session
- ✅ GET /api/v1/ai/sessions/{id} returns session details
- ✅ DELETE /api/v1/ai/sessions/{id} ends session
- ✅ Invalid session IDs return 404
- ✅ Permission checks in place

---

### 2.5 Frontend: Store and Use Session ID

#### Task: Frontend - Session management in React context

**File:** `src/context/AISessionContext.tsx`

```typescript
import React, { createContext, useState, useCallback } from "react";

interface AISession {
  sessionId: string;
  courseId: string;
  expiresAt: string;
}

interface AISessionContextType {
  session: AISession | null;
  createSession: (courseId: string) => Promise<void>;
  endSession: () => Promise<void>;
  isSessionActive: boolean;
}

export const AISessionContext = createContext<AISessionContextType | undefined>(undefined);

export function AISessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AISession | null>(null);

  const createSession = useCallback(async (courseId: string) => {
    const response = await fetch("/api/v1/ai/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: getCurrentUserId(), // Get from auth context
        course_id: courseId,
        organization_id: getCurrentOrgId(),
      }),
    });

    if (!response.ok) throw new Error("Failed to create session");

    const data = await response.json();
    setSession({
      sessionId: data.sessionId,
      courseId: data.courseId,
      expiresAt: data.expiresAt,
    });
    
    // Store in localStorage for persistence
    localStorage.setItem("ai_session", JSON.stringify(data));
  }, []);

  const endSession = useCallback(async () => {
    if (!session) return;
    
    await fetch(`/api/v1/ai/sessions/${session.sessionId}`, {
      method: "DELETE",
    });
    
    setSession(null);
    localStorage.removeItem("ai_session");
  }, [session]);

  const isSessionActive = session && new Date(session.expiresAt) > new Date();

  return (
    <AISessionContext.Provider value={{ session, createSession, endSession, isSessionActive: !!isSessionActive }}>
      {children}
    </AISessionContext.Provider>
  );
}

export function useAISession() {
  const context = React.useContext(AISessionContext);
  if (!context) {
    throw new Error("useAISession must be used within AISessionProvider");
  }
  return context;
}
```

**Usage in AI Chat Panel:**

```typescript
function AIChat Panel() {
  const { session, createSession, isSessionActive } = useAISession();
  const { courseId } = useParams();

  // Create session on mount
  useEffect(() => {
    if (!session && courseId) {
      createSession(courseId).catch(console.error);
    }
  }, [courseId, session]);

  if (!isSessionActive) {
    return <div>Session expired. Please refresh.</div>;
  }

  // Send session ID in all API calls
  const callTool = async (toolName: string, input: any) => {
    const response = await fetch(`/api/v1/ai/tools/${toolName}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Session ${session.sessionId}`, // Add session header
      },
      body: JSON.stringify(input),
    });
    return response.json();
  };

  return (
    <div>
      {/* Chat UI here */}
    </div>
  );
}
```

**Acceptance Criteria:**
- ✅ Session created when AI chat panel opens
- ✅ Session ID stored in localStorage
- ✅ Session ID sent in Authorization header
- ✅ Session expiry monitored; user warned
- ✅ Session automatically ends on logout

---

## Chunk 2 Sign-Off Checklist

- [ ] Session manager implemented with 24h expiry
- [ ] Session middleware enforces scope on every tool call
- [ ] Re-fetch-before-edit rule enforced (DB always source of truth)
- [ ] Permission scoping validated server-side
- [ ] API endpoints for session CRUD
- [ ] Frontend stores and uses session ID
- [ ] All tool calls authenticated with session header
- [ ] Expired sessions auto-cleaned up
- [ ] Audit log includes session context
- [ ] All tests pass (100% coverage)
- [ ] Code reviewed
- [ ] Deployed to dev environment
- [ ] Manual testing: session expires after 24h
- [ ] Manual testing: cannot access other users' courses
- [ ] **Product Owner Sign-Off:** ✅

**Exit Criteria Met:** DB = source of truth; permission scoping enforced server-side.

---

## Next Steps

### After Chunk 2 Sign-Off

1. **Begin Chunk 3:** Validation & Gating Pipeline
   - Propose → validate → confirm → apply flow
   - Destructive operation confirmation gates
   - Error recovery strategies

2. **Parallel: QA Test Case Development**
   - Begin writing E2E test cases for chunks 3–5
   - Prepare test data fixtures

3. **Release Planning**
   - Schedule Chunks 3–4 for week of [date]
   - Reserve staging environment

---

*Document Version: 1.0*  
*Status: Production Specification*  
*Last Updated: 2026-06-13*
