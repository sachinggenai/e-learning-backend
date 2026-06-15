"""Centralized Confirmation Token Service for Destructive/Irreversible Operations.

US-BKND-AI-049: Provides reusable token generation, scope binding, hashing,
expiry, and validation logic used by ALL destructive operation proposals
across the AI authoring system.

Architecture:
  - Tokens are generated with 256-bit entropy via secrets.token_hex(32).
  - The token is SCOPE-BOUND: HMAC-SHA256(token, scope_string) is stored,
    NOT the bare token hash. This binds the token to its specific proposal,
    session, resource, and operation.
  - The plaintext token is NEVER persisted. It exists only in the propose
    API response and in the frontend's in-memory state.
  - Validation re-computes the scope-bound hash from the received token
    and the proposal's stored scope metadata.

Usage:
  service = ConfirmationTokenService(session)
  result = await service.generate_token(
      session_id="sess_abc",
      proposal_id="prop_001",
      target_resource_type="page",
      target_resource_id="page_xyz",
      operation_type="delete_page",
      resource_hash="a1b2c3d4...",
      ttl_minutes=15,
  )
  # result: {token: "64hexchars", token_hash: "sha256hash", expires_at: datetime}

  # During confirmation:
  is_valid, error = await service.validate_token(
      proposal=proposal_record,
      received_token="64hexchars",
  )
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.models.ai_models import AIProposalRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfirmationTokenError(Exception):
    """Base exception for confirmation token failures."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class TokenExpiredError(ConfirmationTokenError):
    def __init__(self, expired_at: datetime):
        super().__init__(
            code="CONFIRMATION_EXPIRED",
            message=(
                f"Confirmation token expired at {expired_at.isoformat()}. "
                "Maximum TTL is configured via AI_CONFIRMATION_TOKEN_TTL_MINUTES."
            ),
            status_code=410,
        )


class TokenMismatchError(ConfirmationTokenError):
    def __init__(self):
        super().__init__(
            code="INVALID_CONFIRMATION_TOKEN",
            message="The provided confirmation token is invalid. This may indicate tampering.",
            status_code=403,
        )


class ResourceChangedError(ConfirmationTokenError):
    def __init__(self, base_hash: str, current_hash: str):
        super().__init__(
            code="RESOURCE_CHANGED",
            message=(
                "The target resource has changed since the proposal was created. "
                "Please review the current state and re-propose."
            ),
            status_code=409,
        )
        self.base_hash = base_hash
        self.current_hash = current_hash


class ProposalNotInConfirmableStateError(ConfirmationTokenError):
    def __init__(self, status: str):
        super().__init__(
            code="PROPOSAL_NOT_CONFIRMABLE",
            message=(
                f"Proposal is in status '{status}' and cannot be confirmed. "
                "Only PENDING_CONFIRMATION proposals are confirmable."
            ),
            status_code=409,
        )


class ResourceNotFoundError(ConfirmationTokenError):
    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            code="RESOURCE_NOT_FOUND",
            message=f"{resource_type} '{resource_id}' not found. It may have been deleted.",
            status_code=410,
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TTL_MINUTES = 15
SECURITY_EVENT_LOGGER_NAME = "ai.security.confirmation_token"

# Destructive operations that require confirmation tokens
DESTRUCTIVE_OPERATIONS = frozenset({
    "delete_page",
    "delete_course",
    "batch_delete",
    "batch_update_delete",
    "delete_asset",
    "course_archive",
})


