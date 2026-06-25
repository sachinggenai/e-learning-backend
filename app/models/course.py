"""
Pydantic Models for Course Data

These models provide type validation and serialization for the eLearning course structure.
They follow the JSON Schema specification defined in /shared/schema/course.json
and implement the Phase 1 requirements for data validation.
"""

from typing import Any, List, Optional, Literal
# Pydantic v1/v2 compatibility imports
try:  # Prefer Pydantic v2 style APIs
    from pydantic import BaseModel, Field, field_validator, model_validator
    from pydantic import ConfigDict
    PYDANTIC_V2 = True
except ImportError:  # Fallback to Pydantic v1
    from pydantic import BaseModel, Field, validator  # type: ignore
    PYDANTIC_V2 = False
from datetime import datetime

# Template type definitions - hybrid enum/DB approach for Phase 2
# Built-in types (always available)
BUILTIN_TEMPLATE_TYPES = [
    "welcome", 
    "content-video", 
    "mcq", 
    "content-text", 
    "summary",
    "final-assessment",  # Assessment template type
    "tabs",              # Content organization
    "accordion",         # Content organization
    "video",             # Alias for content-video
    "quiz",              # Alias for mcq
]

# Type normalization: map AI-generated / legacy types → canonical BUILTIN_TEMPLATE_TYPES.
# Single source of truth for all downstream consumers (assembler, export, SCORM).
TYPE_NORMALIZATION: dict[str, str] = {
    # AI-generated → canonical
    "text-content": "content-text",
    "text-with-media": "content-text",
    "content-media": "content-text",
    "content-audio": "content-text",
    "content-image": "content-text",
    "click-reveal": "accordion",
    "interactive": "content-text",
    "video": "content-video",
    "quiz": "mcq",
    # Canonical types (identity, for safe pass-through)
    "content-text": "content-text",
    "accordion": "accordion",
    "tabs": "tabs",
    "final-assessment": "final-assessment",
    "content-video": "content-video",
    "mcq": "mcq",
    "welcome": "welcome",
    "summary": "summary",
}


def normalize_template_type(template_type: str) -> str:
    """Map type alias to its canonical BUILTIN_TEMPLATE_TYPE.

    Unknown types are returned as-is for forward compatibility.
    """
    return TYPE_NORMALIZATION.get(template_type, template_type)


# Allow any string for dynamic types loaded from DB
TemplateType = str  # Changed from Literal for hybrid enum/DB support
AssetType = Literal["video", "image", "audio", "document", "other"]
ThemeType = Literal["default", "dark", "light", "corporate"]
LanguageType = Literal["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"]

