# US-AI-039: Session Context Window Recovery

**Status:** Draft
**Priority:** SHOULD (Production Hardening)
**Depends on:** US-AI-006 (AI Sessions), US-AI-023 (AI Chat Endpoint and LLM Interaction Loop)
**Source flows:** 27. Session Context Window Recovery
**Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As an **Author**, I want the AI session to recover gracefully when the LLM context window truncates mid-session, so that I can continue working without losing course state or restarting from scratch.

As an **Operator**, I want the system to proactively manage context window pressure through token accounting, summarization, and transparent rehydration, so that long AI authoring sessions remain usable and cost-predictable without silent data loss.

### 1.2 Overview

The Anthropic Claude Messages API enforces a maximum context window (typically 200,000 tokens for `claude-sonnet-4-20250514`). Each chat turn appends the user message, the assistant's tool calls and text responses, and tool result blocks to the message array. Over a long authoring session -- 15-30+ turns of editing pages, running validation, and reviewing proposals -- the accumulated conversation history can approach or exceed this limit.

The existing context pruning mechanism (US-AI-023, `ContextBuilder.prune_context()`) performs a simple oldest-first removal of message pairs. However, this approach has several gaps:

1. **Silent information loss**: Removing old messages may discard implicit context (the user's earlier preferences, the rationale behind a rejected proposal, the specific wording an author preferred).
2. **No user visibility**: The user is never informed that context was pruned or refreshed, which can lead to the LLM "forgetting" earlier instructions.
3. **No structured session summary**: Pruning removes messages but does not inject a structured summary of the session's state (active proposals, key decisions, current focus), forcing the LLM to re-fetch everything via tools.
4. **No proactive detection**: Pruning only happens when the turn's message construction exceeds the token limit, not proactively when approaching it.

This story addresses these gaps by introducing a **Session Context Window Recovery** system with four capabilities:

**Capability A -- Proactive Token Tracking**: Every LLM call records token usage, and the `ChatOrchestrator` proactively tracks the running total per session. When usage crosses configurable thresholds (e.g., 60%, 80%, 95% of model max), the system either warns or triggers a context refresh.

**Capability B -- Structured Session Summary**: The system maintains a distilled, always-current summary of the session in `ai_sessions.summary_json`. This summary includes active proposal IDs, the last page the user was editing, key decisions made, course metadata, and a chronological digest of actions taken. The summary is updated after every turn.

**Capability C -- Transparent Context Refresh**: When the context window limit is reached (or when the user explicitly requests it via `POST /api/v1/ai/chat` with `context_refresh: true`), the orchestrator:
1. Persists the current conversation as a single compressed summary message.
2. Discards the detailed conversation history from the LLM context.
3. Injects a fresh system prompt with current course state and the session summary.
4. Informs the user via a system-level chat message: "Context has been refreshed. The AI now has a fresh view of your course. Active proposals and changes are preserved."
5. Instructs the LLM that it should re-fetch any page data it needs via tool calls.

**Capability D -- User-Initiated Refresh**: The chat endpoint already accepts `context_refresh: true` (US-AI-023). This story implements that path end-to-end, and adds a `POST /api/v1/ai/sessions/{session_id}/refresh` endpoint for explicit frontend-triggered refreshes (e.g., a "Refresh context" button in the chat header).

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Engages in long AI chat sessions; can request context refresh manually |
| AI Agent (LLM) | Receives refreshed context with instruction to re-fetch state via tools |
| ChatOrchestrator (Server) | Monitors token usage, triggers context refresh, manages session summary |
| SessionManager (Server) | Stores and retrieves session summary data |
| ContextBuilder (Server) | Builds compressed summaries and rehydrated message arrays |
| Frontend (Chat UI) | Shows context refresh indicator, exposes refresh button, displays token usage widget |

### 1.4 Flow: Context Window Recovery

**Precondition:** An active AI session exists with at least 10 completed turns. The session has accumulated approximately 65,000 input tokens (65% of the 100,000 configured limit).

**Phase 0 -- Proactive Warning**
1. The `ChatOrchestrator` completes turn N. The telemetry event records 5,800 input tokens for this turn.
2. The orchestrator's `_prune_context_if_needed()` method computes the running 30-turn rolling sum of input tokens: 67,300.
3. The session's `AI_CONTEXT_REFRESH_WARN_THRESHOLD` is 0.80 (80%).
4. The orchestrator checks `67,300 / 100,000 = 0.673` -- below the warn threshold. No action.

**Phase 1 -- Trigger Refresh**
1. Turn N+1 completes. Token sum is now 82,100 (82%).
2. Exceeds warn threshold. The orchestrator appends a system message to the chat: "Note: The AI's context window is at 82% capacity. Consider refreshing context for optimal performance."
3. Turn N+2 is larger (a batch `propose_create_page` with full page data). Token sum: 96,400 (96.4%).
4. Exceeds the hard refresh threshold (`AI_CONTEXT_REFRESH_HARD_THRESHOLD` = 0.95).
5. Orchestrator triggers automated context refresh.

**Phase 2 -- Context Refresh Execution**
1. Orchestrator calls `SessionSummaryBuilder.build_summary()` which:
   - Loads the full conversation history for the session.
   - Compresses it into a structured JSON summary: `{session_id, turn_count, active_proposal_ids: [...], last_focus_page_id, key_decisions: [...], action_timeline: [...], course_snapshot: {title, page_count, status}}`.
   - Generates a natural-language summary paragraph.
2. Orchestrator stores the summary in `ai_sessions.summary_json`.
3. Orchestrator calls `ContextBuilder.rehydrate_context()`:
   - Loads the system prompt (fresh, current version).
   - Loads the session summary from `ai_sessions`.
   - Loads the current course state (pages, proposals) from the database.
   - Loads the current user message (if mid-turn) -- but discards all prior message history from the LLM context.
   - Constructs a new messages array: `[system_prompt, session_summary_as_user_message, rehydration_instruction_as_assistant, user_current_message]`.
4. Orchestrator writes a telemetry event `context_refreshed` with `token_saved` estimate and `summary_token_count`.
5. Orchestrator sends a chat message to the frontend: "I have refreshed my context to stay within performance limits. Your course state and proposals are preserved. Let me know how you would like to proceed."
6. The interaction loop continues with the refreshed context.

**Phase 3 -- User-Initiated Refresh**
1. User clicks "Refresh context" in the chat UI.
2. Frontend calls `POST /api/v1/ai/sessions/{session_id}/refresh`.
3. Backend validates the session, generates a session summary, stores it, and returns a refreshed context token that the frontend passes to the next `POST /api/v1/ai/chat` call.
4. Alternatively, frontend uses the existing `context_refresh: true` flag on the next chat request.

**Phase 4 -- Recovery After Truncation**
1. The LLM provider returns a `400` error with `"type": "error", "error": {"type": "invalid_request_error", "message": "context_length_exceeded"}`.
2. The `ChatOrchestrator._call_llm()` catches this error and does NOT treat it as a transient retryable error.
3. Instead, it raises a new `ContextWindowExceededError`.
4. The orchestrator catches this error at the `_execute_llm_loop` level and initiates an emergency context refresh (same as Phase 2).
5. After refresh, the orchestrator retries the LLM call once with the reduced context.
6. If the retry succeeds, the turn completes normally. The user sees a message: "My context window was full. I have refreshed my view and can continue. Please re-state your last instruction if it was not completed."
7. If the retry also fails, the turn fails with `CONTEXT_REFRESH_FAILED` and directions to start a new session.

### 1.5 Error Conditions

| Condition | HTTP Status | Error Code | Behavior |
|---|---|---|---|
| Context window exceeded during LLM call | 200 (with error in SSE) | `CONTEXT_WINDOW_EXCEEDED` | Automatic context refresh and retry (once) |
| Context refresh fails (summary generation error) | 200 (with error in SSE) | `CONTEXT_REFRESH_FAILED` | Turn fails; user asked to start new session |
| Manual refresh on non-existent session | 404 | `SESSION_NOT_FOUND` | Standard session error |
| Manual refresh on expired session | 404 | `SESSION_EXPIRED` | Frontend creates new session |
| Refresh during active turn (race condition) | 409 | `REFRESH_IN_PROGRESS` | Frontend should wait for current turn to complete |
| Context refresh retry also exceeds limit | 200 (with error in SSE) | `CONTEXT_RECOVERY_FAILED` | Turn terminates; user must start new session |
| Session summary too large to fit in context | 500 | `SUMMARY_TOO_LARGE` | Summary truncated to fit; logged as alert |

---

## 2. Technical Specification

### 2.1 Database Changes -- DDL

**Table: `ai_sessions` (ALTER) -- Add column for session summary**

```sql
ALTER TABLE ai_sessions
ADD COLUMN summary_json JSONB DEFAULT '{}'::jsonb;

ALTER TABLE ai_sessions
ADD COLUMN total_input_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE ai_sessions
ADD COLUMN total_output_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE ai_sessions
ADD COLUMN last_refreshed_at TIMESTAMPTZ;

ALTER TABLE ai_sessions
ADD COLUMN refresh_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN ai_sessions.summary_json IS
  'Structured session summary for context recovery: {active_proposal_ids, last_focus_page_id, key_decisions:[], action_timeline:[], course_snapshot:{title,page_count,status}, turn_count, model_used}';

COMMENT ON COLUMN ai_sessions.total_input_tokens IS
  'Running total of input tokens consumed across all turns in this session';

COMMENT ON COLUMN ai_sessions.total_output_tokens IS
  'Running total of output tokens consumed across all turns in this session';

COMMENT ON COLUMN ai_sessions.last_refreshed_at IS
  'Timestamp of the most recent context refresh';

COMMENT ON COLUMN ai_sessions.refresh_count IS
  'Number of context refreshes performed for this session';
```

**Table: `ai_context_refresh_log` (NEW)**

```sql
CREATE TABLE ai_context_refresh_log (
    id                  SERIAL PRIMARY KEY,
    refresh_id          VARCHAR(64) UNIQUE NOT NULL,
    session_id          VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    turn_id             VARCHAR(64),                              -- the turn that triggered the refresh (if auto)
    trigger_type        VARCHAR(32) NOT NULL
                        CHECK (trigger_type IN (
                            'auto_threshold',    -- exceeded hard threshold %
                            'auto_provider',     -- provider returned context_length_exceeded
                            'user_initiated',    -- user clicked refresh button
                            'context_refresh_flag' -- context_refresh:true in chat request
                        )),

    -- Context state before refresh
    token_usage_before  JSONB NOT NULL,                           -- {total_input, total_output, estimated_total}
    message_count_before INTEGER NOT NULL,                        -- number of messages in history before pruning
    estimated_tokens_saved INTEGER,                               -- approximate tokens removed

    -- Summary generated
    summary_json        JSONB NOT NULL DEFAULT '{}'::jsonb,       -- the summary that was injected
    summary_token_count INTEGER,                                  -- token count of the generated summary

    -- Timing
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    duration_ms         INTEGER,

    -- Outcome
    status              VARCHAR(16) NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('completed', 'failed')),
    error_message       TEXT,

    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_acrl_session ON ai_context_refresh_log(session_id);
CREATE INDEX idx_acrl_trigger ON ai_context_refresh_log(trigger_type);
CREATE INDEX idx_acrl_created ON ai_context_refresh_log(created_at DESC);
```

### 2.2 SQLAlchemy ORM Model Changes

**Modify: `app/models/ai_chat.py` -- Extend AISessionRecord**

```python
# Add to existing AISessionRecord in app/models/ai_chat.py
# New columns on the existing ai_sessions model (assumed US-AI-004 created AISessionRecord)

from sqlalchemy import BigInteger

# In AISessionRecord class, add:
summary_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
refresh_count: Mapped[int] = mapped_column(Integer, default=0)
```

**New: `app/models/ai_context_refresh.py`**

```python
"""ORM model for AI context refresh audit log."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Integer, ForeignKey, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AIContextRefreshRecord(Base):
    """Audit log entry for each context refresh event."""

    __tablename__ = "ai_context_refresh_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    refresh_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True
    )
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    trigger_type: Mapped[str] = mapped_column(String(32))
    # 'auto_threshold', 'auto_provider', 'user_initiated', 'context_refresh_flag'

    token_usage_before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    message_count_before: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens_saved: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    summary_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary_token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="completed")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "refreshId": self.refresh_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "triggerType": self.trigger_type,
            "tokenUsageBefore": self.token_usage_before,
            "messageCountBefore": self.message_count_before,
            "estimatedTokensSaved": self.estimated_tokens_saved,
            "summaryTokenCount": self.summary_token_count,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "durationMs": self.duration_ms,
            "status": self.status,
            "errorMessage": self.error_message,
        }
```

### 2.3 Pydantic DTOs

**Add to `app/routers/ai_chat_dtos.py`:**

```python
# =============================================================================
# Session Context Recovery DTOs
# =============================================================================

class SessionSummary(BaseModel):
    """Structured session summary for context recovery."""
    session_id: str
    turn_count: int = 0
    active_proposal_ids: list[str] = Field(default_factory=list)
    last_focus_page_id: Optional[str] = None
    key_decisions: list[dict] = Field(
        default_factory=list,
        description="Key decisions made during the session: [{turn_id, decision_summary, timestamp}]"
    )
    action_timeline: list[dict] = Field(
        default_factory=list,
        description="Chronological actions: [{turn_id, action_type, target, summary}]"
    )
    course_snapshot: dict = Field(
        default_factory=lambda: {"title": "", "page_count": 0, "status": "draft"}
    )
    model_used: Optional[str] = None
    created_at: Optional[str] = None


class RefreshContextRequest(BaseModel):
    """Request to manually refresh an AI session's context."""
    session_id: str = Field(..., description="Active AI session ID to refresh")
    reason: Optional[str] = Field(None, description="Optional reason for manual refresh (e.g., 'user_requested')")


class RefreshContextResponse(BaseModel):
    """Response after a context refresh."""
    session_id: str
    refresh_id: str
    trigger_type: str
    summary_token_count: int = 0
    estimated_tokens_saved: int = 0
    message_count_before: int = 0
    message: str = "Context refreshed successfully. Active proposals and course state are preserved."


class SessionTokenUsage(BaseModel):
    """Token usage information for a session."""
    session_id: str
    total_input_tokens: int
    total_output_tokens: int
    estimated_total_tokens: int
    model: str = ""
    model_max_context: int = 200000
    usage_pct: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of model's max context window consumed (0.0 to 1.0)"
    )
    refresh_count: int = 0
    last_refreshed_at: Optional[str] = None
    status: str = "healthy"  # 'healthy', 'warn', 'critical'
```

### 2.4 API Contracts

#### POST /api/v1/ai/sessions/{session_id}/refresh

Manually triggers a context refresh for the given session. The session summary is regenerated from conversation history, stored, and used to rehydrate the next turn's context.

**Request Body:**
```json
{
  "session_id": "sess_abc123",
  "reason": "user_requested"
}
```

**Response 200:**
```json
{
  "session_id": "sess_abc123",
  "refresh_id": "ref_xyz789",
  "trigger_type": "user_initiated",
  "summary_token_count": 380,
  "estimated_tokens_saved": 64200,
  "message_count_before": 48,
  "message": "Context refreshed successfully. Active proposals and course state are preserved."
}
```

**Error Responses:**

`404 SESSION_NOT_FOUND`:
```json
{
  "code": "SESSION_NOT_FOUND",
  "message": "Session 'sess_abc123' not found or has expired.",
  "retryable": false
}
```

`409 REFRESH_IN_PROGRESS`:
```json
{
  "code": "REFRESH_IN_PROGRESS",
  "message": "A chat turn is currently in progress. Wait for completion before refreshing.",
  "retryable": true,
  "details": {"active_turn_id": "turn_def456"}
}
```

#### GET /api/v1/ai/sessions/{session_id}/tokens (Enhanced from US-AI-023)

Returns enhanced token usage information including context utilization percentage, refresh history, and proactive warnings.

**Response 200:**
```json
{
  "session_id": "sess_abc123",
  "total_input_tokens": 82300,
  "total_output_tokens": 14100,
  "estimated_total_tokens": 96400,
  "model": "claude-sonnet-4-20250514",
  "model_max_context": 200000,
  "usage_pct": 0.482,
  "refresh_count": 2,
  "last_refreshed_at": "2026-06-14T15:30:00Z",
  "status": "healthy"
}
```

When `usage_pct >= 0.80`, status is `"warn"`. When `usage_pct >= 0.95`, status is `"critical"`.

#### GET /api/v1/ai/sessions/{session_id}/summary

Returns the current structured session summary.

**Response 200:**
```json
{
  "session_id": "sess_abc123",
  "turn_count": 24,
  "active_proposal_ids": ["prop_001", "prop_002"],
  "last_focus_page_id": "page_03",
  "key_decisions": [
    {"turn_id": "turn_010", "decision_summary": "User prefers concise explanations with code examples", "timestamp": "..."},
    {"turn_id": "turn_015", "decision_summary": "Quiz passing score set to 70%", "timestamp": "..."}
  ],
  "action_timeline": [
    {"turn_id": "turn_001", "action_type": "create_page", "target": "Welcome", "summary": "Created welcome page"},
    {"turn_id": "turn_005", "action_type": "update_page", "target": "Module 1", "summary": "Updated objectives section"}
  ],
  "course_snapshot": {
    "title": "Python Programming 101",
    "page_count": 8,
    "status": "draft"
  },
  "model_used": "claude-sonnet-4-20250514",
  "created_at": "2026-06-14T15:30:00Z"
}
```

#### POST /api/v1/ai/chat -- Enhanced with `context_refresh` handling

The existing `context_refresh` field in `ChatRequest` (from US-AI-023) is now fully implemented:

When `context_refresh: true`:
1. Before processing the turn, the orchestrator generates a fresh session summary from the current conversation history.
2. The orchestrator stores the summary in `ai_sessions.summary_json` and writes a `ai_context_refresh_log` entry.
3. The turn proceeds with a rehydrated context (fresh system prompt + summary + current user message).

When `context_refresh: false` (default):
1. The orchestrator checks the current token usage before building messages.
2. If `usage_pct >= AI_CONTEXT_REFRESH_HARD_THRESHOLD` (default 0.95), automatic refresh is triggered as if `context_refresh` were true.
3. If `usage_pct >= AI_CONTEXT_REFRESH_WARN_THRESHOLD` (default 0.80), a warning message is appended to the assistant's response.

### 2.5 Service Signatures

**New file: `app/services/ai/session_summary_builder.py`**

```python
"""Builds structured session summaries for context window recovery.

The SessionSummaryBuilder compresses a session's conversation history
into a structured JSON summary that preserves key decisions, active
proposals, and course state in a token-efficient format.

Usage:
    summary = await SessionSummaryBuilder(db_session).build_summary(
        session_id="sess_abc123",
        llm_client=llm_client,   # Optional: LLM for NL summary generation
    )
    # summary is a dict suitable for storage in ai_sessions.summary_json
    # and for injection as a context message in the rehydrated prompt.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SessionSummaryBuilder:
    """Compresses session conversation history into a structured summary."""

    # Max summary tokens before truncation is required
    MAX_SUMMARY_TOKENS = 2000

    def __init__(self, db_session: AsyncSession):
        self.session = db_session

    async def build_summary(
        self,
        session_id: str,
        llm_client: Optional[object] = None,
    ) -> dict:
        """Build a structured session summary from conversation history.

        Strategy:
          1. Load all messages for the session (from ai_session_messages).
          2. Extract key decisions (user preferences, accepted/rejected proposals).
          3. Build action timeline from tool call logs.
          4. Load active proposals from ai_proposals.
          5. Load current course state from CourseRecord / PageRecord.
          6. Compress into a structured JSON blob under MAX_SUMMARY_TOKENS.
          7. If llm_client is provided, generate a natural-language summary
             paragraph for better LLM comprehension.

        Returns:
            Dict with keys: session_id, turn_count, active_proposal_ids,
            last_focus_page_id, key_decisions, action_timeline,
            course_snapshot, model_used, created_at.
        """
        raise NotImplementedError

    async def extract_key_decisions(
        self,
        messages: list[dict],
        tool_logs: list[dict],
    ) -> list[dict]:
        """Extract key decisions from the conversation history.

        Scans user messages for preference statements ("I prefer...",
        "make it more...", "use darker colors") and tool call results
        for accepted proposals. Returns deduplicated list.
        """
        raise NotImplementedError

    async def build_action_timeline(
        self,
        tool_logs: list[dict],
    ) -> list[dict]:
        """Build a chronological timeline of actions taken during the session.

        Each entry: {turn_id, action_type, target, summary}.
        Action types: create_page, update_page, delete_page,
        apply_proposal, validate_course, query_similar.
        """
        raise NotImplementedError

    async def build_summary_message(
        self,
        summary: dict,
    ) -> dict:
        """Build a user-role message containing the session summary.

        Returns a dict with role='user' and content containing a
        human-readable paragraph + bullet points of the summary data.

        This message is injected into the rehydrated context as the
        most recent 'user' message before the system prompt, so the
        LLM can see it.
        """
        raise NotImplementedError

    def _compress_summary(
        self,
        summary: dict,
        max_tokens: int = 2000,
    ) -> dict:
        """Truncate summary fields to fit within max_tokens.

        If the summary JSON exceeds max_tokens, trim:
          - Oldest key_decisions first (keep 5 most recent).
          - Oldest action_timeline entries (keep 10 most recent).
          - Truncate course_snapshot to essential fields only.
        """
        raise NotImplementedError

    @staticmethod
    def rough_token_count(data: dict) -> int:
        """Approximate token count of a dict (serialized JSON length / 4)."""
        import json
        return len(json.dumps(data, default=str)) // 4
```

**Modified: `app/services/ai/chat_orchestrator.py` -- Enhanced with context recovery**

```python
# New import
from app.services.ai.session_summary_builder import SessionSummaryBuilder
from app.services.ai.context_builder import ContextBuilder

# New configuration constants (add to ChatOrchestrator class body)
CONTEXT_WARN_THRESHOLD = float(os.getenv("AI_CONTEXT_REFRESH_WARN_THRESHOLD", "0.80"))
CONTEXT_HARD_THRESHOLD = float(os.getenv("AI_CONTEXT_REFRESH_HARD_THRESHOLD", "0.95"))
CONTEXT_MODEL_MAX = int(os.getenv("AI_CONTEXT_MODEL_MAX_TOKENS", "200000"))
CONTEXT_REFRESH_ENABLED = os.getenv("AI_CONTEXT_REFRESH_ENABLED", "true").lower() == "true"

# New method signatures:

async def _check_context_pressure(
    self,
    session_id: str,
    turn_input_tokens: int,
    turn_output_tokens: int,
) -> dict:
    """Check context window pressure and return action recommendation.

    Args:
        session_id: Current session ID.
        turn_input_tokens: Input tokens consumed by the current turn.
        turn_output_tokens: Output tokens consumed by the current turn.

    Returns:
        Dict with keys:
          - action: 'none', 'warn', 'refresh', or 'emergency'
          - usage_pct: float 0.0-1.0
          - warning_message: Optional[str] for frontend display
    """
    raise NotImplementedError

async def _refresh_context(
    self,
    session_id: str,
    trigger_type: str,
    turn_id: Optional[str] = None,
) -> dict:
    """Perform a full context refresh for the session.

    1. Build session summary via SessionSummaryBuilder.
    2. Store summary in ai_sessions.summary_json.
    3. Write ai_context_refresh_log entry.
    4. Update session counters (refresh_count, last_refreshed_at).
    5. Return refresh metadata.

    Args:
        session_id: Session to refresh.
        trigger_type: 'auto_threshold', 'auto_provider',
                      'user_initiated', or 'context_refresh_flag'.
        turn_id: The turn that triggered the refresh (if any).

    Returns:
        Dict with refresh_id, estimated_tokens_saved,
        summary_token_count, message_count_before.
    """
    raise NotImplementedError

async def _build_rehydrated_context(
    self,
    session_id: str,
    context: dict,
    user_message: str,
) -> tuple[list[dict], list[dict]]:
    """Build a rehydrated messages array after context refresh.

    Instead of loading conversation history, this method:
      1. Loads the stored session summary from ai_sessions.
      2. Constructs: [system_prompt, summary_message,
         rehydration_instruction, user_message].
      3. Returns the minimal messages array and full tool definitions.

    Args:
        session_id: Current session ID.
        context: Session context dict (course state, proposals).
        user_message: The current user message (or empty if just refreshing).

    Returns:
        (messages, tools) tuple ready for LLM call.
    """
    raise NotImplementedError

async def _handle_context_exceeded_error(
    self,
    session_id: str,
    turn_id: str,
    user_message: str,
    context: dict,
) -> AsyncGenerator[dict, None] | dict:
    """Handle a context_length_exceeded provider error.

    Called by _execute_llm_loop when the LLM call raises
    ContextWindowExceededError.

    1. Initiate emergency context refresh.
    2. Rebuild messages with rehydrated context.
    3. Retry the LLM call once.
    4. If retry succeeds, continue the loop.
    5. If retry fails, return error.

    Yields or returns appropriate SSE events / error response.
    """
    raise NotImplementedError
```

**New file: `app/repositories/ai_context_refresh_repo.py`**

```python
"""Repository for ai_context_refresh_log persistence."""
from __future__ import annotations
from typing import Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_context_refresh import AIContextRefreshRecord


class AIContextRefreshRepository:
    """DB access for ai_context_refresh_log."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, record: AIContextRefreshRecord
    ) -> AIContextRefreshRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_session(
        self,
        session_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> Sequence[AIContextRefreshRecord]:
        q = (
            select(AIContextRefreshRecord)
            .where(AIContextRefreshRecord.session_id == session_id)
            .order_by(AIContextRefreshRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(q)).scalars().all()

    async def count_by_session(self, session_id: str) -> int:
        q = (
            select(func.count())
            .select_from(AIContextRefreshRecord)
            .where(AIContextRefreshRecord.session_id == session_id)
        )
        return (await self.session.execute(q)).scalar() or 0

    async def get_latest_by_session(
        self, session_id: str
    ) -> Optional[AIContextRefreshRecord]:
        q = (
            select(AIContextRefreshRecord)
            .where(AIContextRefreshRecord.session_id == session_id)
            .order_by(AIContextRefreshRecord.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(q)).scalar_one_or_none()
```

### 2.6 Context Rehydration Strategy

The rehydrated message array for a context refresh turn follows this structure:

```python
messages = [
    # 1. System prompt (fresh, includes current course state and rules)
    {
        "role": "system",
        "content": system_prompt  # with course metadata, proposal list, rules
    },

    # 2. Session summary (user-role message containing the compressed history)
    {
        "role": "user",
        "content": (
            "Here is a summary of what has happened in this session so far:\n\n"
            "Session Summary:\n"
            "- Total turns completed: 24\n"
            "- Active proposals: 2 (prop_001: update page 'Module 1', prop_002: create 'Quiz')\n"
            "- Pages in course: 8\n"
            "- Last page focused: 'Module 1: Variables'\n\n"
            "Key decisions made:\n"
            "  - Turn 10: User prefers concise explanations with code examples\n"
            "  - Turn 15: Quiz passing score set to 70%\n\n"
            "Recent actions:\n"
            "  - Turn 22: Updated page 'Module 1' objectives section (pending proposal)\n"
            "  - Turn 23: Validated course -- passed with 2 warnings\n\n"
            "Course snapshot:\n"
            "  - Title: Python Programming 101\n"
            "  - Pages: 8 (3 complete, 4 draft, 1 pending review)\n"
            "  - Status: draft\n\n"
            "IMPORTANT: This summary replaces the full conversation history. "
            "Your context has been refreshed to stay within performance limits. "
            "Please use the available tools to fetch any page data you need "
            "before responding."
        )
    },

    # 3. Rehydration instruction (assistant message -- meta-instruction)
    {
        "role": "assistant",
        "content": (
            "Understood. I have refreshed my context and will use the available "
            "tools to fetch current page data as needed. I see there are 2 active "
            "proposals and 8 pages in the course. Let me know how you would like "
            "to proceed."
        )
    },

    # 4. Current user message (what the user just sent, or re-prompt)
    {
        "role": "user",
        "content": user_message
    }
]
```

This structure ensures:
- The LLM sees a fresh system prompt with current state.
- The session summary provides essential context without consuming the full history.
- The rehydration instruction explicitly tells the LLM to use tools to re-fetch state (preventing hallucination of stale data).
- The user's current message is processed normally.

### 2.7 Session Summary JSON Schema

The `summary_json` stored in `ai_sessions.summary_json` follows this schema:

```json
{
  "session_id": "sess_abc123",
  "turn_count": 24,
  "active_proposal_ids": ["prop_001", "prop_002"],
  "last_focus_page_id": "page_03",
  "model_used": "claude-sonnet-4-20250514",
  "key_decisions": [
    {
      "turn_id": "turn_010",
      "decision_summary": "User prefers concise explanations with code examples",
      "timestamp": "2026-06-14T14:30:00Z",
      "type": "preference"
    },
    {
      "turn_id": "turn_015",
      "decision_summary": "Quiz passing score set to 70%",
      "timestamp": "2026-06-14T15:00:00Z",
      "type": "configuration"
    }
  ],
  "action_timeline": [
    {
      "turn_id": "turn_001",
      "action_type": "propose_create_page",
      "target": "Welcome",
      "target_page_id": "page_01",
      "summary": "Created welcome page with course overview",
      "status": "applied",
      "timestamp": "2026-06-14T13:00:00Z"
    },
    {
      "turn_id": "turn_012",
      "action_type": "propose_update_page",
      "target": "Module 1",
      "target_page_id": "page_02",
      "summary": "Updated objectives section to include Python 3.12",
      "status": "pending",
      "timestamp": "2026-06-14T14:45:00Z"
    }
  ],
  "course_snapshot": {
    "title": "Python Programming 101",
    "page_count": 8,
    "page_ids": ["page_01", "page_02", "page_03", "page_04", "page_05", "page_06", "page_07", "page_08"],
    "status": "draft",
    "course_id": "course_001"
  },
  "created_at": "2026-06-14T15:30:00Z"
}
```

### 2.8 Token Tracking in ChatOrchestrator

The `ChatOrchestrator` maintains a running token counter per session using `ai_sessions.total_input_tokens` and `ai_sessions.total_output_tokens`. The counter is updated after every LLM call completes successfully.

```python
async def _update_session_token_count(
    self,
    session_id: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Update running token counts for the session."""
    from app.repositories.ai_chat_repo import AISessionRepository  # or similar
    
    repo = AISessionRepository(self.session)
    await repo.add_token_usage(
        session_id=session_id,
        input_delta=input_tokens,
        output_delta=output_tokens,
    )

async def _get_session_usage_pct(self, session_id: str) -> float:
    """Get the fraction of context window consumed."""
    from app.repositories.ai_chat_repo import AISessionRepository
    
    repo = AISessionRepository(self.session)
    tokens = await repo.get_token_usage(session_id)
    total = tokens["total_input_tokens"] + tokens["total_output_tokens"]
    model_max = self.CONTEXT_MODEL_MAX
    return total / model_max
```

**`AISessionRepository` additions:**

```python
class AISessionRepository:
    # ... existing methods ...

    async def add_token_usage(
        self,
        session_id: str,
        input_delta: int,
        output_delta: int,
    ) -> None:
        """Atomically add to the running token counters."""
        from sqlalchemy import update
        stmt = (
            update(AISessionRecord)
            .where(AISessionRecord.session_id == session_id)
            .values(
                total_input_tokens=AISessionRecord.total_input_tokens + input_delta,
                total_output_tokens=AISessionRecord.total_output_tokens + output_delta,
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_token_usage(self, session_id: str) -> dict:
        """Get current token usage for the session."""
        q = select(
            AISessionRecord.total_input_tokens,
            AISessionRecord.total_output_tokens,
            AISessionRecord.refresh_count,
            AISessionRecord.last_refreshed_at,
        ).where(AISessionRecord.session_id == session_id)
        row = (await self.session.execute(q)).one()
        return {
            "total_input_tokens": row[0],
            "total_output_tokens": row[1],
            "refresh_count": row[2],
            "last_refreshed_at": row[3].isoformat() if row[3] else None,
        }

    async def update_refresh_metadata(
        self,
        session_id: str,
        summary_json: dict,
    ) -> None:
        """Update session summary and refresh metadata."""
        from sqlalchemy import update
        from datetime import datetime
        stmt = (
            update(AISessionRecord)
            .where(AISessionRecord.session_id == session_id)
            .values(
                summary_json=summary_json,
                last_refreshed_at=datetime.utcnow(),
                refresh_count=AISessionRecord.refresh_count + 1,
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_summary(self, session_id: str) -> Optional[dict]:
        """Get the stored session summary."""
        q = select(AISessionRecord.summary_json).where(
            AISessionRecord.session_id == session_id
        )
        row = (await self.session.execute(q)).scalar_one_or_none()
        return row if row else None
```

### 2.9 API Router Additions

**New routes in `app/routers/ai_chat.py`:**

```python
# =============================================================================
# Context Refresh Endpoints
# =============================================================================

@router.post(
    "/sessions/{session_id}/refresh",
    response_model=RefreshContextResponse,
    summary="Manually refresh the context for an AI session",
    responses={
        404: {"description": "Session not found"},
        409: {"description": "Refresh already in progress (active turn)"},
    },
)
async def refresh_session_context(
    session_id: str,
    body: RefreshContextRequest,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Manually refresh the context for an AI session.

    Generates a session summary from conversation history, stores it,
    and resets the effective context window. The next chat turn will
    start with a fresh system prompt and the session summary instead
    of the full history.

    Use this endpoint for user-initiated refreshes (e.g., from a
    "Refresh context" button in the chat UI).
    """
    # Validate session exists and is active
    # Check no active turn is in progress (409 if so)
    # Build session summary
    # Store summary and refresh metadata
    # Write ai_context_refresh_log entry
    # Return refresh response
    raise NotImplementedError


@router.get(
    "/sessions/{session_id}/summary",
    response_model=SessionSummary,
    summary="Get the current session summary",
    responses={
        404: {"description": "Session not found"},
    },
)
async def get_session_summary(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(ai_authoring_enabled),
):
    """Get the structured session summary.

    Returns the current summary_json from ai_sessions, or builds
    one on-the-fly if none exists yet. Useful for frontend to
    show session state and context utilization.
    """
    raise NotImplementedError
```

### 2.10 Environment Variables

Add to `.env` and `.env.example`:

```ini
# ============================================
# Session Context Window Recovery Configuration
# ============================================

# Enable/disable automatic context refresh
AI_CONTEXT_REFRESH_ENABLED=true

# Thresholds (fraction of model max context, 0.0 to 1.0)
AI_CONTEXT_REFRESH_WARN_THRESHOLD=0.80
AI_CONTEXT_REFRESH_HARD_THRESHOLD=0.95

# Model max context tokens (for tracking)
# claude-sonnet-4-20250514 = 200000
# claude-haiku-3-5-20241022 = 200000
AI_CONTEXT_MODEL_MAX_TOKENS=200000

# Session summary generation
AI_CONTEXT_SUMMARY_MAX_TOKENS=2000
AI_CONTEXT_SUMMARY_USE_LLM=false           # Use LLM for NL summary (vs. deterministic only)

# Context refresh limits
AI_CONTEXT_MAX_REFRESHES_PER_SESSION=20    # Max refreshes before forcing new session
AI_CONTEXT_REFILL_TOKENS_AFTER_REFRESH=5000  # Approx tokens freed up by refresh (for accounting)
```

### 2.11 Main Application Registration

**In `app/main.py`, add to lifespan imports:**
```python
import app.models.ai_context_refresh  # noqa: F401 — register ORM model
```

**In `app/models/__init__.py`, add:**
```python
from app.models.ai_context_refresh import AIContextRefreshRecord

__all__.extend([
    "AIContextRefreshRecord",
])
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Session summary generation (deterministic) | < 200 ms p95 | Time to build summary from DB state |
| Session summary generation (with LLM) | < 5 s p95 | Time to build summary + LLM NL generation |
| Context rehydration | < 50 ms p95 | Time to construct rehydrated messages array |
| Token tracking overhead | < 5 ms | Time to update session token counters |
| Context refresh response (<empty>POST) | < 500 ms p95 | Full refresh endpoint latency |
| Summary retrieval (<empty>GET summary) | < 50 ms p95 | Time to load and return stored summary |
| Emergency recovery (provider error -> retry) | < 2 s additional latency | Time to refresh + retry after context_length_exceeded |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Summary data isolation | Session summaries never include PII, credentials, or content from other sessions |
| Summary access control | Summary retrieval is gated by session ownership validation (same as all AI endpoints) |
| No prompt injection via summary | Summary is constructed server-side from DB state, never from raw user input |
| Refresh audit trail | Every context refresh is logged in `ai_context_refresh_log` with trigger type and timing |
| Rate-limited refreshes | Maximum refreshes per session enforced via `AI_CONTEXT_MAX_REFRESHES_PER_SESSION` |

### 3.3 Data Integrity

| Requirement | Implementation |
|---|---|
| Summary accuracy | Summary is rebuilt from database state, not from LLM output; course snapshot is live DB query |
| No data loss on refresh | Active proposals remain in `ai_proposals` table; course state in `CourseRecord`/`PageRecord` |
| Summary versioning | Old summary is overwritten on refresh; prior summary is preserved in `ai_context_refresh_log.summary_json` |
| Provider error atomicity | If context refresh during provider error fails, the original error is returned to the user (no silent degradation) |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Graceful degradation | If session summary generation fails, the orchestrator falls back to simple message pruning (US-AI-023) |
| No cascading refreshes | Refresh is only triggered once per turn; a `refresh_count` limit prevents infinite refresh loops |
| Provider error recovery | `context_length_exceeded` from provider triggers exactly one retry after refresh; second failure returns error |

### 3.5 Observability

| Metric | Type | Tags |
|---|---|---|
| `ai_context_refreshes_total` | Counter | trigger_type, status |
| `ai_context_refresh_duration_seconds` | Histogram | trigger_type |
| `ai_context_summary_token_count` | Gauge | session_id |
| `ai_context_tokens_saved` | Counter | session_id |
| `ai_context_token_usage_pct` | Gauge | session_id, model |
| `ai_context_provider_truncations_total` | Counter | model |
| `ai_context_refresh_retries_total` | Counter | outcome (success/failure) |

---

## 4. Current State

### 4.1 What Exists Today

1. **`ChatOrchestrator` with basic pruning** (US-AI-023): The `ContextBuilder.prune_context()` method already removes oldest user/assistant pairs when the estimated token count exceeds `AI_CHAT_CONTEXT_TOKEN_LIMIT`. A basic summary message is injected if more than 2 pairs are removed.

2. **`ContextBuilder.build_summary_message()`** (US-AI-023): Stub method exists to build a summary message from removed context, but it has no structured session summary logic -- it only provides a placeholder message.

3. **`ChatOrchestrator._prune_context_if_needed()`** (US-AI-023): Stub method exists that checks token count against `CONTEXT_TOKEN_LIMIT` and calls `ContextBuilder.prune_context()` on stored messages.

4. **Telemetry infrastructure** (US-AI-023): `AITelemetryEventRecord` captures `input_tokens`, `output_tokens`, and `model_id` per LLM call.

5. **Session management** (US-AI-006): `ai_sessions` table exists with `session_id`, `course_id`, `user_id`, expiry, and status.

6. **`context_refresh` field in `ChatRequest`** (US-AI-023): The `ChatRequest` DTO already has a `context_refresh: bool` field, but it is not yet implemented in the `ChatOrchestrator`.

7. **Message persistence** (US-AI-023): All messages are persisted to `ai_session_messages` via `AISessionMessageRepository`.

### 4.2 What Is Missing

1. **`ai_sessions.summary_json` column** -- no structured summary storage exists.
2. **`ai_sessions.total_input_tokens` / `total_output_tokens` columns** -- no running token counter at session level.
3. **`ai_context_refresh_log` table** -- no audit trail for context refreshes.
4. **`AIContextRefreshRecord` ORM model** -- no model for the new table.
5. **`AIContextRefreshRepository`** -- no repository for the new table.
6. **`SessionSummaryBuilder` service** -- no service to build structured summaries from conversation history.
7. **Tokenizer for accurate token counting** -- current `count_tokens()` uses `len(text)//4`, which is inaccurate for long sessions; need proper tokenization.
8. **Context pressure monitoring** -- `_check_context_pressure()` is not implemented.
9. **Context refresh logic** -- `_refresh_context()`, `_build_rehydrated_context()`, and `_handle_context_exceeded_error()` are not implemented.
10. **`POST /api/v1/ai/sessions/{session_id}/refresh` endpoint** -- not implemented.
11. **`GET /api/v1/ai/sessions/{session_id}/summary` endpoint** -- not implemented.
12. **Enhanced `GET /api/v1/ai/sessions/{session_id}/tokens`** -- `usage_pct`, `status` fields not implemented.
13. **`context_refresh: true` in chat request** -- field exists in DTO but orchestrator ignores it.
14. **`LLMClient` error handling for `context_length_exceeded`** -- provider error for context exceeded is not distinguished from other `invalid_request_error` types.
15. **Frontend context refresh indicator** -- no UI for context pressure warning or refresh button (frontend US-AI-024).
16. **Alembic migration** for the new columns and table.
17. **Environment variables** for the new configuration.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-006 | `ai_sessions` table for `summary_json`, token counters, and refresh metadata columns |
| US-AI-023 | `ChatOrchestrator`, `ContextBuilder`, `LLMClient`, `AISessionMessageRecord`, `AITelemetryEventRecord` |
| US-AI-023 | `ChatRequest.context_refresh` DTO field (already exists) |
| US-AI-023 | `_prune_context_if_needed()` stub for integration point |

---

## 5. Expansion Points

### 5.1 LLM-Generated Summaries (Post-MVP)

The current `SessionSummaryBuilder.build_summary()` uses deterministic extraction (scanning tool logs and proposal states). Future iterations should optionally use a fast/cheap LLM call (e.g., `claude-haiku-3-5-20241022`) to generate a natural-language session summary paragraph that captures nuance, user sentiment, and implicit preferences that deterministic extraction might miss. This is gated by `AI_CONTEXT_SUMMARY_USE_LLM` (default `false`).

### 5.2 Per-Turn Token Budget (Post-MVP)

Instead of a single monolithic context window, future iterations could allocate a token budget per turn (e.g., 8K tokens per turn, rolling window of 10 turns = 80K budget). This prevents a single verbose turn from consuming the entire budget and gives the orchestrator finer-grained control over pruning decisions.

### 5.3 Semantic Compression of Tool Results (Post-MVP)

Tool call results (especially `list_pages` and `fetch_page`) can consume significant tokens. The orchestrator could compress these results by summarizing page data before passing it back to the LLM, e.g., "Page 'Module 1' has 5 components: 1 text block, 2 MCQ questions, 1 video embed, 1 image." This would reduce per-turn token consumption by 40-60% for data-heavy turns.

### 5.4 Predictive Context Refresh (Post-MVP)

Using historical token consumption patterns, the orchestrator could predict when the context window will be exhausted and trigger a refresh during a low-activity period (e.g., while the user is reading a response) rather than mid-turn. This would make refreshes invisible to the user.

### 5.5 Cross-Session Context Carry-Over (Future)

For users who work on the same course across multiple sessions, a "long-term memory" mechanism could carry over key decisions and preferences from one session to the next via the session summary structure. This would require extending `summary_json` with a `carry_over_to_next_session` flag and merging summaries on new session creation.

### 5.6 Summary Quality Monitoring (US-AI-042)

Once system prompt versioning (US-AI-042) is in place, the quality of context refreshes should be monitored: does the LLM successfully re-fetch state after refresh? How many tool calls are needed to recover context? Are there regression in output quality after refresh? These metrics should feed into prompt version evaluation.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests

```python
# File: tests/test_session_summary_builder.py

class TestSessionSummaryBuilder:
    async def test_build_summary_from_empty_session(self, db_session, sample_ai_session):
        """A session with no messages returns a minimal summary."""
        pass

    async def test_build_summary_with_turns(self, db_session, sample_ai_session_with_messages):
        """A session with 10+ messages includes turn_count and action_timeline."""
        pass

    async def test_build_summary_extracts_key_decisions(self, db_session, sample_ai_session_with_messages):
        """User messages containing 'prefer', 'like', or 'change' are extracted as key decisions."""
        pass

    async def test_build_summary_includes_active_proposals(self, db_session, sample_ai_session_with_proposals):
        """Active (PENDING_REVIEW) proposals are included in active_proposal_ids."""
        pass

    async def test_build_summary_includes_applied_proposals_in_timeline(self, db_session, sample_ai_session_with_applied_proposals):
        """Applied proposals appear in the action_timeline with status 'applied'."""
        pass

    async def test_build_summary_reflects_course_state(self, db_session, sample_ai_session_with_pages):
        """Course snapshot includes current page count and title from CourseRecord."""
        pass

    async def test_compress_summary_trims_oldest_decisions_first(self):
        """When summary exceeds MAX_SUMMARY_TOKENS, oldest decisions are trimmed first."""
        pass

    async def test_compress_summary_preserves_course_snapshot(self):
        """Course snapshot fields are never trimmed."""
        pass

    async def test_build_summary_message_includes_rehydration_instruction(self, db_session, sample_ai_session):
        """The summary message includes the rehydration instruction paragraph."""
        pass


class TestContextPressureCheck:
    async def test_below_warn_threshold_returns_none_action(self, db_session, sample_ai_session):
        """When usage_pct < warn_threshold, action='none'."""
        pass

    async def test_above_warn_threshold_returns_warn_action(self, db_session, sample_ai_session_with_high_tokens):
        """When usage_pct >= warn_threshold, action='warn' with warning message."""
        pass

    async def test_above_hard_threshold_returns_refresh_action(self, db_session, sample_ai_session_with_critical_tokens):
        """When usage_pct >= hard_threshold, action='refresh'."""
        pass

    async def test_token_usage_accounts_for_model_max(self, db_session, sample_ai_session):
        """usage_pct is computed against CONTEXT_MODEL_MAX, not a fixed value."""
        pass


class TestContextRefresh:
    async def test_refresh_stores_summary(self, db_session, sample_ai_session_with_messages, monkeypatch):
        """After refresh, ai_sessions.summary_json contains the built summary."""
        pass

    async def test_refresh_writes_audit_log(self, db_session, sample_ai_session_with_messages, monkeypatch):
        """After refresh, ai_context_refresh_log has a new entry."""
        pass

    async def test_refresh_updates_session_counters(self, db_session, sample_ai_session, monkeypatch):
        """refresh_count is incremented and last_refreshed_at is set."""
        pass

    async def test_refresh_with_trigger_type_auto_threshold(self, db_session, sample_ai_session, monkeypatch):
        """Trigger type is recorded as 'auto_threshold' when automatic."""
        pass

    async def test_refresh_with_trigger_type_user_initiated(self, db_session, sample_ai_session, monkeypatch):
        """Trigger type is recorded as 'user_initiated' when manual."""
        pass

    async def test_max_refreshes_limit_enforced(self, db_session, sample_ai_session_high_refresh_count, monkeypatch):
        """After AI_CONTEXT_MAX_REFRESHES_PER_SESSION, refresh returns an error."""
        pass


class TestRehydratedContext:
    async def test_rehydrated_context_has_system_prompt(self, db_session, sample_ai_session):
        """Rehydrated messages array starts with system prompt."""
        pass

    async def test_rehydrated_context_includes_summary_message(self, db_session, sample_ai_session):
        """Rehydrated messages include a user-role summary message."""
        pass

    async def test_rehydrated_context_includes_rehydration_instruction(self, db_session, sample_ai_session):
        """Rehydrated messages include an assistant-role rehydration instruction."""
        pass

    async def test_rehydrated_context_excludes_conversation_history(self, db_session, sample_ai_session_with_messages):
        """Rehydrated context does not include previous user/assistant/tool messages."""
        pass

    async def test_rehydrated_context_includes_current_user_message(self, db_session, sample_ai_session):
        """The current user message is included at the end of the messages array."""
        pass

    async def test_rehydrated_context_tool_definitions_unchanged(self, db_session, sample_ai_session):
        """Tool definitions are identical before and after refresh (same context)."""
        pass
```

### 6.2 Integration Tests

```python
# File: tests/test_context_refresh_api.py

class TestRefreshAPI:
    async def test_manual_refresh_returns_200(self, async_client, sample_ai_session_with_messages):
        """POST /api/v1/ai/sessions/{session_id}/refresh returns 200 with refresh metadata."""
        pass

    async def test_manual_refresh_nonexistent_session_returns_404(self, async_client):
        """Refresh on non-existent session returns 404."""
        pass

    async def test_manual_refresh_expired_session_returns_404(self, async_client, sample_expired_ai_session):
        """Refresh on expired session returns 404."""
        pass

    async def test_manual_refresh_response_shape(self, async_client, sample_ai_session_with_messages):
        """Response includes refresh_id, estimated_tokens_saved, message_count_before, summary_token_count."""
        pass

    async def test_manual_refresh_preserves_active_proposals(self, async_client, sample_ai_session_with_proposals):
        """After refresh, active proposals remain queryable via GET /api/v1/ai/proposals."""
        pass

    async def test_chat_with_context_refresh_flag(self, async_client, sample_ai_session_with_messages, monkeypatch):
        """Chat with context_refresh=true builds a summary and uses rehydrated context."""
        pass

    async def test_automatic_refresh_at_threshold(self, async_client, sample_ai_session_near_limit, monkeypatch):
        """When token usage exceeds hard threshold, the turn automatically refreshes."""
        pass

    async def test_provider_context_exceeded_triggers_emergency_refresh(self, async_client, sample_ai_session, monkeypatch):
        """A context_length_exceeded provider error triggers emergency refresh and retry."""
        pass

    async def test_emergency_refresh_retry_succeeds(self, async_client, sample_ai_session, monkeypatch):
        """After emergency refresh, the retry to the LLM succeeds and the turn completes."""
        pass

    async def test_emergency_refresh_retry_fails_returns_error(self, async_client, sample_ai_session, monkeypatch):
        """If both original call and retry fail, CONTEXT_RECOVERY_FAILED is returned."""
        pass


class TestSummaryAPI:
    async def test_get_summary_returns_stored_summary(self, async_client, sample_ai_session_with_summary):
        """GET /api/v1/ai/sessions/{session_id}/summary returns the stored summary."""
        pass

    async def test_get_summary_builds_on_demand(self, async_client, sample_ai_session_with_messages):
        """If no summary exists, one is built on the fly and returned."""
        pass

    async def test_get_summary_empty_session(self, async_client, sample_ai_session):
        """A session with no messages returns a minimal summary with turn_count=0."""
        pass


class TestTokenUsageAPI:
    async def test_get_tokens_includes_usage_pct(self, async_client, sample_ai_session):
        """GET /api/v1/ai/sessions/{session_id}/tokens returns usage_pct."""
        pass

    async def test_get_tokens_status_healthy(self, async_client, sample_ai_session):
        """When usage_pct < 0.80, status is 'healthy'."""
        pass

    async def test_get_tokens_status_warn(self, async_client, sample_ai_session_high_tokens):
        """When usage_pct >= 0.80, status is 'warn'."""
        pass

    async def test_get_tokens_status_critical(self, async_client, sample_ai_session_critical_tokens):
        """When usage_pct >= 0.95, status is 'critical'."""
        pass

    async def test_get_tokens_includes_refresh_count(self, async_client, sample_ai_session_with_refreshes):
        """Token usage response includes refresh_count."""
        pass
```

### 6.3 E2E Scenarios

**Scenario 1: Proactive warning and user-initiated refresh**
1. User completes 15 chat turns editing a course. Each turn averages 4,500 input tokens.
2. At turn 16, the orchestrator detects 75,000 tokens used (75% of 100K limit).
3. No warning yet. Turn 16 completes with 79,000 tokens (79%).
4. Turn 17 starts. The orchestrator detects 83,000 tokens (83% -- exceeds warn threshold).
5. The assistant's response includes a note: "Your session has used 83% of its context window. Consider refreshing context for optimal performance."
6. The user clicks "Refresh context" in the chat UI.
7. Frontend calls `POST /api/v1/ai/sessions/{session_id}/refresh`.
8. Backend builds a summary with 18 turns, 3 active proposals, 1 key decision, and current course state.
9. Backend returns `{refresh_id, estimated_tokens_saved: 78000, message_count_before: 72}`.
10. User sends next message. The orchestrator uses rehydrated context (fresh system prompt + summary + user message).
11. The assistant re-fetches the current page via `fetch_page` tool before responding.
12. Context pressure is reset; the session continues with minimal summary overhead (~400 tokens vs ~78,000).

**Scenario 2: Automatic refresh at hard threshold**
1. User is in a productive editing session with 22 turns completed.
2. Turn 23 involves a large `propose_create_page` with multiple components.
3. After the turn, token usage is 186,000 (93% of 200K limit).
4. Turn 24 user sends: "Update the quiz to add 2 more questions."
5. The `_check_context_pressure()` method computes 93% -- above warn threshold.
6. The turn proceeds. Tool calls for `fetch_page` and `propose_update_page` execute.
7. After the final LLM call, the assistant's response includes a warning about context pressure.
8. Turn 25 user sends: "I also want to change the welcome page title."
9. Token usage is now 197,000 (98.5%).
10. `_check_context_pressure()` returns action='refresh'.
11. Before the turn processes, the orchestrator triggers `_refresh_context(trigger_type='auto_threshold')`.
12. Summary is built, stored, and the turn starts with rehydrated context.
13. Assistant response includes: "I have refreshed my context to stay within performance limits. All proposals and your course state are preserved."
14. The assistant uses `fetch_page("welcome")` and `fetch_page("quiz")` to get current data before responding.
15. Token usage drops to ~2,000 (1% -- just the summary + fresh context).

**Scenario 3: Emergency recovery from provider truncation**
1. User has been working for 30 turns. Context pressure checks were operating with a smaller model max setting (120K).
2. Actual token usage reaches 180K. The LLM provider returns `context_length_exceeded`.
3. `LLMClient._attempt_call()` catches the error, classifies it as `CONTEXT_WINDOW_EXCEEDED` (not retryable as a transient error).
4. `ChatOrchestrator._execute_llm_loop()` catches `ContextWindowExceededError`.
5. `_handle_context_exceeded_error()` is called:
   a. Emergency refresh builds a summary from DB state (not from messages, which may be incomplete).
   b. Rehydrated context is built.
   c. LLM call is retried once with the rehydrated context.
   d. Retry succeeds. The turn completes.
6. Frontend shows: "My context was full. I have refreshed my view. Your last instruction has been processed. Please confirm the result."
7. All active proposals are preserved.

**Scenario 4: Manual refresh preserves proposals mid-apply**
1. User has 2 pending proposals (prop_001: create "Quiz" page, prop_002: update "Module 1").
2. User clicks "Refresh context".
3. Backend builds summary with `active_proposal_ids: ["prop_001", "prop_002"]`.
4. After refresh, user sends: "Apply the quiz page proposal."
5. Assistant calls `apply_page_proposal(proposal_id="prop_001")` -- succeeds because proposal is still in DB.
6. Proposal was properly preserved across the refresh boundary.

### 6.4 Safety Invariant Tests

```python
# Invariant: refresh never removes active proposals
async def test_invariant_refresh_never_removes_proposals(test_client, sample_ai_session_with_proposals):
    """A context refresh does not delete or change the status of active proposals."""
    # Get proposals before refresh
    proposals_before = await get_proposals(test_client, sample_ai_session)
    # Perform refresh
    await test_client.post(f"/api/v1/ai/sessions/{sample_ai_session['session_id']}/refresh", json={})
    # Get proposals after refresh
    proposals_after = await get_proposals(test_client, sample_ai_session)
    assert proposals_before == proposals_after

# Invariant: refresh never modifies course data
async def test_invariant_refresh_never_modifies_course(test_client, sample_ai_session_with_pages):
    """A context refresh does not modify CourseRecord, PageRecord, or ComponentRecord."""
    course_before = (await test_client.get(f"/api/v1/courses/{sample_ai_session['course_id']}")).json()
    await test_client.post(f"/api/v1/ai/sessions/{sample_ai_session['session_id']}/refresh", json={})
    course_after = (await test_client.get(f"/api/v1/courses/{sample_ai_session['course_id']}")).json()
    assert course_before == course_after

# Invariant: provider context_length_exceeded error never loses user messages
async def test_invariant_provider_truncation_never_loses_messages(test_client, sample_ai_session, monkeypatch):
    """When provider returns context_length_exceeded, the user's message is retried and preserved."""
    pass

# Invariant: refresh does not cause cascade (refresh during refresh)
async def test_invariant_no_cascade_refresh(test_client, sample_ai_session, monkeypatch):
    """A refresh that triggers during rehydrated context does not cause a second refresh."""
    pass
```

### 6.5 Concurrency Tests

```python
async def test_concurrent_refresh_different_sessions(test_client, sample_ai_session, second_ai_session):
    """Refreshing two different sessions concurrently does not cause interference."""
    pass

async def test_concurrent_chat_turn_and_refresh_same_session(test_client, sample_ai_session):
    """A refresh request during an active chat turn returns 409 REFRESH_IN_PROGRESS."""
    pass
```

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `app/models/ai_chat.py` -- Extended `AISessionRecord` with `summary_json`, `total_input_tokens`, `total_output_tokens`, `last_refreshed_at`, `refresh_count`.
- [ ] `app/models/ai_context_refresh.py` -- New ORM model `AIContextRefreshRecord`.
- [ ] `app/repositories/ai_context_refresh_repo.py` -- `AIContextRefreshRepository` with `create`, `get_by_session`, `count_by_session`, `get_latest_by_session`.
- [ ] `app/repositories/ai_chat_repo.py` -- Extended `AISessionRepository` with `add_token_usage`, `get_token_usage`, `update_refresh_metadata`, `get_summary`.
- [ ] `app/services/ai/session_summary_builder.py` -- `SessionSummaryBuilder` with `build_summary`, `extract_key_decisions`, `build_action_timeline`, `build_summary_message`, `_compress_summary`.
- [ ] `app/services/ai/chat_orchestrator.py` -- Enhanced `ChatOrchestrator` with `_check_context_pressure`, `_refresh_context`, `_build_rehydrated_context`, `_handle_context_exceeded_error`, `_update_session_token_count`, `_get_session_usage_pct`.
- [ ] `app/services/ai/context_builder.py` -- Enhanced `ContextBuilder` with `rehydrate_context` method.
- [ ] `app/services/ai/llm_client.py` -- Enhanced `LLMClient` with `context_length_exceeded` error classification (distinct from other `invalid_request_error`).
- [ ] `app/routers/ai_chat_dtos.py` -- Added `SessionSummary`, `RefreshContextRequest`, `RefreshContextResponse`, `SessionTokenUsage` DTOs.
- [ ] `app/routers/ai_chat.py` -- Added `POST /api/v1/ai/sessions/{session_id}/refresh`, `GET /api/v1/ai/sessions/{session_id}/summary` endpoints. Enhanced `GET /api/v1/ai/sessions/{session_id}/tokens` with `usage_pct` and `status`. Implemented `context_refresh: true` handling in chat endpoint.
- [ ] Alembic migration for `ai_sessions` columns and `ai_context_refresh_log` table.
- [ ] Registration in `app/main.py` (new ORM model import in lifespan).
- [ ] Registration in `app/models/__init__.py` (new model export).
- [ ] Environment variables added to `.env` and `.env.example`.

### 7.2 Tests Pass

- [ ] All unit tests pass (20+ tests across `test_session_summary_builder.py`, `test_context_refresh.py`, `test_rehydrated_context.py`).
- [ ] All integration tests pass (15+ tests in `test_context_refresh_api.py`).
- [ ] All safety invariant tests pass (4 tests).
- [ ] All concurrency tests pass (2 tests).
- [ ] Existing US-AI-023 chat tests still pass (regression).
- [ ] Coverage >= 85% for new/modified code.

### 7.3 Documentation

- [ ] API contracts for `POST /api/v1/ai/sessions/{session_id}/refresh` and `GET /api/v1/ai/sessions/{session_id}/summary` documented in OpenAPI spec.
- [ ] Context refresh flow documented in `docs/AI_Implemenation/01_SystemArchitecture/` flow diagrams.
- [ ] Environment variables documented in `.env.example`.
- [ ] Session summary JSON schema documented in this story.

### 7.4 Security

- [ ] Refresh endpoint gated by `AI_AUTHORING_ENABLED` feature flag.
- [ ] Session ownership validation on all new endpoints.
- [ ] Summary data never contains PII, credentials, or secrets.
- [ ] Max refreshes per session enforced (`AI_CONTEXT_MAX_REFRESHES_PER_SESSION`).
- [ ] Refresh audit trail in `ai_context_refresh_log` with trigger type and timing.

### 7.5 Operational Readiness

- [ ] `AI_CONTEXT_REFRESH_ENABLED` flag can disable automatic refreshes (only manual).
- [ ] Configurable thresholds (`AI_CONTEXT_REFRESH_WARN_THRESHOLD`, `AI_CONTEXT_REFRESH_HARD_THRESHOLD`).
- [ ] Provider `context_length_exceeded` error triggers exactly one retry after refresh.
- [ ] Refresh cascading prevented (max one refresh per turn, max N refreshes per session).
- [ ] Telemetry events for every context refresh with trigger type, tokens saved, and duration.

---

## 8. Tasks

### Task 1: Extend AISessionRecord ORM Model and Create AIContextRefreshRecord

**Files to create/modify:**
- `app/models/ai_chat.py` (extend `AISessionRecord`)
- `app/models/ai_context_refresh.py` (new)
- `app/models/__init__.py` (add import)

**Acceptance:**
- `AISessionRecord` gains columns: `summary_json` (JSONB, nullable, default `{}`), `total_input_tokens` (BigInteger, default 0), `total_output_tokens` (BigInteger, default 0), `last_refreshed_at` (TIMESTAMPTZ, nullable), `refresh_count` (Integer, default 0).
- `AIContextRefreshRecord` has all columns: refresh_id, session_id (FK to ai_sessions), turn_id, trigger_type (with CHECK constraint), token_usage_before (JSONB), message_count_before, estimated_tokens_saved, summary_json (JSONB), summary_token_count, started_at, completed_at, duration_ms, status, error_message.
- `AISessionRecord.to_dict()` includes the new fields.
- `AIContextRefreshRecord.to_dict()` serializes all fields.
- Both models registered in `app/models/__init__.py`.

**Effort:** 3 hours
**Dependencies:** US-AI-006 (ai_sessions table), US-AI-023 (existing ai_chat.py model)

---

### Task 2: Create AIContextRefreshRepository and Extend AISessionRepository

**Files to create/modify:**
- `app/repositories/ai_context_refresh_repo.py` (new)
- `app/repositories/ai_chat_repo.py` (extend `AISessionRepository`)

**Acceptance:**
- `AIContextRefreshRepository` supports: `create`, `get_by_session` (with pagination), `count_by_session`, `get_latest_by_session`.
- `AISessionRepository` extended with: `add_token_usage` (atomic UPDATE with delta addition), `get_token_usage` (returns input + output totals, refresh_count, last_refreshed_at), `update_refresh_metadata` (sets summary_json, last_refreshed_at, increments refresh_count), `get_summary` (returns stored summary_json).
- All methods use existing repository pattern (AsyncSession, execute, commit).

**Effort:** 2 hours
**Dependencies:** Task 1

---

### Task 3: Build SessionSummaryBuilder Service

**File to create:**
- `app/services/ai/session_summary_builder.py` (new)

**Acceptance:**
- `build_summary()` loads session messages, tool call logs, proposals, and course state and returns a structured summary dict.
- `extract_key_decisions()` scans user messages for preference-indicating patterns and tool call results for state changes.
- `build_action_timeline()` builds chronological action list from tool call logs (not messages), deduplicating by turn_id.
- `build_summary_message()` constructs a user-role message with a human-readable summary paragraph and rehydration instruction.
- `_compress_summary()` trims oldest decisions and timeline entries when summary exceeds `MAX_SUMMARY_TOKENS`.
- `rough_token_count()` provides fast approximation.
- Summary is deterministic (no LLM call required) but optional LLM parameter is accepted for future NL summary generation.
- Summary JSON matches the schema in Section 2.7.

**Effort:** 6 hours
**Dependencies:** Task 2 (repositories), US-AI-023 (message + tool call persistence)

---

### Task 4: Enhance ChatOrchestrator with Context Pressure Monitoring and Refresh

**File to modify:**
- `app/services/ai/chat_orchestrator.py`

**Acceptance:**
- `_check_context_pressure()`: Reads session token totals, computes `usage_pct` against `CONTEXT_MODEL_MAX`, returns `{action: str, usage_pct: float, warning_message: str|None}`.
  - `usage_pct < WARN_THRESHOLD`: action='none'.
  - `WARN_THRESHOLD <= usage_pct < HARD_THRESHOLD`: action='warn', includes warning text.
  - `usage_pct >= HARD_THRESHOLD` or `context_refresh` flag set: action='refresh'.
- `_refresh_context()`: Calls `SessionSummaryBuilder.build_summary()`, stores summary via repository, writes `AIContextRefreshRecord`, updates session refresh metadata.
- `_build_rehydrated_context()`: Loads stored summary, constructs `[system_prompt, summary_message, rehydration_instruction, user_message]` array, returns with full tool definitions.
- `_handle_context_exceeded_error()`: Called when LLM returns context_length_exceeded. Performs emergency refresh, rebuilds context, retries LLM call once. Returns error if retry fails.
- `_update_session_token_count()`: Calls `AISessionRepository.add_token_usage()` after each LLM call.
- `process_turn()` enhanced to:
  - Call `_check_context_pressure()` before building messages.
  - If action='refresh', call `_refresh_context()` and `_build_rehydrated_context()` instead of normal context building.
  - If action='warn', append warning to final response.
  - After turn completes, update token counters.
- `_execute_llm_loop()` enhanced to catch `ContextWindowExceededError` and delegate to `_handle_context_exceeded_error()`.
- Maximum one refresh per turn; refresh count incremented and checked against `AI_CONTEXT_MAX_REFRESHES_PER_SESSION`.
- All new methods follow the existing async generator pattern for SSE streaming.

**Effort:** 10 hours
**Dependencies:** Tasks 2 (repositories), 3 (SessionSummaryBuilder), US-AI-023 (existing ChatOrchestrator)

---

### Task 5: Enhance LLMClient with Context Exceeded Error Classification

**File to modify:**
- `app/services/ai/llm_client.py`

**Acceptance:**
- `_attempt_call()` inspects error response for `type: "error"` with `error.type: "invalid_request_error"` and `error.message` containing `"context_length_exceeded"`.
- Classifies this error as `ContextWindowExceededError` (subclass of `LLMProviderError`, NOT retryable as transient).
- All other `invalid_request_error` types remain non-retryable `LLMProviderError`.
- `ContextWindowExceededError` has properties: `provider_message`, `current_token_count` (extracted from error response if available).
- Unit tests mock the specific Anthropic API error response shape for `context_length_exceeded`.

**Effort:** 2 hours
**Dependencies:** US-AI-023 (existing LLMClient)

---

### Task 6: Create Context Refresh and Summary API Endpoints

**Files to modify:**
- `app/routers/ai_chat_dtos.py` (add DTOs)
- `app/routers/ai_chat.py` (add endpoints)

**Acceptance:**
- `POST /api/v1/ai/sessions/{session_id}/refresh`:
  - Validates session exists, not expired, user owns session.
  - Checks no active turn in progress (returns 409 if so).
  - Calls `ChatOrchestrator._refresh_context()` with `trigger_type='user_initiated'`.
  - Returns `RefreshContextResponse` with refresh_id, estimated_tokens_saved, message_count_before, summary_token_count.
  - Error responses use error envelope pattern.
- `GET /api/v1/ai/sessions/{session_id}/summary`:
  - Returns stored `summary_json` if exists, or builds on-the-fly if not.
  - Returns `SessionSummary` shape.
  - 404 if session not found.
- `GET /api/v1/ai/sessions/{session_id}/tokens` enhanced:
  - Returns `usage_pct`, `status` ('healthy'/'warn'/'critical'), `refresh_count`, `last_refreshed_at`.
  - Computes status from token totals.
- `POST /api/v1/ai/chat` enhanced:
  - When `ChatRequest.context_refresh == true`: orchestrator performs context refresh before processing turn.
- All endpoints gated by `ai_authoring_enabled` dependency.

**Effort:** 4 hours
**Dependencies:** Task 4 (ChatOrchestrator refresh methods), Task 5 (LLMClient error handling)

---

### Task 7: Enhance ContextBuilder with Rehydrate Context Method

**File to modify:**
- `app/services/ai/context_builder.py`

**Acceptance:**
- `rehydrate_context()` method added:
  - Accepts: `system_prompt`, `summary_message` (from SessionSummaryBuilder), `rehydration_instruction`, `user_message`, `tools`.
  - Returns: `(messages: list[dict], tools: list[dict])`.
  - Messages array order: `[system_prompt, summary_message, rehydration_instruction, user_message]`.
  - The `rehydration_instruction` is built with a standard template instructing the LLM to re-fetch state via tools.
  - The method supports optional `include_previous_context` flag for debugging purposes.
- Existing `build_messages_array()` unchanged (used for normal turns).
- Token counting method enhanced with option to use Anthropic's token counting API if available, falling back to `len//4`.

**Effort:** 2 hours
**Dependencies:** US-AI-023 (existing ContextBuilder)

---

### Task 8: Create Alembic Migration

**File to create:**
- `alembic/versions/20260614_0004_add_context_window_recovery.py`

**Acceptance:**
- ALTER TABLE `ai_sessions` ADD columns: `summary_json` (JSONB, default '{}'), `total_input_tokens` (BIGINT, default 0), `total_output_tokens` (BIGINT, default 0), `last_refreshed_at` (TIMESTAMPTZ), `refresh_count` (INTEGER, default 0).
- Creates `ai_context_refresh_log` table with all columns and indexes as specified in Section 2.1.
- Foreign key from `ai_context_refresh_log.session_id` to `ai_sessions.session_id` with ON DELETE CASCADE.
- `downgrade()` drops the new table and removes the added columns.
- Migration runs cleanly against both SQLite (dev/tests) and PostgreSQL (prod).
- Existing `ai_sessions` data is preserved (columns are nullable with defaults).

**Effort:** 1 hour
**Dependencies:** Task 1 (column definitions)

---

### Task 9: Write Unit Tests

**Files to create:**
- `tests/test_session_summary_builder.py`
- `tests/test_context_refresh.py`

**Acceptance:**
- All test scenarios from Section 6.1 are covered.
- Tests use in-memory SQLite test fixtures.
- Mock LLM client for optional NL summary tests.
- Session summary builder tests verify: empty session, populated session, key decision extraction, action timeline, compression, summary message.
- Context pressure tests verify: below threshold, warn threshold, hard threshold, model max variance.
- Context refresh tests verify: summary storage, audit log writing, counter updates, trigger types, max refreshes limit.
- Rehydrated context tests verify: correct message composition, history exclusion, tool definitions unchanged.
- Coverage >= 85% for `session_summary_builder.py` and new/modified methods in `chat_orchestrator.py`.

**Effort:** 8 hours
**Dependencies:** Tasks 3, 4, 5, 7

---

### Task 10: Write Integration Tests

**File to create:**
- `tests/test_context_refresh_api.py`

**Acceptance:**
- All test scenarios from Section 6.2 are covered.
- Tests verify: manual refresh success, non-existent session, expired session, response shape, proposal preservation, chat with context_refresh flag, automatic refresh at threshold, provider error recovery, emergency retry success/failure.
- Test fixtures include: `sample_ai_session_with_messages` (15+ messages), `sample_ai_session_near_limit` (token usage at 96%), `sample_ai_session_with_summary`, `sample_ai_session_with_refreshes`, `sample_ai_session_high_tokens` (82% usage), `sample_ai_session_critical_tokens` (96% usage), `sample_ai_session_high_refresh_count` (at max limit).
- Tests use `TestClient` with async httpx support.
- Existing chat tests still pass (regression).

**Effort:** 6 hours
**Dependencies:** Task 6 (endpoints), Task 9 (unit tests)

---

### Task 11: Add Environment Variables and Configuration

**Files to modify:**
- `.env.example`
- `.env`

**Acceptance:**
- All environment variables from Section 2.10 are documented in `.env.example`.
- Default values provided for all variables.
- `AI_CONTEXT_REFRESH_ENABLED` defaults to `true`.
- Configuration is read at module level in `chat_orchestrator.py` and `session_summary_builder.py`.
- Missing optional variables log a warning and use documented defaults.

**Effort:** 0.5 hours
**Dependencies:** Tasks 3, 4

---

### Task 12: Documentation and Review

**Files to modify:**
- `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` (update status to "in progress")
- `docs/AI_Implemenation/01_SystemArchitecture/` (update flow diagrams)
- OpenAPI spec (document new endpoints)

**Acceptance:**
- API contracts for `POST /api/v1/ai/sessions/{session_id}/refresh` and `GET /api/v1/ai/sessions/{session_id}/summary` documented.
- Context refresh flow diagram added to architecture docs.
- Session summary JSON schema documented.
- Environment variables documented in `.env.example`.
- Story is marked in progress in the canonical user stories list.

**Effort:** 2 hours
**Dependencies:** Tasks 6, 9, 10, 11

---

### Task 13: Code Review and Merge

**Acceptance:**
- All CI checks pass.
- Two approvals on the PR.
- No regression in existing tests (chat, session, proposal CRUD).
- `AI_CONTEXT_REFRESH_ENABLED` defaults to `true` but can be disabled via env var.
- Refresh audit trail is complete: every refresh is logged with trigger type and timing.
- Migration runs without errors on a fresh database.
- Token tracking counters are atomic (no race conditions on concurrent updates -- use `UPDATE ... SET total_input_tokens = total_input_tokens + :delta`).
- Frontend refresh indicator integration path is documented for US-AI-024.

**Effort:** 2 hours
**Dependencies:** All prior tasks

---

## Summary

| Metric | Value |
|---|---|
| New files | 3 (`session_summary_builder.py`, `ai_context_refresh.py`, `ai_context_refresh_repo.py`) |
| Modified files | 8 (models, repositories, services, routers, config) |
| New tables | 1 (`ai_context_refresh_log`) |
| Altered tables | 1 (`ai_sessions` -- 5 new columns) |
| New API endpoints | 2 (`POST /refresh`, `GET /summary`) |
| Enhanced endpoints | 2 (`POST /chat` context_refresh handling, `GET /tokens` usage_pct) |
| New services | 1 (`SessionSummaryBuilder`) |
| Enhanced services | 3 (`ChatOrchestrator`, `ContextBuilder`, `LLMClient`) |
| Total estimated effort | ~48.5 hours |
| Key safety invariant | Context refresh never modifies course data or proposal state |
| Key risk | Token counter accuracy -- approximate counting may trigger refresh too early or too late; mitigated by configurable thresholds |
