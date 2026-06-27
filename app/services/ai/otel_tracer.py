"""OpenTelemetry integration for AI Authoring — Phase 0.3.

Replaces custom X-Trace-ID propagation with W3C Trace Context (OpenTelemetry).
Provides AI-specific tracer and span helpers for agent calls, LLM calls,
tool calls, and DB operations.

Usage:
    from app.services.ai.otel_tracer import AI_TRACER, trace_agent_call

    # Automatic span context
    with AI_TRACER.start_as_current_span("agent.planner") as span:
        span.set_attribute("ai.phase", "plan")
        # ... agent logic ...

    # Manual span management
    span = await trace_agent_call("planner", "plan", {"query": "..."})
    # ... work ...
    span.end()

Graceful degradation: if OTel is not enabled (OTEL_ENABLED != true),
all operations are no-ops — no code changes needed.

Architecture:
    - Keep existing AITelemetryMiddleware as fallback for 2 weeks
    - Run both OTel and custom telemetry in parallel
    - Validate trace equivalence, then deprecate custom middleware
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger("ai_authoring")

# ── Lazy OTel imports (graceful when not installed) ────────────────

_otel_available = False
_trace: Any = None
_Tracer: Any = None
_SpanKind: Any = None
_StatusCode: Any = None

try:
    from opentelemetry import trace as _trace
    from opentelemetry.trace import Tracer, SpanKind, StatusCode, Span
    _otel_available = True
except ImportError:
    # OpenTelemetry SDK not installed — all operations are no-ops
    pass


# ── Tracer instance ─────────────────────────────────────────────────

class _NoOpSpan:
    """No-op span that silently ignores all calls."""
    def set_attribute(self, *args, **kwargs): return None
    def set_attributes(self, *args, **kwargs): return None
    def add_event(self, *args, **kwargs): return None
    def set_status(self, *args, **kwargs): return None
    def record_exception(self, *args, **kwargs): return None
    def end(self, *args, **kwargs): return None
    def get_span_context(self): return None
    def is_recording(self): return False

class _NoOpTracer:
    """No-op tracer that returns no-op spans."""
    def start_as_current_span(self, *args, **kwargs):
        return _NoOpContextManager()
    def start_span(self, *args, **kwargs):
        return _NoOpSpan()

@contextmanager
def _NoOpContextManager():
    yield _NoOpSpan()

def _create_noop_context_manager():
    return _NoOpContextManager()

def get_tracer(name: str = "ai-authoring") -> Any:
    """Get the AI authoring tracer, or a no-op if OTel is disabled."""
    if not _otel_available or not os.getenv("OTEL_ENABLED", "").lower() == "true":
        return _NoOpTracer()
    return _trace.get_tracer(name)


AI_TRACER = get_tracer("ai-authoring")


# ── Span helpers ─────────────────────────────────────────────────────

def trace_agent_call(
    agent_name: str,
    phase: str,
    input_data: Optional[Dict[str, Any]] = None,
    parent_span: Any = None,
) -> Any:
    """Create a span for an agent invocation.

    Args:
        agent_name: e.g., "planner", "template_selector", "content_generator"
        phase: Workflow phase, e.g., "plan", "select_templates", "generate_content"
        input_data: Optional structured input for trace context
        parent_span: Optional parent span context

    Returns:
        An OTel Span (or no-op span if OTel disabled).
        Caller is responsible for calling span.end().
    """
    ctx = None
    if parent_span is not None and hasattr(parent_span, 'get_span_context'):
        from opentelemetry.trace import set_span_in_context
        ctx = set_span_in_context(parent_span)

    tracer = get_tracer("ai-authoring")
    span = tracer.start_span(
        f"agent.{agent_name}",
        attributes={
            "agent.name": agent_name,
            "agent.phase": phase,
            "ai.input.type": input_data.get("type", "unknown") if input_data else "unknown",
        },
        context=ctx,
        kind=_SpanKind.INTERNAL if _otel_available else None,
    )

    if input_data and _otel_available:
        # Set key input attributes (truncated for trace size)
        for k, v in input_data.items():
            if isinstance(v, (str, int, float, bool)):
                span.set_attribute(f"ai.input.{k}", v)

    return span


def trace_llm_call(
    model: str,
    provider: str,
    operation: str = "chat",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    parent_span: Any = None,
) -> Any:
    """Create a span for an LLM API call."""
    ctx = None
    if parent_span is not None and hasattr(parent_span, 'get_span_context'):
        from opentelemetry.trace import set_span_in_context
        ctx = set_span_in_context(parent_span)

    tracer = get_tracer("ai-authoring")
    span = tracer.start_span(
        f"llm.{operation}",
        attributes={
            "llm.model": model,
            "llm.provider": provider,
            "llm.temperature": temperature,
            "llm.max_tokens": max_tokens,
            "llm.operation": operation,
        },
        context=ctx,
        kind=_SpanKind.CLIENT if _otel_available else None,
    )
    return span


def trace_tool_call(
    tool_name: str,
    tool_input: Optional[Dict[str, Any]] = None,
    parent_span: Any = None,
) -> Any:
    """Create a span for a tool execution."""
    ctx = None
    if parent_span is not None and hasattr(parent_span, 'get_span_context'):
        from opentelemetry.trace import set_span_in_context
        ctx = set_span_in_context(parent_span)

    tracer = get_tracer("ai-authoring")
    span = tracer.start_span(
        f"tool.{tool_name}",
        attributes={
            "tool.name": tool_name,
            "tool.input.keys": ",".join(sorted(tool_input.keys())) if tool_input else "",
        },
        context=ctx,
        kind=_SpanKind.INTERNAL if _otel_available else None,
    )
    return span


def trace_db_operation(
    operation: str,
    table: str = "",
    parent_span: Any = None,
) -> Any:
    """Create a span for a database operation."""
    ctx = None
    if parent_span is not None and hasattr(parent_span, 'get_span_context'):
        from opentelemetry.trace import set_span_in_context
        ctx = set_span_in_context(parent_span)

    tracer = get_tracer("ai-authoring")
    span = tracer.start_span(
        f"db.{operation}",
        attributes={
            "db.operation": operation,
            "db.table": table,
            "db.system": "postgresql",
        },
        context=ctx,
        kind=_SpanKind.CLIENT if _otel_available else None,
    )
    return span


# ── Span attribute helpers ──────────────────────────────────────────

def set_span_attributes(span: Any, **attrs) -> None:
    """Set multiple attributes on a span at once."""
    if span is None or isinstance(span, _NoOpSpan):
        return
    for k, v in attrs.items():
        if v is not None and isinstance(v, (str, int, float, bool)):
            span.set_attribute(k, v)


def set_span_status(span: Any, success: bool, message: str = "") -> None:
    """Set span status — success or error."""
    if span is None or isinstance(span, _NoOpSpan) or not _otel_available:
        return
    if success:
        span.set_status(StatusCode.OK)
    else:
        span.set_status(StatusCode.ERROR, message)


def record_span_exception(span: Any, exc: Exception) -> None:
    """Record an exception on a span."""
    if span is None or isinstance(span, _NoOpSpan):
        return
    span.record_exception(exc)
    if _otel_available:
        span.set_status(StatusCode.ERROR, str(exc))


# ── OTel SDK initialisation (called from app/main.py) ─────────────────

def init_otel(app: Any) -> bool:
    """Initialise OpenTelemetry SDK with OTLP exporter.

    Configures:
        - TracerProvider with BatchSpanProcessor
        - OTLP gRPC exporter (configurable endpoint)
        - FastAPI auto-instrumentation
        - SQLAlchemy auto-instrumentation
        - Redis auto-instrumentation

    Returns:
        True if OTel was successfully initialised, False otherwise.
    """
    if not os.getenv("OTEL_ENABLED", "").lower() == "true":
        logger.info("OpenTelemetry DISABLED (OTEL_ENABLED != true)")
        return False

    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME

        otel_endpoint = os.getenv(
            "OTEL_EXPORTER_ENDPOINT", "http://localhost:4317"
        )
        otel_protocol = os.getenv("OTEL_EXPORTER_PROTOCOL", "grpc")

        resource = Resource.create({
            SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "elearning-backend"),
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })

        provider = TracerProvider(resource=resource)

        if otel_protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=otel_endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            exporter = OTLPSpanExporter(endpoint=otel_endpoint)

        provider.add_span_processor(BatchSpanProcessor(exporter))
        _trace.set_tracer_provider(provider)

        # ── Auto-instrumentation ─────────────────────────────────
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
            logger.info("OTel: FastAPI instrumented")
        except ImportError:
            logger.info("OTel: FastAPI instrumentation skipped (not installed)")

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
            SQLAlchemyInstrumentor().instrument()
            logger.info("OTel: SQLAlchemy instrumented")
        except ImportError:
            logger.info("OTel: SQLAlchemy instrumentation skipped (not installed)")

        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor
            RedisInstrumentor().instrument()
            logger.info("OTel: Redis instrumented")
        except ImportError:
            logger.info("OTel: Redis instrumentation skipped (not installed)")

        global _otel_available
        _otel_available = True

        logger.info(
            "OpenTelemetry INITIALISED (endpoint=%s, protocol=%s, service=%s)",
            otel_endpoint, otel_protocol,
            os.getenv("OTEL_SERVICE_NAME", "elearning-backend"),
        )
        return True

    except ImportError as exc:
        logger.warning(
            "OpenTelemetry SDK not installed (%s). "
            "Run: pip install opentelemetry-sdk opentelemetry-exporter-otlp",
            exc,
        )
        return False
    except Exception as exc:
        logger.exception("OpenTelemetry initialisation failed: %s", exc)
        return False