if PYDANTIC_V2:
    # Pydantic v2 implementations
    class QuestionOption(BaseModel):
        """MCQ Question Option Model"""
        id: str = Field(..., description="Option identifier")
        text: str = Field(..., min_length=1, description="Option text")
        isCorrect: bool = Field(default=False, description="Whether this option is correct")

    class Question(BaseModel):
        """MCQ Question Model"""
        id: str = Field(..., description="Question identifier")
        question: str = Field(..., min_length=1, description="Question text")
        options: List[QuestionOption] = Field(..., min_length=2, max_length=6, description="Answer options")

        @field_validator('options')
        def validate_options(cls, v: List[QuestionOption]):
            if not any(opt.isCorrect for opt in v):
                raise ValueError("At least one correct answer is required")
            return v

    class MCQData(BaseModel):
        """MCQ Template Data Model"""
        content: str = Field(..., description="MCQ content/instructions")
        questions: List[Question] = Field(..., min_length=1, description="List of questions")

    class FinalAssessmentQuestion(BaseModel):
        """Final Assessment Question Model (mixed question formats)."""
        id: str = Field(..., description="Question identifier")
        type: Literal["mcq", "multiple-select", "true-false", "fill-in-blank"] = Field(..., description="Question interaction type")
        question: str = Field(..., min_length=1, description="Question text")
        options: Optional[List[QuestionOption]] = Field(None, min_length=2, description="Options for mcq/multiple-select/true-false questions")
        correctAnswer: Optional[bool] = Field(None, description="Correct answer for true-false questions")
        correctAnswers: Optional[List[str]] = Field(None, min_length=1, description="Accepted answers for fill-in-blank questions")
        explanation: Optional[str] = Field(None, description="Optional explanation shown after submit")
        points: float = Field(default=1, ge=0, description="Points allocated to this question")

        @model_validator(mode='after')
        def validate_question_shape(self):  # type: ignore[override]
            if self.type in {"mcq", "multiple-select"}:
                if not self.options:
                    raise ValueError(f"{self.type} final-assessment questions require options")
                if not any(opt.isCorrect for opt in self.options):
                    raise ValueError(f"{self.type} final-assessment questions require at least one correct option")
            if self.type == "true-false":
                if self.correctAnswer is None:
                    raise ValueError("True/False final-assessment questions require correctAnswer")
            if self.type == "fill-in-blank":
                if not self.correctAnswers:
                    raise ValueError("Fill-in-blank final-assessment questions require correctAnswers")
            return self

    class FinalAssessmentData(BaseModel):
        """Final Assessment Template Data Model."""
        introText: Optional[str] = Field(None, description="Assessment introduction text")
        passingScore: int = Field(default=80, ge=0, le=100, description="Passing score percentage")
        maxAttempts: int = Field(default=1, ge=1, description="Maximum attempts allowed")
        shuffleQuestions: bool = Field(default=False, description="Whether question order can be shuffled")
        shuffleOptions: bool = Field(default=False, description="Whether option order can be shuffled")
        showCorrectAnswers: bool = Field(default=True, description="Show correct answers after submission")
        questions: List[FinalAssessmentQuestion] = Field(..., min_length=1, description="Assessment questions")

    class TemplateData(BaseModel):
        """Template Data Model - flexible structure for different template types"""
        model_config = ConfigDict(extra="allow")

        content: Optional[str] = Field(None, description="Main content text")
        subtitle: Optional[str] = Field(None, description="Optional subtitle")
        videoUrl: Optional[str] = Field(None, description="Video URL for content-video templates")
        # Keep raw question objects to avoid lossy coercion before template-specific validation.
        questions: Optional[List[dict[str, Any]]] = Field(None, description="Questions for assessment templates")
        tabs: Optional[List[dict]] = Field(None, description="Tabs data for tabs templates")
        panels: Optional[List[dict]] = Field(None, description="Panel data for accordion templates")
        # text-with-media / content-media fields
        body: Optional[str] = Field(None, description="Rich text body for text-with-media")
        mediaUrl: Optional[str] = Field(None, description="Media URL for text-with-media")
        mediaType: Optional[str] = Field(None, description="Media type: image | video | none")
        mediaPosition: Optional[str] = Field(None, description="Media position: left | right | top | bottom")

    class Template(BaseModel):
        """Course Template/Slide Model"""
        id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$", description="Unique template identifier")
        type: TemplateType = Field(..., description="Template type")
        order: int = Field(..., ge=0, description="Display order")
        title: str = Field(..., max_length=100, description="Template title")
        data: TemplateData = Field(..., description="Template-specific data")
        pageId: Optional[str] = Field(None, description="Source page ID for theme scoping")

        @model_validator(mode='after')
        def validate_template_data(self):  # type: ignore[override]
            template_type = self.type
            data = self.data
            if template_type == 'mcq':
                if not data.questions or len(data.questions) == 0:
                    raise ValueError("MCQ templates must have at least one question")
                for question in data.questions:
                    if isinstance(question, Question):
                        continue
                    Question(**question)
            if template_type == 'final-assessment':
                FinalAssessmentData(**data.model_dump())
            if template_type == 'content-video':
                if data.videoUrl and not data.videoUrl.startswith(('http://', 'https://')):
                    raise ValueError("Video URL must be a valid HTTP/HTTPS URL")
            return self
