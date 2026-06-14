## US-AI-014 — Support Simple Chat Edit Scenario

**As an** Author,
**I want** to ask the AI in chat to refine a page using natural language,
**So that** I can make targeted edits (rewrite, restructure, rephrase) without manually locating every field in the editor.

- **Source flow:** 9. Simple Chat Edit Scenario Flow (`01_SystemArchitecture/Simple_Chat_Edit_Scenario_Flow.mmd`)
- **Priority:** MUST
- **Depends on:** US-AI-007 (Page List and Fetch Tools), US-AI-012 (Update Page Proposal and Apply)
- **Unlocks:** US-AI-022 (E2E Regression Suite), US-AI-030 (Course Assembly into Editor)
- **Story point estimate:** 13 (Fibonacci)

---

### 1. FUNCTIONAL SPECIFICATION

#### 1.1 User Narrative

The author is in the course editor with the AI chat panel open. They type a natural-language instruction such as:
- "Simplify the intro paragraph on the Welcome page"
- "Make the tone more conversational on the Overview tab"
- "Add a third accordion item about safety protocols"
- "Shorten the bullet points on page 3"

The AI agent must:
1. Re-fetch the current course state from the database (never trust conversation history).
2. Resolve which page the user means (by title, by order, or by asking).
3. Fetch the full page data including components.
4. Plan the minimal patch needed to fulfill the instruction.
5. Call `propose_update_page` with the patch -- never mutate directly.
6. Return a diff, validation results, and a natural-language explanation.
7. Wait for the user to approve in the UI before calling `apply_update_proposal`.
8. After apply, return refreshed course state so the editor updates.

#### 1.2 Actor Roles

| Actor | Role |
|---|---|
| Author | Initiates chat, reviews the diff, approves/rejects the proposal, sees the updated editor |
| AI Agent (LLM) | Plans the edit, calls tools, explains changes, handles ambiguity and retries |
| Backend System | Validates session, enforces tool scope, runs validation pipeline, persists audit, returns state |
| Frontend | Renders chat UI, displays proposal diff with before/after, handles confirmation, refreshes editor |

#### 1.3 Conversation Turn Lifecycle

Each chat turn follows this state machine:

```
USER_PROMPT → SESSION_VALIDATED → AGENT_PLANNING → TOOL_CALLING → PROPOSAL_CREATED → 
USER_REVIEW → USER_APPROVED → APPLYING → APPLIED (or FAILED)
```

A turn may loop back from TOOL_CALLING to AGENT_PLANNING if validation errors occur (max 3 retries per turn).

#### 1.4 Ambiguity Resolution Protocol

When the AI cannot determine which page the user means:

| Scenario | Behavior |
|---|---|
| User says "simplify it" with no page context | AI responds: "I see 5 pages in this course. Which one would you like me to simplify? Pages: 1. Welcome, 2. Overview, 3. Safety, 4. Assessment, 5. Summary" |
| User says "update the intro" and there are 2 text-content pages | AI responds: "There are two text-content pages: 'Welcome' and 'Overview'. Which one's intro should I update?" |
| User says "change page 3" and page 3 was deleted since session start | AI re-lists pages and says: "Page 3 no longer exists. The current pages are: 1. Welcome, 2. Overview, 3. Safety, 4. Summary" |
| User says "make the first page more engaging" with no template type specified | AI fetches the first page, identifies its template type, and proposes template-appropriate improvements |

#### 1.5 Valid Chat Edit Instructions (What the System Supports)

| Category | Examples | Supported Templates |
|---|---|---|
| Content rewrite | "Simplify the intro", "Make it more concise", "Add more detail" | text-content, tabs, accordion, click-reveal |
| Tone adjustment | "Make it conversational", "More formal", "Professional tone" | text-content, tabs, accordion |
| Content addition | "Add a third bullet point", "Add another accordion item about X" | text-content (components), accordion (items), tabs (tabs) |
| Content removal | "Remove the second paragraph", "Drop the last bullet" | text-content, accordion, tabs |
| Structural | "Reorder the tabs", "Make the intro a bullet list instead of paragraphs" | text-content, tabs, accordion |
| Assessment edits | "Add a question about safety", "Make question 2 easier" | final-assessment |
| Title change | "Rename this page to 'Getting Started'" | All |

#### 1.6 What the System Rejects

- Instructions that reference unsupported templates: returns "I can only work with these template types: Text Content, Tabs, Accordion, Click and Reveal, Final Assessment"
- Instructions that attempt direct deletion: "I cannot delete pages via chat. Please use the delete page feature."
- Instructions that attempt cross-course operations: "This session is scoped to course '{course title}'. I cannot access other courses."
- Instructions that include PII or prompt injection: returns a safety violation error (per US-AI-025).
- Instructions with ambiguous targets after one clarification round: "I'm still not sure which page you mean. Please specify the page title or number."

#### 1.7 Feature Flag Gating

The entire chat endpoint is gated by `AI_AUTHORING_ENABLED` (from US-AI-002). When disabled:
- `POST /api/v1/ai/chat` returns `403 { "error": { "code": "AI_DISABLED", "message": "AI authoring is currently disabled" } }`
- Frontend hides the AI chat panel

---

### 2. TECHNICAL SPECIFICATION

#### 2.1 New Endpoint: `POST /api/v1/ai/chat`

**Router file:** `app/routers/ai_chat.py` (new file)

**Request:**

```
POST /api/v1/ai/chat
Authorization: Session {session_id}
Content-Type: application/json
```

```json
{
  "session_id": "uuid-string",
  "prompt": "Simplify the intro paragraph on the Welcome page",
  "mode": "chat_edit",
  "selected_context": {
    "page_id": "uuid-string | null",
    "component_id": "uuid-string | null"
  }
}
```

**Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string (UUID) | Yes | Active AI session from US-AI-006 |
| `prompt` | string (1-2000 chars) | Yes | The user's natural-language instruction |
| `mode` | string enum | No | `"chat_edit"` (default) or `"chat_create"` or `"chat_delete"` |
| `selected_context` | object | No | Optional frontend-provided context hint |
| `selected_context.page_id` | string (UUID) | No | Page the user has highlighted/selected in the editor |
| `selected_context.component_id` | string (UUID) | No | Component the user has focused on |

**Response (200):**

