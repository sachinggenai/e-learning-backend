"""AI Chat Orchestrator — US-BKND-AI-023.

Manages the LLM interaction loop: receives user messages, constructs
system prompts with tool definitions, calls the LLM (or mock), executes
tool calls via ToolExecutor, and returns structured responses.

Architecture:
- DB-first state: every turn re-fetches course state from the database
- Propose-before-apply: mutation tools create proposals, never mutate
- Server-side tool execution: validates inputs/outputs, routes to services
- Streaming-ready: SSE events for real-time progress
- Multi-turn loop: LLM may call multiple tools before responding
- Mock mode: deterministic intent parsing for testing without LLM

US-BKND-AI-023: Full LLM interaction loop with tool calling
US-BKND-AI-025: Input/output safety guardrails
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.config import get_ai_config

logger = logging.getLogger("ai_authoring")

# ── System prompt template ──────────────────────────────────────

SYSTEM_PROMPT = """You are an AI course authoring assistant. You help instructors create and edit e-learning courses.

Your capabilities:
- List and fetch pages from the current course
- Propose new pages with validated template types
- Propose updates to existing pages
- Validate course content against template rules
- Search for similar courses for style and tone guidance (via query_similar_courses tool)

IMPORTANT RULES:
1. NEVER mutate data directly — always create proposals first
2. Always validate before proposing — use the validate tool
3. Always fetch current state — never trust conversation history
4. For destructive actions — always require explicit user confirmation
5. Stay within the session's course scope — do not access other courses
6. The `query_similar_courses` tool returns example courses for tone and structural
   reference ONLY. Do NOT derive API contracts, validation rules, template schemas,
   or configuration values from these results. Always rely on the tool definitions,
   template contracts, and schemas provided in your system prompt for authoritative
   specifications.
7. If `query_similar_courses` returns empty results, continue generation without
   examples. Quality may be slightly lower but this should not block progress.