else:
    # Pydantic v1 implementations (original)
    class QuestionOption(BaseModel):
        """MCQ Question Option Model"""
        id: str = Field(..., description="Option identifier")
        text: str = Field(..., min_length=1, description="Option text")
        isCorrect: bool = Field(default=False, description="Whether this option is correct")

    class Question(BaseModel):
        """MCQ Question Model"""
        id: str = Field(..., description="Question identifier")
        question: str = Field(..., min_length=1, description="Question text")
        options: List[QuestionOption] = Field(..., min_items=2, max_items=6, description="Answer options")

        @validator('options')
        def validate_options(cls, options):  # type: ignore[override]
            if not any(opt.isCorrect for opt in options):
                raise ValueError("At least one correct answer is required")
            return options

    class MCQData(BaseModel):
        """MCQ Template Data Model"""
        content: str = Field(..., description="MCQ content/instructions")
        questions: List[Question] = Field(..., min_items=1, description="List of questions")

    class FinalAssessmentQuestion(BaseModel):
        """Final Assessment Question Model (mixed question formats)."""
        id: str = Field(..., description="Question identifier")
        type: Literal["mcq", "multiple-select", "true-false", "fill-in-blank"] = Field(..., description="Question interaction type")
        question: str = Field(..., min_length=1, description="Question text")
        options: Optional[List[QuestionOption]] = Field(None, min_items=2, description="Options for mcq/multiple-select/true-false questions")
        correctAnswer: Optional[bool] = Field(None, description="Correct answer for true-false questions")
        correctAnswers: Optional[List[str]] = Field(None, min_items=1, description="Accepted answers for fill-in-blank questions")
        explanation: Optional[str] = Field(None, description="Optional explanation shown after submit")
        points: float = Field(default=1, ge=0, description="Points allocated to this question")

        @validator('correctAnswers', always=True)
        def validate_question_shape(cls, correct_answers, values):  # type: ignore[override]
            question_type = values.get("type")
            options = values.get("options")
            correct_answer = values.get("correctAnswer")

            if question_type in {"mcq", "multiple-select"}:
                if not options:
                    raise ValueError(f"{question_type} final-assessment questions require options")
                if not any(opt.isCorrect for opt in options):
                    raise ValueError(f"{question_type} final-assessment questions require at least one correct option")
            if question_type == "true-false":
                if correct_answer is None:
                    raise ValueError("True/False final-assessment questions require correctAnswer")
            if question_type == "fill-in-blank":
                if not correct_answers:
                    raise ValueError("Fill-in-blank final-assessment questions require correctAnswers")
            return correct_answers

    class FinalAssessmentData(BaseModel):
        """Final Assessment Template Data Model."""
        introText: Optional[str] = Field(None, description="Assessment introduction text")
        passingScore: int = Field(default=80, ge=0, le=100, description="Passing score percentage")
        maxAttempts: int = Field(default=1, ge=1, description="Maximum attempts allowed")
        shuffleQuestions: bool = Field(default=False, description="Whether question order can be shuffled")
        shuffleOptions: bool = Field(default=False, description="Whether option order can be shuffled")
        showCorrectAnswers: bool = Field(default=True, description="Show correct answers after submission")
        questions: List[FinalAssessmentQuestion] = Field(..., min_items=1, description="Assessment questions")

    class TemplateData(BaseModel):
        """Template Data Model - flexible structure for different template types"""
        class Config:
            extra = "allow"

        content: Optional[str] = Field(None, description="Main content text")
        subtitle: Optional[str] = Field(None, description="Optional subtitle")
        videoUrl: Optional[str] = Field(None, description="Video URL for content-video templates")
        # Keep raw question objects to avoid lossy coercion before template-specific validation.
        questions: Optional[List[dict[str, Any]]] = Field(None, description="Questions for assessment templates")
        tabs: Optional[List[dict]] = Field(None, description="Tabs data for tabs templates")
        panels: Optional[List[dict]] = Field(None, description="Panel data for accordion templates")
        # text-with-media fields
        body: Optional[str] = Field(None, description="Rich text body for text-with-media")
        mediaUrl: Optional[str] = Field(None, description="Media URL for text-with-media")
        mediaType: Optional[str] = Field(None, description="Media type: image | video | none")
        mediaPosition: Optional[str] = Field(None, description="Media position: left | right | top | bottom")

    class Template(BaseModel):
        """Course Template/Slide Model"""
        id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$", description="Unique template identifier")
        type: TemplateType = Field(..., description="Template type")
        order: int = Field(..., ge=0, description="Display order")
        title: str = Field(..., max_length=100, description="Template title")
        data: TemplateData = Field(..., description="Template-specific data")
        pageId: Optional[str] = Field(None, description="Source page ID for theme scoping")

        @validator('data')
        def validate_template_data(cls, data, values):  # type: ignore[override]
            template_type = values.get('type')
            if template_type == 'mcq':
                if not data.questions or len(data.questions) == 0:
                    raise ValueError("MCQ templates must have at least one question")
                for question in data.questions:
                    if isinstance(question, Question):
                        continue
                    Question(**question)
            if template_type == 'final-assessment':
                try:
                    # Validate final assessment structure
                    questions = data.questions
                    if not isinstance(questions, list):
                        if isinstance(questions, str):
                            # Handle case where questions is a string (malformed data)
                            raise ValueError(
                                f"Final Assessment 'questions' must be a list of question objects, got string: {repr(questions[:50])}"
                            )
                        raise ValueError(f"Final Assessment 'questions' must be a list, got {type(questions).__name__}")
                    
                    if len(questions) == 0:
                        raise ValueError("Final Assessment must have at least one question")
                    
                    # Validate each question
                    for idx, question in enumerate(questions):
                        if isinstance(question, dict):
                            FinalAssessmentQuestion(**question)
                        elif hasattr(question, '__dict__'):
                            FinalAssessmentQuestion(**question.__dict__)
                        else:
                            raise ValueError(f"Question {idx} has invalid format: {type(question)}")
                    
                    # Full data validation
                    FinalAssessmentData(**data.dict())
                except ValueError as ve:
                    raise ValueError(f"Final Assessment validation failed: {str(ve)}")
                except Exception as e:
                    raise ValueError(f"Final Assessment validation error: {type(e).__name__}: {str(e)}")
            if template_type == 'content-video':
                if data.videoUrl and not data.videoUrl.startswith(('http://', 'https://')):
                    raise ValueError("Video URL must be a valid HTTP/HTTPS URL")
            return data