```json
{
  "chat_turn_id": "uuid-string",
  "session_id": "uuid-string",
  "message": {
    "role": "assistant",
    "content": "I've reviewed the Welcome page and simplified the intro paragraph. Here's what changed:\n\n**Before:** 'Welcome to our comprehensive safety training program designed to ensure all employees understand workplace hazards...'\n\n**After:** 'Welcome to Safety First. This course covers the key workplace hazards you need to know.'\n\nThe page now has one proposal ready for your review. Does this look good?"
  },
  "proposals": [
    {
      "proposal_id": "uuid-string",
      "proposal_type": "update_page",
      "page_id": "uuid-string",
      "status": "pending_review",
      "diff": {
        "before": { "title": "Welcome", "data": { "body": "Welcome to our comprehensive..." } },
        "after": { "title": "Welcome", "data": { "body": "Welcome to Safety First..." } },
        "changed_fields": ["data.body"]
      },
      "validation": {
        "status": "valid",
        "messages": []
      }
    }
  ],
  "tool_calls": [
    { "tool": "list_pages", "status": "success", "duration_ms": 45 },
    { "tool": "fetch_page", "page_id": "uuid", "status": "success", "duration_ms": 32 },
    { "tool": "propose_update_page", "proposal_id": "uuid", "status": "success", "duration_ms": 120 }
  ],
  "session_summary": {
    "active_proposal_ids": ["uuid"],
    "course_state_hash": "sha256-of-course-state"
  }
}
```

**Response (422 — Validation Error):**
```json
{
  "detail": "Validation failed",
  "errors": [
    { "code": "PROMPT_TOO_LONG", "field": "prompt", "message": "Prompt exceeds 2000 characters" },
    { "code": "INVALID_SESSION", "field": "session_id", "message": "Session does not exist or has expired" }
  ]
}
```

**Response (429 — Rate Limited):**
```json
{
  "detail": "Rate limit exceeded",
  "errors": [
    { "code": "RATE_LIMITED", "field": null, "message": "Max 60 chat requests per hour. Resets at 2026-06-14T13:00:00Z" }
  ]
}
```

#### 2.2 Service Layer: `app/services/ai/chat_orchestrator.py`

```python
"""AI Chat Orchestrator — manages the LLM interaction loop for chat turns."""

from __future__ import annotations
from typing import Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)

# --- Data classes ---

@dataclass
class ChatTurn:
    """One complete chat turn: user prompt -> tool loop -> assistant response."""
    chat_turn_id: str
    session_id: str
    user_prompt: str
    mode: str
    selected_context: Optional[dict]
    tool_calls: List[dict] = field(default_factory=list)
    proposals: List[dict] = field(default_factory=list)
    assistant_content: str = ""
    model_used: str = ""
    prompt_version: str = ""
    trace_id: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    max_tool_rounds: int = 10
    max_retries_per_tool: int = 3
    status: str = "in_progress"  # in_progress | completed | failed | rate_limited


class ChatOrchestrator:
    """Orchestrates the LLM interaction loop for one chat turn.

    Responsibilities:
    - Validates session and course state.
    - Builds the system prompt with current course context, tool schemas, and template registry.
    - Runs the tool-calling loop: LLM -> tool calls -> tool results -> LLM.
    - Handles tool errors by feeding them back to the LLM for retry.
    - Persists the chat turn record and links to any proposals created.
    - Returns the final assistant message with proposal diffs and session state.
    """

    def __init__(
        self,
        session_service,
        model_router,
        tool_executor,
        prompt_builder,
        turn_repo,
        audit_service,
    ):
        self.session_service = session_service
        self.model_router = model_router
        self.tool_executor = tool_executor
        self.prompt_builder = prompt_builder
        self.turn_repo = turn_repo
        self.audit_service = audit_service

    async def process_turn(
        self,
        session_id: str,
        prompt: str,
        mode: str = "chat_edit",
        selected_context: Optional[dict] = None,
    ) -> ChatTurn:
        """Process one chat turn end-to-end."""
        turn = ChatTurn(
            chat_turn_id=str(uuid.uuid4()),
            session_id=session_id,
            user_prompt=prompt,
            mode=mode,
            selected_context=selected_context,
            trace_id=str(uuid.uuid4()),
        )

        try:
            # 1. Validate session (active, not expired, correct user)
            session = await self.session_service.get_active_session(session_id)

            # 2. Build system prompt with course context, tool schemas, template registry
            system_prompt = await self.prompt_builder.build_chat_prompt(
                session=session,
                mode=mode,
                selected_context=selected_context,
            )

            # 3. Get the model (primary with fallback per US-AI-026)
            model = await self.model_router.get_model_for_task("chat_edit")

            # 4. Run the tool-calling loop (max rounds)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            tool_round = 0

            while tool_round < self.max_tool_rounds:
                tool_round += 1

                # Call LLM
                response = await model.generate(
                    messages=messages,
                    tools=self.tool_executor.get_available_tools(session),
                )

                # Check for tool calls
                if not response.tool_calls:
                    # No more tool calls; this is the final assistant response
                    turn.assistant_content = response.content
                    turn.model_used = response.model
                    turn.prompt_version = response.prompt_version
                    turn.status = "completed"
                    break

                # Execute each tool call
                for tool_call in response.tool_calls:
                    result = await self._execute_tool_with_retry(
                        session=session,
                        turn=turn,
                        tool_call=tool_call,
                    )
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call.dict()],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })

                # If we exceeded max rounds, force a summary
                if tool_round >= self.max_tool_rounds:
                    response = await model.generate(
                        messages=messages + [{
                            "role": "user",
                            "content": "You have reached the maximum number of tool calls. "
                                       "Please provide your final response based on the results you have so far."
                        }],
                    )
                    turn.assistant_content = response.content

            # 5. Persist the chat turn
            await self.turn_repo.save(turn)

            return turn

        except Exception as e:
            turn.status = "failed"
            turn.assistant_content = "I encountered an error processing your request. Please try again."
            await self.turn_repo.save(turn)
            logger.error(f"Chat turn {turn.chat_turn_id} failed", exc_info=True)
            return turn

    async def _execute_tool_with_retry(
        self,
        session,
        turn: ChatTurn,
        tool_call,
        retries: int = 3,
    ) -> dict:
        """Execute a tool call with retry on validation errors."""
        last_error = None
        for attempt in range(retries):
            try:
                result = await self.tool_executor.execute(
                    session=session,
                    tool_name=tool_call.name,
                    arguments=tool_call.input,
                )
                turn.tool_calls.append({
                    "tool": tool_call.name,
                    "status": "success",
                    "duration_ms": result.get("_duration_ms", 0),
                    "attempt": attempt + 1,
                })
                return result
            except ProposalValidationError as e:
                last_error = e
                # Feed validation error back to LLM for retry
                if attempt < retries - 1:
                    continue
        # All retries exhausted
        turn.tool_calls.append({
            "tool": tool_call.name,
            "status": "failed",
            "error": str(last_error),
            "attempt": retries,
        })
        return {"error": str(last_error), "status": "failed"}
```