class ConfirmationTokenService:
    """Centralized service for generating, binding, and validating
    confirmation tokens for destructive/irreversible operations.

    This service is stateless aside from the DB session. All token
    state is persisted in the ai_proposals table.
    """

    # Scope field separator for canonical scope string construction
    SCOPE_SEPARATOR = "::"

    def __init__(
        self,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ):
        self.ttl_minutes = ttl_minutes
        self.security_logger = logging.getLogger(SECURITY_EVENT_LOGGER_NAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_token(
        self,
        *,
        session_id: str,
        proposal_id: str,
        target_resource_type: str,
        target_resource_id: str,
        operation_type: str,
        resource_hash: str,
        ttl_minutes: Optional[int] = None,
    ) -> dict:
        """Generate a confirmation token bound to the given scope.

        Args:
            session_id: The AI session ID.
            proposal_id: The proposal ID this token is for.
            target_resource_type: Type of resource being acted upon
                (e.g., 'page', 'course', 'batch', 'asset').
            target_resource_id: The ID of the target resource.
            operation_type: The operation type (e.g., 'delete_page',
                'delete_course', 'batch_delete').
            resource_hash: The deterministic hash of the resource's
                current state.
            ttl_minutes: Override the default TTL for this token.
                If not provided, uses the service default.

        Returns:
            dict with:
                - token (str): The plaintext token (64 hex chars).
                - token_hash (str): The SHA-256 hash of the scope-bound
                  token, to be stored in the proposal record.
                - expires_at (datetime): The token's expiry datetime.

        Raises:
            ValueError: If any required argument is empty or invalid.
        """
        # Validate inputs
        self._validate_required(
            session_id=session_id,
            proposal_id=proposal_id,
            target_resource_type=target_resource_type,
            target_resource_id=target_resource_id,
            operation_type=operation_type,
            resource_hash=resource_hash,
        )

        # 1. Generate the cryptographically random token
        token = secrets.token_hex(32)  # 64 hex chars, 256 bits

        # 2. Build the canonical scope string
        scope_string = self._build_scope_string(
            session_id=session_id,
            proposal_id=proposal_id,
            target_resource_type=target_resource_type,
            target_resource_id=target_resource_id,
            operation_type=operation_type,
        )

        # 3. Compute the scope-bound hash
        token_hash = self._compute_scope_bound_hash(token, scope_string)

        # 4. Compute expiry
        effective_ttl = ttl_minutes if ttl_minutes is not None else self.ttl_minutes
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=effective_ttl)

        logger.info(
            "Confirmation token generated: proposal=%s, resource=%s/%s, op=%s, ttl=%dmin",
            proposal_id,
            target_resource_type,
            target_resource_id,
            operation_type,
            effective_ttl,
        )

        return {
            "token": token,
            "token_hash": token_hash,
            "expires_at": expires_at,
        }

    async def validate_token(
        self,
        *,
        proposal: AIProposalRecord,
        received_token: str,
        user_approved: bool = True,
        admin_override: bool = False,
        admin_override_reason: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Validate a confirmation token against a proposal.

        Performs the full validation pipeline from FR-CT-08.

        Args:
            proposal: The AIProposalRecord to validate against.
            received_token: The plaintext token received from the frontend.
            user_approved: Whether the user explicitly approved the operation.
            admin_override: Whether this is an admin bypass attempt.
            admin_override_reason: Reason for admin override (required if
                admin_override is True).

        Returns:
            Tuple of (is_valid: bool, error_code: Optional[str]).
            If valid, error_code is None.

        Note:
            After validation passes, the caller must still verify the
            resource hash by calling verify_resource_hash() separately,
            since the resource state fetch is operation-specific.
        """
        # Step 1-2: Basic proposal state validation
        if proposal.status != "PENDING_CONFIRMATION" and proposal.status != "pending":
            return False, f"PROPOSAL_NOT_CONFIRMABLE:{proposal.status}"

        # Step 3: Check operation is destructive
        if proposal.action_type not in DESTRUCTIVE_OPERATIONS:
            return False, f"NON_DESTRUCTIVE_OPERATION:{proposal.action_type}"

        # Step 4: User approval
        if not user_approved and not admin_override:
            return False, "USER_CONFIRMATION_REQUIRED"

        # Admin override path: bypass token validation
        if admin_override:
            if not admin_override_reason or len(admin_override_reason.strip()) < 20:
                return False, "ADMIN_OVERRIDE_REASON_TOO_SHORT"
            logger.warning(
                "ADMIN OVERRIDE: proposal=%s, admin bypassing token validation. Reason: %s",
                proposal.proposal_id,
                admin_override_reason,
            )
            # Admin override still performs hash validation later
            # (the caller must call verify_resource_hash)
            return True, None

        # Step 5: Token format check
        if not received_token or len(received_token) != 64:
            return False, "INVALID_TOKEN_FORMAT"
        try:
            bytes.fromhex(received_token)
        except ValueError:
            return False, "INVALID_TOKEN_FORMAT"

        # Step 6: Token mismatch check (scope-bound hash comparison)
        scope_parts = {
            "session_id": proposal.session_id,
            "proposal_id": proposal.proposal_id,
            "target_resource_type": self._get_target_resource_type(proposal),
            "target_resource_id": self._get_target_resource_id(proposal),
            "operation_type": proposal.action_type,
        }
        scope_string = self._build_scope_string(**scope_parts)
        computed_hash = self._compute_scope_bound_hash(received_token, scope_string)

        if not proposal.confirmation_token_sha256:
            return False, "NO_CONFIRMATION_TOKEN_SET"
        if computed_hash != proposal.confirmation_token_sha256:
            # SECURITY EVENT: Token mismatch indicates potential tampering
            self._log_security_event(
                event_type="CONFIRMATION_TOKEN_MISMATCH",
                proposal_id=proposal.proposal_id,
                session_id=proposal.session_id,
                details={
                    "expected_hash_prefix": proposal.confirmation_token_sha256[:16] + "...",
                    "computed_hash_prefix": computed_hash[:16] + "...",
                },
            )
            return False, "INVALID_CONFIRMATION_TOKEN"

        # Step 7: Expiry check
        if proposal.confirmation_token_expires_at:
            if datetime.now(timezone.utc) > proposal.confirmation_token_expires_at:
                return False, (
                    f"CONFIRMATION_EXPIRED:"
                    f"{proposal.confirmation_token_expires_at.isoformat()}"
                )

        # Step 8: Resource existence check (delegated to caller)
        # Step 9: Resource hash check (delegated to caller via verify_resource_hash)

        return True, None

    async def verify_resource_hash(
        self,
        *,
        proposal: AIProposalRecord,
        current_resource_hash: str,
    ) -> Tuple[bool, Optional[str]]:
        """Verify that the current resource hash matches the proposal's base_hash.

        This must be called by the operation-specific orchestrator AFTER
        validate_token() passes, inside the execution transaction.

        Args:
            proposal: The AIProposalRecord.
            current_resource_hash: The hash of the resource's current state.

        Returns:
            Tuple of (is_match: bool, error_code: Optional[str]).
        """
        if not proposal.base_hash:
            return False, "BASE_HASH_MISSING"

        if current_resource_hash != proposal.base_hash:
            return False, f"RESOURCE_CHANGED:{proposal.base_hash}:{current_resource_hash}"

        return True, None

    # ------------------------------------------------------------------
    # Resource hash computation
    # ------------------------------------------------------------------

    def compute_resource_hash(self, resource_state: dict) -> str:
        """Compute a deterministic hash from a resource state dictionary.

        The dictionary is serialized with sorted keys to ensure
        determinism, then SHA-256 hashed.

        This is the base implementation. Operation-specific callers
        may provide their own hash computation logic, but MUST use
        this same deterministic approach.
        """
        import json

        canonical = json.dumps(resource_state, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_scope_string(
        self,
        *,
        session_id: str,
        proposal_id: str,
        target_resource_type: str,
        target_resource_id: str,
        operation_type: str,
    ) -> str:
        """Build the canonical scope string for token binding.

        The scope string is a deterministic concatenation of the scope
        fields, sorted alphabetically by field name to ensure consistency.
        """
        parts = [
            f"operation_type={operation_type}",
            f"proposal_id={proposal_id}",
            f"session_id={session_id}",
            f"target_resource_id={target_resource_id}",
            f"target_resource_type={target_resource_type}",
        ]
        # Sort for deterministic ordering
        parts.sort()
        return self.SCOPE_SEPARATOR.join(parts)

    def _compute_scope_bound_hash(self, token: str, scope_string: str) -> str:
        """Compute HMAC-SHA256 of the token bound to the scope string.

        Uses HMAC-SHA256 for additional protection against length extension.
        """
        key = token.encode("utf-8")
        message = scope_string.encode("utf-8")
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    def _get_target_resource_type(self, proposal: AIProposalRecord) -> str:
        """Derive the target_resource_type from the proposal."""
        # For page-level operations
        if proposal.action_type in ("delete_page",):
            return "page"
        # For course-level operations
        if proposal.action_type in ("delete_course", "course_archive"):
            return "course"
        # For batch operations
        if proposal.action_type in ("batch_delete", "batch_update_delete"):
            return "batch"
        # For asset operations
        if proposal.action_type in ("delete_asset",):
            return "asset"
        # Default: use target_type
        return proposal.target_type or proposal.action_type

    def _get_target_resource_id(self, proposal: AIProposalRecord) -> str:
        """Derive the target_resource_id from the proposal."""
        if proposal.target_id:
            return proposal.target_id
        return proposal.proposal_id  # fallback to proposal ID

    def _validate_required(self, **kwargs) -> None:
        """Validate that all required arguments are non-empty strings."""
        for name, value in kwargs.items():
            if not value or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"'{name}' is required and cannot be empty")

    def _log_security_event(
        self,
        event_type: str,
        proposal_id: str,
        session_id: str,
        details: Optional[dict] = None,
    ) -> None:
        """Log a security event for audit and monitoring."""
        self.security_logger.error(
            "SECURITY_EVENT type=%s proposal=%s session=%s details=%s",
            event_type,
            proposal_id,
            session_id,
            details or {},
        )
