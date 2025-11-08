"""Courses router providing CRUD endpoints for persisted courses.

Initial Phase 2 foundation: minimal CRUD over persisted JSON course data.
"""
from __future__ import annotations
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.db.config import get_session
from app.repositories.course_repo import (
    CourseRepository,
    CourseConflictError,
    CourseNotFoundError,
)

router = APIRouter(prefix="/courses", tags=["Courses"])

# Pydantic DTOs (simplified for initial scaffold)


class CourseCreate(BaseModel):
    courseId: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    data: dict = Field(default_factory=dict)


# New models for Add Page from Template feature

class CoursePage(BaseModel):
    """Individual page within a course"""
    id: str
    course_id: str
    title: str
    type: Optional[str] = None  # Page type for editor compatibility
    content: dict = {}
    template_id: Optional[str] = None
    page_order: int
    is_published: bool = True
    created_at: str
    updated_at: str


class ValidationError(BaseModel):
    id: str
    field: str
    category: str  # 'schema' | 'business' | 'template' | 'navigation'
    message: str
    level: str  # 'error' | 'warning' | 'info'
    context: Optional[dict] = None

class ValidationResult(BaseModel):
    valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    timestamp: str


class CourseValidationRequest(BaseModel):
    courseData: dict
    customizations: dict = {}
    page_order: Optional[int] = None

class TemplateForPages(BaseModel):
    """Template metadata for page creation"""
    id: str
    name: str
    description: str
    category: str
    thumbnail: str
    estimated_duration: Optional[int] = None  # minutes
    rating: float = 0.0
    usage_count: int = 0
    fields: List[dict] = []
    can_be_page: bool = True


class CourseUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    data: Optional[dict] = None
    status: Optional[str] = Field(None, pattern=r"^(draft|published)$")


class CreatePageFromTemplate(BaseModel):
    """Request model for creating a page from template"""
    template_id: str = Field(..., description="ID of the template to use")
    page_title: str = Field(..., description="Title for the new page")
    customizations: dict = Field(
        default_factory=dict, description="Custom field values"
    )
    page_order: Optional[int] = Field(
        None, description="Position in course (auto-assigned if not provided)"
    )


class CourseOut(BaseModel):
    id: int
    courseId: str
    title: str
    status: str
    description: Optional[str]
    createdAt: str
    updatedAt: str
    data: dict

    class Config:
        orm_mode = True

# Helpers ------------------------------------------------------------------


async def _get_repo(
    session: AsyncSession = Depends(get_session),
) -> CourseRepository:
    return CourseRepository(session)

# Routes -------------------------------------------------------------------


@router.post(
    "",
    response_model=CourseOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_course(
    payload: CourseCreate, repo: CourseRepository = Depends(_get_repo)
):
    try:
        record = await repo.create(
            course_id=payload.courseId,
            title=payload.title,
            description=payload.description,
            data=payload.data,
        )
    except CourseConflictError:
        raise HTTPException(status_code=400, detail="courseId already exists")
    return record.to_dict()

 
@router.get("", response_model=List[CourseOut])
async def list_courses(repo: CourseRepository = Depends(_get_repo)):
    courses = await repo.list()
    return [c.to_dict() for c in courses]

 
@router.get("/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: str, repo: CourseRepository = Depends(_get_repo)
):
    try:
        course = await repo.get_by_course_id(course_id)
    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return course.to_dict()

 
@router.patch("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: str,
    payload: CourseUpdate,
    repo: CourseRepository = Depends(_get_repo),
):
    try:
        # First get the course to find its primary key
        course_record = await repo.get_by_course_id(course_id)
        course = await repo.update_record(
            pk=course_record.id,
            title=payload.title,
            description=payload.description,
            data=payload.data,
            status=payload.status,
        )
    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return course.to_dict()

 
@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: str, repo: CourseRepository = Depends(_get_repo)
):
    try:
        # First get the course to find its primary key
        course_record = await repo.get_by_course_id(course_id)
        await repo.delete_record(course_record.id)
    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return None


# Add Page from Template Feature Endpoints

# In-memory storage for course pages (replace with database later)
COURSE_PAGES: dict = {}

