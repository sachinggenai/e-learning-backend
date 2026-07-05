"""Generation quality metrics — TRD-CGQ Phase 1 (R6).

Per-generation quality telemetry emitted as structured logs and available
for OTEL metrics / Grafana dashboards. Tracks template diversity, mock
fallback rate, assessment quality, and section extraction quality.

Alert thresholds are config-driven via AIConfig.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GenerationQualityMetrics:
    """Per-generation quality telemetry.

    Emitted after each course generation completes. All fields are
    observable via structured logging and available for dashboarding.

    Alert thresholds (from AIConfig / env):
      - TEMPLATE_ENTROPY_ALERT = 0.3   (below this → mostly one template type)
      - MOCK_FALLBACK_ALERT_RATE = 0.3  (above 30% → check LLM health)
      - ASSESSMENT_MIN_QUESTIONS = 3    (below this → assessment degraded)
    """

    job_id: str = ""
    course_id: str = ""

    # ── Template diversity ─────────────────────────────────────────
    template_distribution: Dict[str, int] = field(default_factory=dict)
    template_entropy: float = 0.0               # Shannon entropy (>0 = diverse)
    total_pages: int = 0

    # ── Generation quality ─────────────────────────────────────────
    mock_fallback_count: int = 0                # Pages using mock fallback
    mock_fallback_rate: float = 0.0             # fallback_count / total_pages
    assessment_question_count: int = 0          # MCQs generated
    multi_component_page_count: int = 0         # Pages with ≥2 components

    # ── Section extraction quality ─────────────────────────────────
    section_extraction_quality: float = 0.0     # distinct_previews / total_sections
    total_sections: int = 0
    distinct_preview_count: int = 0

    # ── Provider provenance ────────────────────────────────────────
    llm_model_used: str = "mock"
    provider: str = "mock"
    total_duration_ms: int = 0

    # ── Warnings ───────────────────────────────────────────────────
    alerts: List[str] = field(default_factory=list)

    # ── Computed properties ────────────────────────────────────────

    @property
    def has_low_template_diversity(self) -> bool:
        """True if template entropy is below alert threshold."""
        return self.template_entropy < 0.3 and self.total_pages > 3

    @property
    def has_high_mock_fallback(self) -> bool:
        """True if mock fallback rate exceeds 30%."""
        return self.mock_fallback_rate > 0.3 and self.total_pages > 0

    @property
    def has_degraded_assessment(self) -> bool:
        """True if assessment has fewer than 3 questions."""
        return self.assessment_question_count < 3 and "final-assessment" in self.template_distribution

    @property
    def is_healthy(self) -> bool:
        """True if no alerts are firing."""
        return len(self.alerts) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for structured logging / API response."""
        return {
            "job_id": self.job_id,
            "course_id": self.course_id,
            "template_distribution": self.template_distribution,
            "template_entropy": round(self.template_entropy, 4),
            "total_pages": self.total_pages,
            "mock_fallback_count": self.mock_fallback_count,
            "mock_fallback_rate": round(self.mock_fallback_rate, 4),
            "assessment_question_count": self.assessment_question_count,
            "multi_component_page_count": self.multi_component_page_count,
            "section_extraction_quality": round(self.section_extraction_quality, 4),
            "total_sections": self.total_sections,
            "distinct_preview_count": self.distinct_preview_count,
            "llm_model_used": self.llm_model_used,
            "provider": self.provider,
            "total_duration_ms": self.total_duration_ms,
            "alerts": self.alerts,
            "healthy": self.is_healthy,
        }


# ═══════════════════════════════════════════════════════════════════════
# Metric Collectors
# ═══════════════════════════════════════════════════════════════════════


def compute_template_entropy(distribution: Dict[str, int]) -> float:
    """Compute Shannon entropy of template distribution.

    Entropy = -Σ p(x) * log2(p(x))
    0.0 = all one type, higher = more diverse.

    Args:
        distribution: Dict mapping template_type → count.
    """
    total = sum(distribution.values())
    if total == 0:
        return 0.0

    entropy = 0.0
    for count in distribution.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    return entropy


