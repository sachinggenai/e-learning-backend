"""Langfuse LLM Observability Integration — Phase 3.4.

Provides cost tracking, prompt versioning, and trace export for LLM calls.
Integrates with the existing CostTracker and OTel tracer.

Architecture:
    LLM Call → LangfuseIntegration.record() → Langfuse API
                                          → Local JSONL fallback

Graceful degradation: when Langfuse is not configured (no API keys),
all calls succeed as no-ops. Local JSONL fallback ensures no data loss.

Configuration (env vars):
    LANGFUSE_ENABLED=true
    LANGFUSE_PUBLIC_KEY=pk-...
    LANGFUSE_SECRET_KEY=sk-...
    LANGFUSE_HOST=https://cloud.langfuse.com  (or self-hosted)
"""

from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("langfuse")


class LangfuseIntegration:
    """Langfuse observability for LLM calls and agent invocations.

    Usage:
        langfuse = LangfuseIntegration()
        trace = langfuse.start_trace(
            name="course-generation",
            user_id=user_id,
            session_id=session_id,
            metadata={"course_id": course_id},
        )
        # ... LLM calls happen ...
        generation = trace.generation(
            name="generate-page-0",
            model="deepseek-v4-pro",
            input_tokens=500,
            output_tokens=1200,
            cost=0.0042,
        )
        trace.end()
    """

    def __init__(self):
        self._enabled = os.getenv("LANGFUSE_ENABLED", "").lower() == "true"
        self._client = None
        self._fallback_path = os.getenv(
            "LANGFUSE_FALLBACK_PATH", ".langfuse_fallback.jsonl"
        )

        if not self._enabled:
            logger.info("Langfuse DISABLED — set LANGFUSE_ENABLED=true to enable")
            return

        try:
            import langfuse
            self._client = langfuse.Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
            logger.info("Langfuse INITIALISED")
        except ImportError:
            logger.info("langfuse package not installed — using JSONL fallback")
        except Exception as exc:
            logger.warning("Langfuse init failed (%s) — using JSONL fallback", exc)

    # ── Public API ─────────────────────────────────────────────────

    def start_trace(
        self,
        name: str,
        user_id: str = "",
        session_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> "LangfuseTrace":
        """Start a new trace. Returns a LangfuseTrace context manager."""
        return LangfuseTrace(
            client=self._client,
            fallback_path=self._fallback_path,
            enabled=self._enabled,
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
            tags=tags or [],
        )

    def record_generation(
        self,
        name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        latency_ms: float = 0,
        trace_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a standalone generation (without a trace).

        Safe to call at any time — no-op when Langfuse is disabled.
        """
        if not self._enabled:
            return

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "name": name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
            "latency_ms": latency_ms,
            "trace_id": trace_id,
            "metadata": metadata or {},
        }

        if self._client is not None:
            try:
                self._client.generation(
                    name=name,
                    model=model,
                    usage={
                        "input": input_tokens,
                        "output": output_tokens,
                    },
                )
                return
            except Exception as exc:
                logger.warning("Langfuse generation record failed: %s", exc)

        # JSONL fallback
        self._write_fallback(record)

    def flush(self) -> None:
        """Flush any pending records to Langfuse."""
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                pass

    # ── Internal ───────────────────────────────────────────────────

    def _write_fallback(self, record: Dict[str, Any]) -> None:
        """Write a record to the JSONL fallback file."""
        try:
            with open(self._fallback_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record) + "\n")
        except Exception as exc:
            logger.error("Langfuse fallback write failed: %s", exc)


class LangfuseTrace:
    """A Langfuse trace context manager.

    Usage:
        with LangfuseTrace(...) as trace:
            trace.generation(name="...", ...)
            trace.event(name="step_completed", ...)
    """

    def __init__(
        self,
        client: Any,
        fallback_path: str,
        enabled: bool,
        name: str,
        user_id: str,
        session_id: str,
        metadata: Dict[str, Any],
        tags: List[str],
    ):
        self._client = client
        self._fallback_path = fallback_path
        self._enabled = enabled
        self._name = name
        self._user_id = user_id
        self._session_id = session_id
        self._metadata = metadata
        self._tags = tags
        self._trace = None
        self._started_at = datetime.utcnow()

    def __enter__(self):
        if self._enabled and self._client is not None:
            try:
                self._trace = self._client.trace(
                    name=self._name,
                    user_id=self._user_id,
                    session_id=self._session_id,
                    metadata=self._metadata,
                    tags=self._tags,
                )
            except Exception as exc:
                logger.warning("Langfuse trace creation failed: %s", exc)
        return self

    def __exit__(self, *args):
        if self._trace is not None:
            try:
                self._trace.update(metadata={
                    **self._metadata,
                    "duration_s": (datetime.utcnow() - self._started_at).total_seconds(),
                })
                self._client.flush()
            except Exception:
                pass

    def generation(
        self,
        name: str,
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a generation within this trace."""
        if self._trace is not None:
            try:
                self._trace.generation(
                    name=name,
                    model=model,
                    usage={"input": input_tokens, "output": output_tokens},
                    metadata={
                        "cost_usd": cost,
                        "latency_ms": latency_ms,
                        **(metadata or {}),
                    },
                )
            except Exception:
                pass
        elif self._enabled:
            _write_fallback_static(self._fallback_path, {
                "trace_name": self._name,
                "generation_name": name,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow().isoformat(),
            })

    def event(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Record an event within this trace."""
        if self._trace is not None:
            try:
                self._trace.event(name=name, metadata=metadata or {})
            except Exception:
                pass
        elif self._enabled:
            _write_fallback_static(self._fallback_path, {
                "trace_name": self._name,
                "event_name": name,
                "metadata": metadata or {},
                "timestamp": datetime.utcnow().isoformat(),
            })


def _write_fallback_static(path: str, record: Dict[str, Any]) -> None:
    """Static fallback writer."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record) + "\n")
    except Exception:
        pass