class Asset(BaseModel):
    """Course Asset Model"""
    id: str = Field(..., description="Asset identifier")
    path: str = Field(..., description="Asset file path")
    type: AssetType = Field(..., description="Asset type")
    name: str = Field(..., description="Asset display name")
    size: Optional[int] = Field(None, ge=0, description="File size in bytes")
    mimeType: Optional[str] = Field(None, description="MIME type")


class NavigationSettings(BaseModel):
    """Course Navigation Settings"""
    allowSkip: bool = Field(default=True, description="Allow users to skip slides")
    showProgress: bool = Field(default=True, description="Show progress indicator")
    linearProgression: bool = Field(default=False, description="Force linear progression")


class CourseSettings(BaseModel):
    """Course Settings"""
    theme: ThemeType = Field(default="default", description="Course theme")
    autoplay: bool = Field(default=False, description="Auto-advance slides")
    duration: Optional[int] = Field(None, ge=1, description="Expected duration in minutes")


class Course(BaseModel):
    """Main Course Model"""
    courseId: str = Field(
        ..., pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=50, description="Unique course identifier"
    )
    title: str = Field(..., min_length=1, max_length=200, description="Course title")
    author: str = Field(..., min_length=1, max_length=100, description="Course author")
    language: LanguageType = Field(default="en", description="Course language")
    description: Optional[str] = Field(None, max_length=500, description="Course description")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$", description="Course version")
    createdAt: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updatedAt: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")
    templates: List[Template] = Field(default_factory=list, description="Course templates/slides")
    assets: List[Asset] = Field(default_factory=list, description="Course assets")
    navigation: NavigationSettings = Field(default_factory=NavigationSettings, description="Navigation settings")
    settings: CourseSettings = Field(default_factory=CourseSettings, description="Course settings")

    if PYDANTIC_V2:
        @field_validator('templates')  # type: ignore[misc]
        def validate_template_ordering(cls, templates: List[Template]):
            if not templates:
                return templates
            orders = [t.order for t in templates]
            if len(orders) != len(set(orders)):
                raise ValueError("Template orders must be unique")
            expected_orders = list(range(len(templates)))
            if sorted(orders) != expected_orders:
                raise ValueError(
                    f"Template orders must be sequential starting from 0. Expected: {expected_orders}, got: {sorted(orders)}"
                )
            return templates
    else:
        @validator('templates')  # type: ignore[misc]
        def validate_template_ordering(cls, templates):  # type: ignore[override]
            if not templates:
                return templates
            orders = [t.order for t in templates]
            if len(orders) != len(set(orders)):
                raise ValueError("Template orders must be unique")
            expected_orders = list(range(len(templates)))
            if sorted(orders) != expected_orders:
                raise ValueError(
                    f"Template orders must be sequential starting from 0. Expected: {expected_orders}, got: {sorted(orders)}"
                )
            return templates


# API Request/Response Models
class CourseExportRequest(BaseModel):
    """Request model for course export

    NOTE: Intentionally only validates that the payload is syntactically valid JSON.
    Full semantic validation (Pydantic Course model + business rules) is performed
    once inside the FastAPI dependency `validate_course_json` in utils/validation.py.

    This avoids performing the heavy Course(**data) construction twice which previously
    produced duplicated 422 error entries and masked the true source of failures.
    """
    course: str = Field(..., description="JSON stringified course object")

    if PYDANTIC_V2:
        @field_validator('course')  # type: ignore[misc]
        def validate_json_only(cls, course_str: str):
            import json
            try:
                json.loads(course_str)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format")
            return course_str
    else:
        @validator('course')  # type: ignore[misc]
        def validate_json_only(cls, course_str):  # type: ignore[override]
            import json
            try:
                json.loads(course_str)
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON format")
            return course_str


class CourseExportResponse(BaseModel):
    """Response model for course export"""
    success: bool = Field(..., description="Export success status")
    filename: str = Field(..., description="Generated filename")
    size: int = Field(..., description="File size in bytes")
    message: str = Field(..., description="Success message")


class ApiResponse(BaseModel):
    """Generic API Response Model"""
    success: bool = Field(..., description="Request success status")
    message: str = Field(..., description="Response message")
    data: Optional[dict] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message if any")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


class HealthCheckResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Current environment")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Check timestamp")
    uptime: Optional[float] = Field(None, description="Uptime in seconds")


# Validation utility function
def validate_course_data(course_data: dict) -> Course:
    """
    Validate course data dictionary against Course model
    
    Args:
        course_data: Dictionary containing course data
        
    Returns:
        Validated Course instance
        
    Raises:
        ValidationError: If course data is invalid
    """
    return Course(**course_data)
