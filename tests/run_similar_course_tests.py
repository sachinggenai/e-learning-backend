"""Standalone test runner for US-BKND-AI-015 — Similar Course Retrieval.

Run: PYTHONPATH=. python tests/run_similar_course_tests.py

Tests: Embedding provider (UT-1..4), PII redaction (UT-3), Service logic,
       Feature flag gating, Tone notes, Empty results.
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.embedding_provider import (
    MockEmbeddingProvider, OpenAIBackend, EmbeddingError,
    DEFAULT_EMBEDDING_DIMENSION, get_embedding_provider,
)
from app.services.ai.similar_course_service import (
    SimilarCourseService, FeatureDisabledError, SessionValidationError,
)

passed = 0
failed = 0
failures: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))


# ═══════════════════════════════════════════════════════════════════
# UNIT: Embedding Provider (UT-1 through UT-4)
# ═══════════════════════════════════════════════════════════════════

async def test_mock_dimension():
    """UT-1: Mock returns 1536-dim vector, all floats in [0, 1)."""
    p = MockEmbeddingProvider()
    v = await p.embed("safety training")
    check("UT-1a: dimension == 1536", len(v) == DEFAULT_EMBEDDING_DIMENSION,
          f"got {len(v)}")
    check("UT-1b: all floats", all(isinstance(x, float) for x in v))
    check("UT-1c: all in [0, 1)", all(0.0 <= x < 1.0 for x in v),
          f"min={min(v):.4f} max={max(v):.4f}")


async def test_mock_deterministic():
    """UT-2: Same input → same vector. Different input → different vector."""
    p = MockEmbeddingProvider()
    v1 = await p.embed("hello world")
    v2 = await p.embed("hello world")
    v3 = await p.embed("different text")
    check("UT-2a: deterministic", v1 == v2)
    check("UT-2b: different inputs → different vectors", v1 != v3)


async def test_mock_property():
    """UT-2c: dimension property."""
    p = MockEmbeddingProvider(dimension=768)
    check("UT-2c: custom dimension", p.dimension == 768)


async def test_pii_redaction():
    """UT-3: PII patterns correctly redacted from text."""
    from app.repositories.similar_course_repo import _PII_RE

    text = "Contact john@example.com or call 555-123-4567. SSN: 123-45-6789."
    result = _PII_RE.sub("[REDACTED]", text)
    check("UT-3a: email redacted", "john@example.com" not in result)
    check("UT-3b: phone redacted", "555-123" not in result)
    check("UT-3c: SSN redacted", "123-45" not in result)
    check("UT-3d: redaction marker present", result.count("[REDACTED]") == 3)

    clean = "This is clean text with no PII."
    result2 = _PII_RE.sub("[REDACTED]", clean)
    check("UT-3e: clean text unchanged", result2 == clean)


# ═══════════════════════════════════════════════════════════════════
# UNIT: Tone Notes (UT-7)
# ═══════════════════════════════════════════════════════════════════

async def test_tone_notes():
    from app.repositories.similar_course_repo import SimilarCourseRepository as R
    notes = R._derive_tone_notes({"welcome", "mcq", "summary"})
    check("UT-7a: returns string", isinstance(notes, str))
    check("UT-7b: mentions knowledge checks",
          "knowledge checks" in notes.lower())
    check("UT-7c: mentions introduction",
          "introduction" in notes.lower() or "objectives" in notes.lower())

    empty = R._derive_tone_notes(set())
    check("UT-7d: empty set → None", empty is None)


# ═══════════════════════════════════════════════════════════════════
# UNIT: Service Empty Result (UT-6)
# ═══════════════════════════════════════════════════════════════════

async def test_empty_result():
    r = SimilarCourseService._empty_result("Test", "tier3")
    check("UT-6a: courses empty", r["courses"] == [])
    check("UT-6b: total_count 0", r["total_count"] == 0)
    check("UT-6c: guidance message", "continue without examples" in r["message"].lower())
    check("UT-6d: tier recorded", r["retrieval_tier_used"] == "tier3")


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION: Feature Flag (IT)
# ═══════════════════════════════════════════════════════════════════

async def test_feature_disabled_raises():
    db_mock = AsyncMock()
    with patch(
        "app.utils.feature_flags.is_feature_enabled",
        return_value=False,
    ):
        service = SimilarCourseService(db_mock)
        try:
            await service.query_similar_courses(
                session_id="test", query="test",
            )
            check("IT-flag: should have raised", False)
        except FeatureDisabledError:
            check("IT-flag: FeatureDisabledError raised", True)


async def test_empty_query_returns_empty():
    db_mock = AsyncMock()
    with patch(
        "app.utils.feature_flags.is_feature_enabled",
        return_value=True,
    ):
        service = SimilarCourseService(db_mock)
        mock_session = MagicMock()
        mock_session.organization_id = "test-org"
        mock_session.user_id = "test-user"
        service.session_repo.get_active = AsyncMock(return_value=mock_session)

        result = await service.query_similar_courses(
            session_id="test", query="   ", user_id="test-user",
        )
        check("IT-empty: courses empty", result["courses"] == [])
        check("IT-empty: mentions empty", "empty" in result["message"].lower())


# ═══════════════════════════════════════════════════════════════════
# Main Runner
# ═══════════════════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("US-BKND-AI-015 — Similar Course Retrieval Tests")
    print("=" * 60)

    await test_mock_dimension()
    await test_mock_deterministic()
    await test_mock_property()
    await test_pii_redaction()
    await test_tone_notes()
    await test_empty_result()
    await test_feature_disabled_raises()
    await test_empty_query_returns_empty()

    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failures:
        for name, detail in failures:
            print(f"  FAIL: {name}")
            if detail:
                print(f"        {detail}")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