#### 2.3 Repository: `app/repositories/ai_turn_repo.py`

```python
"""Repository for AI chat turns persistence."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIChatTurnRecord


class ChatTurnRepository:
    """Persistence for AI chat turns."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, turn) -> AIChatTurnRecord:
        """Upsert a chat turn record."""
        record = AIChatTurnRecord(
            chat_turn_id=turn.chat_turn_id,
            session_id=turn.session_id,
            user_prompt=turn.user_prompt,
            mode=turn.mode,
            selected_context=turn.selected_context,
            tool_calls=turn.tool_calls,
            proposals=turn.proposals,
            assistant_content=turn.assistant_content,
            model_used=turn.model_used,
            prompt_version=turn.prompt_version,
            trace_id=turn.trace_id,
            started_at=turn.started_at,
            completed_at=turn.completed_at or datetime.utcnow(),
            status=turn.status,
            max_tool_rounds=turn.max_tool_rounds,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_session(self, session_id: str, limit: int = 50) -> List[AIChatTurnRecord]:
        """Get recent turns for a session, newest first."""
        q = (
            select(AIChatTurnRecord)
            .where(AIChatTurnRecord.session_id == session_id)
            .order_by(AIChatTurnRecord.started_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get_trace(self, chat_turn_id: str) -> Optional[AIChatTurnRecord]:
        """Get a single turn by ID (for audit/debug)."""
        q = select(AIChatTurnRecord).where(
            AIChatTurnRecord.chat_turn_id == chat_turn_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def delete_expired(self, before: Optional[datetime] = None) -> int:
        """Hard-delete turns older than the cutoff (default 90 days)."""
        cutoff = before or (datetime.utcnow() - timedelta(days=90))
        q = delete(AIChatTurnRecord).where(
            AIChatTurnRecord.started_at < cutoff
        )
        result = await self.session.execute(q)
        await self.session.commit()
        return result.rowcount
```

#### 2.4 New Model: `app/models/ai_models.py`

```python
"""SQLAlchemy ORM models for AI persistence layer.

Includes: ai_sessions, ai_proposals, ai_confirmation_tokens,
ai_chat_turns, ai_audit_logs, outbox_events.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSON, Text, Integer, Boolean, ForeignKey, Float, Enum as SAEnum,
)
import enum

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# --- Enums ---

class ProposalState(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class ChatTurnStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


# --- AI Sessions ---

class AISessionRecord(Base):
    __tablename__ = "ai_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("courses.course_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active"
    )  # active | expired | revoked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    session_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


# --- AI Proposals ---

class AIProposalRecord(Base):
    __tablename__ = "ai_proposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(
        String(32)
    )  # create_page | update_page | delete_page | batch
    state: Mapped[ProposalState] = mapped_column(
        SAEnum(ProposalState, name="proposal_state"), default=ProposalState.PENDING_REVIEW
    )
    page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    base_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_candidate: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    changed_fields: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confirmation_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    chat_turn_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_chat_turns.chat_turn_id", ondelete="SET NULL"), nullable=True
    )
    tool_schema_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# --- AI Chat Turns ---

class AIChatTurnRecord(Base):
    __tablename__ = "ai_chat_turns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_turn_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"), index=True
    )
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="chat_edit")
    selected_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    proposals: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    assistant_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    max_tool_rounds: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[ChatTurnStatus] = mapped_column(
        SAEnum(ChatTurnStatus, name="chat_turn_status"),
        default=ChatTurnStatus.IN_PROGRESS,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# --- AI Audit Logs ---

class AIAuditLogRecord(Base):
    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="SET NULL"), nullable=True, index=True
    )
    chat_turn_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_chat_turns.chat_turn_id", ondelete="SET NULL"), nullable=True
    )
    proposal_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("ai_proposals.proposal_id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    course_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))  # ChatTurnCreated, ProposalCreated, ProposalApplied, etc.
    event_version: Mapped[str] = mapped_column(String(16), default="1.0")
    before_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    diff_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# --- Outbox Events ---

class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_version: Mapped[str] = mapped_column(String(16), default="1.0")
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | published | failed
```

#### 2.5 Alembic Migration: New AI Tables

Create migration file: `alembic/versions/20260614_0001_add_ai_tables.py`

