"""AI Chat Router — US-BKND-AI-023.

Chat orchestration endpoint for the AI authoring assistant. Accepts
natural-language instructions in the context of an AI session.

Implemented:
    US-BKND-AI-014: Basic chat endpoint with session validation and turn persistence
    US-BKND-AI-023: Full LLM interaction loop with tool calling and SSE streaming
    US-BKND-AI-025: Input/output safety guardrails (via SafetyService)

Endpoints:
    POST /api/v1/ai/chat          — Send a message (JSON response)
    POST /api/v1/ai/chat/stream   — Send a message (SSE streaming)
    GET  /api/v1/ai/chat/history  — Get conversation history
"""

import logging
from datetime import datetime
from typing import Optional, List, AsyncIterator
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.models.ai_models import AIChatTurnRecord
from app.repositories.ai_chat_turn_repo import AIChatTurnRepository
from app.repositories.ai_session_repo import AISessionRepository
from app.services.ai.error_envelope import ai_error, AIErrorCode

logger = logging.getLogger("ai_authoring")
router = APIRouter(prefix="/ai", tags=["AI - Chat"])


# ── Schemas ──────────────────────────────────────────────────────

class SelectedContext(BaseModel):
    """Optional context hint from frontend about what the user selected."""
    page_id: Optional[str] = Field(default=None)
    component_id: Optional[str] = Field(default=None)


class ChatRequest(BaseModel):
    """Request body for POST /api/v1/ai/chat."""
    session_id: str = Field(..., min_length=1, max_length=128)
    prompt: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(default="chat_edit")
    selected_context: Optional[SelectedContext] = None
    stream: bool = Field(
        default=False,
        description="If true, response is streamed via Server-Sent Events",
    )


class ChatResponse(BaseModel):
    """Response body for POST /api/v1/ai/chat."""
    chat_turn_id: str
    session_id: str
    message: dict
    proposals: list = Field(default_factory=list)
    tool_calls: list = Field(default_factory=list)
    session_summary: dict = Field(default_factory=dict)


# ── Shared Session Validation ─────────────────────────────────────

