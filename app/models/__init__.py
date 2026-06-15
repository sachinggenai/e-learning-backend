# Models package
from app.models.base import Base
from app.models.persisted_course import (
    CourseRecord,
    TemplateRecord,
    TemplateDefinition,
    ImportJob,
    GlobalTemplate,
)
from app.models.template_type import TemplateType
from app.models.component_type import ComponentType
from app.models.page_component import PageRecord, ComponentRecord
from app.models.theme import ThemeRecord
from app.models.scoring import CourseScoringRecord
from app.models.interaction_event import InteractionEventRecord
from app.models.branching import BranchRule, BranchEvent
from app.models.social import (
    DiscussionThread,
    DiscussionReply,
    PeerReviewSubmission,
    PeerReview,
    Poll,
    PollVote,
    Team,
)
from app.models.ai_models import (
    AISessionRecord,
    AIProposalRecord,
    AIConfirmationTokenRecord,
    AIAuditLogRecord,
    AIOutboxEventRecord,
    AIChatTurnRecord,
    AIIdempotencyKeyRecord,
    AIIngestionJobRecord,
)
from app.models.ai_admin_override import AIAdminOverrideRecord
from app.models.ai_safety_event import AISafetyEvent

__all__ = [
    "Base",
    "CourseRecord",
    "TemplateRecord",
    "TemplateDefinition",
    "ImportJob",
    "GlobalTemplate",
    "TemplateType",
    "ComponentType",
    "PageRecord",
    "ComponentRecord",
    "ThemeRecord",
    "CourseScoringRecord",
    "InteractionEventRecord",
    "BranchRule",
    "BranchEvent",
    "DiscussionThread",
    "DiscussionReply",
    "PeerReviewSubmission",
    "PeerReview",
    "Poll",
    "PollVote",
    "Team",
    # AI Persistence
    "AISessionRecord",
    "AIProposalRecord",
    "AIConfirmationTokenRecord",
    "AIAuditLogRecord",
    "AIOutboxEventRecord",
    "AIChatTurnRecord",
    "AIIdempotencyKeyRecord",
    "AIIngestionJobRecord",
    # Admin Override (US-BKND-AI-049)
    "AIAdminOverrideRecord",
    # Safety Events (US-BKND-AI-025)
    "AISafetyEvent",
]