```python
"""Add AI persistence tables: sessions, proposals, chat turns, audit, outbox.

Revision ID: 20260614_0001
Revises: 20260412_0003_add_export_columns_and_tables.py
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260614_0001"
down_revision = "20260412_0003_add_export_columns_and_tables"
branch_labels = None
depends_on = None


def upgrade():
    # --- ai_sessions ---
    op.create_table(
        "ai_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("session_metadata", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.course_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index("ix_ai_sessions_session_id", "ai_sessions", ["session_id"])
    op.create_index("ix_ai_sessions_user_id", "ai_sessions", ["user_id"])
    op.create_index("ix_ai_sessions_course_id", "ai_sessions", ["course_id"])
    op.create_index("ix_ai_sessions_org_id", "ai_sessions", ["organization_id"])

    # --- ai_proposals ---
    op.create_table(
        "ai_proposals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), server_default="pending_review"),
        sa.Column("page_id", sa.String(64), nullable=True),
        sa.Column("base_hash", sa.String(64), nullable=True),
        sa.Column("before_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("after_candidate", postgresql.JSONB(), nullable=True),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=True),
        sa.Column("validation_result", postgresql.JSONB(), nullable=True),
        sa.Column("confirmation_token", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("chat_turn_id", sa.String(64), nullable=True),
        sa.Column("tool_schema_version", sa.String(32), nullable=True),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_turn_id"], ["ai_chat_turns.chat_turn_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id"),
    )
    op.create_index("ix_ai_proposals_proposal_id", "ai_proposals", ["proposal_id"])
    op.create_index("ix_ai_proposals_session_id", "ai_proposals", ["session_id"])
    op.create_index("ix_ai_proposals_state", "ai_proposals", ["state"])
    op.create_index("ix_ai_proposals_idempotency", "ai_proposals", ["idempotency_key"])

    # --- ai_chat_turns ---
    op.create_table(
        "ai_chat_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_turn_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(32), server_default="chat_edit"),
        sa.Column("selected_context", postgresql.JSONB(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("proposals", postgresql.JSONB(), nullable=True),
        sa.Column("assistant_content", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("max_tool_rounds", sa.Integer(), server_default="10"),
        sa.Column("status", sa.String(32), server_default="in_progress"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_turn_id"),
    )
    op.create_index("ix_ai_chat_turns_chat_turn_id", "ai_chat_turns", ["chat_turn_id"])
    op.create_index("ix_ai_chat_turns_session_id", "ai_chat_turns", ["session_id"])
    op.create_index("ix_ai_chat_turns_trace_id", "ai_chat_turns", ["trace_id"])

    # --- ai_audit_logs ---
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("chat_turn_id", sa.String(64), nullable=True),
        sa.Column("proposal_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_version", sa.String(16), server_default="1.0"),
        sa.Column("before_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("diff_summary", postgresql.JSONB(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["ai_sessions.session_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chat_turn_id"], ["ai_chat_turns.chat_turn_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["ai_proposals.proposal_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_ai_audit_logs_event_id", "ai_audit_logs", ["event_id"])
    op.create_index("ix_ai_audit_logs_session_id", "ai_audit_logs", ["session_id"])
    op.create_index("ix_ai_audit_logs_user_id", "ai_audit_logs", ["user_id"])
    op.create_index("ix_ai_audit_logs_course_id", "ai_audit_logs", ["course_id"])
    op.create_index("ix_ai_audit_logs_event_type", "ai_audit_logs", ["event_type"])

    # --- outbox_events ---
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_version", sa.String(16), server_default="1.0"),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])


def downgrade():
    op.drop_table("outbox_events")
    op.drop_table("ai_audit_logs")
    op.drop_table("ai_chat_turns")
    op.drop_table("ai_proposals")
    op.drop_table("ai_sessions")
```

#### 2.6 Tool Executor: `app/services/ai/tool_executor.py`

```python
"""Tool executor — routes tool calls to domain services.

Every tool call is validated server-side for:
- Session validity and ownership
- Course scope (page must belong to session.course_id)
- Rate limits
- Allowed tool names
"""

from __future__ import annotations
from typing import Dict, Any, List
import time
import logging

from app.services.ai.session_service import SessionService
from app.services.ai.proposal_service import ProposalService
from app.repositories.page_component_repo import PageRepository, ComponentRepository

logger = logging.getLogger(__name__)


class ToolExecutorError(Exception):
    pass


class ToolExecutor:
    """Stateless executor that routes tool calls to underlying services."""

    def __init__(
        self,
        session_service: SessionService,
        proposal_service: ProposalService,
        page_repo: PageRepository,
        component_repo: ComponentRepository,
    ):
        self.session_service = session_service
        self.proposal_service = proposal_service
        self.page_repo = page_repo
        self.component_repo = component_repo

    def get_available_tools(self, session) -> List[Dict[str, Any]]:
        """Return the tool schemas available for this session."""
        # Return tools from TOOL_SCHEMAS_CLAUDE_NATIVE.md, filtered by session permissions
        return [
            {
                "name": "list_pages",
                "description": "List all pages in the current course.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"}
                    },
                    "required": ["session_id"],
                },
            },
            {
                "name": "fetch_page",
                "description": "Fetch a single page with full component data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "page_id": {"type": "string"},
                    },
                    "required": ["session_id", "page_id"],
                },
            },
            {
                "name": "propose_update_page",
                "description": "Propose updating an existing page. Returns a diff. Does NOT mutate.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "page_id": {"type": "string"},
                        "patch": {"type": "object"},
                    },
                    "required": ["session_id", "page_id", "patch"],
                },
            },
            {
                "name": "apply_update_proposal",
                "description": "Apply a proposed page update. Requires user_confirmed=true.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "proposal_id": {"type": "string"},
                        "user_confirmed": {"type": "boolean"},
                    },
                    "required": ["session_id", "proposal_id", "user_confirmed"],
                },
            },
            {
                "name": "query_similar_courses",
                "description": "Query for similar course examples and tone references.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "maximum": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "validate_course",
                "description": "Validate the course against schema, business rules, and export requirements.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                    "required": ["session_id"],
                },
            },
        ]

    async def execute(self, session, tool_name: str, arguments: dict) -> dict:
        """Execute a tool call with server-side validation."""
        start = time.monotonic()

        # Validate tool is allowed
        allowed_names = {t["name"] for t in self.get_available_tools(session)}
        if tool_name not in allowed_names:
            raise ToolExecutorError(f"Tool '{tool_name}' is not available in this session")

        # Validate session ownership
        if arguments.get("session_id") and arguments["session_id"] != session.session_id:
            raise ToolExecutorError("Session ID mismatch")

        try:
            if tool_name == "list_pages":
                result = await self._list_pages(session)
            elif tool_name == "fetch_page":
                result = await self._fetch_page(session, arguments)
            elif tool_name == "propose_update_page":
                result = await self._propose_update_page(session, arguments)
            elif tool_name == "apply_update_proposal":
                result = await self._apply_update_proposal(session, arguments)
            elif tool_name == "query_similar_courses":
                result = await self._query_similar_courses(arguments)
            elif tool_name == "validate_course":
                result = await self._validate_course(session)
            else:
                raise ToolExecutorError(f"Unknown tool: {tool_name}")

            result["_duration_ms"] = int((time.monotonic() - start) * 1000)
            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}", exc_info=True)
            raise ToolExecutorError(str(e))
```

#### 2.7 Prompt Builder: `app/services/ai/prompt_builder.py`