async def _validate_chat_session(
    session_id: str, user: UserContext, db: AsyncSession,
):
    """Validate session exists, is active, and belongs to user."""
    srepo = AISessionRepository(db)
    session = await srepo.get_active(session_id)
    if session is None:
        existing = await srepo.get(session_id)
        if existing and existing.is_expired():
            return None, ai_error("SESSION_EXPIRED",
                "Session has expired. Please create a new session.", status=440)
        return None, ai_error("SESSION_INVALID",
            "Session not found or invalid.", status=401)

    if session.user_id != user.user_id:
        return None, ai_error("PERMISSION_DENIED",
            "Session does not belong to the authenticated user.", status=403)

    return session, None


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/chat")
async def chat_message(
    body: ChatRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Send a message to the AI authoring assistant (JSON response).

    US-BKND-AI-023: Full LLM interaction loop with tool calling.
    Validates the session, runs the LLM loop, persists turns, and
    returns a structured JSON response with proposals and tool calls.
    """
    # 1. Validate session
    session, err = await _validate_chat_session(body.session_id, user, db)
    if err:
        return err

    # 2. Store user's chat turn
    trepo = AIChatTurnRepository(db)
    user_turn = AIChatTurnRecord(
        session_id=body.session_id,
        user_id=user.user_id,
        role="user",
        content=body.prompt,
        tokens_input=len(body.prompt.split()),
        tokens_output=0,
        created_at=datetime.utcnow(),
    )
    await trepo.create(user_turn)

    # 3. Process through ChatOrchestrator
    from app.services.ai.chat_orchestrator import ChatOrchestrator
    orchestrator = ChatOrchestrator(db)

    # Use full LLM loop when AI authoring is enabled, else mock
    from app.services.ai.config import get_ai_config
    ai_config = get_ai_config()

    response = await orchestrator.process_message(
        session_id=body.session_id,
        user_id=user.user_id,
        prompt=body.prompt,
        course_id=session.course_id,
    )
    response_content = response["content"]

    # 4. Store assistant's chat turn with tool call data
    assistant_turn = AIChatTurnRecord(
        session_id=body.session_id,
        user_id=user.user_id,
        role="assistant",
        content=response_content,
        tool_calls=response.get("tool_uses", response.get("tool_calls", [])),
        tool_results=None,
        tokens_input=response.get("token_usage", {}).get("input", 0),
        tokens_output=response.get("token_usage", {}).get("output", len(response_content.split())),
        created_at=datetime.utcnow(),
    )
    await trepo.create(assistant_turn)

    # 5. Touch session activity
    srepo = AISessionRepository(db)
    await srepo.touch(body.session_id)

    return {
        "status": "ok",
        "chat_turn_id": assistant_turn.turn_id,
        "session_id": body.session_id,
        "message": {
            "role": "assistant",
            "content": response_content,
        },
        "proposals": response.get("proposals", []),
        "tool_calls": response.get("tool_calls", response.get("tool_uses", [])),
        "token_usage": response.get("token_usage", {}),
        "latency_ms": response.get("latency_ms", 0),
        "intent": response.get("intent", "unknown"),
        "session_summary": {
            "active_proposal_count": len(response.get("proposals", [])),
            "course_id": session.course_id,
            "intent": response.get("intent", "unknown"),
        },
    }


@router.post("/chat/stream")
async def chat_message_stream(
    body: ChatRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Send a message to the AI authoring assistant (SSE streaming).

    US-BKND-AI-023: Returns a Server-Sent Events stream with real-time
    progress on tool calls, text generation, and turn completion.

    Event types:
        turn_start     — Turn has started
        tool_call_start — A tool call is about to execute
        tool_call_result — Tool call completed
        text_delta     — Partial text from the LLM
        turn_complete  — Turn finished with proposals and token usage
        turn_error     — Error occurred
    """
    import json as _json

    # 1. Validate session
    session, err = await _validate_chat_session(body.session_id, user, db)
    if err:
        return err

    # 2. Store user's chat turn
    trepo = AIChatTurnRepository(db)
    user_turn = AIChatTurnRecord(
        session_id=body.session_id,
        user_id=user.user_id,
        role="user",
        content=body.prompt,
        tokens_input=len(body.prompt.split()),
        tokens_output=0,
        created_at=datetime.utcnow(),
    )
    await trepo.create(user_turn)

    # 3. Define the SSE streaming generator
    async def event_stream() -> AsyncIterator[str]:
        import time as _time

        turn_id = user_turn.turn_id
        started_at = datetime.utcnow().isoformat()

        # Send turn_start
        yield f"event: turn_start\ndata: {_json.dumps({'turn_id': turn_id, 'session_id': body.session_id, 'started_at': started_at})}\n\n"

        try:
            from app.services.ai.chat_orchestrator import ChatOrchestrator
            orchestrator = ChatOrchestrator(db)

            response = await orchestrator.process_message(
                session_id=body.session_id,
                user_id=user.user_id,
                prompt=body.prompt,
                course_id=session.course_id,
            )

            # Stream tool calls as they complete
            for tc in response.get("tool_calls", []):
                yield f"event: tool_call_start\ndata: {_json.dumps({'tool_call_id': tc.get('tool_call_id', ''), 'tool_name': tc.get('tool', tc.get('tool_name', '')), 'input': {}})}\n\n"

                yield f"event: tool_call_result\ndata: {_json.dumps({'tool_call_id': tc.get('tool_call_id', ''), 'tool_name': tc.get('tool', tc.get('tool_name', '')), 'status': tc.get('status', 'success'), 'output_summary': str(tc.get('result', {}))[:200]})}\n\n"

            # Stream text content
            content = response.get("content", "")
            chunk_size = 50
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                yield f"event: text_delta\ndata: {_json.dumps({'delta': chunk})}\n\n"

            # Store assistant's turn
            assistant_turn = AIChatTurnRecord(
                session_id=body.session_id,
                user_id=user.user_id,
                role="assistant",
                content=content,
                tool_calls=response.get("tool_uses", response.get("tool_calls", [])),
                tokens_input=response.get("token_usage", {}).get("input", 0),
                tokens_output=response.get("token_usage", {}).get("output", 0),
                created_at=datetime.utcnow(),
            )
            await trepo.create(assistant_turn)

            # Send turn_complete
            yield f"event: turn_complete\ndata: {_json.dumps({'turn_id': turn_id, 'chat_turn_id': assistant_turn.turn_id, 'proposal_ids': [p.get('proposal_id') for p in response.get('proposals', [])], 'token_usage': response.get('token_usage', {}), 'latency_ms': response.get('latency_ms', 0)})}\n\n"

        except Exception as exc:
            logger.exception("Chat stream error")
            yield f"event: turn_error\ndata: {_json.dumps({'turn_id': turn_id, 'code': 'LLM_PROVIDER_ERROR', 'message': str(exc), 'retryable': True})}\n\n"

        # Touch session
        try:
            srepo = AISessionRepository(db)
            await srepo.touch(body.session_id)
        except Exception:
            pass

        yield "event: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history")
async def chat_history(
    session_id: str = Query(..., min_length=1),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get conversation history for a session.

    Returns all chat turns in chronological order. Used by the frontend
    to restore the chat panel on page reload.
    """
    session, err = await _validate_chat_session(session_id, user, db)
    if err:
        return err

    trepo = AIChatTurnRepository(db)
    turns = await trepo.list_by_session(session_id)

    return {
        "status": "ok",
        "session_id": session_id,
        "turns": [
            {
                "turn_id": t.turn_id,
                "role": t.role,
                "content": t.content,
                "tool_calls": t.tool_calls,
                "tool_results": t.tool_results,
                "tokens_input": t.tokens_input,
                "tokens_output": t.tokens_output,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in turns
        ],
        "total_turns": len(turns),
    }
