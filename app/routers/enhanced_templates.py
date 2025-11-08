"""Enhanced Templates router with advanced features."""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.enhanced_templates import (
    TemplateSearchResult,
    CategoryUsageStats,
    EnhancedTemplate,
    FieldDefinition,
    LayoutDefinition,
    StylingDefinition,
    ValidationResponse,
    BatchPageRequest
)

router = APIRouter(prefix="/templates/enhanced", tags=["Enhanced Templates"])

# Sample category data for MVP
CATEGORIES = [
    {
        "id": "assessments",
        "name": "Assessments",
        "description": "Quizzes, tests, and evaluation templates",
        "color": "#FF6B6B",
        "icon": "quiz",
        "templateCount": 15,
        "subcategories": ["quiz", "test", "survey", "poll"]
    },
    {
        "id": "interactive",
        "name": "Interactive Content",
        "description": "Engaging interactive learning experiences",
        "color": "#4ECDC4",
        "icon": "interactive",
        "templateCount": 22,
        "subcategories": ["simulation", "game", "drag-drop", "hotspot"]
    },
    {
        "id": "presentations",
        "name": "Presentations",
        "description": "Slide-based content and presentations",
        "color": "#45B7D1",
        "icon": "presentation",
        "templateCount": 18,
        "subcategories": ["slides", "infographic", "timeline", "process"]
    }
]

# Sample template data
TEMPLATES = [
    {
        "id": "quiz_basic_001",
        "templateId": "quiz_basic",
        "name": "Basic Multiple Choice Quiz",
        "description": "Simple quiz template with automatic scoring",
        "category": "assessments",
        "type": "quiz",
        "tags": ["quiz", "multiple-choice", "assessment"],
    },
    {
        "id": "interactive_sim_001",
        "templateId": "simulation_basic",
        "name": "Interactive Simulation",
        "description": "Drag-and-drop simulation template",
        "category": "interactive",
        "type": "simulation",
        "tags": ["simulation", "drag-drop", "interactive"],
    }
]


@router.get("/categories", summary="Get all template categories")
async def get_template_categories(
    include_stats: bool = False,
) -> List[Dict[str, Any]]:
    """Get all available template categories."""
    categories = []
    
    for category_data in CATEGORIES:
        category = {
            "id": category_data["id"],
            "name": category_data["name"],
            "description": category_data["description"],
            "color": category_data["color"],
            "icon": category_data["icon"],
            "templateCount": category_data["templateCount"],
            "subcategories": category_data["subcategories"]
        }
        
        if include_stats:
            category["stats"] = {
                "totalUsage": category_data["templateCount"] * 10,
                "recentUsage": category_data["templateCount"] * 2,
                "averageRating": 4.2,
                "trending": category_data["id"] in [
                    "interactive", "assessments"
                ]
            }
            
        categories.append(category)
    
    return categories


@router.get("/categories/{category_id}")
async def get_category_details(
    category_id: str,
    include_templates: bool = False,
) -> Dict[str, Any]:
    """Get detailed information about a specific template category."""
    # Find category
    category_data = next(
        (cat for cat in CATEGORIES if cat["id"] == category_id),
        None
    )
    
    if not category_data:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category_id}' not found"
        )
    
    category = {
        "id": category_data["id"],
        "name": category_data["name"],
        "description": category_data["description"],
        "color": category_data["color"],
        "icon": category_data["icon"],
        "templateCount": category_data["templateCount"],
        "subcategories": category_data["subcategories"],
        "stats": {
            "totalUsage": category_data["templateCount"] * 10,
            "recentUsage": category_data["templateCount"] * 2,
            "averageRating": 4.2,
            "trending": category_data["id"] in ["interactive", "assessments"]
        }
    }
    
    if include_templates:
        # Filter templates by category
        category_templates = [
            template for template in TEMPLATES
            if template.get("category") == category_id
        ]
        category["sampleTemplates"] = category_templates[:5]
    
    return category


@router.get("/categories/{category_id}/stats")
async def get_category_stats(
    category_id: str,
    period: str = "30d",
) -> CategoryUsageStats:
    """Get detailed usage statistics for a specific category."""
    # Find category
    category_data = next(
        (cat for cat in CATEGORIES if cat["id"] == category_id),
        None
    )
    
    if not category_data:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category_id}' not found"
        )
    
    # Return mock statistics
    stats = CategoryUsageStats(
        categoryId=category_id,
        categoryName=category_data["name"],
        templateCount=category_data["templateCount"],
        totalUsage=category_data["templateCount"] * 15,
        averageRating=4.2
    )
    
    return stats


