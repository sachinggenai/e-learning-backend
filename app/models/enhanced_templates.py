"""
Enhanced Template Models for Template Enhancement Features

This module provides comprehensive template models supporting:
- Template categories and organization
- Advanced search and filtering
- Template customization and configuration
- Custom template creation and management
- Sharing and collaboration features
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal, Union
from datetime import datetime
from enum import Enum
try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    PYDANTIC_V2 = True
except ImportError:
    from pydantic import BaseModel, Field, validator
    PYDANTIC_V2 = False


# Template Categories
class TemplateCategory(str, Enum):
    WELCOME = "welcome"
    CONTENT = "content"
    ASSESSMENT = "assessment"
    INTERACTIVE = "interactive"
    CUSTOM = "custom"


# Template Types (expanded from original)
TemplateType = Literal[
    "welcome",
    "content-text",
    "content-video",
    "content-audio",
    "content-image",
    "mcq",
    "true-false",
    "matching",
    "drag-drop",
    "summary",
    "interactive",
    "custom"
]


# Difficulty Levels
DifficultyLevel = Literal["beginner", "intermediate", "advanced"]


# Field Types for Custom Templates
FieldType = Literal[
    "text",
    "rich-text",
    "textarea",
    "number",
    "boolean",
    "select",
    "multiselect",
    "media",
    "list",
    "date",
    "email",
    "url"
]


# Share Types
ShareType = Literal["private", "organization", "public", "link"]


class FieldValidation(BaseModel):
    """Validation rules for template fields"""
    required: Optional[bool] = False
    minLength: Optional[int] = None
    maxLength: Optional[int] = None
    min: Optional[int] = None
    max: Optional[int] = None
    pattern: Optional[str] = None
    customRules: Optional[List[str]] = None


class SelectOption(BaseModel):
    """Option for select/multiselect fields"""
    value: str
    label: str
    disabled: Optional[bool] = False


class FieldDefinition(BaseModel):
    """Definition of a template field"""
    id: str = Field(..., description="Unique field identifier")
    name: str = Field(..., description="Field name for data binding")
    type: FieldType = Field(..., description="Field type")
    label: str = Field(..., description="Display label")
    description: Optional[str] = None
    required: bool = False
    defaultValue: Optional[Any] = None
    placeholder: Optional[str] = None
    validation: Optional[FieldValidation] = None
    options: Optional[List[SelectOption]] = None  # For select fields
    order: int = Field(0, description="Display order")
    
    # Media field specific
    mediaTypes: Optional[List[str]] = None
    maxFileSize: Optional[int] = None
    
    # Rich text field specific
    toolbarOptions: Optional[List[str]] = None


class LayoutDefinition(BaseModel):
    """Template layout configuration"""
    type: Literal[
        "single-column", "two-column", "grid", "custom"
    ] = "single-column"
    columns: Optional[int] = 1
    sections: Optional[List[Dict[str, Any]]] = None


class StylingDefinition(BaseModel):
    """Template styling configuration"""
    theme: Optional[str] = "default"
    primaryColor: Optional[str] = None
    backgroundColor: Optional[str] = None
    fontFamily: Optional[str] = None
    customCSS: Optional[str] = None


class PreviewData(BaseModel):
    """Template preview information"""
    thumbnailUrl: Optional[str] = None
    previewType: Literal["static", "interactive", "video"] = "static"
    previewImages: Optional[List[str]] = None
    previewHtml: Optional[str] = None
    interactiveUrl: Optional[str] = None


class TemplateMetadata(BaseModel):
    """Template metadata and usage information"""
    estimatedTime: Optional[int] = None  # Minutes
    difficulty: Optional[DifficultyLevel] = None
    tags: List[str] = []
    learningObjectives: Optional[List[str]] = None
    prerequisites: Optional[List[str]] = None
    usageCount: int = 0
    lastUsed: Optional[datetime] = None
    averageRating: Optional[float] = None
    keyFeatures: Optional[List[str]] = None


class TemplateStructure(BaseModel):
    """Template structure definition"""
    fields: List[FieldDefinition] = []
    layout: LayoutDefinition = LayoutDefinition()
    styling: Optional[StylingDefinition] = None
    sections: Optional[List[Dict[str, Any]]] = None


class SharePermissions(BaseModel):
    """Template sharing permissions"""
    canView: bool = True
    canEdit: bool = False
    canComment: bool = False
    canShare: bool = False
    canDelete: bool = False


class TemplateShare(BaseModel):
    """Template sharing information"""
    id: str
    shareType: ShareType
    permissions: SharePermissions
    sharedBy: str  # User ID
    sharedAt: datetime
    expiresAt: Optional[datetime] = None
    recipients: Optional[List[str]] = None  # Email addresses or user IDs
    shareUrl: Optional[str] = None
    message: Optional[str] = None


class EnhancedTemplate(BaseModel):
    """Enhanced template model with full feature support"""
    
    # Basic template information
    id: str = Field(..., description="Unique template identifier")
    templateId: str = Field(..., description="Template ID for referencing")
    name: str = Field(..., min_length=1, max_length=200,
                      description="Template name")
    description: str = Field("", max_length=1000,
                             description="Template description")
    
    # Template classification
    category: TemplateCategory = Field(..., description="Template category")
    type: TemplateType = Field(..., description="Template type")
    
    # Template structure and configuration
    structure: TemplateStructure = Field(default_factory=TemplateStructure)
    defaultContent: Optional[Dict[str, Any]] = None
    sampleContent: Optional[Dict[str, Any]] = None
    
    # Preview and metadata
    preview: Optional[PreviewData] = None
    metadata: TemplateMetadata = Field(default_factory=TemplateMetadata)
    
    # Custom template properties
    isCustom: bool = False
    isSystem: bool = True
    createdBy: Optional[str] = None  # User ID
    organizationId: Optional[str] = None
    
    # Sharing and collaboration
    isPublic: bool = False
    shares: Optional[List[TemplateShare]] = None
    
    # Tags and categorization
    tags: List[str] = []
    
    # Timestamps
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)
    
    # Version control
    version: str = "1.0.0"
    parentTemplateId: Optional[str] = None  # For template variants
    
    if PYDANTIC_V2:
        @field_validator('name')
        @classmethod
        def validate_name(cls, v: str) -> str:
            if not v.strip():
                raise ValueError("Template name cannot be empty")
            return v.strip()
        
        @field_validator('tags', mode='before')
        @classmethod
        def validate_tags(cls, v):
            if isinstance(v, str):
                return [tag.strip() for tag in v.split(',') if tag.strip()]
            return v or []
        
        @model_validator(mode='after')
        def validate_template_consistency(self):
            # Validate that custom templates have required fields
            if self.isCustom and not self.createdBy:
                raise ValueError("Custom templates must have a creator")
            
            # Validate structure consistency
            if self.structure.fields:
                field_ids = [f.id for f in self.structure.fields]
                if len(field_ids) != len(set(field_ids)):
                    raise ValueError(
                        "Duplicate field IDs in template structure"
                    )
            
            return self
    else:
        @validator('name')
        def validate_name(cls, v):
            if not v.strip():
                raise ValueError("Template name cannot be empty")
            return v.strip()
        
        @validator('tags', pre=True, check_fields=False)
        def validate_tags(cls, v):
            if isinstance(v, str):
                return [tag.strip() for tag in v.split(',') if tag.strip()]
            return v or []

# Template Configuration Models


class PageConfiguration(BaseModel):
    """Configuration for pages created from templates"""
    
    # Basic settings
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    tags: List[str] = []
    
    # Learning design
    learningObjectives: List[str] = []
    prerequisites: List[str] = []
    estimatedDuration: Optional[int] = None  # Minutes
    
    # Navigation settings
    allowSkip: bool = True
    showProgress: bool = True
    requireCompletion: bool = False
    
    # Assessment settings (for assessment templates)
    passingScore: Optional[int] = None  # Percentage
    maxAttempts: Optional[int] = None
    timeLimit: Optional[int] = None  # Minutes
    showFeedback: bool = True
    randomizeQuestions: bool = False
    
    # Accessibility
    accessibility: Optional[Dict[str, bool]] = None


class ConfigurationSection(BaseModel):
    """Section in the configuration form"""
    id: str
    title: str
    description: Optional[str] = None
    order: int = 0
    fields: List[str] = []  # Field IDs
    conditional: Optional[Dict[str, Any]] = None


class TemplateConfigurationSchema(BaseModel):
    """Schema for template configuration"""
    templateId: str
    sections: List[ConfigurationSection] = []
    validation: Optional[Dict[str, FieldValidation]] = None
    defaults: Optional[Dict[str, Any]] = None

# Search and Filter Models


class TemplateSearchFilters(BaseModel):
    """Filters for template search"""
    query: Optional[str] = None
    categories: Optional[List[TemplateCategory]] = None
    types: Optional[List[TemplateType]] = None
    difficulty: Optional[List[DifficultyLevel]] = None
    tags: Optional[List[str]] = None
    isCustom: Optional[bool] = None
    createdBy: Optional[str] = None
    dateRange: Optional[Dict[str, datetime]] = None


class TemplateSortOptions(BaseModel):
    """Sorting options for templates"""
    field: Literal[
        "name", "created", "updated", "usage", "rating", "relevance"
    ] = "name"
    order: Literal["asc", "desc"] = "asc"


class TemplateSearchRequest(BaseModel):
    """Template search request"""
    filters: Optional[TemplateSearchFilters] = None
    sort: Optional[TemplateSortOptions] = None
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    includePreview: bool = False
    includeMetadata: bool = False


class TemplateSearchResult(BaseModel):
    """Template search result"""
    templates: List[EnhancedTemplate]
    totalResults: int
    page: int
    limit: int
    totalPages: int
    searchTime: Optional[float] = None  # Milliseconds
    suggestions: Optional[List[str]] = None


# Batch Operations


class BatchPageRequest(BaseModel):
    """Request for creating a page in batch operation"""
    templateId: str
    title: str
    configuration: Optional[PageConfiguration] = None
    content: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class BatchCreateRequest(BaseModel):
    """Request for batch page creation"""
    pages: List[BatchPageRequest] = Field(..., min_length=1, max_length=100)
    commonSettings: Optional[PageConfiguration] = None
    insertPosition: Union[Literal["start", "end"], Dict[str, str]] = "end"
    dryRun: bool = False


class BatchError(BaseModel):
    """Error in batch operation"""
    pageIndex: int
    pageTitle: str
    error: str
    code: str
    recoverable: bool = False


class BatchOperationStatus(BaseModel):
    """Status of batch operation"""
    batchId: str
    status: Literal[
        "pending", "processing", "completed", "failed", "cancelled"
    ]
    progress: float = 0.0  # 0-100
    totalItems: int
    processedItems: int = 0
    errors: List[BatchError] = []
    startedAt: Optional[datetime] = None
    completedAt: Optional[datetime] = None
    estimatedTimeRemaining: Optional[int] = None  # Seconds


# Course Structure Patterns


class PatternParameter(BaseModel):
    """Parameter for course structure pattern"""
    id: str
    name: str
    type: Literal["number", "select", "boolean", "text"]
    label: str
    description: str
    required: bool = False
    defaultValue: Optional[Any] = None
    options: Optional[List[SelectOption]] = None
    validation: Optional[FieldValidation] = None


class StructureItem(BaseModel):
    """Item in course structure"""
    templateId: str
    title: str
    description: str
    order: int
    section: Optional[str] = None
    configuration: Optional[PageConfiguration] = None


class CoursePattern(BaseModel):
    """Course structure pattern"""
    id: str
    name: str
    description: str
    category: str
    difficulty: DifficultyLevel
    estimatedPages: int
    customizable: bool = False
    parameters: Optional[List[PatternParameter]] = None
    structure: List[StructureItem] = []
    tags: List[str] = []


class GenerateStructureRequest(BaseModel):
    """Request to generate course structure"""
    patternId: str
    parameters: Optional[Dict[str, Any]] = None
    customization: Optional[Dict[str, Any]] = None


# Analytics Models


class TemplateUsageStats(BaseModel):
    """Template usage statistics"""
    templateId: str
    totalUsage: int
    recentUsage: int  # Last 30 days
    averageCompletionTime: Optional[float] = None  # Minutes
    successRate: Optional[float] = None  # Percentage
    userCount: int = 0
    trending: bool = False


class CategoryUsageStats(BaseModel):
    """Category usage statistics"""
    categoryId: str
    categoryName: str
    templateCount: int
    totalUsage: int
    averageRating: Optional[float] = None


class AdminDashboardData(BaseModel):
    """Admin dashboard data"""
    overview: Dict[str, Any]
    usage: Dict[str, Any]
    performance: Dict[str, Any]
    health: Dict[str, Any]
    generatedAt: datetime = Field(default_factory=datetime.utcnow)


# Error Models


class ValidationError(BaseModel):
    """Validation error details"""
    field: str
    message: str
    code: str
    value: Optional[Any] = None


class ValidationResponse(BaseModel):
    """Validation response"""
    valid: bool
    errors: List[ValidationError] = []
    warnings: Optional[List[Dict[str, Any]]] = None
    suggestions: Optional[List[Dict[str, Any]]] = None
