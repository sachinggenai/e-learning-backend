"""Tests for US-BKND-AI-049 — Confirmation Token System.

Covers:
    - ConfirmationTokenService: token generation, validation, expiry
    - Scope-bound hashing: deterministic scope strings, HMAC-SHA256 binding
    - Resource hash verification: match, mismatch, missing base_hash
    - Security event logging: token mismatch logging
    - Error classes: proper codes and messages
    - Edge cases: empty fields, invalid formats, non-hex tokens, admin override
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.confirmation_token_service import (
    ConfirmationTokenService,
    ConfirmationTokenError,
    TokenExpiredError,
    TokenMismatchError,
    ResourceChangedError,
    ProposalNotInConfirmableStateError,
    ResourceNotFoundError,
    DESTRUCTIVE_OPERATIONS,
    DEFAULT_TTL_MINUTES,
)
from app.models.ai_models import AIProposalRecord


# ═══════════════════════════════════════════════════════════════════
# Test Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_proposal(**overrides) -> MagicMock:
    """Create a mock proposal in PENDING_CONFIRMATION state."""
    props = {
        "proposal_id": "prop_001",
        "session_id": "sess_001",
        "course_id": "course_001",
        "target_id": "page_001",
        "target_type": "page",
        "action_type": "delete_page",
        "status": "PENDING_CONFIRMATION",
        "confirmation_token_sha256": None,
        "confirmation_token_expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "confirmation_ttl_override_minutes": None,
        "base_hash": "abc123def456",
        "before_snapshot": None,
    }
    props.update(overrides)
    record = MagicMock(spec=AIProposalRecord)
    for k, v in props.items():
        setattr(record, k, v)
    return record


# ═══════════════════════════════════════════════════════════════════
# Token Generation Tests (FR-CT-01, FR-CT-02, FR-CT-03, FR-CT-05)
# ═══════════════════════════════════════════════════════════════════

class TestTokenGeneration:
    """FR-CT-01, FR-CT-02, FR-CT-03, FR-CT-05: Token generation correctness."""

    @pytest.fixture
    def service(self):
        return ConfirmationTokenService()

    @pytest.mark.asyncio
    async def test_generate_token_returns_valid_structure(self, service):
        """A generated token has the correct structure:
        64 hex chars token, 64 hex chars hash, future expires_at."""
        result = await service.generate_token(
            session_id="sess_001",
            proposal_id="prop_001",
            target_resource_type="page",
            target_resource_id="page_001",
            operation_type="delete_page",
            resource_hash="a1b2c3d4",
        )
        assert "token" in result
        assert "token_hash" in result
        assert "expires_at" in result
        assert len(result["token"]) == 64
        assert len(result["token_hash"]) == 64
        assert result["expires_at"] > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_generate_token_is_cryptographically_random(self, service):
        """Two consecutive token generations produce different tokens."""
        result1 = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )
        result2 = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )
        assert result1["token"] != result2["token"]
        assert result1["token_hash"] != result2["token_hash"]

    @pytest.mark.asyncio
    async def test_generate_token_default_ttl_is_15_minutes(self, service):
        """Default TTL is 15 minutes from now."""
        before = datetime.now(timezone.utc)
        result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )
        after = datetime.now(timezone.utc)
        expected_min = before + timedelta(minutes=15) - timedelta(seconds=2)
        expected_max = after + timedelta(minutes=15) + timedelta(seconds=2)
        assert expected_min <= result["expires_at"] <= expected_max

    @pytest.mark.asyncio
    async def test_generate_token_custom_ttl(self):
        """A custom TTL override is respected."""
        service = ConfirmationTokenService(ttl_minutes=15)
        result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
            ttl_minutes=5,
        )
        expected = datetime.now(timezone.utc) + timedelta(minutes=5)
        assert abs((result["expires_at"] - expected).total_seconds()) < 3

    @pytest.mark.asyncio
    async def test_generate_token_scope_binding_consistency(self, service):
        """The same inputs always produce an HMAC that validates against the scope."""
        result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )
        # Re-compute the expected hash
        scope = service._build_scope_string(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page",
        )
        expected_hash = hmac.new(
            result["token"].encode("utf-8"),
            scope.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert result["token_hash"] == expected_hash

    @pytest.mark.asyncio
    async def test_generate_token_different_scope_different_hash(self, service):
        """Two tokens with different scopes produce different hashes."""
        result_a = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_A",
            operation_type="delete_page", resource_hash="h1",
        )
        result_b = await service.generate_token(
            session_id="sess_001", proposal_id="prop_002",
            target_resource_type="page", target_resource_id="page_B",
            operation_type="delete_page", resource_hash="h1",
        )
        assert result_a["token_hash"] != result_b["token_hash"]

    @pytest.mark.asyncio
    async def test_generate_token_validates_required_fields(self, service):
        """Empty required fields raise ValueError."""
        with pytest.raises(ValueError, match="session_id"):
            await service.generate_token(
                session_id="", proposal_id="prop_001",
                target_resource_type="page", target_resource_id="page_001",
                operation_type="delete_page", resource_hash="h1",
            )
        with pytest.raises(ValueError, match="resource_hash"):
            await service.generate_token(
                session_id="sess_001", proposal_id="prop_001",
                target_resource_type="page", target_resource_id="page_001",
                operation_type="delete_page", resource_hash="",
            )
        with pytest.raises(ValueError, match="proposal_id"):
            await service.generate_token(
                session_id="sess_001", proposal_id="",
                target_resource_type="page", target_resource_id="page_001",
                operation_type="delete_page", resource_hash="h1",
            )

    @pytest.mark.asyncio
    async def test_generate_token_hex_format(self, service):
        """Token is a valid 64-character hex string."""
        result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )
        # Should be valid hex
        int(result["token"], 16)
        # Should be 64 hex chars = 256 bits
        assert len(bytes.fromhex(result["token"])) == 32


# ═══════════════════════════════════════════════════════════════════
# Token Validation Tests (FR-CT-07, FR-CT-08)
# ═══════════════════════════════════════════════════════════════════

class TestTokenValidation:
    """FR-CT-07, FR-CT-08: Full validation pipeline."""

    @pytest.fixture
    def service(self):
        return ConfirmationTokenService()

    @pytest.mark.asyncio
    async def test_validate_token_happy_path(self, service):
        """A valid token with correct scope and not expired passes validation."""
        # Generate a real token first
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = _make_proposal(
            confirmation_token_sha256=gen_result["token_hash"],
            confirmation_token_expires_at=gen_result["expires_at"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token=gen_result["token"],
            user_approved=True,
        )
        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_token_also_accepts_pending_status(self, service):
        """The service accepts both 'pending' and 'PENDING_CONFIRMATION' statuses."""
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = _make_proposal(
            status="pending",
            confirmation_token_sha256=gen_result["token_hash"],
            confirmation_token_expires_at=gen_result["expires_at"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token=gen_result["token"],
            user_approved=True,
        )
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_validate_token_rejects_expired_token(self, service):
        """An expired token is rejected."""
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        # Set expiry in the past
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        proposal = _make_proposal(
            confirmation_token_sha256=gen_result["token_hash"],
            confirmation_token_expires_at=expired_time,
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token=gen_result["token"],
            user_approved=True,
        )
        assert is_valid is False
        assert "CONFIRMATION_EXPIRED" in error

    @pytest.mark.asyncio
    async def test_validate_token_rejects_wrong_token(self, service):
        """An incorrect token is rejected and logged as security event."""
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = _make_proposal(
            confirmation_token_sha256=gen_result["token_hash"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token="1111111111111111111111111111111111111111111111111111111111111111",
            user_approved=True,
        )
        assert is_valid is False
        assert "INVALID_CONFIRMATION_TOKEN" in error

    @pytest.mark.asyncio
    async def test_validate_token_rejects_non_confirmable_status(self, service):
        """Proposals not in PENDING_CONFIRMATION/pending state are rejected."""
        for bad_status in ["applied", "expired", "rejected", "failed", "cancelled"]:
            proposal = _make_proposal(status=bad_status)
            is_valid, error = await service.validate_token(
                proposal=proposal,
                received_token="a" * 64,
                user_approved=True,
            )
            assert is_valid is False, f"Status {bad_status} should be rejected"
            assert "PROPOSAL_NOT_CONFIRMABLE" in error

    @pytest.mark.asyncio
    async def test_validate_token_requires_user_approval(self, service):
        """Setting user_approved=False rejects the confirmation."""
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = _make_proposal(
            confirmation_token_sha256=gen_result["token_hash"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token=gen_result["token"],
            user_approved=False,
        )
        assert is_valid is False
        assert "USER_CONFIRMATION_REQUIRED" in error

    @pytest.mark.asyncio
    async def test_validate_token_rejects_non_destructive_operation(self, service):
        """Non-destructive operations are rejected."""
        for non_destructive in ["create_page", "update_page", "batch_create", "batch_update"]:
            proposal = _make_proposal(action_type=non_destructive)
            is_valid, error = await service.validate_token(
                proposal=proposal,
                received_token="a" * 64,
                user_approved=True,
            )
            assert is_valid is False, f"Op {non_destructive} should be rejected"
            assert "NON_DESTRUCTIVE_OPERATION" in error

    @pytest.mark.asyncio
    async def test_validate_token_rejects_invalid_token_format(self, service):
        """Tokens that are not 64 hex characters are rejected."""
        proposal = _make_proposal(
            confirmation_token_sha256="abc123",
        )

        for bad_token in ["", "abc", "x" * 64, "z" * 64, "a" * 63]:
            is_valid, error = await service.validate_token(
                proposal=proposal,
                received_token=bad_token,
                user_approved=True,
            )
            assert is_valid is False, f"Token '{bad_token[:20]}' should be rejected"
            if bad_token:
                assert "INVALID_TOKEN_FORMAT" in error

    @pytest.mark.asyncio
    async def test_validate_token_rejects_when_no_confirmation_hash_set(self, service):
        """When proposal has no confirmation_token_sha256, reject."""
        proposal = _make_proposal(confirmation_token_sha256=None)
        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token="a" * 64,
            user_approved=True,
        )
        assert is_valid is False
        assert "NO_CONFIRMATION_TOKEN_SET" in error

    @pytest.mark.asyncio
    async def test_validate_token_admin_override_happy_path(self, service):
        """Admin override with valid reason bypasses token validation."""
        proposal = _make_proposal(confirmation_token_sha256=None)
        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token="invalid",
            user_approved=True,
            admin_override=True,
            admin_override_reason="This is a valid admin override reason for testing purposes",
        )
        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_token_admin_override_requires_long_reason(self, service):
        """Admin override with short reason is rejected."""
        proposal = _make_proposal()
        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token="a" * 64,
            user_approved=True,
            admin_override=True,
            admin_override_reason="Too short",
        )
        assert is_valid is False
        assert "ADMIN_OVERRIDE_REASON_TOO_SHORT" in error

    @pytest.mark.asyncio
    async def test_validate_token_different_scope_fails(self, service):
        """A token generated for one resource fails validation against another."""
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        # Proposal has different session_id => scope doesn't match
        proposal = _make_proposal(
            session_id="sess_DIFFERENT",
            confirmation_token_sha256=gen_result["token_hash"],
            confirmation_token_expires_at=gen_result["expires_at"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token=gen_result["token"],
            user_approved=True,
        )
        assert is_valid is False
        assert "INVALID_CONFIRMATION_TOKEN" in error


# ═══════════════════════════════════════════════════════════════════
# Security Event Logging Tests (FR-CT-10)
# ═══════════════════════════════════════════════════════════════════

class TestSecurityEventLogging:
    """FR-CT-10: Security event logging on token mismatch."""

    @pytest.mark.asyncio
    async def test_security_event_logged_on_token_mismatch(self):
        """A token mismatch logs a SECURITY_EVENT."""
        service = ConfirmationTokenService()

        with patch.object(service, "_log_security_event") as mock_log:
            gen_result = await service.generate_token(
                session_id="sess_001", proposal_id="prop_001",
                target_resource_type="page", target_resource_id="page_001",
                operation_type="delete_page", resource_hash="h1",
            )
            proposal = _make_proposal(
                confirmation_token_sha256=gen_result["token_hash"],
            )
            await service.validate_token(
                proposal=proposal,
                received_token="f" * 64,
                user_approved=True,
            )
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            kwargs = call_args[1] if call_args[1] else {}
            assert kwargs.get("event_type") == "CONFIRMATION_TOKEN_MISMATCH"
            assert kwargs.get("proposal_id") == "prop_001"
            assert kwargs.get("session_id") == "sess_001"

    @pytest.mark.asyncio
    async def test_security_event_not_logged_on_expiry(self):
        """An expiry error does not log a security event."""
        service = ConfirmationTokenService()

        with patch.object(service, "_log_security_event") as mock_log:
            gen_result = await service.generate_token(
                session_id="sess_001", proposal_id="prop_001",
                target_resource_type="page", target_resource_id="page_001",
                operation_type="delete_page", resource_hash="h1",
            )
            expired_time = datetime.now(timezone.utc) - timedelta(minutes=1)
            proposal = _make_proposal(
                confirmation_token_sha256=gen_result["token_hash"],
                confirmation_token_expires_at=expired_time,
            )
            await service.validate_token(
                proposal=proposal,
                received_token=gen_result["token"],
                user_approved=True,
            )
            mock_log.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# Resource Hash Verification Tests (FR-CT-06, FR-CT-07)
# ═══════════════════════════════════════════════════════════════════

class TestResourceHashVerification:
    """FR-CT-06, FR-CT-07: Resource hash computation and verification."""

    @pytest.fixture
    def service(self):
        return ConfirmationTokenService()

    @pytest.mark.asyncio
    async def test_verify_resource_hash_happy_path(self, service):
        """When the current hash matches base_hash, verification passes."""
        proposal = _make_proposal(base_hash="abc123def456")

        is_match, error = await service.verify_resource_hash(
            proposal=proposal,
            current_resource_hash="abc123def456",
        )
        assert is_match is True
        assert error is None

    @pytest.mark.asyncio
    async def test_verify_resource_hash_rejects_mismatch(self, service):
        """When the current hash differs from base_hash, verification fails."""
        proposal = _make_proposal(base_hash="abc123def456")

        is_match, error = await service.verify_resource_hash(
            proposal=proposal,
            current_resource_hash="xyz789mno012",
        )
        assert is_match is False
        assert "RESOURCE_CHANGED" in error
        assert "abc123def456" in error
        assert "xyz789mno012" in error

    @pytest.mark.asyncio
    async def test_verify_resource_hash_fails_when_base_hash_missing(self, service):
        """If base_hash is None on the proposal, verification fails."""
        proposal = _make_proposal(base_hash=None)

        is_match, error = await service.verify_resource_hash(
            proposal=proposal,
            current_resource_hash="abc123",
        )
        assert is_match is False
        assert "BASE_HASH_MISSING" in error

    def test_compute_resource_hash_is_deterministic(self, service):
        """The same dict always produces the same hash."""
        state = {"title": "Test Page", "order": 1, "components": ["a", "b"]}
        h1 = service.compute_resource_hash(state)
        h2 = service.compute_resource_hash(state)
        assert h1 == h2

    def test_compute_resource_hash_differs_when_state_changes(self, service):
        """Changing any field changes the hash."""
        state1 = {"title": "Test Page", "order": 1}
        state2 = {"title": "Test Page", "order": 2}
        h1 = service.compute_resource_hash(state1)
        h2 = service.compute_resource_hash(state2)
        assert h1 != h2

    def test_compute_resource_hash_is_stable_hex(self, service):
        """The computed hash is a valid 64-character hex string."""
        h = service.compute_resource_hash({"a": 1})
        assert len(h) == 64
        # Should be valid hex
        int(h, 16)


# ═══════════════════════════════════════════════════════════════════
# Scope String Construction Tests (FR-CT-03)
# ═══════════════════════════════════════════════════════════════════

class TestScopeStringConstruction:
    """FR-CT-03: Scope string is built deterministically."""

    def test_build_scope_string_is_deterministic(self):
        """The same inputs always produce the same scope string."""
        service = ConfirmationTokenService()
        scope1 = service._build_scope_string(
            session_id="sess_001",
            proposal_id="prop_001",
            target_resource_type="page",
            target_resource_id="page_001",
            operation_type="delete_page",
        )
        scope2 = service._build_scope_string(
            session_id="sess_001",
            proposal_id="prop_001",
            target_resource_type="page",
            target_resource_id="page_001",
            operation_type="delete_page",
        )
        assert scope1 == scope2

    def test_build_scope_string_differs_when_field_changes(self):
        """Changing any input field changes the scope string."""
        service = ConfirmationTokenService()
        base = service._build_scope_string(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page",
        )
        changed = service._build_scope_string(
            session_id="sess_002", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page",
        )
        assert base != changed

    def test_build_scope_string_includes_all_five_fields(self):
        """The scope string contains all five required fields."""
        service = ConfirmationTokenService()
        scope = service._build_scope_string(
            session_id="s_1", proposal_id="p_1",
            target_resource_type="page", target_resource_id="r_1",
            operation_type="delete",
        )
        assert "session_id=s_1" in scope
        assert "proposal_id=p_1" in scope
        assert "target_resource_type=page" in scope
        assert "target_resource_id=r_1" in scope
        assert "operation_type=delete" in scope

    def test_build_scope_string_is_sorted(self):
        """The scope string parts are sorted alphabetically."""
        service = ConfirmationTokenService()
        scope = service._build_scope_string(
            session_id="s_1", proposal_id="p_1",
            target_resource_type="page", target_resource_id="r_1",
            operation_type="delete",
        )
        parts = scope.split(service.SCOPE_SEPARATOR)
        assert parts == sorted(parts)


# ═══════════════════════════════════════════════════════════════════
# Error Class Tests
# ═══════════════════════════════════════════════════════════════════

class TestErrorClasses:
    """Verify error classes have correct codes and status codes."""

    def test_token_expired_error(self):
        expired_at = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        e = TokenExpiredError(expired_at)
        assert e.code == "CONFIRMATION_EXPIRED"
        assert e.status_code == 410
        assert "expired" in e.message.lower()

    def test_token_mismatch_error(self):
        e = TokenMismatchError()
        assert e.code == "INVALID_CONFIRMATION_TOKEN"
        assert e.status_code == 403
        assert "invalid" in e.message.lower()

    def test_resource_changed_error(self):
        e = ResourceChangedError("base", "current")
        assert e.code == "RESOURCE_CHANGED"
        assert e.status_code == 409
        assert e.base_hash == "base"
        assert e.current_hash == "current"

    def test_proposal_not_confirmable_error(self):
        e = ProposalNotInConfirmableStateError("applied")
        assert e.code == "PROPOSAL_NOT_CONFIRMABLE"
        assert e.status_code == 409
        assert "applied" in e.message

    def test_resource_not_found_error(self):
        e = ResourceNotFoundError("page", "page_xyz")
        assert e.code == "RESOURCE_NOT_FOUND"
        assert e.status_code == 410
        assert "page" in e.message
        assert "page_xyz" in e.message

    def test_base_error(self):
        e = ConfirmationTokenError("CUSTOM_CODE", "Custom message", 418)
        assert e.code == "CUSTOM_CODE"
        assert e.message == "Custom message"
        assert e.status_code == 418


# ═══════════════════════════════════════════════════════════════════
# Target Resource Type/ID Derivation Tests
# ═══════════════════════════════════════════════════════════════════

class TestTargetResourceDerivation:
    """Verify correct derivation of resource type and ID from proposals."""

    def test_get_target_resource_type_page_delete(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(action_type="delete_page", target_type="page", target_id="p1")
        assert service._get_target_resource_type(proposal) == "page"

    def test_get_target_resource_type_course_delete(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(action_type="delete_course", target_type="course", target_id="c1")
        assert service._get_target_resource_type(proposal) == "course"

    def test_get_target_resource_type_batch(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(action_type="batch_delete", target_type="batch", target_id=None)
        assert service._get_target_resource_type(proposal) == "batch"

    def test_get_target_resource_type_asset(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(action_type="delete_asset", target_type="asset", target_id="a1")
        assert service._get_target_resource_type(proposal) == "asset"

    def test_get_target_resource_type_fallback(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(action_type="course_archive", target_type="course", target_id="c1")
        assert service._get_target_resource_type(proposal) == "course"

    def test_get_target_resource_id_from_target(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(target_id="page_123")
        assert service._get_target_resource_id(proposal) == "page_123"

    def test_get_target_resource_id_fallback_to_proposal(self):
        service = ConfirmationTokenService()
        proposal = _make_proposal(target_id=None, proposal_id="prop_xyz")
        assert service._get_target_resource_id(proposal) == "prop_xyz"


# ═══════════════════════════════════════════════════════════════════
# Destructive Operations Set Tests
# ═══════════════════════════════════════════════════════════════════

class TestDestructiveOperations:
    """Verify the destructive operations set contains all expected operations."""

    def test_delete_page_in_destructive_ops(self):
        assert "delete_page" in DESTRUCTIVE_OPERATIONS

    def test_delete_course_in_destructive_ops(self):
        assert "delete_course" in DESTRUCTIVE_OPERATIONS

    def test_batch_delete_in_destructive_ops(self):
        assert "batch_delete" in DESTRUCTIVE_OPERATIONS

    def test_delete_asset_in_destructive_ops(self):
        assert "delete_asset" in DESTRUCTIVE_OPERATIONS

    def test_course_archive_in_destructive_ops(self):
        assert "course_archive" in DESTRUCTIVE_OPERATIONS

    def test_create_page_not_in_destructive_ops(self):
        assert "create_page" not in DESTRUCTIVE_OPERATIONS

    def test_update_page_not_in_destructive_ops(self):
        assert "update_page" not in DESTRUCTIVE_OPERATIONS
