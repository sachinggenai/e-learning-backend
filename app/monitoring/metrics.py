"""Prometheus metrics for AI Authoring — Phase 0.4.

Provides RED (Rate, Errors, Duration) metrics for:
    - Course generation jobs
    - Per-page generation timing
    - LLM API calls
    - Token consumption
    - Cost tracking

Exposed via GET /metrics endpoint in app/main.py.

Graceful degradation: if prometheus_client is not installed, all metrics
are no-ops (counters/histograms silently discard values).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("ai_authoring")

try:
    from prometheus_client import (
        Counter as _PCounter,
        Histogram as _PHistogram,
        Gauge as _PGauge,
        Info as _PInfo,
        generate_latest,
        REGISTRY,
        CollectorRegistry,
    )
    _prometheus_available = True
except ImportError:
    _prometheus_available = False
    _PCounter = None  # type: ignore
    _PHistogram = None  # type: ignore
    _PGauge = None  # type: ignore
    _PInfo = None  # type: ignore
    generate_latest = None  # type: ignore
    REGISTRY = None  # type: ignore
    logger.info("prometheus_client not installed — metrics disabled")


# ── No-op stubs for when prometheus_client is unavailable ──────────

class _NoOpMetric:
    """Metric stub that silently discards all observations."""
    Counter = None
    Histogram = None
    Gauge = None
    Info = None
    def labels(self, **kwargs): return self
    def inc(self, amount=1): pass
    def observe(self, amount): pass
    def set(self, value): pass
    def info(self, info_dict): pass

def _make_metric(metric_type, name: str, description: str, labelnames=None, **kwargs):
    """Create a real metric or a no-op stub depending on availability."""
    if not _prometheus_available or metric_type is None:
        return _NoOpMetric()
    try:
        if labelnames:
            return metric_type(name, description, labelnames=labelnames, **kwargs)
        return metric_type(name, description, **kwargs)
    except ValueError as exc:
        logger.warning("Metric '%s' already registered: %s", name, exc)
        return _NoOpMetric()


# ── Course Generation Metrics ────────────────────────────────────────

ai_course_generations_total = _make_metric(
    _PCounter,
    "ai_course_generations_total",
    "Total course generation jobs",
    labelnames=["status"],  # "started", "success", "failed", "cancelled"
)

ai_course_generation_duration_seconds = _make_metric(
    _PHistogram,
    "ai_course_generation_duration_seconds",
    "End-to-end course generation duration",
    labelnames=["workflow_type"],  # "sequential", "parallel"
    buckets=[5, 10, 30, 60, 120, 300, 600, 900, 1800],
)

ai_page_generation_duration_seconds = _make_metric(
    _PHistogram,
    "ai_page_generation_duration_seconds",
    "Per-page content generation duration",
    labelnames=["template_type"],  # "content-text", "tabs", "accordion", "click-reveal", "final-assessment"
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120],
)

ai_pages_generated_total = _make_metric(
    _PCounter,
    "ai_pages_generated_total",
    "Total pages generated",
    labelnames=["status"],  # "success", "fallback", "error"
)

# ── LLM Call Metrics ─────────────────────────────────────────────────

ai_llm_calls_total = _make_metric(
    _PCounter,
    "ai_llm_calls_total",
    "Total LLM API calls",
    labelnames=["model", "tier", "status"],
)

ai_llm_call_duration_seconds = _make_metric(
    _PHistogram,
    "ai_llm_call_duration_seconds",
    "LLM API call duration",
    labelnames=["model", "operation"],  # operation="chat", "embedding"
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

# ── Token & Cost Metrics ─────────────────────────────────────────────

ai_tokens_total = _make_metric(
    _PCounter,
    "ai_tokens_total",
    "Total tokens consumed",
    labelnames=["model", "direction"],  # direction="input", "output"
)

ai_cost_usd_total = _make_metric(
    _PCounter,
    "ai_cost_usd_total",
    "Total USD cost of AI operations",
    labelnames=["model", "operation"],
)

ai_active_cost_budget_remaining = _make_metric(
    _PGauge,
    "ai_active_cost_budget_remaining",
    "Remaining USD budget for the current billing period",
    labelnames=["tenant"],
)

# ── Agent Metrics ────────────────────────────────────────────────────

ai_agent_calls_total = _make_metric(
    _PCounter,
    "ai_agent_calls_total",
    "Total agent invocations",
    labelnames=["agent", "phase", "status"],
)

ai_agent_duration_seconds = _make_metric(
    _PHistogram,
    "ai_agent_duration_seconds",
    "Agent execution duration",
    labelnames=["agent", "phase"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

# ── Safety Metrics ───────────────────────────────────────────────────

ai_safety_blocks_total = _make_metric(
    _PCounter,
    "ai_safety_blocks_total",
    "Total safety guard blocks",
    labelnames=["layer", "pattern"],
)

ai_pii_redactions_total = _make_metric(
    _PCounter,
    "ai_pii_redactions_total",
    "Total PII redactions",
    labelnames=["pii_type"],
)

# ── Rate Limiting Metrics ────────────────────────────────────────────

ai_rate_limit_hits_total = _make_metric(
    _PCounter,
    "ai_rate_limit_hits_total",
    "Total rate limit rejections",
    labelnames=["tier", "user_id"],
)

# ── MCP Server Metrics ───────────────────────────────────────────────

ai_mcp_calls_total = _make_metric(
    _PCounter,
    "ai_mcp_calls_total",
    "Total MCP tool calls",
    labelnames=["server", "tool", "status"],
)

ai_mcp_call_duration_seconds = _make_metric(
    _PHistogram,
    "ai_mcp_call_duration_seconds",
    "MCP call duration",
    labelnames=["server", "tool"],
    buckets=[0.05, 0.1, 0.5, 1, 2, 5, 10, 30],
)

# ── Application Info ─────────────────────────────────────────────────

ai_info = _make_metric(
    _PInfo,
    "ai_authoring",
    "AI Authoring subsystem information",
)


def set_ai_info(status: str, primary_model: str, environment: str):
    """Set AI subsystem info metric."""
    if _prometheus_available and not isinstance(ai_info, _NoOpMetric):
        ai_info.info({
            "status": status,
            "primary_model": primary_model,
            "environment": environment,
            "version": os.getenv("APP_VERSION", "1.0.0"),
        })


# ── Metrics endpoint helper ──────────────────────────────────────────

def get_metrics_response() -> str:
    """Return Prometheus text format metrics. Safe to call when disabled."""
    if not _prometheus_available:
        return (
            "# Prometheus metrics disabled\n"
            "# Install prometheus_client to enable\n"
        )
    return generate_latest(REGISTRY)


def is_available() -> bool:
    """Check if Prometheus metrics are available."""
    return _prometheus_available