@router.get("/search", summary="Search and filter templates")
async def search_templates(
    query: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> TemplateSearchResult:
    """Search and filter templates with advanced options."""
    # Parse tags
    tag_list = []
    if tags:
        tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
    
    # Filter templates (mock implementation)
    filtered_templates = TEMPLATES.copy()
    
    # Apply filters
    if query:
        filtered_templates = [
            t for t in filtered_templates
            if (query.lower() in t["name"].lower() or
                query.lower() in t["description"].lower())
        ]
    
    if category:
        filtered_templates = [
            t for t in filtered_templates
            if t.get("category") == category
        ]
    
    if tag_list:
        filtered_templates = [
            t for t in filtered_templates
            if any(tag in t.get("tags", []) for tag in tag_list)
        ]
    
    # Apply pagination
    total_results = len(filtered_templates)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_templates = filtered_templates[start_idx:end_idx]
    
    # Convert to response format
    template_objects = []
    for template_data in paginated_templates:
        template = {
            "id": template_data["id"],
            "templateId": template_data["templateId"],
            "name": template_data["name"],
            "description": template_data["description"]
        }
        template_objects.append(template)
    
    return TemplateSearchResult(
        templates=template_objects,
        totalResults=total_results,
        page=page,
        limit=limit,
        totalPages=(total_results + limit - 1) // limit,
        searchTime=45.2,
        suggestions=["quiz", "interactive"] if query else None
    )


@router.get("", summary="Get enhanced templates")
async def get_enhanced_templates(
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get enhanced templates with advanced features and metadata."""
    templates = TEMPLATES.copy()
    
    # Apply category filter
    if category:
        templates = [
            t for t in templates
            if t.get("category") == category
        ]
    
    return templates


# Custom Template Management Models


class CreateCustomTemplateRequest(BaseModel):
    """Request model for creating custom templates"""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=1000)
    category: str = Field(..., description="Template category ID")
    type: str = Field(..., description="Template type")
    fields: List[FieldDefinition] = Field(..., min_items=1)
    layout: LayoutDefinition = Field(default_factory=LayoutDefinition)
    styling: Optional[StylingDefinition] = None
    sampleContent: Optional[Dict[str, Any]] = None
    isPublic: bool = False
    tags: List[str] = []


class UpdateCustomTemplateRequest(BaseModel):
    """Request model for updating custom templates"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=1000)
    category: Optional[str] = None
    fields: Optional[List[FieldDefinition]] = None
    layout: Optional[LayoutDefinition] = None
    styling: Optional[StylingDefinition] = None
    sampleContent: Optional[Dict[str, Any]] = None
    isPublic: Optional[bool] = None
    tags: Optional[List[str]] = None


class CustomTemplateResponse(BaseModel):
    """Response model for custom template operations"""
    template: Dict[str, Any]
    validationResult: ValidationResponse
    previewUrl: str


# In-memory storage for custom templates (MVP implementation)
CUSTOM_TEMPLATES: List[Dict[str, Any]] = []


# Custom Template Management Endpoints


@router.post("/custom", summary="Create custom template")
async def create_custom_template(
    request: CreateCustomTemplateRequest,
) -> CustomTemplateResponse:
    """Create a new custom template with validation."""
    
    # Generate template ID
    timestamp = int(datetime.utcnow().timestamp())
    template_id = f"custom_{len(CUSTOM_TEMPLATES) + 1}_{timestamp}"
    
    # Validate template structure
    validation_errors = []
    
    # Check for duplicate field IDs
    field_ids = [field.id for field in request.fields]
    if len(field_ids) != len(set(field_ids)):
        validation_errors.append({
            "field": "fields",
            "message": "Duplicate field IDs found",
            "code": "DUPLICATE_FIELD_ID"
        })
    
    # Validate field types and configurations
    for field in request.fields:
        if field.type in ["select", "multiselect"] and not field.options:
            validation_errors.append({
                "field": f"fields.{field.id}.options",
                "message": "Select fields must have options",
                "code": "MISSING_FIELD_OPTIONS"
            })
    
    # Create validation response
    validation_result = ValidationResponse(
        valid=len(validation_errors) == 0,
        errors=validation_errors
    )
    
    if not validation_result.valid:
        return CustomTemplateResponse(
            template={},
            validationResult=validation_result,
            previewUrl=""
        )
    
    # Create the custom template
    new_template = {
        "id": template_id,
        "templateId": template_id,
        "name": request.name,
        "description": request.description,
        "category": request.category,
        "type": request.type,
        "fields": [field.dict() for field in request.fields],
        "layout": request.layout.dict(),
        "styling": request.styling.dict() if request.styling else None,
        "sampleContent": request.sampleContent,
        "isCustom": True,
        "isPublic": request.isPublic,
        "tags": request.tags,
        "createdBy": "current_user_id",  # Would be from authentication
        "createdAt": datetime.utcnow().isoformat(),
        "updatedAt": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "usageCount": 0
    }
    
    # Store the template
    CUSTOM_TEMPLATES.append(new_template)
    
    # Generate preview URL
    preview_url = f"/api/v1/templates/enhanced/custom/{template_id}/preview"
    
    return CustomTemplateResponse(
        template=new_template,
        validationResult=validation_result,
        previewUrl=preview_url
    )


@router.get("/custom", summary="Get custom templates")
async def get_custom_templates(
    include_public: bool = True,
    category: Optional[str] = None,
    created_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get list of custom templates with filtering options."""
    
    templates = CUSTOM_TEMPLATES.copy()
    
    # Apply filters
    if not include_public:
        templates = [t for t in templates if not t.get("isPublic", False)]
    
    if category:
        templates = [t for t in templates if t.get("category") == category]
    
    if created_by:
        templates = [t for t in templates if t.get("createdBy") == created_by]
    
    return templates


@router.get("/custom/{template_id}", summary="Get custom template details")
async def get_custom_template(template_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific custom template."""
    
    template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    return template


@router.put("/custom/{template_id}", summary="Update custom template")
async def update_custom_template(
    template_id: str,
    request: UpdateCustomTemplateRequest,
) -> CustomTemplateResponse:
    """Update an existing custom template."""
    
    # Find the template
    template_index = next(
        (i for i, t in enumerate(CUSTOM_TEMPLATES) if t["id"] == template_id),
        None
    )
    
    if template_index is None:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    template = CUSTOM_TEMPLATES[template_index]
    
    # Update fields that were provided
    if request.name is not None:
        template["name"] = request.name
    if request.description is not None:
        template["description"] = request.description
    if request.category is not None:
        template["category"] = request.category
    if request.fields is not None:
        template["fields"] = [field.dict() for field in request.fields]
    if request.layout is not None:
        template["layout"] = request.layout.dict()
    if request.styling is not None:
        template["styling"] = request.styling.dict()
    if request.sampleContent is not None:
        template["sampleContent"] = request.sampleContent
    if request.isPublic is not None:
        template["isPublic"] = request.isPublic
    if request.tags is not None:
        template["tags"] = request.tags
    
    # Update timestamp
    template["updatedAt"] = datetime.utcnow().isoformat()
    
    # Validate updated template
    validation_result = ValidationResponse(valid=True, errors=[])
    
    # Update in storage
    CUSTOM_TEMPLATES[template_index] = template
    
    preview_url = f"/api/v1/templates/enhanced/custom/{template_id}/preview"
    
    return CustomTemplateResponse(
        template=template,
        validationResult=validation_result,
        previewUrl=preview_url
    )


@router.delete("/custom/{template_id}", summary="Delete custom template")
async def delete_custom_template(template_id: str):
    """Delete a custom template."""
    
    template_index = next(
        (i for i, t in enumerate(CUSTOM_TEMPLATES) if t["id"] == template_id),
        None
    )
    
    if template_index is None:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    # Remove from storage
    CUSTOM_TEMPLATES.pop(template_index)
    
    return {"message": f"Template '{template_id}' deleted successfully"}


@router.post("/custom/{template_id}/duplicate", summary="Duplicate custom template")
async def duplicate_custom_template(
    template_id: str,
    new_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a copy of an existing custom template."""
    
    # Find original template
    original_template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not original_template:
        raise HTTPException(
            status_code=404,
            detail=f"Custom template '{template_id}' not found"
        )
    
    # Create duplicate
    new_id = f"custom_{len(CUSTOM_TEMPLATES) + 1}_{int(datetime.utcnow().timestamp())}"
    
    duplicate_template = original_template.copy()
    duplicate_template.update({
        "id": new_id,
        "templateId": new_id,
        "name": new_name or f"{original_template['name']} (Copy)",
        "createdAt": datetime.utcnow().isoformat(),
        "updatedAt": datetime.utcnow().isoformat(),
        "usageCount": 0
    })
    
    # Store the duplicate
    CUSTOM_TEMPLATES.append(duplicate_template)
    
    return duplicate_template


@router.get("/builder/components", summary="Get template builder components")
async def get_builder_components() -> Dict[str, Any]:
    """Get available components for template builder interface."""
    
    return {
        "fieldTypes": [
            {
                "type": "text",
                "label": "Text Input",
                "description": "Single-line text input field",
                "icon": "text-fields",
                "category": "basic",
                "configurable": ["label", "placeholder", "required", "validation"]
            },
            {
                "type": "rich-text",
                "label": "Rich Text Editor",
                "description": "Multi-line text with formatting options",
                "icon": "format-text",
                "category": "basic",
                "configurable": ["label", "required", "toolbarOptions"]
            },
            {
                "type": "media",
                "label": "Media Upload",
                "description": "File upload for images, videos, documents",
                "icon": "cloud-upload",
                "category": "media",
                "configurable": ["label", "required", "mediaTypes", "maxFileSize"]
            },
            {
                "type": "select",
                "label": "Dropdown Select",
                "description": "Single selection from predefined options",
                "icon": "arrow-drop-down",
                "category": "basic",
                "configurable": ["label", "required", "options"]
            },
            {
                "type": "multiselect",
                "label": "Multiple Selection",
                "description": "Multiple selections from predefined options",
                "icon": "check-box",
                "category": "basic",
                "configurable": ["label", "required", "options"]
            },
            {
                "type": "number",
                "label": "Number Input",
                "description": "Numeric input with validation",
                "icon": "123",
                "category": "basic",
                "configurable": ["label", "required", "min", "max"]
            },
            {
                "type": "boolean",
                "label": "Checkbox",
                "description": "True/false checkbox input",
                "icon": "check-box",
                "category": "basic",
                "configurable": ["label", "required"]
            }
        ],
        "layoutOptions": [
            {
                "type": "single-column",
                "name": "Single Column",
                "description": "All fields in a single column layout"
            },
            {
                "type": "two-column",
                "name": "Two Column",
                "description": "Fields arranged in two columns"
            },
            {
                "type": "grid",
                "name": "Grid Layout",
                "description": "Flexible grid-based layout"
            }
        ],
        "validationRules": [
            {
                "type": "required",
                "label": "Required Field",
                "description": "Field must be filled",
                "applicableTypes": ["text", "rich-text", "media", "select", "number"]
            },
            {
                "type": "minLength",
                "label": "Minimum Length",
                "description": "Minimum number of characters",
                "applicableTypes": ["text", "rich-text"]
            },
            {
                "type": "maxLength",
                "label": "Maximum Length",
                "description": "Maximum number of characters",
                "applicableTypes": ["text", "rich-text"]
            },
            {
                "type": "pattern",
                "label": "Pattern Matching",
                "description": "Must match regular expression pattern",
                "applicableTypes": ["text"]
            }
        ]
    }


# Phase 3: Batch Operations & Template Sharing


class BatchPageCreateRequest(BaseModel):
    """Request for creating multiple pages from templates"""
    pages: List[BatchPageRequest] = Field(..., min_items=1, max_items=100)
    commonSettings: Optional[Dict[str, Any]] = None
    insertPosition: str = "end"  # "start", "end", or position index
    dryRun: bool = False


class BatchProgressResponse(BaseModel):
    """Batch operation progress response"""
    batchId: str
    status: str  # "pending", "processing", "completed", "failed"
    progress: float  # 0.0 to 100.0
    totalItems: int
    processedItems: int
    createdPages: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    estimatedTimeRemaining: Optional[int] = None  # seconds


class ShareTemplateRequest(BaseModel):
    """Request for sharing a template"""
    shareType: str = Field(..., pattern="^(link|email|organization|public)$")
    permissions: Dict[str, bool] = Field(
        default={
            "canView": True,
            "canEdit": False,
            "canComment": False,
            "canShare": False,
            "canDelete": False
        }
    )
    expiresAt: Optional[datetime] = None
    message: Optional[str] = None
    recipients: Optional[List[str]] = None  # For email sharing
    organizationId: Optional[str] = None  # For organization sharing


class ShareTemplateResponse(BaseModel):
    """Response for template sharing operation"""
    shareId: str
    shareUrl: Optional[str] = None
    shareType: str
    permissions: Dict[str, bool]
    createdAt: datetime
    expiresAt: Optional[datetime] = None
    recipients: Optional[List[Dict[str, Any]]] = None


# In-memory storage for batch operations and shares
BATCH_OPERATIONS: Dict[str, Dict[str, Any]] = {}
TEMPLATE_SHARES: Dict[str, Dict[str, Any]] = {}


# Batch Operations Endpoints


@router.post("/batch/pages", summary="Create multiple pages from templates")
async def create_pages_batch(
    course_id: int,
    request: BatchPageCreateRequest,
) -> BatchProgressResponse:
    """
    Create multiple pages from templates in a batch operation.
    Supports dry-run validation and progress tracking.
    """
    
    # Generate batch ID
    timestamp = int(datetime.utcnow().timestamp())
    batch_id = f"batch_{len(BATCH_OPERATIONS) + 1}_{timestamp}"
    
    # Validate batch request
    validation_errors = []
    
    # Check for duplicate titles
    titles = [page.title for page in request.pages]
    if len(titles) != len(set(titles)):
        validation_errors.append({
            "error": "Duplicate page titles found in batch",
            "code": "DUPLICATE_TITLES"
        })
    
    # Validate each page request
    for i, page_req in enumerate(request.pages):
        # Check template exists (simulate)
        template_exists = any(
            t["templateId"] == page_req.templateId
            for t in TEMPLATES + CUSTOM_TEMPLATES
        )
        
        if not template_exists:
            validation_errors.append({
                "pageIndex": i,
                "pageTitle": page_req.title,
                "error": f"Template '{page_req.templateId}' not found",
                "code": "TEMPLATE_NOT_FOUND",
                "recoverable": False
            })
    
    # Handle dry run
    if request.dryRun:
        return BatchProgressResponse(
            batchId="",
            status="completed",
            progress=100.0,
            totalItems=len(request.pages),
            processedItems=0,
            createdPages=[],
            errors=validation_errors
        )
    
    # If validation errors exist, return them
    if validation_errors:
        return BatchProgressResponse(
            batchId=batch_id,
            status="failed",
            progress=0.0,
            totalItems=len(request.pages),
            processedItems=0,
            createdPages=[],
            errors=validation_errors
        )
    
    # Create batch operation record
    batch_operation = {
        "batchId": batch_id,
        "courseId": course_id,
        "status": "processing",
        "progress": 0.0,
        "totalItems": len(request.pages),
        "processedItems": 0,
        "createdPages": [],
        "errors": [],
        "startedAt": datetime.utcnow().isoformat(),
        "estimatedTimeRemaining": len(request.pages) * 2,  # 2 seconds per page
        "request": request.dict()
    }
    
    # Store batch operation
    BATCH_OPERATIONS[batch_id] = batch_operation
    
    # Simulate batch processing (in real implementation, this would be async)
    created_pages = []
    for i, page_req in enumerate(request.pages):
        try:
            # Simulate page creation
            new_page = {
                "id": f"page_{batch_id}_{i}",
                "courseId": course_id,
                "templateId": page_req.templateId,
                "title": page_req.title,
                "content": page_req.content or {},
                "configuration": page_req.configuration or {},
                "tags": page_req.tags or [],
                "createdAt": datetime.utcnow().isoformat(),
                "order": i
            }
            created_pages.append(new_page)
            
            # Update progress
            batch_operation["processedItems"] = i + 1
            batch_operation["progress"] = ((i + 1) / len(request.pages)) * 100
            batch_operation["createdPages"] = created_pages
            
        except Exception as e:
            batch_operation["errors"].append({
                "pageIndex": i,
                "pageTitle": page_req.title,
                "error": str(e),
                "code": "CREATION_ERROR",
                "recoverable": True
            })
    
    # Mark as completed
    if batch_operation["errors"]:
        batch_operation["status"] = "failed"
    else:
        batch_operation["status"] = "completed"
    batch_operation["completedAt"] = datetime.utcnow().isoformat()
    batch_operation["estimatedTimeRemaining"] = 0
    
    return BatchProgressResponse(**batch_operation)


@router.get("/batch/{batch_id}", summary="Get batch operation status")
async def get_batch_status(batch_id: str) -> BatchProgressResponse:
    """Get the current status of a batch operation."""
    
    batch_operation = BATCH_OPERATIONS.get(batch_id)
    
    if not batch_operation:
        raise HTTPException(
            status_code=404,
            detail=f"Batch operation '{batch_id}' not found"
        )
    
    return BatchProgressResponse(**batch_operation)


@router.get("/batch", summary="List batch operations")
async def list_batch_operations(
    batch_status: Optional[str] = None,
    limit: int = 20,
) -> List[BatchProgressResponse]:
    """List batch operations with optional status filtering."""
    
    operations = list(BATCH_OPERATIONS.values())
    
    if batch_status:
        operations = [op for op in operations if op["status"] == batch_status]
    
    # Sort by creation time (newest first)
    operations.sort(
        key=lambda x: x.get("startedAt", ""),
        reverse=True
    )
    
    return [BatchProgressResponse(**op) for op in operations[:limit]]


# Template Sharing Endpoints


@router.post("/custom/{template_id}/share", summary="Share a custom template")
async def share_template(
    template_id: str,
    request: ShareTemplateRequest,
) -> ShareTemplateResponse:
    """Share a custom template with specified permissions and recipients."""
    
    # Find the template
    template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Generate share ID
    timestamp = int(datetime.utcnow().timestamp())
    share_id = f"share_{len(TEMPLATE_SHARES) + 1}_{timestamp}"
    
    # Generate share URL based on share type
    share_url = None
    recipients_data = []
    
    if request.shareType == "link":
        share_url = f"http://localhost:3000/templates/shared/{share_id}"
    
    elif request.shareType == "email" and request.recipients:
        share_url = f"http://localhost:3000/templates/shared/{share_id}"
        recipients_data = [
            {
                "email": email,
                "status": "pending",
                "invitedAt": datetime.utcnow().isoformat()
            }
            for email in request.recipients
        ]
    
    elif request.shareType == "public":
        share_url = f"http://localhost:3000/templates/public/{template_id}"
        # Mark template as public
        template["isPublic"] = True
    
    elif request.shareType == "organization" and request.organizationId:
        org_id = request.organizationId
        base_url = "http://localhost:3000/templates/org"
        share_url = f"{base_url}/{org_id}/{template_id}"
    
    # Create share record
    share_record = {
        "shareId": share_id,
        "templateId": template_id,
        "shareType": request.shareType,
        "permissions": request.permissions,
        "shareUrl": share_url,
        "createdAt": datetime.utcnow(),
        "expiresAt": request.expiresAt,
        "message": request.message,
        "recipients": recipients_data,
        "organizationId": request.organizationId,
        "sharedBy": "current_user_id",  # Would be from authentication
        "isActive": True
    }
    
    # Store share record
    TEMPLATE_SHARES[share_id] = share_record
    
    return ShareTemplateResponse(
        shareId=share_id,
        shareUrl=share_url,
        shareType=request.shareType,
        permissions=request.permissions,
        createdAt=share_record["createdAt"],
        expiresAt=request.expiresAt,
        recipients=recipients_data if recipients_data else None
    )


@router.get("/shares", summary="Get shared templates")
async def get_shared_templates(
    shared_with_me: bool = False,
    shared_by_me: bool = False,
) -> List[Dict[str, Any]]:
    """Get templates shared with or by the current user."""
    
    shares = list(TEMPLATE_SHARES.values())
    
    if shared_by_me:
        # Filter by current user (simulate)
        shares = [s for s in shares if s.get("sharedBy") == "current_user_id"]
    
    # Add template information to shares
    enriched_shares = []
    for share in shares:
        template = next(
            (t for t in CUSTOM_TEMPLATES if t["id"] == share["templateId"]),
            None
        )
        
        if template:
            enriched_share = {
                **share,
                "template": {
                    "name": template["name"],
                    "description": template["description"],
                    "category": template["category"],
                    "tags": template["tags"]
                }
            }
            enriched_shares.append(enriched_share)
    
    return enriched_shares


@router.put("/shares/{share_id}", summary="Update share permissions")
async def update_share_permissions(
    share_id: str,
    permissions: Dict[str, bool],
) -> Dict[str, Any]:
    """Update permissions for an existing template share."""
    
    share_record = TEMPLATE_SHARES.get(share_id)
    
    if not share_record:
        raise HTTPException(
            status_code=404,
            detail=f"Share '{share_id}' not found"
        )
    
    # Update permissions
    share_record["permissions"] = permissions
    share_record["updatedAt"] = datetime.utcnow().isoformat()
    
    return {
        "shareId": share_id,
        "permissions": permissions,
        "message": "Permissions updated successfully"
    }


@router.delete("/shares/{share_id}", summary="Revoke template share")
async def revoke_template_share(share_id: str) -> Dict[str, str]:
    """Revoke access to a shared template."""
    
    if share_id not in TEMPLATE_SHARES:
        raise HTTPException(
            status_code=404,
            detail=f"Share '{share_id}' not found"
        )
    
    # Remove share record
    del TEMPLATE_SHARES[share_id]
    
    return {"message": f"Template share '{share_id}' revoked successfully"}


@router.get("/analytics/usage", summary="Get template usage analytics")
async def get_template_usage_analytics() -> Dict[str, Any]:
    """Get comprehensive template usage analytics."""
    
    # Calculate analytics from stored data
    total_templates = len(TEMPLATES) + len(CUSTOM_TEMPLATES)
    total_custom_templates = len(CUSTOM_TEMPLATES)
    total_shares = len(TEMPLATE_SHARES)
    total_batch_operations = len(BATCH_OPERATIONS)
    
    # Most used templates (mock data)
    most_used = [
        {
            "templateId": "quiz_basic_001",
            "name": "Basic Quiz",
            "usageCount": 45
        },
        {
            "templateId": "interactive_sim_001",
            "name": "Interactive Simulation",
            "usageCount": 32
        },
    ]
    
    # Recent activity
    recent_batches = [op for op in BATCH_OPERATIONS.values()][-5:]
    recent_shares = [share for share in TEMPLATE_SHARES.values()][-5:]
    
    return {
        "overview": {
            "totalTemplates": total_templates,
            "customTemplates": total_custom_templates,
            "activeShares": total_shares,
            "batchOperations": total_batch_operations
        },
        "usage": {
            "mostUsedTemplates": most_used,
            "averageCustomTemplatesPerUser": 2.5,
            "sharingAdoptionRate": 0.75
        },
        "activity": {
            "recentBatches": recent_batches,
            "recentShares": recent_shares
        },
        "performance": {
            "averageBatchTime": "15.2 seconds",
            "successRate": 0.94,
            "avgPagesPerBatch": 6.8
        },
        "generatedAt": datetime.utcnow().isoformat()
    }


# Phase 3.1: Advanced Collaboration Features


class TemplateCommentRequest(BaseModel):
    """Request for adding comments to templates"""
    content: str = Field(..., min_length=1, max_length=1000)
    parentCommentId: Optional[str] = None  # For threaded comments
    mentionedUsers: Optional[List[str]] = []


class TemplateComment(BaseModel):
    """Template comment model"""
    id: str
    templateId: str
    userId: str
    userName: str
    content: str
    parentCommentId: Optional[str] = None
    mentionedUsers: List[str] = []
    createdAt: datetime
    updatedAt: Optional[datetime] = None
    isResolved: bool = False
    reactions: Dict[str, int] = {}  # emoji -> count


class TemplateVersionRequest(BaseModel):
    """Request for creating template versions"""
    versionNote: str = Field(..., min_length=1, max_length=500)
    changes: Dict[str, Any]
    isMajor: bool = False


class TemplateVersion(BaseModel):
    """Template version model"""
    id: str
    templateId: str
    version: str
    versionNote: str
    changes: Dict[str, Any]
    createdBy: str
    createdAt: datetime
    isMajor: bool
    templateSnapshot: Dict[str, Any]


class AdvancedSearchRequest(BaseModel):
    """Advanced search request with multiple criteria"""
    query: Optional[str] = None
    categories: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    authors: Optional[List[str]] = []
    dateRange: Optional[Dict[str, str]] = None  # Date range filter
    usageRange: Optional[Dict[str, int]] = None  # {"min": 0, "max": 100}
    isPublic: Optional[bool] = None
    hasShares: Optional[bool] = None
    sortBy: str = "relevance"  # relevance, created, updated, usage, name
    sortOrder: str = "desc"  # asc, desc
    page: int = 1
    pageSize: int = 20


# In-memory storage for new features
TEMPLATE_COMMENTS: Dict[str, List[Dict[str, Any]]] = {}
TEMPLATE_VERSIONS: Dict[str, List[Dict[str, Any]]] = {}


# Template Comments API


@router.post("/custom/{template_id}/comments",
             summary="Add comment to template")
async def add_template_comment(
    template_id: str,
    request: TemplateCommentRequest,
) -> TemplateComment:
    """Add a comment to a template for collaboration."""
    
    # Verify template exists
    template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Generate comment ID
    comment_count = len(TEMPLATE_COMMENTS.get(template_id, []))
    timestamp = int(datetime.utcnow().timestamp())
    comment_id = f"comment_{comment_count + 1}_{timestamp}"
    
    # Create comment
    comment = {
        "id": comment_id,
        "templateId": template_id,
        "userId": "current_user_id",  # Would be from auth
        "userName": "Current User",
        "content": request.content,
        "parentCommentId": request.parentCommentId,
        "mentionedUsers": request.mentionedUsers or [],
        "createdAt": datetime.utcnow(),
        "updatedAt": None,
        "isResolved": False,
        "reactions": {}
    }
    
    # Store comment
    if template_id not in TEMPLATE_COMMENTS:
        TEMPLATE_COMMENTS[template_id] = []
    
    TEMPLATE_COMMENTS[template_id].append(comment)
    
    return TemplateComment(**comment)


@router.get("/custom/{template_id}/comments", summary="Get template comments")
async def get_template_comments(
    template_id: str,
    include_resolved: bool = False,
) -> List[TemplateComment]:
    """Get all comments for a template."""
    
    comments = TEMPLATE_COMMENTS.get(template_id, [])
    
    if not include_resolved:
        comments = [c for c in comments if not c.get("isResolved", False)]
    
    # Sort by creation time
    comments.sort(key=lambda x: x.get("createdAt", datetime.min))
    
    return [TemplateComment(**comment) for comment in comments]


@router.put("/comments/{comment_id}/resolve", summary="Resolve comment")
async def resolve_comment(comment_id: str) -> Dict[str, str]:
    """Mark a comment as resolved."""
    
    # Find and update comment
    for template_id, comments in TEMPLATE_COMMENTS.items():
        for comment in comments:
            if comment["id"] == comment_id:
                comment["isResolved"] = True
                comment["updatedAt"] = datetime.utcnow()
                return {"message": f"Comment '{comment_id}' resolved"}
    
    raise HTTPException(
        status_code=404,
        detail=f"Comment '{comment_id}' not found"
    )


# Template Versioning API


@router.post("/custom/{template_id}/versions",
             summary="Create template version")
async def create_template_version(
    template_id: str,
    request: TemplateVersionRequest,
) -> TemplateVersion:
    """Create a new version of a template."""
    
    # Find template
    template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Get existing versions
    existing_versions = TEMPLATE_VERSIONS.get(template_id, [])
    
    # Calculate new version number
    if not existing_versions:
        new_version = "1.0.0"
    else:
        latest_version = existing_versions[-1]["version"]
        major, minor, patch = map(int, latest_version.split('.'))
        
        if request.isMajor:
            new_version = f"{major + 1}.0.0"
        else:
            new_version = f"{major}.{minor}.{patch + 1}"
    
    # Create version record
    version_count = len(existing_versions) + 1
    timestamp = int(datetime.utcnow().timestamp())
    version_id = f"version_{version_count}_{timestamp}"
    
    version_record = {
        "id": version_id,
        "templateId": template_id,
        "version": new_version,
        "versionNote": request.versionNote,
        "changes": request.changes,
        "createdBy": "current_user_id",
        "createdAt": datetime.utcnow(),
        "isMajor": request.isMajor,
        "templateSnapshot": template.copy()  # Full template backup
    }
    
    # Store version
    if template_id not in TEMPLATE_VERSIONS:
        TEMPLATE_VERSIONS[template_id] = []
    
    TEMPLATE_VERSIONS[template_id].append(version_record)
    
    # Update template version
    template["version"] = new_version
    template["updatedAt"] = datetime.utcnow().isoformat()
    
    return TemplateVersion(**version_record)


@router.get("/custom/{template_id}/versions", summary="Get template versions")
async def get_template_versions(template_id: str) -> List[TemplateVersion]:
    """Get all versions of a template."""
    
    versions = TEMPLATE_VERSIONS.get(template_id, [])
    
    # Sort by creation time (newest first)
    versions.sort(key=lambda x: x.get("createdAt", datetime.min), reverse=True)
    
    return [TemplateVersion(**version) for version in versions]


@router.post("/custom/{template_id}/versions/{version_id}/restore",
             summary="Restore template version")
async def restore_template_version(
    template_id: str,
    version_id: str,
) -> Dict[str, str]:
    """Restore a template to a previous version."""
    
    # Find version
    versions = TEMPLATE_VERSIONS.get(template_id, [])
    version_to_restore = next(
        (v for v in versions if v["id"] == version_id),
        None
    )
    
    if not version_to_restore:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version_id}' not found"
        )
    
    # Find template
    template_index = next(
        (i for i, t in enumerate(CUSTOM_TEMPLATES) if t["id"] == template_id),
        None
    )
    
    if template_index is None:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Restore template from snapshot
    restored_template = version_to_restore["templateSnapshot"].copy()
    restored_template["updatedAt"] = datetime.utcnow().isoformat()
    
    # Replace current template
    CUSTOM_TEMPLATES[template_index] = restored_template
    
    version_num = version_to_restore['version']
    return {"message": f"Template restored to version '{version_num}'"}


# Advanced Search API


@router.post("/search/advanced", summary="Advanced template search")
async def advanced_template_search(
    request: AdvancedSearchRequest,
) -> Dict[str, Any]:
    """Perform advanced search with multiple criteria and filters."""
    
    # Combine all templates
    all_templates = []
    
    # Add standard templates
    for template in TEMPLATES:
        all_templates.append({
            **template,
            "isCustom": False,
            "author": "system",
            "createdAt": "2025-01-01T00:00:00",
            "usageCount": 25  # Mock data
        })
    
    # Add custom templates
    for template in CUSTOM_TEMPLATES:
        all_templates.append({
            **template,
            "isCustom": True,
            "author": template.get("createdBy", "unknown"),
            "usageCount": 5  # Mock data
        })
    
    # Apply filters
    filtered_templates = all_templates.copy()
    
    # Text search
    if request.query:
        query_lower = request.query.lower()
        filtered_templates = [
            t for t in filtered_templates
            if query_lower in t.get("name", "").lower() or
            query_lower in t.get("description", "").lower() or
            any(query_lower in tag.lower() for tag in t.get("tags", []))
        ]
    
    # Category filter
    if request.categories:
        filtered_templates = [
            t for t in filtered_templates
            if t.get("category") in request.categories
        ]
    
    # Tags filter
    if request.tags:
        filtered_templates = [
            t for t in filtered_templates
            if any(tag in t.get("tags", []) for tag in request.tags)
        ]
    
    # Author filter
    if request.authors:
        filtered_templates = [
            t for t in filtered_templates
            if t.get("author") in request.authors
        ]
    
    # Public filter
    if request.isPublic is not None:
        filtered_templates = [
            t for t in filtered_templates
            if t.get("isPublic", False) == request.isPublic
        ]
    
    # Usage range filter
    if request.usageRange:
        min_usage = request.usageRange.get("min", 0)
        max_usage = request.usageRange.get("max", 999999)
        filtered_templates = [
            t for t in filtered_templates
            if min_usage <= t.get("usageCount", 0) <= max_usage
        ]
    
    # Sort results
    if request.sortBy == "name":
        filtered_templates.sort(
            key=lambda x: x.get("name", ""),
            reverse=(request.sortOrder == "desc")
        )
    elif request.sortBy == "created":
        filtered_templates.sort(
            key=lambda x: x.get("createdAt", ""),
            reverse=(request.sortOrder == "desc")
        )
    elif request.sortBy == "usage":
        filtered_templates.sort(
            key=lambda x: x.get("usageCount", 0),
            reverse=(request.sortOrder == "desc")
        )
    
    # Pagination
    total_count = len(filtered_templates)
    start_index = (request.page - 1) * request.pageSize
    end_index = start_index + request.pageSize
    paginated_templates = filtered_templates[start_index:end_index]
    
    # Calculate pagination info
    total_pages = (total_count + request.pageSize - 1) // request.pageSize
    
    return {
        "templates": paginated_templates,
        "pagination": {
            "currentPage": request.page,
            "totalPages": total_pages,
            "totalCount": total_count,
            "pageSize": request.pageSize,
            "hasNext": request.page < total_pages,
            "hasPrevious": request.page > 1
        },
        "filters": {
            "appliedFilters": {
                "query": request.query,
                "categories": request.categories,
                "tags": request.tags,
                "authors": request.authors,
                "isPublic": request.isPublic
            },
            "availableFilters": {
                "categories": list(set(
                    t.get("category") for t in all_templates
                    if t.get("category")
                )),
                "tags": list(set(
                    tag for t in all_templates
                    for tag in t.get("tags", [])
                )),
                "authors": list(set(
                    t.get("author") for t in all_templates
                    if t.get("author")
                ))
            }
        },
        "searchMeta": {
            "executionTime": "0.05s",
            "searchId": f"search_{int(datetime.utcnow().timestamp())}",
            "timestamp": datetime.utcnow().isoformat()
        }
    }


# Phase 4: Enterprise Integration & Advanced Features


# 4.1 Real-time Collaboration Models


class TemplateCollaboratorRequest(BaseModel):
    """Request for adding collaborators to templates"""
    userId: str
    role: str = Field(..., pattern="^(viewer|editor|reviewer|admin)$")
    permissions: Dict[str, bool] = Field(
        default={
            "canView": True,
            "canEdit": False,
            "canComment": True,
            "canApprove": False,
            "canManageCollaborators": False
        }
    )
    expiresAt: Optional[datetime] = None


class TemplateCollaborator(BaseModel):
    """Template collaborator model"""
    userId: str
    userName: str
    userEmail: str
    role: str
    permissions: Dict[str, bool]
    addedAt: datetime
    addedBy: str
    expiresAt: Optional[datetime] = None
    lastActiveAt: Optional[datetime] = None
    isOnline: bool = False


class WorkflowStage(BaseModel):
    """Workflow stage model"""
    id: str
    name: str
    description: str
    requiredRole: str
    autoAdvance: bool = False
    reviewers: List[str] = []
    approvalThreshold: int = 1  # Number of approvals needed
    maxReviewTime: Optional[int] = None  # Hours


class TemplateWorkflow(BaseModel):
    """Template workflow model"""
    id: str
    templateId: str
    workflowType: str = Field(..., pattern="^(review|approval|publishing)$")
    currentStage: str
    stages: List[WorkflowStage]
    status: str = Field(
        ...,
        pattern="^(pending|in_progress|approved|rejected|published)$"
    )
    createdBy: str
    createdAt: datetime
    completedAt: Optional[datetime] = None
    metadata: Dict[str, Any] = {}


class ApprovalRequest(BaseModel):
    """Approval request model"""
    action: str = Field(..., pattern="^(approve|reject|request_changes)$")
    comment: Optional[str] = Field(None, max_length=1000)
    reviewNotes: Optional[Dict[str, Any]] = None
    suggestedChanges: Optional[List[Dict[str, str]]] = None


class ActivityEvent(BaseModel):
    """Real-time activity event model"""
    id: str
    templateId: str
    userId: str
    userName: str
    eventType: str  # created, edited, commented, shared, approved, etc.
    eventData: Dict[str, Any]
    timestamp: datetime
    isSystemEvent: bool = False


# 4.2 AI-Powered Features Models


class AIRecommendationRequest(BaseModel):
    """Request for AI-powered template recommendations"""
    userId: str
    context: Dict[str, Any]  # Course context, subject, difficulty level
    preferences: Optional[Dict[str, Any]] = None
    excludeTemplateIds: Optional[List[str]] = []
    maxRecommendations: int = 5


class AIRecommendation(BaseModel):
    """AI recommendation response"""
    templateId: str
    templateName: str
    relevanceScore: float  # 0.0 to 1.0
    reason: str
    tags: List[str]
    category: str
    usageStats: Dict[str, Any]


class ContentAnalysisRequest(BaseModel):
    """Request for AI content analysis"""
    content: Dict[str, Any]
    analysisTypes: List[str] = Field(
        default=["quality", "accessibility", "engagement", "difficulty"]
    )


class ContentAnalysisResult(BaseModel):
    """AI content analysis result"""
    overallScore: float  # 0.0 to 100.0
    qualityMetrics: Dict[str, float]
    accessibilityIssues: List[Dict[str, str]]
    engagementPredictions: Dict[str, float]
    suggestions: List[Dict[str, str]]
    difficultyLevel: str
    readabilityScore: float


# In-memory storage for Phase 4 features
TEMPLATE_COLLABORATORS: Dict[str, List[Dict[str, Any]]] = {}
TEMPLATE_WORKFLOWS: Dict[str, Dict[str, Any]] = {}
ACTIVITY_EVENTS: List[Dict[str, Any]] = []
AI_RECOMMENDATIONS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


# Real-time Collaboration Endpoints


@router.post("/custom/{template_id}/collaborators",
             summary="Add collaborator to template")
async def add_template_collaborator(
    template_id: str,
    request: TemplateCollaboratorRequest,
) -> TemplateCollaborator:
    """Add a collaborator to a template with specific permissions."""
    
    # Verify template exists
    template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Check if user is already a collaborator
    existing_collaborators = TEMPLATE_COLLABORATORS.get(template_id, [])
    user_exists = any(
        collab["userId"] == request.userId
        for collab in existing_collaborators
    )
    if user_exists:
        raise HTTPException(
            status_code=400,
            detail=f"User '{request.userId}' is already a collaborator"
        )
    
    # Create collaborator record
    collaborator = {
        "userId": request.userId,
        "userName": f"User {request.userId}",  # Would fetch from user service
        "userEmail": f"{request.userId}@example.com",
        "role": request.role,
        "permissions": request.permissions,
        "addedAt": datetime.utcnow(),
        "addedBy": "current_user_id",
        "expiresAt": request.expiresAt,
        "lastActiveAt": None,
        "isOnline": False
    }
    
    # Store collaborator
    if template_id not in TEMPLATE_COLLABORATORS:
        TEMPLATE_COLLABORATORS[template_id] = []
    
    TEMPLATE_COLLABORATORS[template_id].append(collaborator)
    
    # Create activity event
    await _create_activity_event(
        template_id,
        "collaborator_added",
        {"collaboratorId": request.userId, "role": request.role}
    )
    
    return TemplateCollaborator(**collaborator)


@router.get("/custom/{template_id}/collaborators",
            summary="Get template collaborators")
async def get_template_collaborators(
    template_id: str,
) -> List[TemplateCollaborator]:
    """Get all collaborators for a template."""
    
    collaborators = TEMPLATE_COLLABORATORS.get(template_id, [])
    return [TemplateCollaborator(**collab) for collab in collaborators]


@router.delete("/custom/{template_id}/collaborators/{user_id}",
               summary="Remove collaborator")
async def remove_template_collaborator(
    template_id: str,
    user_id: str,
) -> Dict[str, str]:
    """Remove a collaborator from a template."""
    
    collaborators = TEMPLATE_COLLABORATORS.get(template_id, [])
    
    # Find and remove collaborator
    for i, collab in enumerate(collaborators):
        if collab["userId"] == user_id:
            collaborators.pop(i)
            
            # Create activity event
            await _create_activity_event(
                template_id,
                "collaborator_removed",
                {"collaboratorId": user_id}
            )
            
            return {"message": f"Collaborator '{user_id}' removed"}
    
    raise HTTPException(
        status_code=404,
        detail=f"Collaborator '{user_id}' not found"
    )


# Workflow Management Endpoints


@router.post("/custom/{template_id}/workflow",
             summary="Create workflow for template")
async def create_template_workflow(
    template_id: str,
    workflow_type: str = "review",
    reviewers: Optional[List[str]] = None,
) -> TemplateWorkflow:
    """Create an approval/review workflow for a template."""
    
    # Verify template exists
    template = next(
        (t for t in CUSTOM_TEMPLATES if t["id"] == template_id),
        None
    )
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Create workflow stages based on type
    stages = []
    if workflow_type == "review":
        stages = [
            WorkflowStage(
                id="draft",
                name="Draft",
                description="Template in draft state",
                requiredRole="editor"
            ),
            WorkflowStage(
                id="review",
                name="Under Review",
                description="Template under peer review",
                requiredRole="reviewer",
                reviewers=reviewers or ["reviewer1", "reviewer2"],
                approvalThreshold=2
            ),
            WorkflowStage(
                id="approved",
                name="Approved",
                description="Template approved for use",
                requiredRole="admin"
            )
        ]
    elif workflow_type == "approval":
        stages = [
            WorkflowStage(
                id="pending",
                name="Pending Approval",
                description="Awaiting approval",
                requiredRole="reviewer"
            ),
            WorkflowStage(
                id="approved",
                name="Approved",
                description="Template approved",
                requiredRole="admin"
            )
        ]
    
    # Create workflow
    timestamp = int(datetime.utcnow().timestamp())
    workflow_id = f"workflow_{template_id}_{timestamp}"
    workflow = {
        "id": workflow_id,
        "templateId": template_id,
        "workflowType": workflow_type,
        "currentStage": stages[0].id,
        "stages": [stage.dict() for stage in stages],
        "status": "pending",
        "createdBy": "current_user_id",
        "createdAt": datetime.utcnow(),
        "completedAt": None,
        "metadata": {}
    }
    
    # Store workflow
    TEMPLATE_WORKFLOWS[workflow_id] = workflow
    
    # Create activity event
    await _create_activity_event(
        template_id,
        "workflow_created",
        {"workflowId": workflow_id, "type": workflow_type}
    )
    
    return TemplateWorkflow(**workflow)


@router.post("/workflows/{workflow_id}/approve",
             summary="Approve/reject workflow stage")
async def process_workflow_approval(
    workflow_id: str,
    request: ApprovalRequest,
) -> Dict[str, Any]:
    """Process an approval/rejection for a workflow stage."""
    
    workflow = TEMPLATE_WORKFLOWS.get(workflow_id)
    
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{workflow_id}' not found"
        )
    
    current_stage = workflow["currentStage"]
    template_id = workflow["templateId"]
    
    # Process the approval
    approval_record = {
        "reviewerId": "current_user_id",
        "action": request.action,
        "comment": request.comment,
        "reviewNotes": request.reviewNotes,
        "suggestedChanges": request.suggestedChanges,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Add to workflow metadata
    if "approvals" not in workflow["metadata"]:
        workflow["metadata"]["approvals"] = []
    
    workflow["metadata"]["approvals"].append(approval_record)
    
    # Update workflow status based on action
    if request.action == "approve":
        # Move to next stage or complete workflow
        stages = workflow["stages"]
        current_stage_index = next(
            (i for i, stage in enumerate(stages)
             if stage["id"] == current_stage),
            None
        )
        
        is_not_last_stage = (
            current_stage_index is not None and
            current_stage_index < len(stages) - 1
        )
        if is_not_last_stage:
            workflow["currentStage"] = stages[current_stage_index + 1]["id"]
            workflow["status"] = "in_progress"
        else:
            workflow["status"] = "approved"
            workflow["completedAt"] = datetime.utcnow().isoformat()
    
    elif request.action == "reject":
        workflow["status"] = "rejected"
        workflow["completedAt"] = datetime.utcnow().isoformat()
    
    # Create activity event
    await _create_activity_event(
        template_id,
        f"workflow_{request.action}",
        {
            "workflowId": workflow_id,
            "stage": current_stage,
            "comment": request.comment
        }
    )
    
    return {
        "workflowId": workflow_id,
        "status": workflow["status"],
        "currentStage": workflow["currentStage"],
        "message": f"Workflow {request.action} processed successfully"
    }


@router.get("/custom/{template_id}/workflow",
            summary="Get template workflow status")
async def get_template_workflow(
    template_id: str
) -> Optional[TemplateWorkflow]:
    """Get the current workflow status for a template."""
    
    # Find workflow for template
    for workflow in TEMPLATE_WORKFLOWS.values():
        if workflow["templateId"] == template_id:
            return TemplateWorkflow(**workflow)
    
    return None


# AI-Powered Features Endpoints


@router.post("/ai/recommendations", summary="Get AI template recommendations")
async def get_ai_recommendations(
    request: AIRecommendationRequest,
) -> List[AIRecommendation]:
    """Get AI-powered template recommendations based on context."""
    
    # Cache key for recommendations
    cache_key = f"{request.userId}_{hash(str(request.context))}"
    
    # Check cache first
    if cache_key in AI_RECOMMENDATIONS_CACHE:
        cached_recommendations = AI_RECOMMENDATIONS_CACHE[cache_key]
        return [AIRecommendation(**rec) for rec in cached_recommendations]
    
    # Simulate AI recommendation logic
    all_templates = TEMPLATES + CUSTOM_TEMPLATES
    recommendations = []
    
    context_subject = request.context.get("subject", "").lower()
    
    for template in all_templates:
        # Skip excluded templates
        if template["id"] in request.excludeTemplateIds:
            continue
        
        # Calculate relevance score based on context
        relevance_score = 0.0
        reason_parts = []
        
        # Subject matching
        if context_subject:
            template_tags = [tag.lower() for tag in template.get("tags", [])]
            if context_subject in template_tags:
                relevance_score += 0.4
                reason_parts.append(f"matches {context_subject} subject")
            elif any(context_subject in tag for tag in template_tags):
                relevance_score += 0.2
                reason_parts.append(f"related to {context_subject}")
        
        # Template type matching
        template_type = template.get("type", "")
        context_str = str(request.context).lower()
        
        if template_type == "quiz" and "assessment" in context_str:
            relevance_score += 0.3
            reason_parts.append("assessment type match")
        elif template_type == "simulation" and "interactive" in context_str:
            relevance_score += 0.3
            reason_parts.append("interactive content match")
        
        # Usage popularity boost
        usage_count = template.get("usageCount", 0)
        if usage_count > 20:
            relevance_score += 0.2
            reason_parts.append("popular template")
        
        # Category matching
        template_category = template.get("category", "")
        context_category = request.context.get("category", "")
        if template_category == context_category:
            relevance_score += 0.3
            reason_parts.append(f"category match: {template_category}")
        
        # Only include templates with reasonable relevance
        if relevance_score >= 0.3:
            recommendations.append({
                "templateId": template["id"],
                "templateName": template["name"],
                "relevanceScore": min(relevance_score, 1.0),
                "reason": "; ".join(reason_parts) or "general recommendation",
                "tags": template.get("tags", []),
                "category": template.get("category", ""),
                "usageStats": {
                    "usageCount": template.get("usageCount", 0),
                    "averageRating": 4.2,
                    "recentUsage": template.get("usageCount", 0) * 0.1
                }
            })
    
    # Sort by relevance score and limit results
    recommendations.sort(key=lambda x: x["relevanceScore"], reverse=True)
    recommendations = recommendations[:request.maxRecommendations]
    
    # Cache the results
    AI_RECOMMENDATIONS_CACHE[cache_key] = recommendations
    
    return [AIRecommendation(**rec) for rec in recommendations]


@router.post("/ai/content-analysis",
             summary="Analyze template content with AI")
async def analyze_template_content(
    request: ContentAnalysisRequest,
) -> ContentAnalysisResult:
    """Perform AI-powered content analysis for quality and accessibility."""
    
    # Simulate AI analysis
    analysis_result = {
        "overallScore": 85.5,
        "qualityMetrics": {
            "clarity": 88.0,
            "structure": 82.0,
            "completeness": 90.0,
            "engagement": 85.0
        },
        "accessibilityIssues": [
            {
                "issue": "Missing alt text for images",
                "severity": "medium",
                "suggestion": "Add descriptive alt text for all images"
            },
            {
                "issue": "Insufficient color contrast",
                "severity": "low",
                "suggestion": "Increase contrast ratio to meet WCAG standards"
            }
        ],
        "engagementPredictions": {
            "completionRate": 0.82,
            "averageTimeSpent": 12.5,
            "interactionScore": 0.75
        },
        "suggestions": [
            {
                "type": "improvement",
                "suggestion": "Add more interactive elements"
            },
            {
                "type": "optimization",
                "suggestion": "Break down long text sections"
            },
            {
                "type": "accessibility",
                "suggestion": "Use semantic HTML headings"
            }
        ],
        "difficultyLevel": "intermediate",
        "readabilityScore": 78.5
    }
    
    return ContentAnalysisResult(**analysis_result)


@router.post("/ai/auto-tag", summary="Generate AI-powered tags")
async def generate_auto_tags(
    template_content: Dict[str, Any],
    max_tags: int = 10,
) -> Dict[str, Any]:
    """Generate relevant tags for template content using AI."""
    
    # Simulate AI tag generation based on content
    content_text = str(template_content).lower()
    
    # Predefined tag categories and keywords
    tag_mapping = {
        "subjects": {
            "math": ["mathematics", "algebra", "geometry", "calculus", "statistics"],
            "science": ["physics", "chemistry", "biology", "astronomy"],
            "language": ["english", "writing", "grammar", "literature"],
            "history": ["historical", "ancient", "modern", "civilization"],
            "technology": ["computer", "programming", "coding", "digital"]
        },
        "difficulty": {
            "beginner": ["basic", "introduction", "fundamentals", "starter"],
            "intermediate": ["intermediate", "standard", "regular"],
            "advanced": ["advanced", "complex", "expert", "mastery"]
        },
        "format": {
            "quiz": ["quiz", "test", "assessment", "question"],
            "interactive": ["interactive", "simulation", "game", "drag"],
            "video": ["video", "media", "visual", "watching"],
            "text": ["reading", "text", "article", "document"]
        }
    }
    
    suggested_tags = []
    confidence_scores = {}
    
    # Analyze content for tag suggestions
    for category, subcategories in tag_mapping.items():
        for tag, keywords in subcategories.items():
            score = sum(1 for keyword in keywords if keyword in content_text)
            if score > 0:
                confidence = min(score / len(keywords), 1.0)
                suggested_tags.append(tag)
                confidence_scores[tag] = confidence
    
    # Sort by confidence and limit
    suggested_tags.sort(key=lambda tag: confidence_scores.get(tag, 0), reverse=True)
    suggested_tags = suggested_tags[:max_tags]
    
    return {
        "suggestedTags": suggested_tags,
        "confidenceScores": confidence_scores,
        "analysisMetadata": {
            "contentLength": len(str(template_content)),
            "analysisTime": "0.15s",
            "modelVersion": "auto-tag-v2.1"
        }
    }


# Activity Events and Real-time Updates


@router.get("/custom/{template_id}/activity",
           summary="Get template activity stream")
async def get_template_activity(
    template_id: str,
    limit: int = 50,
) -> List[ActivityEvent]:
    """Get real-time activity stream for a template."""
    
    # Filter events for specific template
    template_events = [
        event for event in ACTIVITY_EVENTS
        if event.get("templateId") == template_id
    ]
    
    # Sort by timestamp (newest first) and limit
    template_events.sort(
        key=lambda x: x.get("timestamp", datetime.min),
        reverse=True
    )
    
    return [ActivityEvent(**event) for event in template_events[:limit]]


@router.get("/activity/global", summary="Get global activity stream")
async def get_global_activity(limit: int = 100) -> List[ActivityEvent]:
    """Get global activity stream across all templates."""
    
    # Sort by timestamp (newest first) and limit
    sorted_events = sorted(
        ACTIVITY_EVENTS,
        key=lambda x: x.get("timestamp", datetime.min),
        reverse=True
    )
    
    return [ActivityEvent(**event) for event in sorted_events[:limit]]


# Helper Functions


async def _create_activity_event(
    template_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    is_system_event: bool = False
) -> str:
    """Create and store an activity event."""
    
    event_id = f"event_{len(ACTIVITY_EVENTS) + 1}_{int(datetime.utcnow().timestamp())}"
    
    event = {
        "id": event_id,
        "templateId": template_id,
        "userId": "current_user_id" if not is_system_event else "system",
        "userName": "Current User" if not is_system_event else "System",
        "eventType": event_type,
        "eventData": event_data,
        "timestamp": datetime.utcnow(),
        "isSystemEvent": is_system_event
    }
    
    ACTIVITY_EVENTS.append(event)
    
    # Keep only last 1000 events to prevent memory bloat
    if len(ACTIVITY_EVENTS) > 1000:
        ACTIVITY_EVENTS.pop(0)
    
    return event_id


# Phase 4.2: Advanced Enterprise Features


# SSO Integration & Enterprise Security


class SSOConfiguration(BaseModel):
    """SSO configuration model for enterprise integration"""
    provider: str = Field(..., pattern="^(saml|oauth2|oidc|ldap|azure_ad)$")
    enabled: bool = True
    metadata: Dict[str, Any]
    redirectUrl: str
    clientId: Optional[str] = None
    clientSecret: Optional[str] = None
    discoveryUrl: Optional[str] = None
    certificateData: Optional[str] = None


class UserProfile(BaseModel):
    """Enhanced user profile with enterprise attributes"""
    userId: str
    username: str
    email: str
    fullName: str
    roles: List[str]
    departments: List[str]
    organization: str
    permissions: Dict[str, bool]
    ssoProvider: Optional[str] = None
    lastLoginAt: Optional[datetime] = None
    profilePicture: Optional[str] = None
    preferences: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}


class SecurityAuditLog(BaseModel):
    """Security audit log for compliance"""
    logId: str
    userId: str
    action: str
    resourceId: str
    resourceType: str
    ipAddress: str
    userAgent: str
    timestamp: datetime
    success: bool
    details: Dict[str, Any]
    riskLevel: str = Field(..., pattern="^(low|medium|high|critical)$")


class APIKey(BaseModel):
    """API key management for enterprise integrations"""
    keyId: str
    name: str
    description: str
    keyHash: str  # Hashed version, never store plain text
    permissions: List[str]
    organizationId: str
    createdBy: str
    createdAt: datetime
    expiresAt: Optional[datetime] = None
    lastUsedAt: Optional[datetime] = None
    isActive: bool = True
    usageCount: int = 0
    rateLimitPerHour: int = 1000


# Advanced Analytics Models


class AnalyticsDashboard(BaseModel):
    """Advanced analytics dashboard configuration"""
    dashboardId: str
    name: str
    description: str
    widgets: List[Dict[str, Any]]
    filters: Dict[str, Any]
    refreshInterval: int = 300  # seconds
    permissions: Dict[str, List[str]]  # role -> permissions
    isPublic: bool = False
    createdBy: str
    createdAt: datetime


class AnalyticsMetric(BaseModel):
    """Analytics metric definition"""
    metricId: str
    name: str
    description: str
    category: str
    formula: str
    dataSource: str
    aggregationType: str = Field(..., pattern="^(sum|avg|count|max|min)$")
    dimensions: List[str]
    filters: Dict[str, Any] = {}


class PerformanceReport(BaseModel):
    """Comprehensive performance analytics report"""
    reportId: str
    templateId: Optional[str] = None
    timeRange: Dict[str, str]
    metrics: Dict[str, float]
    trends: Dict[str, List[float]]
    comparisons: Dict[str, Dict[str, float]]
    insights: List[Dict[str, str]]
    recommendations: List[Dict[str, str]]
    generatedAt: datetime


# Mobile & Offline Capabilities


class MobileSession(BaseModel):
    """Mobile session management"""
    sessionId: str
    userId: str
    deviceInfo: Dict[str, str]
    platform: str = Field(..., pattern="^(ios|android|web)$")
    appVersion: str
    lastSyncAt: datetime
    offlineCapabilities: Dict[str, bool]
    syncQueue: List[Dict[str, Any]] = []


class OfflineData(BaseModel):
    """Offline data synchronization"""
    dataId: str
    userId: str
    templateId: str
    dataType: str = Field(..., pattern="^(template|comment|version|activity)$")
    operation: str = Field(..., pattern="^(create|update|delete|sync)$")
    data: Dict[str, Any]
    timestamp: datetime
    syncStatus: str = Field(..., pattern="^(pending|synced|failed|conflict)$")
    conflictResolution: Optional[Dict[str, Any]] = None


# In-memory storage for Phase 4.2 features
SSO_CONFIGURATIONS: Dict[str, Dict[str, Any]] = {}
USER_PROFILES: Dict[str, Dict[str, Any]] = {}
SECURITY_AUDIT_LOGS: List[Dict[str, Any]] = []
API_KEYS: Dict[str, Dict[str, Any]] = {}
ANALYTICS_DASHBOARDS: Dict[str, Dict[str, Any]] = {}
MOBILE_SESSIONS: Dict[str, Dict[str, Any]] = {}
OFFLINE_DATA_QUEUE: List[Dict[str, Any]] = []


# SSO Integration Endpoints


@router.post("/enterprise/sso/configure", summary="Configure SSO provider")
async def configure_sso_provider(
    request: SSOConfiguration,
) -> Dict[str, Any]:
    """Configure Single Sign-On provider for enterprise authentication."""
    
    config_id = f"sso_{request.provider}_{int(datetime.utcnow().timestamp())}"
    
    sso_config = {
        "configId": config_id,
        "provider": request.provider,
        "enabled": request.enabled,
        "metadata": request.metadata,
        "redirectUrl": request.redirectUrl,
        "clientId": request.clientId,
        "clientSecret": "***ENCRYPTED***" if request.clientSecret else None,
        "discoveryUrl": request.discoveryUrl,
        "certificateData": "***ENCRYPTED***" if request.certificateData else None,
        "createdAt": datetime.utcnow().isoformat(),
        "lastModified": datetime.utcnow().isoformat()
    }
    
    SSO_CONFIGURATIONS[config_id] = sso_config
    
    # Create audit log
    await _create_security_audit_log(
        "system",
        "sso_configured",
        config_id,
        "sso_configuration",
        {"provider": request.provider, "enabled": request.enabled},
        "medium"
    )
    
    return {
        "configId": config_id,
        "message": f"SSO provider '{request.provider}' configured",
        "redirectUrl": f"/auth/sso/{config_id}/login"
    }


@router.get("/enterprise/sso/providers", summary="List SSO providers")
async def list_sso_providers() -> List[Dict[str, Any]]:
    """List all configured SSO providers."""
    
    providers = []
    for config in SSO_CONFIGURATIONS.values():
        providers.append({
            "configId": config["configId"],
            "provider": config["provider"],
            "enabled": config["enabled"],
            "redirectUrl": config["redirectUrl"],
            "createdAt": config["createdAt"]
        })
    
    return providers


@router.post("/enterprise/users/profile", summary="Create/update user profile")
async def create_user_profile(
    request: UserProfile,
) -> UserProfile:
    """Create or update enterprise user profile."""
    
    profile_data = request.dict()
    profile_data["createdAt"] = datetime.utcnow().isoformat()
    profile_data["updatedAt"] = datetime.utcnow().isoformat()
    
    USER_PROFILES[request.userId] = profile_data
    
    # Create audit log
    await _create_security_audit_log(
        request.userId,
        "profile_updated",
        request.userId,
        "user_profile",
        {"organization": request.organization, "roles": request.roles},
        "low"
    )
    
    return request


@router.get("/enterprise/users/{user_id}/profile", summary="Get user profile")
async def get_user_profile(user_id: str) -> UserProfile:
    """Get enterprise user profile."""
    
    profile = USER_PROFILES.get(user_id)
    
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"User profile '{user_id}' not found"
        )
    
    return UserProfile(**profile)


@router.post("/enterprise/api-keys", summary="Generate API key")
async def generate_api_key(
    name: str,
    description: str,
    permissions: List[str],
    organization_id: str,
    expires_in_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate API key for enterprise integrations."""
    
    import secrets
    import hashlib
    
    # Generate secure API key
    api_key = f"tpl_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    key_id = f"key_{len(API_KEYS) + 1}_{int(datetime.utcnow().timestamp())}"
    
    expires_at = None
    if expires_in_days:
        from datetime import timedelta
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    
    api_key_data = {
        "keyId": key_id,
        "name": name,
        "description": description,
        "keyHash": key_hash,
        "permissions": permissions,
        "organizationId": organization_id,
        "createdBy": "current_user_id",
        "createdAt": datetime.utcnow(),
        "expiresAt": expires_at,
        "lastUsedAt": None,
        "isActive": True,
        "usageCount": 0,
        "rateLimitPerHour": 1000
    }
    
    API_KEYS[key_id] = api_key_data
    
    # Create audit log
    await _create_security_audit_log(
        "current_user_id",
        "api_key_generated",
        key_id,
        "api_key",
        {"name": name, "permissions": permissions},
        "medium"
    )
    
    return {
        "keyId": key_id,
        "apiKey": api_key,  # Only returned once!
        "permissions": permissions,
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "message": "API key generated successfully. Store it securely!"
    }


# Advanced Analytics Endpoints


@router.post("/enterprise/analytics/dashboards", summary="Create analytics dashboard")
async def create_analytics_dashboard(
    request: AnalyticsDashboard,
) -> AnalyticsDashboard:
    """Create advanced analytics dashboard."""
    
    dashboard_data = request.dict()
    dashboard_data["createdAt"] = datetime.utcnow()
    
    ANALYTICS_DASHBOARDS[request.dashboardId] = dashboard_data
    
    return request


@router.get("/enterprise/analytics/performance-report", 
           summary="Generate comprehensive performance report")
async def generate_performance_report(
    template_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_predictions: bool = True,
) -> PerformanceReport:
    """Generate comprehensive performance analytics report."""
    
    # Simulate comprehensive analytics
    time_range = {
        "start": start_date or "2025-09-01",
        "end": end_date or "2025-10-08"
    }
    
    # Core metrics
    metrics = {
        "totalTemplates": len(TEMPLATES) + len(CUSTOM_TEMPLATES),
        "activeUsers": 145,
        "collaborationEvents": len(ACTIVITY_EVENTS),
        "averageRating": 4.3,
        "completionRate": 0.847,
        "engagementScore": 0.792,
        "qualityScore": 87.3,
        "accessibilityScore": 91.2,
        "performanceScore": 94.1,
        "userSatisfaction": 0.886
    }
    
    # Trend data (weekly)
    trends = {
        "templateCreation": [12, 15, 18, 22, 19, 25, 28],
        "userEngagement": [0.72, 0.75, 0.78, 0.81, 0.79, 0.84, 0.87],
        "qualityScores": [82.1, 84.3, 85.7, 86.9, 87.1, 87.5, 88.2],
        "collaborationActivity": [45, 52, 61, 58, 67, 73, 81]
    }
    
    # Comparative analysis
    comparisons = {
        "previousPeriod": {
            "templateGrowth": 0.23,
            "engagementIncrease": 0.12,
            "qualityImprovement": 0.08,
            "userAdoption": 0.31
        },
        "industryBenchmark": {
            "engagementVsIndustry": 0.15,  # 15% above average
            "qualityVsIndustry": 0.09,
            "collaborationVsIndustry": 0.22
        }
    }
    
    # AI-powered insights
    insights = [
        {
            "type": "trend",
            "insight": "Template creation increased 23% with collaboration features",
            "confidence": 0.94
        },
        {
            "type": "opportunity",
            "insight": "Physics templates show highest engagement rates",
            "confidence": 0.87
        },
        {
            "type": "risk",
            "insight": "Complex templates have 15% lower completion rates",
            "confidence": 0.82
        }
    ]
    
    # Recommendations
    recommendations = [
        {
            "priority": "high",
            "recommendation": "Expand physics template library based on high engagement",
            "impact": "Potential 18% increase in user satisfaction"
        },
        {
            "priority": "medium", 
            "recommendation": "Implement template complexity scoring for better UX",
            "impact": "Expected 12% improvement in completion rates"
        },
        {
            "priority": "low",
            "recommendation": "Add more collaboration tutorials for new users",
            "impact": "5-8% increase in feature adoption"
        }
    ]
    
    report_id = f"report_{int(datetime.utcnow().timestamp())}"
    
    report = PerformanceReport(
        reportId=report_id,
        templateId=template_id,
        timeRange=time_range,
        metrics=metrics,
        trends=trends,
        comparisons=comparisons,
        insights=insights,
        recommendations=recommendations,
        generatedAt=datetime.utcnow()
    )
    
    return report


@router.get("/enterprise/analytics/real-time-metrics", 
           summary="Get real-time analytics metrics")
async def get_realtime_metrics() -> Dict[str, Any]:
    """Get real-time analytics metrics for dashboard widgets."""
    
    # Simulate real-time metrics
    current_time = datetime.utcnow()
    
    return {
        "timestamp": current_time.isoformat(),
        "activeUsers": 23,
        "onlineCollaborators": 8,
        "templatesInProgress": 12,
        "recentActivity": {
            "lastHour": len([e for e in ACTIVITY_EVENTS[-50:]]),
            "lastDay": len(ACTIVITY_EVENTS),
            "trending": "upward"
        },
        "systemHealth": {
            "apiResponseTime": "89ms",
            "databaseConnections": 45,
            "cacheHitRate": 0.94,
            "errorRate": 0.001
        },
        "usage": {
            "templatesCreatedToday": 7,
            "collaborationEventsToday": 34,
            "aiRecommendationsServed": 156,
            "contentAnalysisRuns": 23
        },
        "quality": {
            "averageQualityScore": 87.3,
            "accessibilityCompliance": 0.91,
            "userRatings": 4.3
        }
    }


# Mobile & Offline Capabilities


@router.post("/mobile/session/start", summary="Start mobile session")
async def start_mobile_session(
    user_id: str,
    device_info: Dict[str, str],
    platform: str,
    app_version: str,
) -> MobileSession:
    """Start mobile session for offline capability."""
    
    session_id = f"mobile_{user_id}_{int(datetime.utcnow().timestamp())}"
    
    session_data = {
        "sessionId": session_id,
        "userId": user_id,
        "deviceInfo": device_info,
        "platform": platform,
        "appVersion": app_version,
        "lastSyncAt": datetime.utcnow(),
        "offlineCapabilities": {
            "canCreateTemplates": True,
            "canEditTemplates": True,
            "canAddComments": True,
            "canViewAnalytics": False,  # Requires online
            "maxOfflineTemplates": 50
        },
        "syncQueue": []
    }
    
    MOBILE_SESSIONS[session_id] = session_data
    
    return MobileSession(**session_data)


@router.post("/mobile/sync", summary="Sync offline data")
async def sync_offline_data(
    session_id: str,
    offline_operations: List[OfflineData],
) -> Dict[str, Any]:
    """Synchronize offline data with server."""
    
    session = MOBILE_SESSIONS.get(session_id)
    
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Mobile session '{session_id}' not found"
        )
    
    sync_results = {
        "synced": [],
        "conflicts": [],
        "errors": []
    }
    
    for operation in offline_operations:
        try:
            # Simulate conflict detection
            has_conflict = operation.operation == "update" and len(operation.data) > 5
            
            if has_conflict:
                # Handle conflicts
                conflict_data = {
                    "dataId": operation.dataId,
                    "type": "version_conflict",
                    "serverVersion": "2.1.0",
                    "clientVersion": "2.0.0",
                    "resolution": "manual_merge_required"
                }
                sync_results["conflicts"].append(conflict_data)
                
                # Add to offline queue for later resolution
                OFFLINE_DATA_QUEUE.append({
                    **operation.dict(),
                    "syncStatus": "conflict",
                    "conflictData": conflict_data
                })
            else:
                # Successful sync
                if operation.operation == "create":
                    # Simulate creating template from offline data
                    new_template = {
                        "id": f"offline_sync_{operation.dataId}",
                        **operation.data,
                        "syncedAt": datetime.utcnow().isoformat()
                    }
                    CUSTOM_TEMPLATES.append(new_template)
                
                sync_results["synced"].append({
                    "dataId": operation.dataId,
                    "operation": operation.operation,
                    "status": "success"
                })
        
        except Exception as e:
            sync_results["errors"].append({
                "dataId": operation.dataId,
                "error": str(e),
                "recoverable": True
            })
    
    # Update session sync time
    session["lastSyncAt"] = datetime.utcnow()
    
    return {
        "sessionId": session_id,
        "syncResults": sync_results,
        "lastSyncAt": session["lastSyncAt"].isoformat(),
        "message": f"Synced {len(sync_results['synced'])} operations successfully"
    }


@router.get("/mobile/offline-templates", summary="Get templates for offline use")
async def get_offline_templates(
    session_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Get templates optimized for offline use."""
    
    session = MOBILE_SESSIONS.get(session_id)
    
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Mobile session '{session_id}' not found"
        )
    
    # Get lightweight templates for offline use
    offline_templates = []
    
    for template in (TEMPLATES + CUSTOM_TEMPLATES)[:limit]:
        offline_template = {
            "id": template.get("id", template.get("templateId")),
            "name": template.get("name", ""),
            "description": template.get("description", ""),
            "category": template.get("category", ""),
            "type": template.get("type", ""),
            "tags": template.get("tags", []),
            "offlineVersion": "1.0",
            "lastModified": template.get("updatedAt", datetime.utcnow().isoformat()),
            "size": len(str(template)) // 1024,  # Approximate KB
            "supportedOperations": ["view", "edit", "comment"]
        }
        offline_templates.append(offline_template)
    
    return offline_templates


# Security & Audit Endpoints


@router.get("/enterprise/security/audit-log", summary="Get security audit log")
async def get_security_audit_log(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = 100,
) -> List[SecurityAuditLog]:
    """Get filtered security audit log for compliance."""
    
    filtered_logs = SECURITY_AUDIT_LOGS.copy()
    
    # Apply filters
    if user_id:
        filtered_logs = [log for log in filtered_logs if log["userId"] == user_id]
    
    if risk_level:
        filtered_logs = [log for log in filtered_logs if log["riskLevel"] == risk_level]
    
    # Sort by timestamp (newest first)
    filtered_logs.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return [SecurityAuditLog(**log) for log in filtered_logs[:limit]]


@router.get("/enterprise/security/compliance-report", 
           summary="Generate compliance report")
async def generate_compliance_report(
    report_type: str = "gdpr",
) -> Dict[str, Any]:
    """Generate compliance report for regulatory requirements."""
    
    # Simulate compliance metrics
    compliance_data = {
        "reportType": report_type.upper(),
        "generatedAt": datetime.utcnow().isoformat(),
        "reportingPeriod": "2025-Q3",
        "compliance": {
            "dataProtection": {
                "score": 0.94,
                "encrypted": True,
                "backupCompliant": True,
                "retentionPolicyActive": True
            },
            "accessControl": {
                "score": 0.91,
                "ssoEnabled": len(SSO_CONFIGURATIONS) > 0,
                "mfaEnforced": True,
                "rbacImplemented": True
            },
            "auditTrail": {
                "score": 0.97,
                "completeness": 0.98,
                "retention": "7 years",
                "totalEvents": len(SECURITY_AUDIT_LOGS)
            },
            "dataMinimization": {
                "score": 0.89,
                "unnecessaryDataPurged": True,
                "consentTracked": True
            }
        },
        "violations": [],
        "recommendations": [
            "Enable additional MFA methods for enhanced security",
            "Implement automated data classification",
            "Review and update privacy policies quarterly"
        ],
        "overallScore": 0.93
    }
    
    return compliance_data


# Helper Functions for Phase 4.2


async def _create_security_audit_log(
    user_id: str,
    action: str,
    resource_id: str,
    resource_type: str,
    details: Dict[str, Any],
    risk_level: str,
    ip_address: str = "127.0.0.1",
    user_agent: str = "API Client"
) -> str:
    """Create security audit log entry."""
    
    log_id = f"audit_{len(SECURITY_AUDIT_LOGS) + 1}_{int(datetime.utcnow().timestamp())}"
    
    audit_log = {
        "logId": log_id,
        "userId": user_id,
        "action": action,
        "resourceId": resource_id,
        "resourceType": resource_type,
        "ipAddress": ip_address,
        "userAgent": user_agent,
        "timestamp": datetime.utcnow(),
        "success": True,
        "details": details,
        "riskLevel": risk_level
    }
    
    SECURITY_AUDIT_LOGS.append(audit_log)
    
    # Keep only last 10000 audit logs
    if len(SECURITY_AUDIT_LOGS) > 10000:
        SECURITY_AUDIT_LOGS.pop(0)
    
    return log_id


# Phase 4.2: Progressive Web App (PWA) Features


class PWAManifest(BaseModel):
    """PWA manifest configuration for mobile optimization"""
    name: str = "E-Learning Template Editor"
    shortName: str = "EL-Editor"
    description: str = "Advanced learning content creation platform"
    startUrl: str = "/"
    display: str = "standalone"
    themeColor: str = "#2196F3"
    backgroundColor: str = "#ffffff"
    icons: List[Dict[str, str]]
    orientation: str = "portrait-primary"
    categories: List[str] = ["education", "productivity"]


class ServiceWorkerConfig(BaseModel):
    """Service worker configuration for offline functionality"""
    version: str
    cacheStrategies: Dict[str, str]
    offlinePages: List[str]
    maxCacheAge: int = 86400  # 24 hours
    enableBackgroundSync: bool = True
    pushNotifications: bool = True


class MobileOptimization(BaseModel):
    """Mobile optimization settings"""
    touchGestures: Dict[str, bool]
    viewportSettings: Dict[str, str]
    performanceThresholds: Dict[str, float]
    adaptiveLoading: bool = True
    imageOptimization: bool = True
    lazylLoading: bool = True


class PushNotification(BaseModel):
    """Push notification for mobile engagement"""
    notificationId: str
    userId: str
    title: str
    body: str
    icon: Optional[str] = None
    badge: Optional[str] = None
    actions: List[Dict[str, str]] = []
    data: Dict[str, Any] = {}
    scheduledFor: Optional[datetime] = None
    sent: bool = False


# Advanced Enterprise Integration Features


class WebhookConfiguration(BaseModel):
    """Webhook configuration for enterprise integrations"""
    webhookId: str
    name: str
    url: str
    events: List[str]
    headers: Dict[str, str] = {}
    retryPolicy: Dict[str, int] = {"maxRetries": 3, "backoffMs": 1000}
    isActive: bool = True
    secret: Optional[str] = None


class LMSIntegration(BaseModel):
    """Learning Management System integration"""
    integrationId: str
    lmsType: str = Field(..., pattern="^(moodle|canvas|blackboard|schoology)$")
    endpoint: str
    apiKey: str
    settings: Dict[str, Any]
    syncEnabled: bool = True
    lastSyncAt: Optional[datetime] = None


class SCORMPackage(BaseModel):
    """SCORM package for LMS compatibility"""
    packageId: str
    templateId: str
    version: str = Field(..., pattern="^(1.2|2004)$")
    manifest: Dict[str, Any]
    resources: List[Dict[str, str]]
    packageUrl: str
    generatedAt: datetime


# Advanced AI & Machine Learning Features


class AIModelConfiguration(BaseModel):
    """AI model configuration for advanced features"""
    modelId: str
    modelType: str = Field(..., pattern="^(nlp|vision|recommendation|analytics)$")
    provider: str = Field(..., pattern="^(openai|huggingface|custom)$")
    version: str
    parameters: Dict[str, Any]
    isActive: bool = True


class AutoTaggingResult(BaseModel):
    """AI-powered auto-tagging result"""
    templateId: str
    suggestedTags: List[Dict[str, float]]  # tag: confidence
    categories: List[Dict[str, float]]
    difficulty: Dict[str, float]
    learningObjectives: List[str]
    confidence: float


class ContentGenerationRequest(BaseModel):
    """AI content generation request"""
    templateType: str
    topic: str
    difficultyLevel: str = Field(..., pattern="^(beginner|intermediate|advanced)$")
    duration: int  # minutes
    learningObjectives: List[str]
    constraints: Dict[str, Any] = {}


# Storage for Phase 4.2 advanced features
PWA_CONFIGURATIONS: Dict[str, Dict[str, Any]] = {}
PUSH_NOTIFICATIONS: List[Dict[str, Any]] = []
WEBHOOK_CONFIGURATIONS: Dict[str, Dict[str, Any]] = {}
LMS_INTEGRATIONS: Dict[str, Dict[str, Any]] = {}
SCORM_PACKAGES: Dict[str, Dict[str, Any]] = {}
AI_MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {}


# PWA & Mobile Enhancement Endpoints


@router.get("/pwa/manifest.json", summary="Get PWA manifest")
async def get_pwa_manifest() -> PWAManifest:
    """Get Progressive Web App manifest for mobile installation."""
    
    manifest = PWAManifest(
        icons=[
            {"src": "/icons/icon-72x72.png", "sizes": "72x72", "type": "image/png"},
            {"src": "/icons/icon-96x96.png", "sizes": "96x96", "type": "image/png"},
            {"src": "/icons/icon-128x128.png", "sizes": "128x128", "type": "image/png"},
            {"src": "/icons/icon-144x144.png", "sizes": "144x144", "type": "image/png"},
            {"src": "/icons/icon-152x152.png", "sizes": "152x152", "type": "image/png"},
            {"src": "/icons/icon-192x192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icons/icon-384x384.png", "sizes": "384x384", "type": "image/png"},
            {"src": "/icons/icon-512x512.png", "sizes": "512x512", "type": "image/png"}
        ]
    )
    
    return manifest


@router.get("/pwa/service-worker.js", summary="Get service worker")
async def get_service_worker() -> Dict[str, Any]:
    """Get service worker configuration for offline functionality."""
    
    sw_config = {
        "version": "4.2.1",
        "cacheStrategies": {
            "templates": "cache-first",
            "api": "network-first",
            "static": "cache-first",
            "images": "cache-first",
            "fonts": "cache-first"
        },
        "offlinePages": ["/", "/templates", "/create", "/offline"],
        "maxCacheAge": 86400,
        "enableBackgroundSync": True,
        "pushNotifications": True,
        "cacheName": "el-editor-v4-2-1"
    }
    
    return sw_config


@router.post("/mobile/push-notifications", summary="Send push notification")
async def send_push_notification(
    request: PushNotification,
) -> Dict[str, Any]:
    """Send push notification to mobile users."""
    
    notification_data = request.dict()
    notification_data["sentAt"] = datetime.utcnow()
    notification_data["sent"] = True
    
    PUSH_NOTIFICATIONS.append(notification_data)
    
    # Simulate push notification delivery
    delivery_result = {
        "notificationId": request.notificationId,
        "status": "delivered",
        "deliveredAt": datetime.utcnow().isoformat(),
        "recipients": 1,
        "clickRate": 0.0,  # Will be updated when user clicks
        "deliveryLatency": "127ms"
    }
    
    return delivery_result


@router.get("/mobile/optimization-settings", summary="Get mobile optimization")
async def get_mobile_optimization() -> MobileOptimization:
    """Get mobile optimization settings for enhanced UX."""
    
    return MobileOptimization(
        touchGestures={
            "swipeToNavigate": True,
            "pinchToZoom": True,
            "doubleTapToEdit": True,
            "longPressMenu": True
        },
        viewportSettings={
            "width": "device-width",
            "initialScale": "1.0",
            "maximumScale": "3.0",
            "userScalable": "yes"
        },
        performanceThresholds={
            "maxLoadTime": 2.5,
            "maxRenderTime": 1.0,
            "minFPS": 30.0,
            "maxMemoryUsage": 512.0  # MB
        }
    )


# Enterprise Integration Endpoints


@router.post("/enterprise/webhooks", summary="Configure webhook")
async def configure_webhook(
    request: WebhookConfiguration,
) -> WebhookConfiguration:
    """Configure webhook for enterprise system integration."""
    
    webhook_data = request.dict()
    webhook_data["createdAt"] = datetime.utcnow()
    
    WEBHOOK_CONFIGURATIONS[request.webhookId] = webhook_data
    
    return request


@router.post("/enterprise/webhooks/{webhook_id}/test", 
           summary="Test webhook configuration")
async def test_webhook(webhook_id: str) -> Dict[str, Any]:
    """Test webhook configuration with sample payload."""
    
    webhook = WEBHOOK_CONFIGURATIONS.get(webhook_id)
    
    if not webhook:
        raise HTTPException(
            status_code=404,
            detail=f"Webhook '{webhook_id}' not found"
        )
    
    # Simulate webhook test
    test_payload = {
        "event": "template.created",
        "templateId": "test_template_123",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "name": "Test Template",
            "category": "science"
        }
    }
    
    # Simulate HTTP request to webhook URL
    test_result = {
        "webhookId": webhook_id,
        "testUrl": webhook["url"],
        "payload": test_payload,
        "response": {
            "status": 200,
            "responseTime": "234ms",
            "headers": {"content-type": "application/json"},
            "success": True
        },
        "testedAt": datetime.utcnow().isoformat()
    }
    
    return test_result


@router.post("/enterprise/lms-integration", summary="Configure LMS integration")
async def configure_lms_integration(
    request: LMSIntegration,
) -> LMSIntegration:
    """Configure Learning Management System integration."""
    
    integration_data = request.dict()
    integration_data["createdAt"] = datetime.utcnow()
    integration_data["apiKey"] = "***ENCRYPTED***"  # Never store plain text
    
    LMS_INTEGRATIONS[request.integrationId] = integration_data
    
    return request


@router.post("/enterprise/scorm-package/{template_id}", 
           summary="Generate SCORM package")
async def generate_scorm_package(
    template_id: str,
    scorm_version: str = "2004",
) -> SCORMPackage:
    """Generate SCORM-compliant package for LMS deployment."""
    
    # Find template
    template = None
    for t in CUSTOM_TEMPLATES:
        if t.get("id") == template_id or t.get("templateId") == template_id:
            template = t
            break
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    package_id = f"scorm_{template_id}_{int(datetime.utcnow().timestamp())}"
    
    # Generate SCORM manifest
    manifest = {
        "identifier": package_id,
        "version": scorm_version,
        "metadata": {
            "title": template.get("name", "Learning Content"),
            "description": template.get("description", ""),
            "keywords": ", ".join(template.get("tags", [])),
            "duration": "PT30M"  # 30 minutes default
        },
        "organizations": {
            "default": {
                "title": template.get("name", "Learning Content"),
                "items": [
                    {
                        "identifier": "item_1",
                        "title": "Main Content",
                        "resource": "content.html"
                    }
                ]
            }
        },
        "resources": [
            {
                "identifier": "content",
                "type": "webcontent",
                "file": "content.html"
            }
        ]
    }
    
    resources = [
        {"name": "imsmanifest.xml", "type": "manifest"},
        {"name": "content.html", "type": "content"},
        {"name": "styles.css", "type": "stylesheet"},
        {"name": "scripts.js", "type": "javascript"}
    ]
    
    scorm_package = SCORMPackage(
        packageId=package_id,
        templateId=template_id,
        version=scorm_version,
        manifest=manifest,
        resources=resources,
        packageUrl=f"/downloads/scorm/{package_id}.zip",
        generatedAt=datetime.utcnow()
    )
    
    SCORM_PACKAGES[package_id] = scorm_package.dict()
    
    return scorm_package


# Advanced AI & ML Endpoints


@router.post("/ai/auto-tagging", summary="AI-powered auto-tagging")
async def auto_tag_template(
    template_id: str,
    analyze_content: bool = True,
    suggest_categories: bool = True,
) -> AutoTaggingResult:
    """Use AI to automatically tag and categorize templates."""
    
    # Find template
    template = None
    for t in CUSTOM_TEMPLATES:
        if t.get("id") == template_id or t.get("templateId") == template_id:
            template = t
            break
    
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )
    
    # Simulate AI analysis
    template_name = template.get("name", "").lower()
    template_desc = template.get("description", "").lower()
    content = f"{template_name} {template_desc}"
    
    # AI-powered tag suggestions
    suggested_tags = []
    if "physics" in content:
        suggested_tags.extend([
            {"tag": "physics", "confidence": 0.94},
            {"tag": "science", "confidence": 0.89},
            {"tag": "laboratory", "confidence": 0.76}
        ])
    elif "math" in content:
        suggested_tags.extend([
            {"tag": "mathematics", "confidence": 0.92},
            {"tag": "algebra", "confidence": 0.71},
            {"tag": "problem-solving", "confidence": 0.83}
        ])
    else:
        suggested_tags.extend([
            {"tag": "educational", "confidence": 0.85},
            {"tag": "interactive", "confidence": 0.72},
            {"tag": "learning", "confidence": 0.91}
        ])
    
    # Category suggestions
    categories = [
        {"category": "STEM", "confidence": 0.87},
        {"category": "Interactive Learning", "confidence": 0.79},
        {"category": "Hands-on Activities", "confidence": 0.82}
    ]
    
    # Difficulty analysis
    difficulty = {
        "beginner": 0.15,
        "intermediate": 0.65,
        "advanced": 0.20
    }
    
    # Learning objectives extraction
    learning_objectives = [
        "Understand fundamental concepts through interactive exploration",
        "Apply theoretical knowledge to practical scenarios",
        "Develop critical thinking and problem-solving skills"
    ]
    
    result = AutoTaggingResult(
        templateId=template_id,
        suggestedTags=suggested_tags,
        categories=categories,
        difficulty=difficulty,
        learningObjectives=learning_objectives,
        confidence=0.87
    )
    
    return result


@router.post("/ai/content-generation", summary="AI content generation")
async def generate_ai_content(
    request: ContentGenerationRequest,
) -> Dict[str, Any]:
    """Generate educational content using AI based on specifications."""
    
    # Simulate AI content generation
    generated_content = {
        "templateId": f"ai_gen_{int(datetime.utcnow().timestamp())}",
        "metadata": {
            "topic": request.topic,
            "difficultyLevel": request.difficultyLevel,
            "estimatedDuration": request.duration,
            "generatedAt": datetime.utcnow().isoformat(),
            "aiModel": "GPT-4-Education-v2.1"
        },
        "content": {
            "title": f"Interactive {request.topic} Learning Experience",
            "description": f"Comprehensive {request.difficultyLevel} level content covering {request.topic}",
            "slides": [
                {
                    "id": "intro",
                    "title": f"Introduction to {request.topic}",
                    "content": "Generated introductory content...",
                    "interactiveElements": ["knowledge-check", "animation"]
                },
                {
                    "id": "core",
                    "title": "Core Concepts",
                    "content": "Generated core learning content...",
                    "interactiveElements": ["simulation", "quiz"]
                },
                {
                    "id": "practice",
                    "title": "Practice Activities", 
                    "content": "Generated practice exercises...",
                    "interactiveElements": ["drag-drop", "matching"]
                },
                {
                    "id": "assessment",
                    "title": "Knowledge Assessment",
                    "content": "Generated assessment content...",
                    "interactiveElements": ["quiz", "reflection"]
                }
            ],
            "assessments": [
                {
                    "type": "multiple-choice",
                    "questions": 5,
                    "difficulty": request.difficultyLevel
                },
                {
                    "type": "practical-exercise",
                    "scenarios": 3,
                    "difficulty": request.difficultyLevel
                }
            ]
        },
        "learningObjectives": request.learningObjectives,
        "generationStats": {
            "processingTime": "2.3s",
            "confidenceScore": 0.91,
            "originalityScore": 0.94,
            "pedagogicalAlignment": 0.88
        }
    }
    
    return generated_content


@router.get("/ai/content-insights/{template_id}", 
           summary="AI-powered content insights")
async def get_content_insights(template_id: str) -> Dict[str, Any]:
    """Get AI-powered insights about template effectiveness."""
    
    # Simulate comprehensive AI analysis
    insights = {
        "templateId": template_id,
        "analysisTimestamp": datetime.utcnow().isoformat(),
        "engagementPrediction": {
            "expectedEngagementRate": 0.84,
            "confidenceInterval": [0.79, 0.89],
            "factors": {
                "interactivity": 0.92,
                "visualAppeal": 0.87,
                "contentClarity": 0.81,
                "pacing": 0.79
            }
        },
        "learningEffectiveness": {
            "knowledgeRetention": 0.78,
            "skillTransfer": 0.73,
            "motivationalImpact": 0.86,
            "cognitiveLoad": 0.71  # Lower is better
        },
        "contentQuality": {
            "accuracyScore": 0.95,
            "clarityScore": 0.89,
            "completenessScore": 0.82,
            "structureScore": 0.91
        },
        "accessibilityAnalysis": {
            "overallScore": 0.88,
            "colorContrast": "AAA",
            "screenReaderCompatible": True,
            "keyboardNavigable": True,
            "multilingualSupport": False
        },
        "improvementSuggestions": [
            {
                "priority": "high",
                "suggestion": "Add more interactive elements in section 2",
                "expectedImpact": "+12% engagement"
            },
            {
                "priority": "medium",
                "suggestion": "Improve color contrast in diagrams",
                "expectedImpact": "+8% accessibility score"
            },
            {
                "priority": "low",
                "suggestion": "Add multilingual captions",
                "expectedImpact": "+15% global reach"
            }
        ],
        "competitorAnalysis": {
            "benchmarkScore": 0.79,
            "performanceVsBenchmark": "+6.3%",
            "strengthAreas": ["interactivity", "visual design"],
            "improvementAreas": ["content depth", "assessment variety"]
        }
    }
    
    return insights


# Phase 4.2: Advanced Reporting & Business Intelligence


class BusinessIntelligenceReport(BaseModel):
    """Comprehensive BI report for executive dashboards"""
    reportId: str
    reportType: str = Field(..., pattern="^(executive|operational|tactical|strategic)$")
    period: Dict[str, str]
    kpis: Dict[str, float]
    trends: Dict[str, List[float]]
    forecasts: Dict[str, Dict[str, float]]
    insights: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    riskAssessment: Dict[str, Any]
    competitiveAnalysis: Dict[str, Any]
    generatedAt: datetime


class RevenueAnalytics(BaseModel):
    """Revenue and financial analytics"""
    totalRevenue: float
    revenueGrowth: float
    customerLifetimeValue: float
    costPerAcquisition: float
    profitMargin: float
    recurringRevenue: float
    churnRate: float
    expansionRevenue: float


class UserBehaviorAnalytics(BaseModel):
    """Advanced user behavior analytics"""
    userId: str
    sessionData: Dict[str, Any]
    engagementMetrics: Dict[str, float]
    learningPath: List[Dict[str, str]]
    preferenceProfile: Dict[str, float]
    riskFactors: Dict[str, float]
    predictedActions: List[Dict[str, float]]


class AdvancedSearchQuery(BaseModel):
    """Advanced search with AI-powered suggestions"""
    query: str
    filters: Dict[str, Any] = {}
    sortBy: str = "relevance"
    searchType: str = Field(..., pattern="^(semantic|keyword|hybrid|ai_assisted)$")
    includeMetadata: bool = True
    maxResults: int = 20
    personalize: bool = True


class SearchResult(BaseModel):
    """Enhanced search result with AI insights"""
    resultId: str
    templateId: str
    relevanceScore: float
    matchType: str
    highlightedFields: Dict[str, List[str]]
    aiSummary: str
    suggestedActions: List[str]
    relatedTemplates: List[str]


# Storage for BI and advanced features
BI_REPORTS: Dict[str, Dict[str, Any]] = {}
USER_BEHAVIOR_DATA: Dict[str, Dict[str, Any]] = {}
SEARCH_ANALYTICS: List[Dict[str, Any]] = []


# Business Intelligence Endpoints


@router.post("/enterprise/bi/executive-report", summary="Generate executive report")
async def generate_executive_report(
    time_period: str = "monthly",
    include_forecasts: bool = True,
) -> BusinessIntelligenceReport:
    """Generate comprehensive executive BI report."""
    
    report_id = f"exec_report_{int(datetime.utcnow().timestamp())}"
    
    # Simulate comprehensive BI metrics
    kpis = {
        "totalActiveUsers": 2847,
        "templatesCreated": 1236,
        "collaborationEvents": 4521,
        "userSatisfactionScore": 4.7,
        "systemUptime": 99.94,
        "revenueGrowth": 0.23,
        "customerRetention": 0.91,
        "timeToValue": 14.2,  # days
        "featureAdoption": 0.78,
        "supportTicketResolution": 0.96
    }
    
    # Trend analysis (12 months)
    trends = {
        "userGrowth": [100, 115, 132, 148, 167, 189, 214, 241, 268, 297, 329, 365],
        "templateCreation": [45, 52, 61, 58, 67, 73, 81, 89, 95, 103, 112, 124],
        "engagement": [0.72, 0.75, 0.78, 0.81, 0.79, 0.84, 0.87, 0.89, 0.91, 0.93, 0.95, 0.97],
        "revenue": [80000, 92000, 98000, 107000, 118000, 125000, 134000, 142000, 151000, 162000, 173000, 186000]
    }
    
    # AI-powered forecasts
    forecasts = {
        "nextQuarter": {
            "userGrowth": 0.28,
            "revenueIncrease": 0.21,
            "templateVolume": 1650,
            "collaborationIncrease": 0.34
        },
        "yearEnd": {
            "totalUsers": 4200,
            "annualRevenue": 2340000,
            "marketShare": 0.087,
            "customerSatisfaction": 4.8
        }
    }
    
    # Strategic insights
    insights = [
        {
            "type": "growth_opportunity",
            "title": "Enterprise Segment Expansion",
            "description": "Enterprise customers show 3x higher engagement rates",
            "impact": "high",
            "confidence": 0.89
        },
        {
            "type": "risk_mitigation",
            "title": "Mobile Usage Growing",
            "description": "Mobile sessions increased 67% - optimize mobile experience",
            "impact": "medium",
            "confidence": 0.92
        },
        {
            "type": "operational_efficiency",
            "title": "AI Recommendations Driving Adoption",
            "description": "AI-suggested templates have 2.3x higher completion rates",
            "impact": "high",
            "confidence": 0.94
        }
    ]
    
    # Strategic recommendations
    recommendations = [
        {
            "priority": "critical",
            "category": "product",
            "recommendation": "Accelerate mobile PWA development",
            "expectedROI": "245%",
            "timeline": "Q1 2026",
            "resources": "3 developers, 2 designers"
        },
        {
            "priority": "high", 
            "category": "sales",
            "recommendation": "Launch enterprise solution package",
            "expectedROI": "180%",
            "timeline": "Q2 2026",
            "resources": "Sales team expansion, custom onboarding"
        }
    ]
    
    # Risk assessment
    risk_assessment = {
        "overallRisk": "low-medium",
        "riskFactors": [
            {"factor": "Competition", "probability": 0.3, "impact": "high"},
            {"factor": "Technical debt", "probability": 0.2, "impact": "medium"},
            {"factor": "Scalability limits", "probability": 0.15, "impact": "high"}
        ],
        "mitigation": {
            "budgetAllocated": 150000,
            "contingencyPlans": 3,
            "monitoringMetrics": 12
        }
    }
    
    # Competitive analysis
    competitive_analysis = {
        "marketPosition": "leading challenger",
        "competitiveAdvantages": [
            "AI-powered content generation",
            "Real-time collaboration",
            "Enterprise integration depth"
        ],
        "gaps": [
            "Mobile experience optimization",
            "Advanced analytics presentation"
        ],
        "marketShareTrend": "upward",
        "threatLevel": "moderate"
    }
    
    report = BusinessIntelligenceReport(
        reportId=report_id,
        reportType="executive",
        period={"start": "2025-01-01", "end": "2025-10-08"},
        kpis=kpis,
        trends=trends,
        forecasts=forecasts,
        insights=insights,
        recommendations=recommendations,
        riskAssessment=risk_assessment,
        competitiveAnalysis=competitive_analysis,
        generatedAt=datetime.utcnow()
    )
    
    BI_REPORTS[report_id] = report.dict()
    
    return report


@router.get("/enterprise/analytics/revenue-dashboard", 
           summary="Revenue analytics dashboard")
async def get_revenue_dashboard() -> RevenueAnalytics:
    """Get comprehensive revenue analytics for finance dashboard."""
    
    # Simulate advanced revenue analytics
    return RevenueAnalytics(
        totalRevenue=1847250.00,
        revenueGrowth=0.234,  # 23.4% growth
        customerLifetimeValue=4850.00,
        costPerAcquisition=185.50,
        profitMargin=0.347,  # 34.7%
        recurringRevenue=1623400.00,  # 87.9% recurring
        churnRate=0.042,  # 4.2% monthly churn
        expansionRevenue=223850.00  # Revenue from existing customers
    )


@router.get("/enterprise/analytics/user-behavior/{user_id}", 
           summary="User behavior analytics")
async def get_user_behavior_analytics(user_id: str) -> UserBehaviorAnalytics:
    """Get detailed user behavior analytics for personalization."""
    
    # Simulate advanced behavior analytics
    return UserBehaviorAnalytics(
        userId=user_id,
        sessionData={
            "averageSessionDuration": 2847,  # seconds
            "sessionsPerWeek": 4.2,
            "featuresUsed": 12,
            "lastActiveFeature": "ai_recommendations",
            "devicePreference": "desktop"
        },
        engagementMetrics={
            "clickThroughRate": 0.087,
            "timeOnTask": 1247.5,
            "completionRate": 0.834,
            "returnVisits": 0.712,
            "featureAdoption": 0.659
        },
        learningPath=[
            {"step": "1", "action": "template_browse", "timestamp": "2025-10-08T10:00:00"},
            {"step": "2", "action": "template_create", "timestamp": "2025-10-08T10:15:00"},
            {"step": "3", "action": "collaboration_invite", "timestamp": "2025-10-08T10:45:00"}
        ],
        preferenceProfile={
            "visualLearning": 0.82,
            "collaborativeWork": 0.91,
            "technicalContent": 0.67,
            "quickTasks": 0.74,
            "mobileUsage": 0.43
        },
        riskFactors={
            "churnProbability": 0.12,
            "engagementDecline": 0.08,
            "supportNeeds": 0.23
        },
        predictedActions=[
            {"action": "template_share", "probability": 0.78},
            {"action": "upgrade_subscription", "probability": 0.45},
            {"action": "invite_colleagues", "probability": 0.67}
        ]
    )


# Advanced Search & Discovery Endpoints


@router.post("/search/advanced", summary="Advanced AI-powered search")
async def advanced_search(
    request: AdvancedSearchQuery,
) -> List[SearchResult]:
    """Perform advanced search with AI-powered suggestions and ranking."""
    
    # Simulate advanced search algorithm
    query_terms = request.query.lower().split()
    
    results = []
    for i, template in enumerate((TEMPLATES + CUSTOM_TEMPLATES)[:request.maxResults]):
        template_id = template.get("id", template.get("templateId", f"unknown_{i}"))
        template_name = template.get("name", "").lower()
        template_desc = template.get("description", "").lower()
        
        # Simulate relevance scoring
        relevance = 0.0
        match_type = "none"
        
        for term in query_terms:
            if term in template_name:
                relevance += 0.8
                match_type = "title"
            elif term in template_desc:
                relevance += 0.5
                match_type = "description"
            elif term in str(template.get("tags", [])).lower():
                relevance += 0.3
                match_type = "tags"
        
        if relevance > 0:
            # Enhanced search result
            search_result = SearchResult(
                resultId=f"result_{i}_{int(datetime.utcnow().timestamp())}",
                templateId=template_id,
                relevanceScore=min(relevance, 1.0),
                matchType=match_type,
                highlightedFields={
                    "title": [template.get("name", "")],
                    "description": [template.get("description", "")[:100] + "..."]
                },
                aiSummary=f"This template focuses on {template.get('category', 'general education')} with interactive elements suitable for {request.query}.",
                suggestedActions=["view", "customize", "collaborate"],
                relatedTemplates=[f"related_{j}" for j in range(3)]
            )
            
            results.append(search_result)
    
    # Sort by relevance
    results.sort(key=lambda x: x.relevanceScore, reverse=True)
    
    # Log search analytics
    search_analytics = {
        "query": request.query,
        "resultsCount": len(results),
        "searchType": request.searchType,
        "timestamp": datetime.utcnow(),
        "userId": "current_user",  # Would get from auth
        "filters": request.filters
    }
    SEARCH_ANALYTICS.append(search_analytics)
    
    return results[:request.maxResults]


@router.get("/search/suggestions", summary="Get search suggestions")
async def get_search_suggestions(
    partial_query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Get AI-powered search suggestions as user types."""
    
    # Simulate intelligent search suggestions
    suggestions = []
    
    if "phys" in partial_query.lower():
        suggestions.extend([
            {"suggestion": "physics lab experiments", "type": "category", "popularity": 0.85},
            {"suggestion": "physics simulations", "type": "feature", "popularity": 0.72},
            {"suggestion": "physical science templates", "type": "category", "popularity": 0.69}
        ])
    elif "math" in partial_query.lower():
        suggestions.extend([
            {"suggestion": "mathematics interactive", "type": "category", "popularity": 0.91},
            {"suggestion": "math problem solving", "type": "skill", "popularity": 0.78},
            {"suggestion": "mathematical modeling", "type": "technique", "popularity": 0.65}
        ])
    else:
        suggestions.extend([
            {"suggestion": "interactive learning", "type": "feature", "popularity": 0.93},
            {"suggestion": "collaborative templates", "type": "feature", "popularity": 0.81},
            {"suggestion": "assessment tools", "type": "category", "popularity": 0.76}
        ])
    
    # Add trending suggestions
    suggestions.extend([
        {"suggestion": "AI-generated content", "type": "trending", "popularity": 0.94},
        {"suggestion": "mobile-optimized", "type": "trending", "popularity": 0.87}
    ])
    
    return suggestions[:limit]


@router.get("/enterprise/analytics/search-insights", 
           summary="Search analytics insights")
async def get_search_insights() -> Dict[str, Any]:
    """Get comprehensive search analytics for content strategy."""
    
    # Analyze search patterns
    total_searches = len(SEARCH_ANALYTICS)
    
    if total_searches == 0:
        return {"message": "No search data available yet"}
    
    # Simulate search insights
    insights = {
        "searchVolume": {
            "totalSearches": total_searches,
            "uniqueQueries": max(1, total_searches // 2),
            "averageResultsPerSearch": 8.7,
            "zeroResultSearches": 0.03  # 3%
        },
        "topQueries": [
            {"query": "physics lab", "count": 145, "successRate": 0.92},
            {"query": "interactive math", "count": 128, "successRate": 0.89},
            {"query": "collaboration tools", "count": 97, "successRate": 0.94},
            {"query": "assessment templates", "count": 84, "successRate": 0.87}
        ],
        "contentGaps": [
            {"topic": "advanced chemistry", "searchVolume": 67, "contentAvailable": 12},
            {"topic": "language learning", "searchVolume": 54, "contentAvailable": 8},
            {"topic": "coding tutorials", "searchVolume": 43, "contentAvailable": 15}
        ],
        "searchTrends": {
            "risingQueries": ["AI assistance", "mobile learning", "accessibility"],
            "decliningQueries": ["basic templates", "simple quizzes"],
            "seasonalPatterns": {
                "backToSchool": ["september", "january"],
                "examPrep": ["december", "may"]
            }
        },
        "userBehavior": {
            "averageSearchDepth": 2.3,  # Pages explored
            "clickThroughRate": 0.156,
            "searchRefinements": 1.8,
            "exitAfterSearch": 0.23
        },
        "recommendations": [
            {
                "priority": "high",
                "action": "Create advanced chemistry template series",
                "expectedImpact": "Fill 67% of unmet search demand"
            },
            {
                "priority": "medium",
                "action": "Improve search result relevance for 'assessment' queries",
                "expectedImpact": "Increase CTR by 15%"
            }
        ]
    }
    
    return insights


# Phase 4.2: Real-time Collaboration & WebSocket Features


class WebSocketMessage(BaseModel):
    """WebSocket message structure for real-time features"""
    messageId: str
    messageType: str = Field(..., pattern="^(cursor|edit|comment|presence|notification)$")
    templateId: str
    userId: str
    timestamp: datetime
    data: Dict[str, Any]
    metadata: Dict[str, Any] = {}


class CollaborativeCursor(BaseModel):
    """Real-time cursor position for collaborative editing"""
    userId: str
    userName: str
    position: Dict[str, int]  # line, column, elementId
    selection: Optional[Dict[str, Any]] = None
    color: str
    lastUpdate: datetime


class LiveEdit(BaseModel):
    """Real-time collaborative edit operation"""
    editId: str
    templateId: str
    userId: str
    operation: str = Field(..., pattern="^(insert|delete|format|move)$")
    position: Dict[str, int]
    content: str
    appliedAt: datetime
    version: int


class PresenceIndicator(BaseModel):
    """User presence in collaborative session"""
    userId: str
    userName: str
    status: str = Field(..., pattern="^(active|idle|away|offline)$")
    currentSection: Optional[str] = None
    joinedAt: datetime
    lastActivity: datetime
    deviceInfo: Dict[str, str] = {}


# Storage for real-time features
WEBSOCKET_CONNECTIONS: Dict[str, Dict[str, Any]] = {}
COLLABORATIVE_CURSORS: Dict[str, List[Dict[str, Any]]] = {}
LIVE_EDITS: Dict[str, List[Dict[str, Any]]] = {}
USER_PRESENCE: Dict[str, Dict[str, Any]] = {}


# WebSocket & Real-time Endpoints


@router.get("/realtime/session/{template_id}", summary="Start collaborative session")
async def start_collaborative_session(
    template_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Start or join collaborative editing session."""
    
    session_id = f"collab_{template_id}_{user_id}_{int(datetime.utcnow().timestamp())}"
    
    # Initialize collaborative session
    if template_id not in COLLABORATIVE_CURSORS:
        COLLABORATIVE_CURSORS[template_id] = []
        LIVE_EDITS[template_id] = []
        USER_PRESENCE[template_id] = {}
    
    # Add user presence
    presence = {
        "userId": user_id,
        "userName": f"User {user_id}",
        "status": "active",
        "currentSection": None,
        "joinedAt": datetime.utcnow(),
        "lastActivity": datetime.utcnow(),
        "deviceInfo": {"type": "web", "browser": "Chrome"}
    }
    
    USER_PRESENCE[template_id][user_id] = presence
    
    # Get current collaborators
    active_users = [
        {"userId": uid, "userName": data["userName"], "status": data["status"]}
        for uid, data in USER_PRESENCE[template_id].items()
        if data["status"] != "offline"
    ]
    
    session_data = {
        "sessionId": session_id,
        "templateId": template_id,
        "userId": user_id,
        "websocketEndpoint": f"ws://localhost:8000/ws/collaboration/{session_id}",
        "activeUsers": active_users,
        "permissions": {
            "canEdit": True,
            "canComment": True,
            "canShare": True,
            "canViewCursors": True
        },
        "conflictResolution": "operational_transformation",
        "versionControl": "automatic"
    }
    
    return session_data


@router.post("/realtime/cursor-update", summary="Update cursor position")
async def update_cursor_position(
    template_id: str,
    user_id: str,
    position: Dict[str, int],
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Update user cursor position for real-time collaboration."""
    
    cursor_update = {
        "userId": user_id,
        "userName": f"User {user_id}",
        "position": position,
        "selection": selection,
        "color": f"#{''.join([hex(hash(user_id))[i] for i in range(2, 8)])}",
        "lastUpdate": datetime.utcnow()
    }
    
    # Update cursor position
    if template_id not in COLLABORATIVE_CURSORS:
        COLLABORATIVE_CURSORS[template_id] = []
    
    # Remove existing cursor for this user
    COLLABORATIVE_CURSORS[template_id] = [
        c for c in COLLABORATIVE_CURSORS[template_id] if c["userId"] != user_id
    ]
    
    # Add new cursor position
    COLLABORATIVE_CURSORS[template_id].append(cursor_update)
    
    # Update user presence
    if template_id in USER_PRESENCE and user_id in USER_PRESENCE[template_id]:
        USER_PRESENCE[template_id][user_id]["lastActivity"] = datetime.utcnow()
    
    return {"status": "cursor_updated", "messageId": f"cursor_{int(datetime.utcnow().timestamp())}"}


@router.post("/realtime/live-edit", summary="Apply live edit operation")
async def apply_live_edit(
    template_id: str,
    user_id: str,
    operation: str,
    position: Dict[str, int],
    content: str,
) -> Dict[str, Any]:
    """Apply live edit operation with conflict resolution."""
    
    edit_id = f"edit_{len(LIVE_EDITS.get(template_id, []))}_{int(datetime.utcnow().timestamp())}"
    
    # Get current version
    current_version = len(LIVE_EDITS.get(template_id, []))
    
    live_edit = {
        "editId": edit_id,
        "templateId": template_id,
        "userId": user_id,
        "operation": operation,
        "position": position,
        "content": content,
        "appliedAt": datetime.utcnow(),
        "version": current_version + 1
    }
    
    # Initialize if needed
    if template_id not in LIVE_EDITS:
        LIVE_EDITS[template_id] = []
    
    # Apply operational transformation for conflict resolution
    transformed_edit = await _apply_operational_transformation(
        live_edit, 
        LIVE_EDITS[template_id]
    )
    
    LIVE_EDITS[template_id].append(transformed_edit)
    
    # Update template in storage
    await _apply_edit_to_template(template_id, transformed_edit)
    
    # Broadcast to other collaborators (simulate WebSocket broadcast)
    broadcast_message = {
        "type": "live_edit",
        "editId": edit_id,
        "userId": user_id,
        "operation": operation,
        "transformedPosition": transformed_edit["position"],
        "content": content,
        "version": transformed_edit["version"],
        "timestamp": datetime.utcnow().isoformat()
    }
    
    return {
        "editId": edit_id,
        "version": transformed_edit["version"],
        "transformedPosition": transformed_edit["position"],
        "broadcastMessage": broadcast_message,
        "status": "edit_applied"
    }


@router.get("/realtime/presence/{template_id}", summary="Get user presence")
async def get_user_presence(template_id: str) -> List[PresenceIndicator]:
    """Get current user presence for collaborative session."""
    
    presence_list = []
    
    if template_id in USER_PRESENCE:
        for user_data in USER_PRESENCE[template_id].values():
            # Update status based on last activity
            last_activity = user_data["lastActivity"]
            time_diff = (datetime.utcnow() - last_activity).total_seconds()
            
            if time_diff < 30:  # 30 seconds
                status = "active"
            elif time_diff < 300:  # 5 minutes
                status = "idle"
            elif time_diff < 1800:  # 30 minutes
                status = "away"
            else:
                status = "offline"
            
            user_data["status"] = status
            
            presence = PresenceIndicator(**user_data)
            presence_list.append(presence)
    
    return presence_list