# Mock template data for page creation  
TEMPLATES_FOR_PAGES = [
    {
        "id": "template_intro_001",
        "name": "Course Introduction", 
        "description": "Welcome page with course overview and objectives",
        "category": "introduction",
        "thumbnail": "/thumbnails/intro.png",
        "estimated_duration": 5,
        "rating": 4.7,
        "usage_count": 156,
        "can_be_page": True,
        "fields": [
            {
                "id": "course_title",
                "name": "courseTitle",
                "type": "text", 
                "label": "Course Title",
                "required": True,
                "placeholder": "Enter course title"
            }
        ]
    },
    {
        "id": "template_lab_001",
        "name": "Virtual Lab Setup",
        "description": "Interactive lab setup with equipment selection", 
        "category": "lab",
        "thumbnail": "/thumbnails/lab_setup.png",
        "estimated_duration": 15,
        "rating": 4.5,
        "usage_count": 89,
        "can_be_page": True,
        "fields": [
            {
                "id": "lab_name",
                "name": "labName",
                "type": "text",
                "label": "Lab Name", 
                "required": True
            }
        ]
    },
    {
        "id": "template_assessment_001",
        "name": "Quiz Assessment",
        "description": "Multiple choice quiz with automatic grading",
        "category": "assessment", 
        "thumbnail": "/thumbnails/quiz.png",
        "estimated_duration": 20,
        "rating": 4.3,
        "usage_count": 234,
        "can_be_page": True,
        "fields": [
            {
                "id": "quiz_title",
                "name": "quizTitle",
                "type": "text",
                "label": "Quiz Title",
                "required": True
            }
        ]
    }
]


@router.get("/{course_id}/pages", response_model=List[CoursePage])
async def get_course_pages(course_id: str) -> List[CoursePage]:
    """Get all pages for a course."""
    pages = COURSE_PAGES.get(course_id, [])
    return [
        CoursePage(**page)
        for page in sorted(pages, key=lambda x: x["page_order"])
    ]