Available template types: text-content, tabs, accordion, click-reveal, final-assessment
"""


class ChatOrchestrator:
    """Manages the AI chat interaction loop.

    In mock mode (default), parses user intent and calls tools directly
    without an LLM. In production mode, calls the Anthropic API with
    tool definitions.

    Usage:
        orch = ChatOrchestrator(db)
        result = await orch.process_message(session_id, user_id, prompt)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.config = get_ai_config()

    async def process_message(
        self,
        session_id: str,
        user_id: str,
        prompt: str,
        course_id: str = "",
    ) -> Dict[str, Any]:
        """Process a user message and return a structured response.

        This is the main entry point for the chat endpoint.
        In mock mode, parses intent and executes tools directly.
        In production mode, runs the full LLM interaction loop.

        Safety checks (US-BKND-AI-025):
        1. Input guard: prompt injection + PII scan before processing
        2. Output guard: blocked terms scan after response generation
        """
        # ── Safety: Input guard (US-BKND-AI-025) ──────────────
        from app.services.ai.safety_service import SafetyService
        safety = SafetyService(
            prompt_safety_enabled=self.config.prompt_safety_enabled,
            output_safety_enabled=self.config.output_safety_enabled,
        )
        safety_result = safety.scan_input(prompt)
        if not safety_result.allowed:
            return {
                "role": "assistant",
                "content": "Your message was blocked by safety filters. "
                           "Please remove any sensitive information and try again.",
                "tool_calls": [],
                "proposals": [],
                "intent": "blocked",
                "safety_blocks": safety_result.blocks,
            }
        # Use sanitized prompt
        prompt = safety_result.sanitized_text or prompt

        # ── Route to LLM when AI is configured ──────────────────
        api_key = self.config.anthropic_api_key
        if api_key and self.config.ai_authoring_enabled:
            return await self._process_with_llm(
                session_id, user_id, prompt, course_id, safety
            )

        # ── Fallback: mock intent parsing (no LLM) ──────────────
        return await self._process_mock(
            session_id, user_id, prompt, course_id, safety
        )

    async def _process_with_llm(
        self,
        session_id: str,
        user_id: str,
        prompt: str,
        course_id: str,
        safety: Any,
    ) -> Dict[str, Any]:
        """Production path: run the full LLM interaction loop."""
        import time
        t0 = time.monotonic()

        llm_result = await self.run_llm_loop(
            session_id=session_id,
            user_id=user_id,
            prompt=prompt,
            course_id=course_id,
        )

        content = llm_result.get("content", "")
        tool_calls = llm_result.get("tool_calls", [])
        proposals = llm_result.get("proposals", [])
        token_usage = llm_result.get("token_usage", {})
        latency_ms = int((time.monotonic() - t0) * 1000)

        # ── Safety: Output guard ──────────────────────────────
        output_safety = safety.scan_output(content)
        if not output_safety.allowed:
            content = output_safety.sanitized_text or content

        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
            "proposals": proposals,
            "intent": llm_result.get("intent", "unknown"),
            "token_usage": token_usage,
            "latency_ms": latency_ms,
            "safety_input_warnings": safety.scan_input(prompt).warnings,
        }

    async def _process_mock(
        self,
        session_id: str,
        user_id: str,
        prompt: str,
        course_id: str,
        safety: Any,
    ) -> Dict[str, Any]:
        """Mock path: keyword-based intent parsing, no LLM."""
        tool_calls = []
        proposals = []

        intent = self._parse_intent(prompt)

        # Execute tools based on intent
        for tool_name, tool_args in intent.get("tool_calls", []):
            try:
                result = await self._execute_mock_tool(
                    tool_name, tool_args, session_id, user_id, course_id
                )
                tool_calls.append({
                    "tool": tool_name,
                    "status": "success",
                    "result": result,
                })
                if "proposal_id" in result:
                    proposals.append({
                        "proposal_id": result.get("proposal_id"),
                        "proposal_type": tool_name.replace("propose_", ""),
                        "status": "pending_review",
                        "validation_status": result.get("validation_status", "valid"),
                        "diff": result.get("diff", {}),
                    })
            except Exception as e:
                tool_calls.append({
                    "tool": tool_name,
                    "status": "error",
                    "error": str(e),
                })

        response_content = self._build_response(prompt, intent, tool_calls, proposals)

        output_safety = safety.scan_output(response_content)
        if not output_safety.allowed:
            response_content = output_safety.sanitized_text or response_content

        return {
            "role": "assistant",
            "content": response_content,
            "tool_calls": tool_calls,
            "proposals": proposals,
            "intent": intent.get("intent", "unknown"),
            "safety_input_warnings": safety.scan_input(prompt).warnings,
        }

    def _parse_intent(self, prompt: str) -> Dict[str, Any]:
        """Parse user intent from natural language (mock LLM).

        In production, this is replaced by the LLM's native tool-calling
        response. In mock mode, we use keyword matching to determine
        what tools to call.
        """
        p = prompt.lower()

        # List pages
        if any(w in p for w in ["list pages", "show pages", "what pages", "page list"]):
            return {
                "intent": "list_pages",
                "tool_calls": [("list_pages", {})],
            }

        # Fetch specific page
        if any(w in p for w in ["fetch page", "get page", "show page", "open page"]):
            return {
                "intent": "fetch_page",
                "tool_calls": [
                    ("list_pages", {}),
                    ("fetch_page", {"title_hint": prompt}),
                ],
            }

        # Create a new page
        if any(w in p for w in ["create page", "add page", "new page", "add a"]):
            title, ttype, data = self._extract_create_params(prompt)
            return {
                "intent": "create_page",
                "tool_calls": [
                    ("list_pages", {}),
                    ("propose_create_page", {
                        "title": title,
                        "template_type": ttype,
                        "data": data,
                    }),
                ],
            }

        # Update a page
        if any(w in p for w in ["update page", "edit page", "change page", "modify", "simplify", "rewrite"]):
            return {
                "intent": "update_page",
                "tool_calls": [
                    ("list_pages", {}),
                    ("propose_update_page", {"title_hint": prompt}),
                ],
            }

        # Delete a page
        if any(w in p for w in ["delete page", "remove page", "delete the"]):
            return {
                "intent": "delete_page",
                "tool_calls": [
                    ("list_pages", {}),
                    ("propose_delete_page", {}),
                ],
            }

        # Validate course
        if any(w in p for w in ["validate", "check course", "course valid"]):
            return {
                "intent": "validate_course",
                "tool_calls": [("validate_course", {"scope": "full"})],
            }

        # Similar courses
        if any(w in p for w in ["similar course", "like this course", "examples of"]):
            return {
                "intent": "query_similar",
                "tool_calls": [("query_similar_courses", {"query": prompt})],
            }

        # Default: list pages + offer help
        return {
            "intent": "help",
            "tool_calls": [("list_pages", {})],
        }

    async def _execute_mock_tool(
        self, tool_name: str, args: Dict[str, Any],
        session_id: str, user_id: str, course_id: str,
    ) -> Dict[str, Any]:
        """Execute a tool in mock mode via ToolExecutor."""
        from app.services.ai.tool_executor import ToolExecutor

        executor = ToolExecutor(self.db)

        if tool_name == "list_pages":
            result = await executor.execute(
                "list_pages", {"session_id": session_id}, user_id
            )
            return result.get("data", result)

        if tool_name == "fetch_page":
            # In mock, return first page if no page_id specified
            pages_result = await executor.execute(
                "list_pages", {"session_id": session_id}, user_id
            )
            pages = pages_result.get("data", {}).get("pages", [])
            if pages:
                page_id = pages[0]["page_id"]
                result = await executor.execute(
                    "fetch_page",
                    {"session_id": session_id, "page_id": page_id},
                    user_id,
                )
                return result.get("data", result)
            return {"pages": [], "message": "No pages found"}

        if tool_name == "propose_create_page":
            from app.services.ai.proposal_service import AIProposalService
            svc = AIProposalService(self.db)
            title = args.get("title", "New Page")
            ttype = args.get("template_type", "text-content")
            data = args.get("data", {"content": "Sample content"})
            result = await svc.create_proposal(
                session_id=session_id, user_id=user_id,
                organization_id="", course_id=course_id,
                operation="create_page", resource_type="page",
                data={"title": title, "template_type": ttype, "data": data},
            )
            return result

        if tool_name == "propose_update_page":
            from app.services.ai.proposal_service import AIProposalService
            svc = AIProposalService(self.db)
            pages_result = await self._execute_mock_tool(
                "list_pages", {}, session_id, user_id, course_id
            )
            pages = pages_result.get("pages", [])
            if pages:
                result = await svc.create_proposal(
                    session_id=session_id, user_id=user_id,
                    organization_id="", course_id=course_id,
                    operation="update_page", resource_type="page",
                    resource_id=pages[0]["page_id"],
                    data={"title": pages[0].get("title", "Updated"),
                          "template_type": "", "data": {"content": "Updated content"}},
                )
                return result
            return {"error": "No pages to update"}

        if tool_name == "propose_delete_page":
            from app.services.ai.proposal_service import AIProposalService
            svc = AIProposalService(self.db)
            pages_result = await self._execute_mock_tool(
                "list_pages", {}, session_id, user_id, course_id
            )
            pages = pages_result.get("pages", [])
            if pages:
                result = await svc.create_proposal(
                    session_id=session_id, user_id=user_id,
                    organization_id="", course_id=course_id,
                    operation="delete_page", resource_type="page",
                    resource_id=pages[-1]["page_id"],
                    data={"title": "", "template_type": "", "data": {}},
                )
                return result
            return {"error": "No pages to delete"}

        if tool_name == "validate_course":
            from app.services.validation.unified_validator import (
                UnifiedValidator, ValidationScope
            )
            validator = UnifiedValidator(self.db)
            result = await validator.validate_course(
                course_id, scope=ValidationScope(args.get("scope", "full"))
            )
            return result.model_dump()

        if tool_name == "query_similar_courses":
            # Real retrieval via SimilarCourseService (US-BKND-AI-015)
            from app.services.ai.similar_course_service import (
                SimilarCourseService,
                FeatureDisabledError,
            )
            try:
                service = SimilarCourseService(self.db)
                result = await service.query_similar_courses(
                    session_id=session_id,
                    query=args.get("query", ""),
                    max_results=args.get("max_results", 5),
                    filters=args.get("filters"),
                    user_id=user_id,
                )
                return result
            except FeatureDisabledError:
                return {
                    "courses": [],
                    "total_count": 0,
                    "message": "Similar course retrieval is not enabled. "
                               "Proceeding without examples.",
                    "retrieval_tier_used": "none",
                }
            except Exception as exc:
                logger.warning(
                    "Similar course retrieval failed (non-fatal): %s", exc
                )
                return {
                    "courses": [],
                    "total_count": 0,
                    "message": "Similar course retrieval temporarily unavailable. "
                               "Proceeding without examples.",
                    "retrieval_tier_used": "none",
                }

        return {"error": f"Unknown tool: {tool_name}"}

    # ------------------------------------------------------------------
    # US-BKND-AI-023: Full LLM Interaction Loop
    # ------------------------------------------------------------------

    async def run_llm_loop(
        self,
        session_id: str,
        user_id: str,
        prompt: str,
        course_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        max_tool_rounds: int = 10,
    ) -> Dict[str, Any]:
        """Run the full LLM interaction loop with tool calling.

        This is the production path for AI chat. It:
        1. Loads course context from DB
        2. Builds system prompt + tool definitions
        3. Sends everything to the LLM
        4. If the LLM returns tool calls, executes them
        5. Sends tool results back to the LLM
        6. Repeats until the LLM produces a final text response

        Args:
            session_id: The active AI session.
            user_id: The authenticated user.
            prompt: The user's natural language message.
            course_id: The course being authored.
            conversation_history: Previous conversation turns for context.
            max_tool_rounds: Max number of tool-calling rounds before forcing stop.

        Returns:
            Dict with content, tool_calls, proposals, token_usage, latency_ms.
        """
        from app.services.ai.llm_client import (
            LLMClient, LLMProvider, LLMMessage, ToolDef,
        )
        from app.services.ai.tool_executor import ToolExecutor

        # 1. Load course context
        course_context = await self._load_course_context(course_id, session_id)

        # 1a. Model tier routing (G-13 fix)
        from app.services.ai.model_tier_router import ModelTierRouter
        tier_router = ModelTierRouter()
        model_tier = tier_router.classify_task(user_message=prompt)
        routed_model = tier_router.get_model_for_tier(model_tier)
        logger.debug(
            "Model tier routing: prompt → %s tier → model=%s",
            model_tier.value, routed_model,
        )

        # 1b. Cost tracker initialisation (G-12 fix)
        from app.services.ai.cost_tracker import CostTracker
        cost_tracker = CostTracker()

        # 2. Build system prompt
        system_prompt = self._build_system_prompt(course_context)

        # 3. Build tool definitions from the tool registry
        tool_defs = self._build_tool_definitions()

        # 4. Build message list
        messages: List[LLMMessage] = []

        # Add conversation history
        for hist_msg in (conversation_history or []):
            messages.append(LLMMessage(
                role=hist_msg.get("role", "user"),
                content=hist_msg.get("content", ""),
            ))

        # Add current user message
        messages.append(LLMMessage(role="user", content=prompt))

        # 4b. Prune context window (US-BKND-AI-028)
        from app.services.ai.context_manager import ContextManager
        from app.services.ai.otel_tracer import (
            AI_TRACER, set_span_status, set_span_attributes, record_span_exception,
            get_tracer,
        )
        ctx_mgr = ContextManager()
        msg_dicts = [
            {"role": m.role, "content": m.content,
             "tool_calls": m.tool_calls, "tool_results": m.tool_results}
            for m in messages
        ]
        tool_dicts = [
            {"name": td.name, "description": td.description,
             "input_schema": td.input_schema}
            for td in tool_defs
        ]

        # ── Trace: context_prune span (G-09 fix) ──────────────────
        tracer = get_tracer("ai-authoring")
        prune_span = tracer.start_span("context_prune")
        try:
            pruned_dicts, pruning_info = ctx_mgr.prune(
                msg_dicts, system_prompt=system_prompt, tool_definitions=tool_dicts,
            )
            set_span_attributes(
                prune_span,
                **{
                    "ai.context.original_tokens": pruning_info.get("original_tokens", 0),
                    "ai.context.pruned_tokens": pruning_info.get("pruned_tokens", 0),
                    "ai.context.messages_removed": pruning_info.get("messages_removed", 0),
                    "ai.context.pruning_strategy": pruning_info.get("strategy", "unknown"),
                }
            )
            set_span_status(prune_span, True)
        except Exception as exc:
            record_span_exception(prune_span, exc)
            # Don't re-raise — context pruning failure is non-fatal
            pruned_dicts = msg_dicts
            pruning_info = {
                "original_tokens": len(str(msg_dicts)),
                "pruned_tokens": len(str(msg_dicts)),
                "messages_removed": 0,
                "strategy": "none (pruning error)",
            }
        finally:
            prune_span.end()

        if pruning_info["messages_removed"] > 0:
            logger.info(
                "Context pruned: removed %d messages (%d -> %d tokens)",
                pruning_info["messages_removed"],
                pruning_info["original_tokens"],
                pruning_info["pruned_tokens"],
            )

        # Rebuild LLMMessage list from pruned dicts
        messages = [
            LLMMessage(
                role=m.get("role", "user"),
                content=m.get("content", ""),
                tool_calls=m.get("tool_calls", []),
                tool_results=m.get("tool_results", []),
            )
            for m in pruned_dicts
        ]

        # 5. Determine provider
        provider = LLMProvider.MOCK
        api_key = self.config.anthropic_api_key
        if api_key and self.config.ai_authoring_enabled:
            provider = LLMProvider.ANTHROPIC

        client = LLMClient(provider=provider, model=routed_model)
        executor = ToolExecutor(self.db)

        # ── Session tracing (US-BKND-AI-TRACE) ──────────────────────
        from app.services.ai.session_tracer import SessionTracer
        tracer = SessionTracer(self.db)
        orchestrator_span = await tracer.start_span(
            session_id=session_id,
            trace_type="orchestrator",
            operation="interaction_loop",
            input_payload={
                "prompt": prompt,
                "course_id": course_id,
                "model": client.model,
                "provider": provider.value,
                "max_tool_rounds": max_tool_rounds,
                "tool_count": len(tool_defs),
                "tool_names": [t.name for t in tool_defs],
            },
        )

        # 6. Run the interaction loop
        tool_calls_log: List[Dict[str, Any]] = []
        proposals: List[Dict[str, Any]] = []
        all_tool_uses: List[Dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0
        final_content = ""
        latency_ms = 0.0

        for round_num in range(max_tool_rounds):
            import time
            start = time.time()

            # ── Trace: LLM request ──────────────────────────────────
            llm_span = await tracer.start_span(
                session_id=session_id,
                trace_type="llm_request",
                operation="chat",
                parent_span_id=orchestrator_span["span_id"],
                trace_id=orchestrator_span["trace_id"],
                input_payload={
                    "round": round_num + 1,
                    "message_count": len(messages),
                    "system_prompt": system_prompt[:500] if system_prompt else None,
                    "tool_count": len(tool_defs),
                    "max_tokens": 4096,
                    "temperature": 0.7,
                },
                model=client.model,
                metadata={"round": round_num + 1},
            )

            response = await client.chat(
                messages=messages,
                tools=tool_defs,
                system_prompt=system_prompt,
            )
            latency_ms += response.latency_ms

            total_input_tokens += response.token_usage.get("input", 0)
            total_output_tokens += response.token_usage.get("output", 0)

            # ── CostTracker: record LLM usage (G-12 fix) ────────────
            try:
                cost_tracker.record(
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id="",  # Inferred from session context
                    model_id=client.model,
                    input_tokens=response.token_usage.get("input", 0),
                    output_tokens=response.token_usage.get("output", 0),
                    latency_ms=response.latency_ms,
                )
            except Exception:
                pass  # Cost tracking failure is non-fatal

            # ── Trace: LLM response ─────────────────────────────────
            await tracer.end_span(
                llm_span,
                output_payload={
                    "content": (response.content or "")[:1000],
                    "tool_calls": [
                        {"name": tc.get("name"), "id": tc.get("id")}
                        for tc in (response.tool_calls or [])
                    ],
                    "stop_reason": response.stop_reason,
                },
                token_usage=response.token_usage,
                latency_ms=response.latency_ms,
            )

            # If the LLM produced text content (final response), we're done
            if response.content and not response.tool_calls:
                final_content = response.content
                messages.append(LLMMessage(
                    role="assistant", content=final_content,
                ))
                break

            # If the LLM produced tool calls, execute them
            if response.tool_calls:
                tool_results = []

                for tc in response.tool_calls:
                    tool_name = tc.get("name", "")
                    tool_input = tc.get("input", {})
                    tool_call_id = tc.get("id", f"call_{tool_name}_{round_num}")

                    # ── Trace: tool call start ──────────────────────
                    tool_span = await tracer.start_span(
                        session_id=session_id,
                        trace_type="tool_call",
                        operation=tool_name,
                        parent_span_id=orchestrator_span["span_id"],
                        trace_id=orchestrator_span["trace_id"],
                        input_payload={
                            "tool_call_id": tool_call_id,
                            "params": tool_input,
                            "round": round_num + 1,
                        },
                        metadata={"round": round_num + 1},
                    )

                    # Execute the tool
                    try:
                        exec_result = await executor.execute(
                            tool_name,
                            {**tool_input, "session_id": session_id},
                            user_id,
                        )
                        output = exec_result.get("data", exec_result)
                        is_error = exec_result.get("status") == "error"

                        # ── Trace: tool result ──────────────────────
                        await tracer.end_span(
                            tool_span,
                            output_payload={
                                "result": output if not is_error else None,
                                "error": exec_result.get("message") if is_error else None,
                            },
                            status="error" if is_error else "success",
                            error_message=exec_result.get("message") if is_error else None,
                        )

                        tool_calls_log.append({
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "input": tool_input,
                            "status": "success" if not is_error else "error",
                            "output": output if not is_error else None,
                            "error": exec_result.get("message") if is_error else None,
                        })

                        # Collect proposals from propose_* tools
                        if tool_name.startswith("propose_") and not is_error:
                            proposals.append({
                                "proposal_id": output.get("proposal_id", ""),
                                "proposal_type": tool_name.replace("propose_", ""),
                                "tool_call_id": tool_call_id,
                                "status": "pending_review",
                                "validation_status": output.get("validation_status", "valid"),
                            })

                    except Exception as exc:
                        is_error = True
                        output = {"error": str(exc)}
                        # Trace failed tool execution
                        await tracer.end_span(
                            tool_span,
                            output_payload={"error": str(exc)},
                            status="error",
                            error_message=str(exc),
                        )
                        tool_calls_log.append({
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "input": tool_input,
                            "status": "error",
                            "error": str(exc),
                        })

                    tool_results.append({
                        "tool_use_id": tool_call_id,
                        "output": output,
                        "is_error": is_error,
                    })

                    all_tool_uses.append({
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "input": tool_input,
                        "output_summary": (
                            str(output)[:200] if output else ""
                        ),
                    })

                # Add assistant message with tool calls
                messages.append(LLMMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {"id": tc.get("id", ""), "name": tc.get("name", ""),
                         "input": tc.get("input", {})}
                        for tc in response.tool_calls
                    ],
                ))

                # Add tool results message
                messages.append(LLMMessage(
                    role="user",
                    content=None,
                    tool_results=tool_results,
                ))
            else:
                # No content and no tool calls — unusual, break
                final_content = "I received your request but couldn't generate a response. Could you rephrase?"
                break
        else:
            # Loop exhausted (max_tool_rounds reached)
            final_content = (
                "I've performed several actions to help with your request. "
                "Let me know if you'd like me to refine anything or make additional changes."
            )

        # ── Close orchestrator trace span ─────────────────────────
        await tracer.end_span(
            orchestrator_span,
            output_payload={
                "final_content": (final_content or "")[:500],
                "tool_calls_made": len(tool_calls_log),
                "proposals_created": len(proposals),
                "loop_rounds": round_num + 1,
            },
            token_usage={
                "input": total_input_tokens,
                "output": total_output_tokens,
            },
            latency_ms=latency_ms,
        )

        return {
            "role": "assistant",
            "content": final_content,
            "tool_calls": tool_calls_log,
            "tool_uses": all_tool_uses,
            "proposals": proposals,
            "intent": "llm_interaction",
            "token_usage": {
                "input": total_input_tokens,
                "output": total_output_tokens,
            },
            "latency_ms": latency_ms,
            "loop_rounds": round_num + 1,
        }

    # ── Real SSE Streaming (G-11 fix) ───────────────────────────

    async def process_message_stream(
        self,
        session_id: str,
        user_id: str,
        prompt: str,
        course_id: str = "",
    ):
        """Process a user message and stream the response as SSE events.

        Yields SSE-formatted strings that can be consumed by a FastAPI
        StreamingResponse. Each event is a JSON object on a `data:` line.

        Event types:
            - thinking: Agent is processing (intermediate updates)
            - tool_call: A tool is being called
            - tool_result: Result from a tool call
            - token: Content chunk (token-by-token streaming)
            - proposal: A proposal was created
            - complete: Final response complete
            - error: An error occurred
            - safety_block: Content was blocked by safety filters

        Usage in router:
            @router.post("/chat/stream")
            async def chat_stream(...):
                orchestrator = ChatOrchestrator(db)

                async def event_generator():
                    async for event in orchestrator.process_message_stream(
                        session_id, user_id, prompt, course_id
                    ):
                        yield event

                return StreamingResponse(event_generator(), media_type="text/event-stream")
        """
        import json as _json
        import time as _time

        # ── Safety: Input guard ───────────────────────────────
        from app.services.ai.safety_service import SafetyService
        safety = SafetyService(
            prompt_safety_enabled=self.config.prompt_safety_enabled,
            output_safety_enabled=self.config.output_safety_enabled,
        )
        safety_result = safety.scan_input(prompt)
        if not safety_result.allowed:
            yield (
                f"event: safety_block\n"
                f"data: {_json.dumps({'reason': 'input_blocked', 'blocks': safety_result.blocks})}\n\n"
            )
            return

        prompt = safety_result.sanitized_text or prompt

        # Emit thinking event
        yield f"event: thinking\ndata: {_json.dumps({'status': 'analysing', 'message': 'Analysing your request...'})}\n\n"

        # Determine if we use LLM or mock
        api_key = self.config.anthropic_api_key
        use_llm = api_key and self.config.ai_authoring_enabled

        if use_llm:
            # Production: call LLM with streaming
            from app.services.ai.llm_client import LLMClient, LLMProvider, LLMMessage

            course_context = await self._load_course_context(course_id, session_id)
            system_prompt = self._build_system_prompt(course_context)

            # Model tier routing
            from app.services.ai.model_tier_router import ModelTierRouter
            router = ModelTierRouter()
            tier = router.classify_task(user_message=prompt)
            model = router.get_model_for_tier(tier)

            client = LLMClient(provider=LLMProvider.ANTHROPIC, model=model)

            try:
                response = await client.chat(
                    messages=[LLMMessage(role="user", content=prompt)],
                    system_prompt=system_prompt,
                    temperature=0.7,
                    max_tokens=4096,
                )

                content = getattr(response, 'content', str(response))

                # Stream content token-by-token (simulated — Anthropic SSE in future)
                words = content.split()
                chunk_size = 5
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i:i + chunk_size]) + " "
                    yield f"event: token\ndata: {_json.dumps({'content': chunk})}\n\n"

                # Emit tool calls if any
                tool_calls = getattr(response, 'tool_calls', []) or []
                for tc in tool_calls:
                    yield (
                        f"event: tool_call\n"
                        f"data: {_json.dumps({'tool': tc.get('name', ''), 'input': tc.get('input', {})})}\n\n"
                    )

                # Record cost
                try:
                    from app.services.ai.cost_tracker import CostTracker
                    CostTracker().record(
                        session_id=session_id,
                        user_id=user_id,
                        tenant_id="",
                        model_id=model,
                        input_tokens=getattr(response, 'token_usage', {}).get('input', 0),
                        output_tokens=getattr(response, 'token_usage', {}).get('output', 0),
                        latency_ms=getattr(response, 'latency_ms', 0),
                    )
                except Exception:
                    pass

                yield (
                    f"event: complete\n"
                    f"data: {_json.dumps({'content': content, 'model': model, 'tier': tier.value})}\n\n"
                )

            except Exception as exc:
                yield f"event: error\ndata: {_json.dumps({'error': str(exc)})}\n\n"
        else:
            # Mock path: use existing intent parsing
            result = await self._process_mock(session_id, user_id, prompt, course_id, safety)

            # Simulate streaming with word chunks
            content = result.get("content", "")
            words = content.split()
            for i in range(0, len(words), 5):
                chunk = " ".join(words[i:i + 5]) + " "
                yield f"event: token\ndata: {_json.dumps({'content': chunk})}\n\n"

            # Emit proposals
            for proposal in result.get("proposals", []):
                yield (
                    f"event: proposal\n"
                    f"data: {_json.dumps({'proposal_id': proposal.get('proposal_id', ''), 'type': proposal.get('proposal_type', '')})}\n\n"
                )

            yield (
                f"event: complete\n"
                f"data: {_json.dumps({'content': content, 'model': 'mock', 'tier': 'planner'})}\n\n"
            )

    def _build_system_prompt(self, course_context: Dict[str, Any]) -> str:
        """Build the system prompt with course context information.

        The system prompt includes:
        - Role definition and capabilities
        - Current course metadata (title, page count, status)
        - Available template types
        - Key rules and constraints
        """
        course_title = course_context.get("title", "Untitled Course")
        page_count = course_context.get("page_count", 0)
        course_status = course_context.get("status", "draft")
        template_types = course_context.get("template_types", [
            "text-content", "tabs", "accordion", "click-reveal", "final-assessment",
        ])

        pages_summary = ""
        for p in course_context.get("pages", [])[:5]:
            pages_summary += (
                f"  - {p.get('title', 'Untitled')} "
                f"({p.get('template_type', 'text-content')})\n"
            )

        return (
            f"You are an AI course authoring assistant. You help instructors "
            f"create and edit e-learning courses.\n\n"
            f"CURRENT COURSE: \"{course_title}\"\n"
            f"Status: {course_status}\n"
            f"Pages: {page_count} total\n"
            f"{pages_summary}\n"
            f"Available template types: {', '.join(template_types)}\n\n"
            f"IMPORTANT RULES:\n"
            f"1. NEVER mutate data directly — always create proposals first\n"
            f"2. Always validate before proposing — use the validate tool\n"
            f"3. Always fetch current state — never trust conversation history\n"
            f"4. For destructive actions — always require explicit user confirmation\n"
            f"5. Stay within the session's course scope — do not access other courses\n"
            f"6. The `query_similar_courses` tool returns example courses for tone and\n"
            f"   structural reference ONLY. Do NOT derive API contracts, validation\n"
            f"   rules, template schemas, or configuration values from these results.\n"
            f"   Always rely on the tool definitions, template contracts, and schemas\n"
            f"   provided in your system prompt for authoritative specifications.\n"
            f"7. If `query_similar_courses` returns empty results, continue generation\n"
            f"   without examples. Quality may be slightly lower but should not block\n"
            f"   progress.\n"
            f"8. Reference pages by their title or position, not by internal IDs\n"
        )

    async def _load_course_context(
        self, course_id: str, session_id: str,
    ) -> Dict[str, Any]:
        """Load current course state from the database for the system prompt."""
        try:
            from app.repositories.ai_session_repo import AISessionRepository

            session_repo = AISessionRepository(self.db)
            session = await session_repo.get(session_id)
            if session is None:
                return {"title": "Unknown", "page_count": 0, "pages": [], "status": "draft"}

            # Try to load pages
            try:
                from app.repositories.page_component_repo import PageRepository
                page_repo = PageRepository(self.db)
                if course_id:
                    pages = await page_repo.list_by_course(course_id)
                else:
                    pages = await page_repo.list_by_course(session.course_id) if session else []
            except Exception:
                pages = []

            return {
                "title": getattr(session, "course_id", "Unknown Course"),
                "page_count": len(pages),
                "pages": [
                    {
                        "title": getattr(p, "title", "Untitled"),
                        "template_type": (
                            p.layout.get("templateType", "text-content")
                            if hasattr(p, "layout") and isinstance(p.layout, dict)
                            else "text-content"
                        ),
                        "page_id": getattr(p, "page_id", ""),
                    }
                    for p in pages
                ],
                "status": "draft",
                "template_types": [
                    "text-content", "tabs", "accordion",
                    "click-reveal", "final-assessment",
                ],
            }
        except Exception:
            logger.exception("Failed to load course context")
            return {"title": "Unknown", "page_count": 0, "pages": [], "status": "draft"}

    def _build_tool_definitions(self) -> list:
        """Build tool definitions from the tool registry for the LLM.

        Returns a list of ToolDef with JSON Schema input definitions.
        These tell the LLM what tools are available and how to call them.
        """
        from app.services.ai.llm_client import ToolDef

        return [
            ToolDef(
                name="list_pages",
                description="List all pages in the current course with titles and types.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "AI session ID"},
                    },
                    "required": ["session_id"],
                },
            ),
            ToolDef(
                name="fetch_page",
                description="Fetch the full content and components of a specific page by its page_id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "AI session ID"},
                        "page_id": {"type": "string", "description": "The page ID to fetch"},
                    },
                    "required": ["session_id", "page_id"],
                },
            ),
            ToolDef(
                name="query_similar_courses",
                description=(
                    "Search for similar courses within your organization to use as "
                    "examples for tone, structure, and pedagogical patterns. Results "
                    "are NOT authoritative for API contracts, validation rules, or "
                    "schema definitions."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Active AI session ID",
                        },
                        "query": {
                            "type": "string",
                            "description": "Natural language query describing the desired course style, topic, or structure",
                        },
                        "max_results": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                        "filters": {
                            "type": "object",
                            "properties": {
                                "template_types": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "min_pages": {"type": "integer"},
                                "max_pages": {"type": "integer"},
                                "language": {"type": "string"},
                            },
                        },
                    },
                    "required": ["session_id", "query"],
                },
            ),
            ToolDef(
                name="propose_create_page",
                description=(
                    "Propose creating a new page. This does NOT immediately create the page "
                    "— it creates a proposal for the user to review and apply."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "AI session ID"},
                        "title": {"type": "string", "description": "Page title"},
                        "template_type": {
                            "type": "string",
                            "enum": ["text-content", "tabs", "accordion",
                                     "click-reveal", "final-assessment"],
                            "description": "Template type for the page",
                        },
                        "content": {"type": "string", "description": "Page content as JSON"},
                    },
                    "required": ["session_id", "title", "template_type"],
                },
            ),
            ToolDef(
                name="propose_update_page",
                description=(
                    "Propose updating an existing page. Creates a proposal for the user "
                    "to review before applying."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "AI session ID"},
                        "page_id": {"type": "string", "description": "Page ID to update"},
                        "title": {"type": "string", "description": "New title"},
                        "content": {"type": "string", "description": "Updated content as JSON"},
                    },
                    "required": ["session_id", "page_id"],
                },
            ),
            ToolDef(
                name="propose_delete_page",
                description=(
                    "Propose deleting a page. This is a destructive operation that "
                    "requires explicit user confirmation with a confirmation token."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "AI session ID"},
                        "page_id": {"type": "string", "description": "Page ID to delete"},
                    },
                    "required": ["session_id", "page_id"],
                },
            ),
            ToolDef(
                name="validate_course",
                description="Validate the entire course for schema, business rules, and accessibility compliance.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "AI session ID"},
                        "scope": {
                            "type": "string",
                            "enum": ["schema", "business", "accessibility", "export", "full"],
                            "description": "Validation scope",
                        },
                    },
                    "required": ["session_id"],
                },
            ),
        ]

    @staticmethod
    def _extract_create_params(prompt: str) -> tuple:
        """Extract title, template type, and data from a create intent."""
        title = "New Page"
        ttype = "text-content"
        data = {"content": "Sample content"}

        p = prompt.lower()
        # Try to extract title
        for marker in ["called ", "named ", "titled ", "title "]:
            if marker in p:
                idx = p.find(marker) + len(marker)
                rest = p[idx:].strip().strip('"\'').split(".")[0].split(",")[0]
                if rest:
                    title = rest.strip().title()

        # Detect template type
        if any(w in p for w in ["assessment", "quiz", "test"]):
            ttype = "final-assessment"
            data = {"passing_score": 80, "questions": []}
        elif any(w in p for w in ["tabs", "compare"]):
            ttype = "tabs"
            data = {"tabs": [{"title": "Tab 1", "content": "..."}]}
        elif any(w in p for w in ["accordion", "faq"]):
            ttype = "accordion"
            data = {"items": [{"title": "Item 1", "content": "..."}]}

        return title, ttype, data

    @staticmethod
    def _build_response(
        prompt: str, intent: Dict[str, Any],
        tool_calls: List[Dict], proposals: List[Dict],
    ) -> str:
        """Build a natural-language response based on intent and results."""
        intent_name = intent.get("intent", "help")

        if intent_name == "list_pages":
            pages_data = tool_calls[0].get("result", {}).get("pages", []) if tool_calls else []
            count = len(pages_data)
            if count == 0:
                return "This course has no pages yet. Would you like me to create one?"
            page_list = "\n".join(
                f"• {p.get('title', 'Untitled')} ({p.get('template_type', 'text-content')})"
                for p in pages_data[:10]
            )
            return f"I found {count} page(s) in this course:\n\n{page_list}\n\nWhat would you like to do with them?"

        if intent_name == "create_page":
            if proposals:
                p = proposals[0]
                return (
                    f"I've created a proposal for a new page: **{p.get('diff', {}).get('after', {}).get('title', 'New Page')}**.\n\n"
                    f"Validation status: {p.get('validation_status', 'valid')}.\n"
                    f"Please review and apply it when ready."
                )
            return "I wasn't able to create that page. Could you provide more details?"

        if intent_name == "update_page":
            if proposals:
                return "I've proposed an update to the page. Please review the changes and apply them when ready."
            return "I couldn't find a page to update. Which page would you like me to modify?"

        if intent_name == "delete_page":
            if proposals:
                return "I've created a delete proposal. ⚠️ This is a destructive action — please confirm before applying."
            return "I couldn't find a page to delete. Which page would you like to remove?"

        if intent_name == "validate_course":
            if tool_calls:
                result = tool_calls[0].get("result", {})
                errors = result.get("errors", [])
                if errors:
                    return f"Validation found {len(errors)} issue(s). The course needs attention before export."
                return "Course validation passed! All pages are well-formed."

        if intent_name == "help":
            return (
                "I'm your AI course authoring assistant! Here's what I can help with:\n\n"
                "• **List pages** — \"Show me all pages in this course\"\n"
                "• **Create pages** — \"Add a new welcome page\"\n"
                "• **Edit content** — \"Simplify the intro on page 2\"\n"
                "• **Validate** — \"Check my course for issues\"\n"
                "• **Find examples** — \"Show me similar courses\"\n\n"
                "What would you like to do?"
            )

        return f"I processed your request: \"{prompt[:100]}\". How can I help further?"