def compute_distinct_preview_ratio(sections: List[Dict[str, Any]]) -> float:
    """Compute the ratio of distinct content previews to total sections.

    Low ratio (< 0.5) indicates garbled extraction — multiple sections
    showing identical preview text.

    Args:
        sections: List of section dicts with "content_preview" keys.
    """
    if not sections:
        return 0.0

    previews = [
        s.get("content_preview", "")[:200]
        for s in sections
        if isinstance(s, dict)
    ]
    distinct = len(set(p.strip() for p in previews if p.strip()))
    total = len(previews)

    return distinct / max(total, 1)


def collect_generation_metrics(
    job_id: str,
    course_id: str,
    pages: List[Dict[str, Any]],
    sections: Optional[List[Dict[str, Any]]] = None,
    model_used: str = "mock",
    provider: str = "mock",
    duration_ms: int = 0,
) -> GenerationQualityMetrics:
    """Collect quality metrics from a completed course generation.

    Args:
        job_id: The ingestion job ID.
        course_id: The target course ID.
        pages: List of generated page dicts.
        sections: Original extracted sections (for extraction quality).
        model_used: Actual LLM model used for generation.
        provider: Actual provider used.
        duration_ms: Total pipeline duration.

    Returns:
        Populated GenerationQualityMetrics.
    """
    # Template distribution
    distribution: Dict[str, int] = {}
    for page in pages:
        ttype = page.get("template_type", "content-text")
        distribution[ttype] = distribution.get(ttype, 0) + 1

    # Template entropy
    entropy = compute_template_entropy(distribution)

    # Mock fallback count
    mock_count = sum(
        1 for p in pages
        if p.get("generation_metadata", {}).get("method") == "mock"
        or p.get("generation_metadata", {}).get("fallback") is True
    )

    # Assessment questions
    assessment_q_count = 0
    for page in pages:
        for comp in page.get("components", []):
            if comp.get("component_type") == "final-assessment":
                assessment_q_count += len(
                    comp.get("data", {}).get("questions", [])
                )

    # Multi-component pages
    multi_comp = sum(
        1 for p in pages
        if len(p.get("components", [])) >= 2
    )

    # Section extraction quality
    extraction_quality = 0.0
    distinct_count = 0
    if sections:
        extraction_quality = compute_distinct_preview_ratio(sections)
        previews = [
            s.get("content_preview", "")[:200]
            for s in sections if isinstance(s, dict)
        ]
        distinct_count = len(set(p.strip() for p in previews if p.strip()))

    metrics = GenerationQualityMetrics(
        job_id=job_id,
        course_id=course_id,
        template_distribution=distribution,
        template_entropy=entropy,
        total_pages=len(pages),
        mock_fallback_count=mock_count,
        mock_fallback_rate=mock_count / max(len(pages), 1),
        assessment_question_count=assessment_q_count,
        multi_component_page_count=multi_comp,
        section_extraction_quality=extraction_quality,
        total_sections=len(sections) if sections else 0,
        distinct_preview_count=distinct_count,
        llm_model_used=model_used,
        provider=provider,
        total_duration_ms=duration_ms,
    )

    # Build alerts
    if metrics.has_low_template_diversity:
        metrics.alerts.append(
            f"Low template diversity: entropy={entropy:.3f}, distribution={distribution}"
        )
    if metrics.has_high_mock_fallback:
        metrics.alerts.append(
            f"High mock fallback rate: {metrics.mock_fallback_rate:.1%} "
            f"({mock_count}/{len(pages)} pages)"
        )
    if metrics.has_degraded_assessment:
        metrics.alerts.append(
            f"Degraded assessment: only {assessment_q_count} questions"
        )
    if extraction_quality < 0.5 and sections and len(sections) > 3:
        metrics.alerts.append(
            f"Low extraction quality: {extraction_quality:.2f} distinct preview ratio"
        )

    # Log metrics as structured log line
    logger.info(
        "Generation quality metrics: job=%s entropy=%.3f templates=%s "
        "mock_rate=%.2f assessment_q=%d multi_comp=%d extract_quality=%.2f "
        "provider=%s model=%s duration_ms=%d alerts=%d",
        job_id[:8], entropy, distribution,
        metrics.mock_fallback_rate, assessment_q_count, multi_comp,
        extraction_quality, provider, model_used, duration_ms, len(metrics.alerts),
    )

    return metrics