```python
"""Builds the dynamic system prompt for each chat turn.

Assembles the prompt from:
- Base system prompt (from PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md section 13.1)
- Current course context (title, page count, template types used)
- Available tool schemas
- Template registry (allowed templates only)
- User role and organization policies
"""

from __future__ import annotations
from typing import Optional

from app.repositories.page_component_repo import PageRepository


SYSTEM_PROMPT_TEMPLATE = """You are an AI Course Authoring Assistant for an enterprise LMS.
Your job is to help users create and refine courses efficiently using approved templates.

COURSE CONTEXT:
- Course: {course_title}
- Total pages: {page_count}
- Available templates: text-content, tabs, accordion, click-reveal, final-assessment

TOOLS AVAILABLE:
{tool_descriptions}

RULES (Non-Negotiable):
1. ALWAYS re-fetch page state before editing: call list_pages() or fetch_page(pageId) first.
2. Use propose_* tools (propose_update_page). These return diffs for user review.
3. Wait for user approval in the UI before calling apply_* tools.
4. Only use the 5 allowed templates listed above.
5. Validation errors are your allies: if you get a validation error, adjust and retry (max 2 retries).
6. If unsure which page the user means, ask for clarification.
7. Never call apply_* without user_confirmed=true.
8. All actions are logged for compliance and debugging.

TONE & PEDAGOGY:
- Be collaborative and educational.
- Explain why you're suggesting changes.
- Offer to refine based on feedback.
- If unsure about learning goals, ask clarifying questions.

OUTPUT FORMAT:
- For updates: "I've made these changes: [diff]. Ready to apply?"
- For errors: "This didn't work because [reason]. Let me try [alternative]."
- For ambiguity: "There are {n} pages. Which one should I update?"
"""


class PromptBuilder:
    """Builds versioned, context-aware system prompts for AI chat."""

    def __init__(self, page_repo: PageRepository, prompt_version_repo=None):
        self.page_repo = page_repo
        self.prompt_version_repo = prompt_version_repo

    async def build_chat_prompt(
        self,
        session,
        mode: str = "chat_edit",
        selected_context: Optional[dict] = None,
    ) -> str:
        """Build a system prompt for a chat turn."""
        pages = await self.page_repo.list_by_course(session.course_id)

        tool_descriptions = "\n".join(
            f"- {t['name']}: {t['description']}"
            for t in self._get_mode_tools(mode)
        )

        return SYSTEM_PROMPT_TEMPLATE.format(
            course_title=session.course_title or "Untitled Course",
            page_count=len(pages),
            tool_descriptions=tool_descriptions,
        )

    def _get_mode_tools(self, mode: str) -> list:
        """Return the tool set for the given mode."""
        core_tools = [
            {"name": "list_pages", "description": "List all pages in the current course with metadata."},
            {"name": "fetch_page", "description": "Fetch a single page with full component data."},
            {"name": "query_similar_courses", "description": "Query for similar course examples and tone references."},
            {"name": "validate_course", "description": "Validate the course against schema, business rules, and export requirements."},
        ]
        if mode == "chat_edit":
            return core_tools + [
                {"name": "propose_update_page", "description": "Propose updating an existing page. Returns a diff. Does NOT mutate."},
                {"name": "apply_update_proposal", "description": "Apply a proposed page update. Requires user_confirmed=true."},
            ]
        elif mode == "chat_create":
            return core_tools + [
                {"name": "propose_create_page", "description": "Propose creating a new page."},
                {"name": "apply_page_proposal", "description": "Apply a proposed page creation."},
            ]
        return core_tools
```

#### 2.8 Router Registration: Update `app/main.py`

Add to imports:
```python
from app.routers import ai_chat
```

Add to the `api_router.include_router(...)` block:
```python
# Only register AI routes if feature flag is enabled
if os.getenv("AI_AUTHORING_ENABLED", "false").lower() == "true":
    api_router.include_router(ai_chat.router)
```

#### 2.9 New Env Vars

| Variable | Type | Default | Description |
|---|---|---|---|
| `AI_AUTHORING_ENABLED` | string | `"false"` | Master switch for all AI authoring features |
| `AI_CHAT_MAX_TOOL_ROUNDS` | int | `10` | Max LLM tool-calling rounds per chat turn |
| `AI_CHAT_MAX_RETRIES` | int | `3` | Max retries per tool call on validation error |
| `AI_CHAT_RATE_LIMIT_PER_HOUR` | int | `60` | Max chat requests per user per hour |
| `AI_CHAT_PROMPT_MAX_LENGTH` | int | `2000` | Max user prompt characters |
| `AI_SESSION_TTL_HOURS` | int | `24` | Session time-to-live |
| `AI_PROPOSAL_TTL_HOURS` | int | `24` | Proposal time-to-live |
| `AI_TURN_RETENTION_DAYS` | int | `90` | Chat turn retention for audit |
| `AI_PRIMARY_MODEL` | string | `"gpt-4.1"` | Primary LLM model for chat |
| `AI_FALLBACK_MODEL` | string | `"gpt-4.1-mini"` | Fallback LLM model |
| `AI_TRACE_ENABLED` | string | `"true"` | Enable distributed tracing |

---

### 3. NON-FUNCTIONAL REQUIREMENTS

#### 3.1 Performance

| Metric | Target | Measurement |
|---|---|---|
| Chat turn latency (p50) | < 5 seconds | From POST to final response body |
| Chat turn latency (p95) | < 15 seconds | Including up to 3 tool-calling rounds |
| Tool call execution per tool | < 200 ms | Excluding LLM response time |
| Concurrent active sessions | >= 100 | Without degradation |
| Max tool rounds per turn | 10 | Hard limit by configuration |

#### 3.2 Availability

- Chat endpoint targets 99.9% availability within the overall API platform.
- Model provider fallback (US-AI-026) ensures continuity if primary fails.
- Database writes use async sessions with connection pooling (pool_size=10, max_overflow=20 from existing `db/config.py`).

#### 3.3 Security

- Every tool call validates session ownership and course scope server-side.
- No `execute_sql`, `direct_db_query`, or cross-course tool calls permitted (enforced in `ToolExecutor`).
- Rate limiting: 60 chat requests per user per hour, tracked by `user_id` in Redis or in-memory cache.
- Prompt injection scanning at intake (US-AI-025 integration point).
- PII redaction in audit logs: emails, phone numbers, SSN patterns replaced with `[REDACTED]` before storage.

#### 3.4 Data Retention

| Data | Retention | Cleanup |
|---|---|---|
| Chat turns | 90 days | Hard-deleted by cron job or on read |
| Proposals | 90 days after expiry/apply | Hard-deleted by cron |
| Sessions | 90 days after expiry | Soft-deleted (status=expired) |
| Audit logs | 1 year | Archival to cold storage |
| Outbox events | 30 days after publishing | Hard-deleted |

#### 3.5 Observability

- `trace_id` is generated per chat turn and propagated to all tool calls, proposals, audit writes, and outbox events.
- Every tool call records `tool_name`, `status`, `duration_ms`, and `model_used`.
- Metrics emitted (to Prometheus or logs): `ai_chat_turns_total{status}`, `ai_tool_calls_total{tool,status}`, `ai_turn_duration_ms`, `ai_model_fallback_total`.
- Logs at INFO level for turn start/completion; ERROR level for failures; DEBUG level for tool call payloads (excluding PII).