@router.post("/{course_id}/pages/from-template")
async def create_page_from_template(
    course_id: str,
    request: CreatePageFromTemplate
) -> dict:
    """Create a new page from a template."""
    
    # Find the template
    template = None
    for t in TEMPLATES_FOR_PAGES:
        if t["id"] == request.template_id:
            template = t
            break
    
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{request.template_id}' not found")
    
    # Generate page content
    from datetime import datetime
    page_content = {
        "template_id": template["id"],
        "template_name": template["name"], 
        "fields": request.customizations,
        "generated_at": datetime.utcnow().isoformat()
    }
    
    # Map template category to page type for editor compatibility
    template_category_to_type = {
        "introduction": "content-text",
        "lab": "content-text",
        "assessment": "mcq"
    }
    
    page_type = template_category_to_type.get(
        template["category"], "content-text"
    )
    
    # Determine page order
    existing_pages = COURSE_PAGES.get(course_id, [])
    page_order = request.page_order if request.page_order else len(
        existing_pages
    ) + 1
    
    # Create new page
    page_id = f"page_{course_id}_{len(existing_pages) + 1}"
    
    new_page = {
        "id": page_id,
        "course_id": course_id,
        "title": request.page_title,
        "type": page_type,  # Add type field for PageEditor compatibility
        "content": page_content,
        "template_id": request.template_id,
        "page_order": page_order,
        "is_published": True,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    
    # Add page to course
    if course_id not in COURSE_PAGES:
        COURSE_PAGES[course_id] = []
    
    COURSE_PAGES[course_id].append(new_page)
    
    return {
        "page": new_page,
        "message": "Page added successfully from template"
    }


@router.get("/templates/available")
async def get_templates_for_pages(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "rating"
) -> dict:
    """Get available templates for creating course pages."""
    
    templates = TEMPLATES_FOR_PAGES.copy()
    
    # Filter by category
    if category and category != "all":
        templates = [t for t in templates if t["category"] == category]
    
    # Search filter
    if search:
        search_lower = search.lower()
        templates = [
            t for t in templates
            if search_lower in t["name"].lower() or
            search_lower in t["description"].lower()
        ]
    
    # Sort templates
    if sort_by == "rating":
        templates.sort(key=lambda x: x["rating"], reverse=True)
    elif sort_by == "usage":
        templates.sort(key=lambda x: x["usage_count"], reverse=True)
    
    # Get categories
    categories = list(set(t["category"] for t in TEMPLATES_FOR_PAGES))
    
    # Convert to frontend format
    frontend_templates = []
    for i, template in enumerate(templates):
        frontend_templates.append({
            "id": i + 1,
            "templateId": template["id"],
            "type": template["category"],
            "title": template["name"],
            "order": i,
            "data": {
                "content": template.get("fields", {}),
                "description": template["description"]
            }
        })
    
    return {
        "templates": frontend_templates,
        "categories": categories,
        "total_count": len(templates)
    }


@router.post("/validate", response_model=ValidationResult)
async def validate_course(request: CourseValidationRequest) -> ValidationResult:
    """
    Validate a course against business rules and schema requirements.
    Returns categorized validation errors and warnings.
    """
    def _validate_mcq_page(page: dict, index: int) -> List[ValidationError]:
        """Validate MCQ page content"""
        errors = []
        content = page.get("content", {})

        # Question validation
        question = content.get("question")
        if not question or not isinstance(question, str) or len(question.strip()) == 0:
            errors.append(ValidationError(
                id=f"page-{index}-mcq-no-question",
                field=f"pages[{index}].content.question",
                category="business",
                message=f"MCQ page {index + 1} must have a question",
                level="error"
            ))
        elif len(question.strip()) < 5:
            errors.append(ValidationError(
                id=f"page-{index}-mcq-short-question",
                field=f"pages[{index}].content.question",
                category="business",
                message=f"MCQ page {index + 1} question should be at least 5 characters long",
                level="warning"
            ))

        # Options validation
        options = content.get("options", [])
        if not isinstance(options, list) or len(options) < 2:
            errors.append(ValidationError(
                id=f"page-{index}-mcq-insufficient-options",
                field=f"pages[{index}].content.options",
                category="business",
                message=f"MCQ page {index + 1} must have at least 2 options",
                level="error"
            ))
        else:
            # Check each option has content
            for j, option in enumerate(options):
                if not option or not isinstance(option, str) or len(option.strip()) == 0:
                    errors.append(ValidationError(
                        id=f"page-{index}-mcq-empty-option-{j}",
                        field=f"pages[{index}].content.options[{j}]",
                        category="business",
                        message=f"MCQ page {index + 1} option {j + 1} cannot be empty",
                        level="error"
                    ))

        # Correct answer validation
        correct_answer = content.get("correctAnswer")
        if correct_answer is None or correct_answer == "":
            errors.append(ValidationError(
                id=f"page-{index}-mcq-no-correct-answer",
                field=f"pages[{index}].content.correctAnswer",
                category="business",
                message=f"MCQ page {index + 1} must have a correct answer selected",
                level="error"
            ))
        elif isinstance(options, list) and isinstance(correct_answer, int):
            if correct_answer < 0 or correct_answer >= len(options):
                errors.append(ValidationError(
                    id=f"page-{index}-mcq-invalid-correct-answer",
                    field=f"pages[{index}].content.correctAnswer",
                    category="business",
                    message=f"MCQ page {index + 1} correct answer index is out of range",
                    level="error"
                ))

        return errors

    def _validate_content_text_page(page: dict, index: int) -> List[ValidationError]:
        """Validate content-text page content"""
        warnings = []
        content = page.get("content", {})

        body = content.get("body")
        if not body or (isinstance(body, str) and len(body.strip()) == 0):
            warnings.append(ValidationError(
                id=f"page-{index}-content-no-body",
                field=f"pages[{index}].content.body",
                category="business",
                message=f"Content page {index + 1} should have body text",
                level="warning"
            ))

        return warnings

    def _validate_welcome_page(page: dict, index: int) -> List[ValidationError]:
        """Validate welcome page content"""
        errors = []
        content = page.get("content", {})

        title = content.get("title")
        if not title or not isinstance(title, str) or len(title.strip()) == 0:
            errors.append(ValidationError(
                id=f"page-{index}-welcome-no-title",
                field=f"pages[{index}].content.title",
                category="business",
                message=f"Welcome page {index + 1} must have a title",
                level="error"
            ))

        return errors

    try:
        course_data = request.courseData

        errors = []
        warnings = []

        # Basic schema validation
        if not isinstance(course_data, dict):
            errors.append(ValidationError(
                id="schema-invalid",
                field="root",
                category="schema",
                message="Course data must be an object",
                level="error"
            ))
            return ValidationResult(
                valid=False,
                errors=errors,
                warnings=warnings,
                timestamp="2024-01-01T00:00:00Z"  # Would use datetime.utcnow().isoformat()
            )

        # Required fields validation
        required_fields = ["courseId", "title", "pages"]
        for field in required_fields:
            if field not in course_data:
                errors.append(ValidationError(
                    id=f"missing-{field}",
                    field=field,
                    category="schema",
                    message=f"Required field '{field}' is missing",
                    level="error"
                ))

        # Title validation
        if "title" in course_data:
            title = course_data["title"]
            if not isinstance(title, str) or len(title.strip()) == 0:
                errors.append(ValidationError(
                    id="title-invalid",
                    field="title",
                    category="business",
                    message="Course title must be a non-empty string",
                    level="error"
                ))
            elif len(title) > 200:
                errors.append(ValidationError(
                    id="title-too-long",
                    field="title",
                    category="business",
                    message="Course title must be 200 characters or less",
                    level="warning"
                ))

        # Pages validation
        if "pages" in course_data:
            pages = course_data["pages"]
            if not isinstance(pages, list):
                errors.append(ValidationError(
                    id="pages-invalid",
                    field="pages",
                    category="schema",
                    message="Pages must be an array",
                    level="error"
                ))
            elif len(pages) == 0:
                errors.append(ValidationError(
                    id="pages-empty",
                    field="pages",
                    category="business",
                    message="Course must have at least one page",
                    level="error"
                ))
            else:
                # Validate each page
                for i, page in enumerate(pages):
                    if not isinstance(page, dict):
                        errors.append(ValidationError(
                            id=f"page-{i}-invalid",
                            field=f"pages[{i}]",
                            category="schema",
                            message=f"Page {i + 1} must be an object",
                            level="error"
                        ))
                        continue

                    # Check required page fields
                    if "id" not in page:
                        errors.append(ValidationError(
                            id=f"page-{i}-missing-id",
                            field=f"pages[{i}].id",
                            category="schema",
                            message=f"Page {i + 1} missing required 'id' field",
                            level="error"
                        ))

                    if "title" not in page:
                        errors.append(ValidationError(
                            id=f"page-{i}-missing-title",
                            field=f"pages[{i}].title",
                            category="schema",
                            message=f"Page {i + 1} missing required 'title' field",
                            level="error"
                        ))

                    # Template validation
                    template_type = page.get("templateType") or page.get("type")
                    if not template_type:
                        errors.append(ValidationError(
                            id=f"page-{i}-missing-template",
                            field=f"pages[{i}].templateType",
                            category="business",
                            message=f"Page {i + 1} missing template type",
                            level="error"
                        ))
                    elif template_type not in ["welcome", "content-text", "mcq", "summary"]:
                        warnings.append(ValidationError(
                            id=f"page-{i}-unknown-template",
                            field=f"pages[{i}].templateType",
                            category="business",
                            message=f"Page {i + 1} has unknown template type: {template_type}",
                            level="warning"
                        ))
                    else:
                        # Template-specific validation
                        if template_type == "mcq":
                            errors.extend(_validate_mcq_page(page, i))
                        elif template_type == "content-text":
                            warnings.extend(_validate_content_text_page(page, i))
                        elif template_type == "welcome":
                            errors.extend(_validate_welcome_page(page, i))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            timestamp="2024-01-01T00:00:00Z"  # Would use datetime.utcnow().isoformat()
        )

    except Exception as e:
        # Return error result for unexpected validation failures
        return ValidationResult(
            valid=False,
            errors=[ValidationError(
                id="validation-error",
                field="general",
                category="schema",
                message=f"Validation failed: {str(e)}",
                level="error"
            )],
            warnings=[],
            timestamp="2024-01-01T00:00:00Z"
        )
