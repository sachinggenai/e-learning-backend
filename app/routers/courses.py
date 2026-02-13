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
from app.repositories.template_type_repo import (
    TemplateTypeRepository,
    TemplateTypeNotFoundError,
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

    model_config = {"from_attributes": True}

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

 
@router.get("/{courseId}", response_model=CourseOut)
async def get_course(
    courseId: str, repo: CourseRepository = Depends(_get_repo)
):
    try:
        course = await repo.get_by_course_id(courseId)
    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return course.to_dict()

 
@router.patch("/{courseId}", response_model=CourseOut)
async def update_course(
    courseId: str,
    payload: CourseUpdate,
    repo: CourseRepository = Depends(_get_repo),
):
    try:
        # First get the course to find its primary key
        course_record = await repo.get_by_course_id(courseId)
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

 
@router.delete("/{courseId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    courseId: str, repo: CourseRepository = Depends(_get_repo)
):
    try:
        # First get the course to find its primary key
        course_record = await repo.get_by_course_id(courseId)
        await repo.delete_record(course_record.id)
    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return None


# Add Page from Template Feature Endpoints


@router.get("/{courseId}/pages")
async def get_course_pages(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    """Get all pages for a course (DB-backed via PageRepository)."""
    from app.repositories.page_component_repo import PageRepository

    repo = PageRepository(session)
    pages = await repo.list_by_course(courseId)
    return [p.to_dict() for p in pages]


@router.post("/{courseId}/pages/from-template")
async def create_page_from_template(
    courseId: str,
    request: CreatePageFromTemplate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new page from a template (DB-backed)."""
    from datetime import datetime
    from app.repositories.page_component_repo import PageRepository

    # Verify template exists
    tmpl_repo = TemplateTypeRepository(session)
    try:
        template_record = await tmpl_repo.get_by_template_id(request.template_id)
    except TemplateTypeNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{request.template_id}' not found",
        )

    page_repo = PageRepository(session)

    # Determine order
    page_count = await page_repo.count_by_course(courseId)
    order = request.page_order if request.page_order is not None else page_count

    from app.models.page_component import PageRecord

    new_page = PageRecord(
        course_id=courseId,
        title=request.page_title,
        order_index=order,
        layout={"template_id": request.template_id, "customizations": request.customizations},
    )
    created = await page_repo.create(new_page)

    return {
        "page": {
            "id": created.page_id,
            "course_id": created.course_id,
            "title": created.title,
            "order_index": created.order_index,
            "layout": created.layout,
            "created_at": created.created_at.isoformat() if created.created_at else None,
            "updated_at": created.updated_at.isoformat() if created.updated_at else None,
        },
        "message": "Page added successfully from template",
    }


@router.get("/templates/available")
async def get_templates_for_pages(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "rating",
    repo: TemplateTypeRepository = Depends(
        lambda session=Depends(get_session): TemplateTypeRepository(session)
    ),
) -> dict:
    """Get available templates for creating course pages."""
    # Get templates from database (active only)
    templates = await repo.list(
        category=category if category and category != "all" else None,
        active_only=True,
    )

    # Search filter
    if search:
        search_lower = search.lower()
        templates = [
            t
            for t in templates
            if search_lower in t.name.lower()
            or search_lower in t.description.lower()
        ]

    # Sort templates
    if sort_by == "rating":
        templates = sorted(
            templates, key=lambda x: x.rating, reverse=True
        )
    elif sort_by == "usage":
        templates = sorted(
            templates, key=lambda x: x.usage_count, reverse=True
        )

    # Get categories
    categories = await repo.get_categories(active_only=True)

    # Convert to frontend format
    frontend_templates = []
    for i, template in enumerate(templates):
        frontend_templates.append(
            {
                "id": template.id,
                "templateId": template.template_id,
                "type": template.category,
                "title": template.name,
                "order": i,
                "data": {
                    "content": template.fields,
                    "description": template.description,
                },
            }
        )

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
                    if template_type:
                        # Known legacy types get specific validation
                        if template_type == "mcq":
                            errors.extend(_validate_mcq_page(page, i))
                        elif template_type == "content-text":
                            warnings.extend(_validate_content_text_page(page, i))
                        elif template_type == "welcome":
                            errors.extend(_validate_welcome_page(page, i))
                        # All other types are accepted (dynamic component types)

                    # Component-based page validation (new format)
                    components = page.get("components", [])
                    if components:
                        for ci, comp in enumerate(components):
                            if not isinstance(comp, dict):
                                errors.append(ValidationError(
                                    id=f"page-{i}-comp-{ci}-invalid",
                                    field=f"pages[{i}].components[{ci}]",
                                    category="schema",
                                    message=f"Component {ci + 1} on page {i + 1} must be an object",
                                    level="error"
                                ))
                                continue
                            if "component_type" not in comp and "componentType" not in comp:
                                errors.append(ValidationError(
                                    id=f"page-{i}-comp-{ci}-no-type",
                                    field=f"pages[{i}].components[{ci}].componentType",
                                    category="schema",
                                    message=f"Component {ci + 1} on page {i + 1} missing componentType",
                                    level="error"
                                ))

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