---

### 4. CURRENT STATE

#### 4.1 What Exists Today

The following from the existing codebase (`C:\Users\ADMIN\e-learning-backend\`) is ready to be reused:

**Persistence layer (SQLAlchemy async + PostgreSQL):**
- `app/models/persisted_course.py`: `CourseRecord`, `TemplateRecord`, `TemplateDefinition`, `ImportJob`, `ComponentStyleRecord`, `ExportAssetRecord`, `GlobalTemplate`
- `app/models/page_component.py`: `PageRecord` (with `page_id`, `title`, `order_index`, `layout`, `theme_config`, `completion_config`, components relationship), `ComponentRecord` (with `component_id`, `component_type`, `order_index`, `data`, `audio_config`, `completion_criteria`, `styling`)
- `app/models/component_type.py`, `app/models/scoring.py`, `app/models/theme.py`, `app/models/branching.py`

**Repository layer:**
- `app/repositories/course_repo.py`: `CourseRepository` with full CRUD
- `app/repositories/page_component_repo.py`: `PageRepository` (list_by_course, get, get_by_course_and_page, create, update, delete, reorder, count_by_course), `ComponentRepository` (list_by_page, get, create, update, delete, reorder, list_by_course)
- `app/repositories/template_definition_repo.py`, `app/repositories/component_type_repo.py`

**Router layer (FastAPI):**
- `app/routers/courses.py`: `GET/POST /api/v1/courses`, `GET/PUT/DELETE /api/v1/courses/{courseId}`
- `app/routers/page_components.py`: `GET/POST /api/v1/courses/{courseId}/pages`, `GET/PATCH/DELETE /api/v1/courses/{courseId}/pages/{pageId}`, plus component CRUD
- `app/routers/imports.py`, `app/routers/export.py`, `app/routers/media.py`

**Existing main.py pattern:** FastAPI app with `APIRouter(prefix="/api/v1")`, `get_session` dependency, CORS middleware, async lifespan with table creation and seeding.

#### 4.2 What Needs to Be Built

| Component | New File | Reference |
|---|---|---|
| AI chat router | `app/routers/ai_chat.py` | New |
| AI chat orchestrator | `app/services/ai/chat_orchestrator.py` | New |
| Tool executor | `app/services/ai/tool_executor.py` | New |
| Prompt builder | `app/services/ai/prompt_builder.py` | New |
| Session service | `app/services/ai/session_service.py` | New |
| Proposal service | `app/services/ai/proposal_service.py` | New |
| AI models (ORM) | `app/models/ai_models.py` | New |
| AI turn repository | `app/repositories/ai_turn_repo.py` | New |
| AI session repository | `app/repositories/ai_session_repo.py` | New |
| AI proposal repository | `app/repositories/ai_proposal_repo.py` | New |
| Alembic migration | `alembic/versions/20260614_0001_add_ai_tables.py` | New |
| Chat tool schemas | Part of `TOOL_SCHEMAS_CLAUDE_NATIVE.md` | Already defined |
| Flow chart | `01_SystemArchitecture/Simple_Chat_Edit_Scenario_Flow.mmd` | Already defined |
| System prompt | Section 13.1 of `PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` | Already defined |

#### 4.3 What Is Already Satisfied by Dependencies

| Capability | Satisfied By |
|---|---|
| Page CRUD repositories | US-AI-007 (list_pages, fetch_page) via existing `PageRepository` |
| Update page proposal | US-AI-012 (propose_update_page, apply_update_proposal) |
| Proposal lifecycle | US-AI-009 (generic proposal lifecycle, states, TTL) |
| Apply safety, audit, outbox | US-AI-010 (transactional apply, audit write, outbox event) |
| Validation pipeline | US-AI-008 (schema, business rules, export, accessibility) |
| AI session management | US-AI-006 (session create, validate, expire, scope) |
| Model routing and fallback | US-AI-026 (primary/fallback model, circuit breaker) |
| Feature flags and config | US-AI-002 (AI_AUTHORING_ENABLED, model config, env vars) |

---

### 5. EXPANSION POINTS (Explicitly Out of Scope for This Story)

| Feature | Story | Why Out of Scope |
|---|---|---|
| Full course creation from file | US-AI-019 | Requires file ingestion pipeline (US-AI-016, US-AI-017) |
| Batch proposal operations | US-AI-029 | Chat edit is single-page; batch is multi-page |
| Streaming responses (SSE) | US-AI-023 | Chat returns complete response; streaming is future |
| Real-time job status polling | US-AI-045 | Not needed: chat edits are synchronous |
| Course-level AI operations | US-AI-046 | Chat edit is page-level; course create/delete separate |
| Multi-user collaboration | US-AI-047 | Session is single-user; collaboration is future |
| Template harvesting | US-AI-037 | Chat edit uses existing templates, does not create new ones |
| Context window recovery | US-AI-039 | Detection and refresh of overflowing context mid-turn |
| JSON repair | US-AI-027 | LLM output repair; useful but not gating for MVP |
| A/B prompt testing | US-AI-042 | Prompt versioning and cohort assignment is separate |

---

### 6. VALIDATION

#### 6.1 Acceptance Criteria

| ID | Criterion | How to Verify |
|---|---|---|
| AC-01 | Chat instruction creates an update proposal, not a direct DB update | Call `propose_update_page`, verify `PageRecord.updated_at` is unchanged until `apply_update_proposal` is called |
| AC-02 | Ambiguous page references return a clarification prompt | Send "simplify this page" with no context; response includes page list and asks "Which page?" |
| AC-03 | Approved chat update refreshes the editor with latest DB state | After apply, `GET /api/v1/courses/{courseId}/pages/{pageId}` returns the updated page |
| AC-04 | Invalid patches return validation errors before apply | Send patch with invalid schema (e.g., missing required field); response includes error list |
| AC-05 | Expired session rejects chat requests | Call `POST /api/v1/ai/chat` with expired session; returns 403 |
| AC-06 | Rate-limited user receives 429 | Exceed 60 requests/hour; receives rate limit error with reset time |
| AC-07 | Chat turn is persisted with full tool call trace | Query `ai_chat_turns` table; verify `tool_calls` JSON includes all tool names and statuses |
| AC-08 | Audit record is created for applied chat edits | Query `ai_audit_logs`; verify event_type="ProposalApplied" with before/after snapshots |
| AC-09 | Proposal is linked to chat turn | Query `ai_proposals`; `chat_turn_id` field references the originating turn |
| AC-10 | Cross-course page reference is rejected | Send patch for a page not in session.course_id; returns permission error |
| AC-11 | Frontend can render proposal diff from response | Response includes `diff.before`, `diff.after`, `diff.changed_fields` in a stable format |
| AC-12 | Max tool rounds enforced | If LLM calls >10 tools in one turn, orchestrator forces summary response |

#### 6.2 Automated Test Scenarios

**Test files:** `tests/test_ai_chat.py`, `tests/test_ai_chat_orchestrator.py`

**Unit tests (service layer):**

```
test_chat_orchestrator_calls_list_pages_first:
  Given: Valid session, prompt="simplify the welcome page"
  When: process_turn is called
  Then: list_pages is the first tool call made (captured by mock)
  Assert: tool_calls[0].tool == "list_pages"

test_chat_orchestrator_creates_proposal_not_direct_mutation:
  Given: Valid session, mock LLM returns propose_update_page tool call
  When: process_turn is called
  Then: propose_update_page is called, PageRepository.update is NOT called
  Assert: tool_calls[1].tool == "propose_update_page"
  Assert: page_repo.update.call_count == 0

test_chat_orchestrator_handles_validation_error_retry:
  Given: First propose_update_page returns validation error
  When: process_turn is called
  Then: Second attempt at propose_update_page is made with corrected data
  Assert: tool_calls count >= 2 for propose_update_page
  Assert: final response does not include error

test_chat_orchestrator_enforces_max_tool_rounds:
  Given: Mock LLM returns tool calls indefinitely
  When: process_turn is called
  Then: After 10 rounds, a summary is returned
  Assert: turn.status == "completed"
  Assert: len(tool_calls) <= 10

test_chat_orchestrator_rejects_cross_course_reference:
  Given: Session for course A, patch references page from course B
  When: ToolExecutor.execute is called
  Then: Permission error is returned
  Assert: result has "error" containing "does not belong to course"

test_chat_orchestrator_persists_turn_record:
  Given: Valid session, successful chat turn
  When: process_turn completes
  Then: ChatTurnRepository.save was called with turn data
  Assert: turn_repo.save.call_count == 1

test_chat_orchestrator_writes_audit_on_apply:
  Given: apply_update_proposal succeeds
  When: ToolExecutor executes apply
  Then: Audit record is created
  Assert: audit_service.log.call_count == 1
```

**Integration tests (router layer):**

```
test_chat_endpoint_successful_edit:
  Given: Valid session and course with a text-content page
  When: POST /api/v1/ai/chat with prompt="simplify the intro"
  Then: Status 200, response has chat_turn_id, message, proposals[], tool_calls[]
  Assert: proposals[0].proposal_type == "update_page"
  Assert: proposals[0].diff.changed_fields includes the modified field

test_chat_endpoint_ambiguous_target:
  Given: Course with 3 pages, no selected_context
  When: POST /api/v1/ai/chat with prompt="make it shorter"
  Then: Status 200, assistant_content includes clarification question
  Assert: "Which page" in message.content
  Assert: proposals is empty (no proposal created)

test_chat_endpoint_expired_session:
  Given: Expired session
  When: POST /api/v1/ai/chat with session_id
  Then: Status 403
  Assert: error.code == "SESSION_INVALID_OR_EXPIRED"

test_chat_endpoint_rate_limited:
  Given: User has made 60 requests in the last hour
  When: POST /api/v1/ai/chat
  Then: Status 429
  Assert: error.code == "RATE_LIMITED"

test_chat_endpoint_ai_disabled:
  Given: AI_AUTHORING_ENABLED=false
  When: POST /api/v1/ai/chat
  Then: Status 403
  Assert: error.code == "AI_DISABLED"

test_chat_endpoint_prompt_too_long:
  Given: Prompt > 2000 characters
  When: POST /api/v1/ai/chat
  Then: Status 422
  Assert: error.code == "PROMPT_TOO_LONG"
```

**E2E test (full pipeline):**

```
test_simple_chat_edit_e2e:
  1. Create course with one text-content page
  2. Create AI session for that course (POST /api/v1/ai/sessions)
  3. Send chat: "Simplify the body text" with page context
  4. Verify response has proposal with diff
  5. Verify no mutation to page (GET page returns original)
  6. Call apply_update_proposal with user_confirmed=true
  7. Verify page is now updated (GET page returns new content)
  8. Verify audit log has event_type="ProposalApplied"
  9. Verify chat turn record has tool_calls and proposal_id
```

#### 6.3 Manual QA Scenarios

| Scenario | Steps | Expected |
|---|---|---|
| Happy path - page edit | 1. Open course in editor<br>2. Click "Build with AI"<br>3. Type "Make the Welcome page more concise"<br>4. Review diff in chat panel<br>5. Click Approve | Proposal created, diff shown, page updated, editor refreshes |
| Ambiguous page reference | 1. In a course with 5 pages<br>2. Type "Update the intro" | AI asks "Which page? 1. Welcome, 2. Overview..." |
| Invalid edit instruction | 1. Type "Delete the Welcome page" | AI responds: "I cannot delete via chat. Use delete page." |
| Edit assessment page | 1. Open a course with a final-assessment page<br>2. Type "Add a true/false question about safety" | Proposal adds a new question object to data.questions |
| Cancel and retry | 1. Receive a proposal<br>2. Click "Request changes"<br>3. Type "Make the tone more formal instead" | Previous proposal is rejected, new proposal created |
| Expired session mid-edit | 1. Start a session<br>2. Wait 24h (or set short TTL in config)<br>3. Send a chat message | 403 error: "Session expired. Please restart." |
| Concurrent edit by manual editor | 1. AI proposes an edit<br>2. Manual editor changes the page<br>3. Approve the AI proposal | 409 conflict: "Page has changed since proposal. Please re-edit." |

---

### 7. DEFINITION OF DONE

| Criteria | Check |
|---|---|
| All 5 acceptance criteria (AC-01 through AC-05 minimum) pass | [ ] |
| All unit tests pass with >= 90% coverage on new `app/services/ai/` and `app/routers/ai_chat.py` | [ ] |
| All integration tests pass against an isolated test database | [ ] |
| E2E test passes (full pipeline: session -> chat -> propose -> apply -> audit) | [ ] |
| Alembic migration runs cleanly both up and down | [ ] |
| Migration does not break existing course/page/component tables | [ ] |
| Feature flag `AI_AUTHORING_ENABLED=false` disables the chat endpoint without affecting other routes | [ ] |
| All new env vars documented in `.env.example` | [ ] |
| OpenAPI spec regenerated (run `generate_tool_schemas_from_openapi`) | [ ] |
| Manual QA passes all 8 scenarios from section 6.3 | [ ] |
| Rate limiting returns 429 with correct headers (Retry-After) | [ ] |
| Audit log records `event_id`, `chat_turn_id`, `proposal_id`, `before_snapshot`, `after_snapshot`, `trace_id` | [ ] |
| No PII or full prompt text stored in audit logs (redaction verified) | [ ] |
| Frontend integration: response shape matches `AIChatResponse` interface contract | [ ] |
| Performance: p95 chat latency < 15 seconds under 10 concurrent sessions | [ ] |

---

### 8. TASK BREAKDOWN

#### Chunk 0: Foundation (4 points)

| Task ID | Description | Files | Dependencies |
|---|---|---|---|
| T-001 | Create `app/models/ai_models.py` with all 5 ORM models | `app/models/ai_models.py` | None |
| T-002 | Create Alembic migration for 5 new tables | `alembic/versions/20260614_0001_add_ai_tables.py` | T-001 |
| T-003 | Implement `AISessionRepository` | `app/repositories/ai_session_repo.py` | T-001 |
| T-004 | Implement `AIProposalRepository` | `app/repositories/ai_proposal_repo.py` | T-001 |
| T-005 | Implement `ChatTurnRepository` | `app/repositories/ai_turn_repo.py` | T-001 |
| T-006 | Add env vars to `.env.example` | `.env.example` | None |
| T-007 | Wire AI tables into `main.py` lifespan import block | `app/main.py` | T-001 |

#### Chunk 1: Session & Proposal Services (3 points)

| Task ID | Description | Files | Dependencies |
|---|---|---|---|
| T-008 | Implement `SessionService` (create, validate, get_active, expire) | `app/services/ai/session_service.py` | T-003 |
| T-009 | Implement `ProposalService` (create_update_proposal, apply, reject) | `app/services/ai/proposal_service.py` | T-004 |
| T-010 | Implement `ToolExecutor` with server-side scope validation | `app/services/ai/tool_executor.py` | T-008, T-009 |
| T-011 | Implement `PromptBuilder` with dynamic context injection | `app/services/ai/prompt_builder.py` | None |

#### Chunk 2: Chat Orchestrator (4 points)

| Task ID | Description | Files | Dependencies |
|---|---|---|---|
| T-012 | Implement `ChatOrchestrator.process_turn()` with full tool loop | `app/services/ai/chat_orchestrator.py` | T-008, T-009, T-010, T-011 |
| T-013 | Implement tool error handling and retry logic in orchestrator | `app/services/ai/chat_orchestrator.py` | T-012 |
| T-014 | Implement max tool rounds enforcement | `app/services/ai/chat_orchestrator.py` | T-012 |
| T-015 | Implement turn persistence and audit coupling | `app/services/ai/chat_orchestrator.py`, T-005 | T-005, T-012 |

#### Chunk 3: Chat Router (2 points)

| Task ID | Description | Files | Dependencies |
|---|---|---|---|
| T-016 | Implement `POST /api/v1/ai/chat` route with request validation | `app/routers/ai_chat.py` | T-012 |
| T-017 | Integrate prompt safety scanning (US-AI-025 interface point) | `app/routers/ai_chat.py` | T-016 |
| T-018 | Wire chat router into `main.py` with feature flag gating | `app/main.py` | T-016 |
| T-019 | Implement rate limiting (60/hour per user, in-memory for MVP) | `app/routers/ai_chat.py` | None |

#### Chunk 4: Auditing & Observability (2 points)

| Task ID | Description | Files | Dependencies |
|---|---|---|---|
| T-020 | Implement audit log writes for successful applies | `app/services/ai/audit_service.py` | T-012 |
| T-021 | Implement trace_id propagation through all tool calls and audit | `app/services/ai/chat_orchestrator.py` | T-012 |
| T-022 | Add PII redaction hook before audit storage | `app/services/ai/audit_service.py` | T-020 |
| T-023 | Add metrics logging (turn count, tool call count, duration, model used) | `app/services/ai/chat_orchestrator.py` | T-012 |

#### Chunk 5: Testing (3 points)

| Task ID | Description | Files | Dependencies |
|---|---|---|---|
| T-024 | Write unit tests for `ChatOrchestrator` (5 test methods) | `tests/test_ai_chat_orchestrator.py` | T-012 |
| T-025 | Write unit tests for `ToolExecutor` (permissions, scoping) | `tests/test_ai_tool_executor.py` | T-010 |
| T-026 | Write integration tests for `POST /api/v1/ai/chat` (8 test cases) | `tests/test_ai_chat.py` | T-016 |
| T-027 | Write E2E test: full session -> chat -> propose -> apply -> audit flow | `tests/test_ai_chat_e2e.py` | T-016, T-020 |
| T-028 | Validate all existing course/page/component tests still pass | Run `pytest tests/` | None |

#### Total Story Points: 18 (adjusted from estimate of 13 for full production quality)

---

**Related files:**
- `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\USER_STORIES.md` (current abbreviated story at line 360)
- `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\Simple_Chat_Edit_Scenario_Flow.mmd` (4-phase flow chart)
- `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\TOOL_SCHEMAS_CLAUDE_NATIVE.md` (tool contract definitions for list_pages, fetch_page, propose_update_page, apply_update_proposal, validate_course, query_similar_courses)
- `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` (section 13.1 system prompt)
- `C:\Users\ADMIN\e-learning-backend\app\models\page_component.py` (PageRecord, ComponentRecord ORM models)
- `C:\Users\ADMIN\e-learning-backend\app\repositories\page_component_repo.py` (PageRepository, ComponentRepository)
- `C:\Users\ADMIN\e-learning-backend\app\routers\page_components.py` (existing page CRUD DTOs and endpoints)
- `C:\Users\ADMIN\e-learning-backend\app\main.py` (router registration pattern)
- `C:\Users\ADMIN\e-learning-backend\app\db\config.py` (DB engine configuration)
- `C:\Users\ADMIN\e-learning-backend\.env` (existing env vars)

---