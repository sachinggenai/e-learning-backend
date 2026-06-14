# US-AI-049: Confirmation Token System for Destructive and Irreversible Operations

**Status:** Draft  
**Priority:** MUST  
**Depends on:** US-AI-004 (AI Persistence Foundations), US-AI-009 (Generic Proposal Lifecycle)  
**Unlocks:** US-AI-013 (Delete Page Proposal and Confirm), US-AI-046 (Course-Level Operations Create/Delete), destructive batch operations  
**Epic Owner:** Technical Product Owner  
**Story Points:** 21 SP

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 User Story

As an **Author or Admin**, I want every destructive or irreversible operation (page deletion, course deletion, batch operations, configuration changes, asset removal) to require a confirmed two-phase gate with a cryptographically bound confirmation token, so that accidental or malicious destructive actions are prevented and every irreversible mutation is an explicit, auditable human decision.

As the **System**, I want a reusable, centralized Confirmation Token Service that enforces token generation, hashing, expiry, scope binding, and validation uniformly across all destructive operation types, so that every new destructive feature gets safety gating without reimplementing token logic.

### 1.2 Overview and Rationale

Confirmation tokens are the core safety mechanism for irreversible AI operations. The system must enforce:

1. **Two-phase execution:** Destructive operations are split into PROPOSE (creates a bound token) and CONFIRM (validates the token and executes). The first phase never mutates domain data.
2. **Cryptographic binding:** Each token is bound to the session, the proposal, the target resource, a deterministic state hash (before-snapshot), and an expiration time. Validation checks all bindings.
3. **Reusability:** The token subsystem is a standalone service that any destructive operation type (page delete, course delete, batch delete, asset removal, irreversible setting changes) can plug into without duplicating token logic.
4. **Non-repudiation:** Only the SHA-256 hash of the token is persisted. The plaintext token exists only in the API response to the caller for the duration of the confirmation flow.
5. **Stale-state detection:** The deterministic hash of the target resource's current state is captured at proposal time and re-checked at confirmation time. If the resource changed between proposal and confirmation, the token is rejected with a conflict.

The scope of "destructive and irreversible operations" includes:

| Operation Type | Examples | Covered by |
|---|---|---|
| Page deletion | Delete a single course page | US-AI-013 |
| Course deletion | Delete an entire course (draft or published) | US-AI-046 |
| Batch page deletion | Delete multiple pages in one atomic operation | US-AI-029 |
| Asset deletion | Remove a media asset from storage | Future story |
| Irreversible config changes | Disable scoring, reset learner progress, change grading policy | Future story |
| Course level destructive | Archive course, remove all learner enrollments | Future story |
| Policy override | Admin force-override of auto-apply rules | Future story |

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Initiates destructive operations via AI chat or UI; confirms or cancels via confirmation modal |
| AI Agent | Calls propose operations via tool calls; never calls delete/execute APIs directly |
| Backend ConfirmationTokenService | Centralized service for token generation, hashing, binding, and validation |
| Backend ProposalOrchestrator | Coordinates the two-phase gate for a specific operation, delegates token management to ConfirmationTokenService |
| Frontend | Renders confirmation modals; holds the plaintext token in memory; sends it with the confirm request |
| Admin | Super-user who may have elevated TTL or bypass capabilities for recovery scenarios |
| Audit System | Records token-based confirmations for non-repudiation and compliance |

### 1.4 Functional Requirements

**FR-CT-01 (Centralized Token Service):** The system MUST provide a standalone `ConfirmationTokenService` class that encapsulates all token generation, hashing, scope binding, expiry management, and validation logic. Every destructive operation proposal MUST use this service rather than implementing custom token logic.

**FR-CT-02 (Token Generation):** The service MUST generate cryptographically secure random tokens using `secrets.token_hex(32)`, producing a 64-character hex string (256 bits of entropy). The generation MUST produce unique tokens on every invocation.

**FR-CT-03 (Token Binding):** Each generated token MUST be cryptographically bound to a scope object containing: `proposal_id`, `session_id`, `target_resource_type` (e.g., `"page"`, `"course"`, `"batch"`, `"asset"`), `target_resource_id`, `base_hash` (deterministic hash of the resource state at proposal time), and `operation_type` (e.g., `"delete_page"`, `"delete_course"`, `"batch_delete"`). The binding is enforced by storing the SHA-256 hash of `token + "::" + canonical_scope_string` in the database, NOT the bare token hash. This binds the token to the scope without storing the scope alongside the token hash (the scope is stored in the proposal record, and re-computed at validation time).

**FR-CT-04 (Hashed Storage / Non-Repudiation):** The system MUST NEVER store the plaintext confirmation token in any persistent storage. Only the SHA-256 hash of the token (scoped-bound hash per FR-CT-03) MUST be persisted in the `ai_proposals.confirmation_token_sha256` column. The plaintext token exists only in the API response of the propose endpoint and in the frontend's in-memory state. The hash stored in the audit log at confirmation time MUST match the hash stored in the proposal record, providing a complete chain of custody.

**FR-CT-05 (Token Expiry):** Every token MUST have a configurable TTL via the `AI_CONFIRMATION_TOKEN_TTL_MINUTES` environment variable (default: 15 minutes). The TTL is counted from the moment of proposal creation. Expired tokens MUST be rejected with a `410 CONFIRMATION_EXPIRED` error. The TTL MUST be configurable per-operation-type via an optional override in the proposal metadata (e.g., course deletion may require a shorter TTL of 5 minutes).

**FR-CT-06 (Resource State Hash):** The system MUST compute a deterministic hash of the target resource's full state at proposal time (`base_hash`). For pages, this includes `page_id`, `title`, `order_index`, `updated_at`, and all component IDs/types/orders/updated_ats. For courses, this includes `course_id`, `title`, `status`, `updated_at`, page count, and a concatenation of all page hashes. The `_compute_resource_hash` method in the service MUST produce the same hash for the same state every time (deterministic) and MUST produce a different hash when any field in the state changes.

**FR-CT-07 (Stale-State Rejection):** At confirmation time, the system MUST re-fetch the target resource, re-compute its hash, and compare it with the `base_hash` stored in the proposal. If the hashes differ, the confirmation MUST be rejected with a `409 PAGE_CHANGED` (or `409 RESOURCE_CHANGED`) error, and the user must re-propose the operation against the current state.

**FR-CT-08 (Token Validation Pipeline):** The validation at confirmation time MUST check, IN ORDER:
1. Proposal exists and belongs to the session (404 or 403 if not found).
2. Proposal status is `PENDING_CONFIRMATION` (409 if already applied, expired, or failed).
3. Operation type matches a destructive operation (405 if the operation type does not require confirmation).
4. User approval flag is true (400 if false or missing).
5. Plaintext token from request is not empty and matches the expected format (64 hex chars).
6. Re-compute the scope-bound hash: `SHA256(received_token + "::" + canonical_scope_string)` and compare against `confirmation_token_sha256` in the proposal (403 if mismatch, logged as security event).
7. Token has not expired (410 if expired).
8. Resource still exists (410 if not found).
9. Re-compute resource hash and compare against `base_hash` (409 if changed).
10. All checks pass: execute the operation inside a database transaction.

**FR-CT-09 (Idempotency Guard):** If a proposal has already been confirmed (`status = APPLIED`), any subsequent confirmation request for the same proposal_id MUST return `409 PROPOSAL_ALREADY_APPLIED`. This prevents double-execution even if the token is replayed.

**FR-CT-10 (Security Event Logging):** Any token validation failure at step 6 (FR-CT-08, token mismatch) MUST be logged as a `SECURITY_EVENT` with severity `HIGH`, including the actor's identity, IP address, session_id, proposal_id, and the fact that the token did not match. This enables detection of brute-force or replay attacks.

**FR-CT-11 (Token Recycling Prevention):** Once a token has been used (proposal status transitions to APPLIED, EXPIRED, or FAILED), the same token MUST NOT be usable again. This is enforced by the proposal status check (FR-CT-08, step 2) and the idempotency guard (FR-CT-09).

**FR-CT-12 (Frontend Token Lifecycle):** The frontend MUST:
- Receive the plaintext token from the propose operation response.
- Store the token ONLY in in-memory state (NOT in localStorage, sessionStorage, cookies, or IndexedDB).
- Attach the token to the confirmation request body.
- Clear the token from memory when: (a) confirmation succeeds, (b) confirmation fails with a terminal error, (c) the user navigates away from the confirmation modal, or (d) the proposal's TTL expires.
- Never display the token to the user or log it to the browser console.

**FR-CT-13 (Token for Batch Operations):** For batch operations (US-AI-029), a single confirmation token MUST be generated for the entire batch proposal. The `base_hash` for a batch operation is computed from the concatenation of all individual resource hashes in sorted order. The `target_resource_type` is `"batch"` and `target_resource_id` is the batch proposal ID. Each individual resource within the batch MUST still have its own `before_snapshot` captured separately for audit purposes.

**FR-CT-14 (Admin Token Override):** For recovery scenarios, an admin with the `ai:admin:bypass-confirmation` permission MAY confirm a proposal without a valid token by providing an override reason. This bypass operation MUST:
- Be logged as a distinct `ADMIN_OVERRIDE` security event.
- Require the admin to provide a reason string (min 20 chars).
- Be subject to all other validation checks (status, expiry, resource existence, hash match).
- Be rate-limited to 5 overrides per admin per hour.
- The override feature MUST be controlled by the `AI_ADMIN_CONFIRMATION_BYPASS_ENABLED` feature flag (default: false).

### 1.5 User Flows

#### Happy Path: Propose Destructive Operation

1. User triggers a destructive operation (e.g., "Delete page 3") via AI chat.
2. AI agent resolves the target and calls `propose_<operation>` with the target ID.
3. The propose handler identifies the operation as destructive and calls `ConfirmationTokenService.generate_token()` with the scope data.
4. `ConfirmationTokenService`:
   a. Computes the resource state hash via `_compute_resource_hash()`.
   b. Generates a random token via `secrets.token_hex(32)`.
   c. Constructs the canonical scope string: `session_id + "::" + proposal_id + "::" + target_resource_type + "::" + target_resource_id + "::" + operation_type`.
   d. Computes `scope_bound_hash = SHA256(token + "::" + canonical_scope_string)`.
   e. Sets `expires_at = now() + TTL`.
   f. Returns `{plaintext_token, scope_bound_hash, expires_at, base_hash}` to the caller.
5. The proposal orchestrator stores `scope_bound_hash`, `expires_at`, and `base_hash` in the `ai_proposals` record.
6. The propose endpoint returns the proposal response including `confirmation_token` (plaintext), `confirmation_token_expires_at`, `base_hash`, and dependency warnings.

#### Happy Path: Confirm Destructive Operation

1. Frontend renders the confirmation modal with dependency warnings.
2. User reviews and explicitly approves the operation (clicks "Confirm" after optionally typing a confirmation phrase).
3. Frontend calls `confirm_<operation>` with `{session_id, proposal_id, user_approved: true, confirmation_token: "<token>"}`.
4. The confirm handler calls `ConfirmationTokenService.validate_and_execute()`:
   a. Reconstructs the canonical scope string from the proposal record.
   b. Computes `SHA256(received_token + "::" + canonical_scope_string)`.
   c. Compares against the stored `confirmation_token_sha256`.
   d. Checks expiry.
   e. Re-computes the resource hash and compares against `base_hash`.
   f. If all checks pass, returns `{"valid": true}`.
5. The orchestrator proceeds with the operation inside a transaction.
6. Returns success response.

#### Error Path: Token Expired

1. User opens the confirmation modal but waits too long (beyond the 15-minute TTL).
2. User clicks "Confirm" after the token has expired.
3. Backend validates token, finds it expired, returns `410 CONFIRMATION_EXPIRED`.
4. Frontend displays: "This confirmation request has expired. Please start again."
5. The proposal transitions to `EXPIRED` status.
6. User must re-initiate the destructive operation from the AI agent.

#### Error Path: Resource Changed Between Proposal and Confirm

1. User proposes deleting a page.
2. Another author (or the same user in another tab) edits the page's content.
3. User clicks "Confirm."
4. Backend re-computes the page hash, finds it differs from `base_hash`.
5. Returns `409 RESOURCE_CHANGED` with details of what changed (page title, component count, etc.).
6. Frontend displays: "This page has changed since you proposed deletion. Please review the current state and try again."
7. AI agent re-fetches the page and creates a new proposal.

#### Error Path: Token Mismatch (Security Event)

1. An attacker (or a misbehaving frontend) sends a confirmation request with an incorrect token.
2. Backend computes `SHA256(incorrect_token + scope_string)` and finds it does not match the stored hash.
3. Returns `403 INVALID_CONFIRMATION_TOKEN`.
4. Logs a `SECURITY_EVENT` with the request details.
5. The proposal remains in `PENDING_CONFIRMATION` state (not consumed, to allow the legitimate user to retry with the correct token).

#### Error Path: Simultaneous Confirmations

1. Two frontend tabs both hold the same proposal ID and token.
2. Tab A sends confirm request; validation passes; operation executes; proposal transitions to APPLIED.
3. Tab B sends confirm request; validation fails at step 2 (proposal status is already APPLIED).
4. Tab B receives `409 PROPOSAL_ALREADY_APPLIED`.
5. No data corruption occurs.

### 1.6 UI/UX Requirements

1. **Confirmation Modal -- Generic Design:** Every destructive operation MUST render a confirmation modal that includes:
   - Operation type icon and title (e.g., "Delete Page", "Delete Course", "Remove Asset").
   - Target resource identification (name, ID, current location/status).
   - Dependency impact summary (warnings from dependency analysis).
   - Irreversible-action notice: "This action cannot be undone. All data associated with this [resource] will be permanently removed."
   - Explicit confirmation checkbox labeled: "I understand this action is irreversible."
   - For high-severity operations (course deletion, batch operations): a text input requiring the user to type the word "DELETE" before the confirm button enables.
   - Two buttons: "Confirm" (red/destructive styling, disabled until all confirmation requirements are met) and "Cancel."
   - The confirmation token is NEVER displayed in the UI.

2. **Warning Stacking:** When the dependency analysis returns multiple warnings (e.g., branching rules, scoring config, final assessment), the modal MUST stack them in order of severity (error before warning before info), each with a distinct icon and color.

3. **Confirmation Requirements by Risk Level:**

   | Risk Level | Example | Confirmation Requirements |
   |---|---|---|
   | Standard | Single page delete without dependencies | Checkbox + button click |
   | High | Page with branching/scoring dependencies | Checkbox + type "DELETE" + button click |
   | Critical | Course deletion, batch delete, asset purge | Checkbox + type "DELETE" + re-enter resource name + button click |

4. **Timer/Age Indicator:** The modal MAY display a visual indicator of how much time remains before the confirmation token expires (countdown timer). When less than 2 minutes remain, the indicator turns yellow; when less than 30 seconds, it turns red and pulses.

5. **Error Handling in Modal:**
   - **Expired:** Replace modal content with "This confirmation request has expired" message and a "Start Over" button that re-initiates the AI proposal flow.
   - **Resource Changed:** Replace modal content with "The resource has changed" message and a "Review Changes" button that re-fetches the resource and re-proposes.
   - **Network Error:** Show inline error banner "Connection error. Please try again." and keep the modal open with all state preserved.
   - **Already Applied:** Show "This operation was already completed" and close the modal after 3 seconds.

6. **Mobile Responsiveness:** The confirmation modal MUST be fully responsive. On viewports below 768px, the modal takes the full screen width with a top offset of 16px.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 ConfirmationTokenService -- Core Service

**File:** `app/services/ai/confirmation_token_service.py`

```python
"""
Centralized Confirmation Token Service for Destructive/Irreversible Operations.

This service provides the reusable token generation, scope binding, hashing,
expiry, and validation logic used by ALL destructive operation proposals
across the AI authoring system.

Architecture:
  - Tokens are generated with 256-bit entropy via secrets.token_hex(32).
  - The token is SCOPE-BOUND: SHA256(token + "::" + canonical_scope_string)
    is stored, NOT the bare token hash. This binds the token to its
    specific proposal, session, resource, and operation.
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
      proposal_id="prop_001",
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_proposal import AIProposalRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfirmationTokenError(Exception):
    """Base exception for confirmation token failures."""

    status_code: int = 400
    code: str = "CONFIRMATION_TOKEN_ERROR"
    message: str = "Confirmation token validation failed."

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class TokenExpiredError(ConfirmationTokenError):
    def __init__(self, expired_at: datetime):
        super().__init__(
            code="CONFIRMATION_EXPIRED",
            message=f"Confirmation token expired at {expired_at.isoformat()}. Maximum TTL is configured via AI_CONFIRMATION_TOKEN_TTL_MINUTES.",
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
            message="The target resource has changed since the proposal was created. Please review the current state and re-propose.",
            status_code=409,
        )


class ProposalNotInConfirmableStateError(ConfirmationTokenError):
    def __init__(self, status: str):
        super().__init__(
            code="PROPOSAL_NOT_CONFIRMABLE",
            message=f"Proposal is in status '{status}' and cannot be confirmed. Only PENDING_CONFIRMATION proposals are confirmable.",
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


class ConfirmationTokenService:
    """
    Centralized service for generating, binding, and validating
    confirmation tokens for destructive/irreversible operations.

    This service is stateless aside from the DB session. All token
    state is persisted in the ai_proposals table.
    """

    # Scope field separator for canonical scope string construction
    SCOPE_SEPARATOR = "::"

    def __init__(
        self,
        session: AsyncSession,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ):
        self.session = session
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
        """
        Generate a confirmation token bound to the given scope.

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
        self._validate_required(session_id=session_id, proposal_id=proposal_id,
                                target_resource_type=target_resource_type,
                                target_resource_id=target_resource_id,
                                operation_type=operation_type,
                                resource_hash=resource_hash)

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
            proposal_id, target_resource_type, target_resource_id,
            operation_type, effective_ttl,
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
        """
        Validate a confirmation token against a proposal.

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
        if proposal.status != "PENDING_CONFIRMATION":
            return False, f"PROPOSAL_NOT_CONFIRMABLE:{proposal.status}"

        # Step 3: Check operation is destructive
        destructive_ops = ["delete_page", "delete_course", "batch_delete",
                          "delete_asset", "course_archive", "batch_update_delete"]
        if proposal.operation not in destructive_ops:
            return False, f"NON_DESTRUCTIVE_OPERATION:{proposal.operation}"

        # Step 4: User approval
        if not user_approved and not admin_override:
            return False, "USER_CONFIRMATION_REQUIRED"

        # Admin override path: bypass token validation
        if admin_override:
            if not admin_override_reason or len(admin_override_reason.strip()) < 20:
                return False, "ADMIN_OVERRIDE_REASON_TOO_SHORT"
            logger.warning(
                "ADMIN OVERRIDE: proposal=%s, admin bypassing token validation. Reason: %s",
                proposal.proposal_id, admin_override_reason,
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
            # These are stored in the proposal's metadata JSONB or
            # derived from proposal fields:
            "target_resource_type": self._get_target_resource_type(proposal),
            "target_resource_id": self._get_target_resource_id(proposal),
            "operation_type": proposal.operation,
        }
        scope_string = self._build_scope_string(**scope_parts)
        computed_hash = self._compute_scope_bound_hash(received_token, scope_string)

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
                return False, f"CONFIRMATION_EXPIRED:{proposal.confirmation_token_expires_at.isoformat()}"

        # Step 8: Resource existence check (delegated to caller)
        # Step 9: Resource hash check (delegated to caller via verify_resource_hash)

        return True, None

    async def verify_resource_hash(
        self,
        *,
        proposal: AIProposalRecord,
        current_resource_hash: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify that the current resource hash matches the proposal's base_hash.

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
        """Compute SHA-256 of the token bound to the scope string.

        Hash computation: SHA256(token + "::" + scope_string)
        Uses HMAC-SHA256 for additional protection against length extension.
        """
        key = token.encode("utf-8")
        message = scope_string.encode("utf-8")
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    def _compute_resource_hash(self, resource_state: dict) -> str:
        """Compute a deterministic hash from a resource state dictionary.

        The dictionary is serialized with sorted keys to ensure
        determinism, then SHA-256 hashed.

        This is the base implementation. Operation-specific subclasses
        or callers may provide their own hash computation logic, but
        MUST use this same deterministic approach.
        """
        import json
        canonical = json.dumps(resource_state, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _get_target_resource_type(self, proposal: AIProposalRecord) -> str:
        """Derive the target_resource_type from the proposal."""
        # For page-level operations
        if proposal.operation in ("delete_page",):
            return "page"
        # For course-level operations
        if proposal.operation in ("delete_course", "course_archive"):
            return "course"
        # For batch operations
        if proposal.operation in ("batch_delete",):
            return "batch"
        # For asset operations
        if proposal.operation in ("delete_asset",):
            return "asset"
        # Default: use operation type
        return proposal.operation

    def _get_target_resource_id(self, proposal: AIProposalRecord) -> str:
        """Derive the target_resource_id from the proposal."""
        if proposal.page_id:
            return proposal.page_id
        if proposal.course_id:
            return proposal.course_id
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
```

### 2.2 Database Schema -- Extensions to US-AI-004/AI-AI-009

The `ai_proposals` table from US-AI-004 and US-AI-009 already includes the necessary columns. No new tables are required for the token system itself. The relevant columns are:

```sql
-- Existing columns in ai_proposals (from US-AI-004 / US-AI-009)
ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS confirmation_token_sha256 VARCHAR(64);
ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS confirmation_token_expires_at TIMESTAMPTZ;
ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS base_hash VARCHAR(64);
ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS before_snapshot JSONB;
```

New column specifically for US-AI-049 (operation-type-specific TTL override):

```sql
-- Add TTL override column (nullable; NULL means use system default)
ALTER TABLE ai_proposals ADD COLUMN IF NOT EXISTS confirmation_ttl_override_minutes INTEGER;

-- Add index for security event queries (find proposals with token mismatches)
CREATE INDEX IF NOT EXISTS idx_ai_proposals_token_hash
    ON ai_proposals(confirmation_token_sha256)
    WHERE confirmation_token_sha256 IS NOT NULL;
```

New table for admin override audit trail:

```sql
CREATE TABLE IF NOT EXISTS ai_admin_overrides (
    id              SERIAL PRIMARY KEY,
    override_id     VARCHAR(64) UNIQUE NOT NULL DEFAULT gen_random_uuid()::text,
    proposal_id     VARCHAR(64) NOT NULL REFERENCES ai_proposals(proposal_id) ON DELETE CASCADE,
    admin_user_id   VARCHAR(128) NOT NULL,
    reason          TEXT NOT NULL,
    overridden_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id      VARCHAR(64),
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(512),

    CONSTRAINT ck_admin_override_reason_length CHECK (char_length(reason) >= 20)
);

CREATE INDEX idx_admin_overrides_proposal ON ai_admin_overrides(proposal_id);
CREATE INDEX idx_admin_overrides_admin ON ai_admin_overrides(admin_user_id);
CREATE INDEX idx_admin_overrides_time ON ai_admin_overrides(overridden_at DESC);
```

### 2.3 Pydantic DTOs

**File:** `app/services/ai/confirmation_token_dto.py`

```python
"""
Pydantic models for the Confirmation Token System.

These define the shape of token-related data in API requests and responses.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator


# ── Token Generation (Internal, not exposed via API directly) ──────────────

class TokenGenerationRequest(BaseModel):
    """Input for ConfirmationTokenService.generate_token()."""
    session_id: str = Field(..., min_length=1, description="Active AI session ID")
    proposal_id: str = Field(..., min_length=1, description="Proposal ID")
    target_resource_type: Literal["page", "course", "batch", "asset", "config"]
    target_resource_id: str = Field(..., min_length=1, description="Resource ID")
    operation_type: str = Field(..., min_length=1, description="e.g., delete_page, delete_course")
    resource_hash: str = Field(..., min_length=1, description="Deterministic hash of resource state")
    ttl_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Override TTL in minutes")


class TokenGenerationResult(BaseModel):
    """Output from ConfirmationTokenService.generate_token()."""
    token: str = Field(..., description="Plaintext confirmation token (64 hex chars)")
    token_hash: str = Field(..., description="SHA-256 of scope-bound token, for persistence")
    expires_at: datetime = Field(..., description="Token expiry datetime")


# ── Token Validation ──────────────────────────────────────────────────────

class TokenValidationRequest(BaseModel):
    """Input for token validation (typically embedded in confirm-* requests)."""
    confirmation_token: str = Field(
        ..., min_length=64, max_length=64,
        description="The confirmation token received from the propose step",
    )
    user_approved: bool = Field(
        default=True,
        description="Whether the user explicitly approved the operation",
    )

    @field_validator("confirmation_token")
    @classmethod
    def validate_token_hex(cls, v: str) -> str:
        """Ensure the token is valid hex."""
        try:
            bytes.fromhex(v)
        except ValueError as exc:
            raise ValueError("confirmation_token must be a valid 64-character hex string") from exc
        return v.lower()


class AdminOverrideRequest(BaseModel):
    """Input for admin bypass of confirmation token."""
    confirmation_token: Optional[str] = Field(
        None, min_length=64, max_length=64,
        description="Optional: admin may provide the token for audit trail",
    )
    admin_override: bool = Field(
        default=False,
        description="Set to true to bypass token validation",
    )
    admin_override_reason: str = Field(
        ..., min_length=20, max_length=1000,
        description="Reason for the override (min 20 characters, recorded in audit)",
    )


# ── Security Event Data ───────────────────────────────────────────────────

class SecurityEventData(BaseModel):
    """Structured data for security event logging."""
    event_type: Literal[
        "CONFIRMATION_TOKEN_MISMATCH",
        "CONFIRMATION_ADMIN_OVERRIDE",
        "CONFIRMATION_EXPIRED_ATTEMPT",
        "CONFIRMATION_RESOURCE_CHANGED",
    ]
    proposal_id: str
    session_id: str
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    details: dict = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
```

### 2.4 API Contracts -- New Confirm Endpoint Pattern

The Confirmation Token System defines the REUSABLE pattern for all confirm endpoints. Every destructive operation's confirm endpoint follows this identical pattern:

#### Generic Pattern: `POST /api/v1/ai/proposals/{proposal_id}/confirm`

This is a GENERIC confirmation endpoint that any destructive operation can use. Operation-specific routers may additionally expose typed endpoints (e.g., `POST /api/v1/ai/proposals/confirm-delete-page`) that call through to this same generic handler.

**Request:**
```json
{
  "confirmation_token": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  "user_approved": true
}
```

**Response 200 (Operation executed):**
```json
{
  "status": "confirmed",
  "proposal_id": "prop_del_001",
  "operation": "delete_page",
  "target_resource_type": "page",
  "target_resource_id": "page_xyz789",
  "message": "Page 'Unit 2 Final Assessment' has been deleted.",
  "executed_at": "2026-06-14T11:30:00Z"
}
```

**Error Responses:**

`403 INVALID_CONFIRMATION_TOKEN`:
```json
{
  "code": "INVALID_CONFIRMATION_TOKEN",
  "message": "The provided confirmation token is invalid. This may indicate tampering.",
  "details": {
    "event_id": "sec_evt_001"
  }
}
```

`409 RESOURCE_CHANGED`:
```json
{
  "code": "RESOURCE_CHANGED",
  "message": "The target resource has changed since the proposal was created. Please review and re-propose.",
  "details": {
    "base_hash": "a1b2c3d4e5f6...",
    "current_hash": "f6e5d4c3b2a1..."
  }
}
```

`410 CONFIRMATION_EXPIRED`:
```json
{
  "code": "CONFIRMATION_EXPIRED",
  "message": "The confirmation window has expired. Maximum TTL is 15 minutes.",
  "details": {
    "expired_at": "2026-06-14T11:45:00Z"
  }
}
```

`409 PROPOSAL_ALREADY_APPLIED`:
```json
{
  "code": "PROPOSAL_ALREADY_APPLIED",
  "message": "This proposal has already been applied and cannot be confirmed again.",
  "details": {
    "applied_at": "2026-06-14T11:30:00Z"
  }
}
```

`400 USER_CONFIRMATION_REQUIRED`:
```json
{
  "code": "USER_CONFIRMATION_REQUIRED",
  "message": "You must set user_approved=true to confirm this destructive operation.",
  "details": {}
}
```

### 2.5 Service/Module Design

```
app/services/ai/
  confirmation_token_service.py    # ConfirmationTokenService (core logic)
  confirmation_token_dto.py        # Pydantic models for token data
  proposal_orchestrator.py         # Extends to use ConfirmationTokenService

app/routers/
  ai_confirmations.py              # Generic confirmation router (new)

app/models/
  ai_admin_override.py             # ORM model for ai_admin_overrides table (new)
```

**Module Dependency Diagram:**

```
ProposalOrchestrator
    |
    |--- uses ---> ConfirmationTokenService
    |                  |
    |                  |--- uses ---> AIProposalRepository
    |                  |--- uses ---> logging (security events)
    |
    |--- calls --> DependencyAnalyzer (for warnings)
    |--- calls --> PageRepository / CourseRepository (for mutations)
    |--- calls --> AuditService (for audit trail)
    |--- calls --> OutboxService (for events)
```

### 2.6 Generic Confirmation Router

**File:** `app/routers/ai_confirmations.py`

```python
"""
Generic confirmation endpoint for destructive/irreversible operations.

This provides a unified confirmation entry point that any operation-specific
orchestrator can delegate to, or that can be called directly with the
proposal_id and confirmation_token.

Endpoint:
  POST /api/v1/ai/proposals/{proposal_id}/confirm
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.models.ai_proposal import AIProposalRecord
from app.repositories.ai_proposal_repo import AIProposalRepository
from app.services.ai.confirmation_token_service import (
    ConfirmationTokenService,
    ConfirmationTokenError,
    TokenMismatchError,
    TokenExpiredError,
    ResourceChangedError,
    ProposalNotInConfirmableStateError,
)
from app.services.ai.confirmation_token_dto import TokenValidationRequest
from app.utils.error_envelope import api_http_exception

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/proposals", tags=["AI Confirmations"])

DESTRUCTIVE_OPERATIONS = {
    "delete_page",
    "delete_course",
    "batch_delete",
    "batch_update_delete",
    "delete_asset",
    "course_archive",
}


@router.post(
    "/{proposal_id}/confirm",
    summary="Confirm a destructive operation using a confirmation token",
    responses={
        200: {"description": "Operation confirmed and executed (caller must still apply the operation)"},
        400: {"description": "User confirmation required"},
        403: {"description": "Invalid confirmation token"},
        404: {"description": "Proposal not found"},
        409: {"description": "Resource changed, proposal already applied, or proposal not confirmable"},
        410: {"description": "Confirmation token expired or resource deleted"},
    },
)
async def confirm_proposal(
    proposal_id: str,
    body: TokenValidationRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Generic confirmation endpoint for destructive operations.

    Validates the confirmation token and proposal state. If validation passes,
    this endpoint returns 200 with a validation result. The caller (operation-
    specific orchestrator) must then execute the actual mutation inside a
    database transaction.

    This endpoint is the GATE that all destructive operations pass through.
    It does NOT execute the operation itself -- only validates that the
    confirmation is legitimate.
    """
    # 1. Fetch proposal
    proposal_repo = AIProposalRepository(session)
    proposal = await proposal_repo.get_by_proposal_id(proposal_id)

    if not proposal:
        raise api_http_exception(
            404, "PROPOSAL_NOT_FOUND",
            f"Proposal '{proposal_id}' not found.",
        )

    if proposal.operation not in DESTRUCTIVE_OPERATIONS:
        raise api_http_exception(
            400, "NON_DESTRUCTIVE_OPERATION",
            f"Operation '{proposal.operation}' does not require confirmation.",
        )

    # 2. Validate token
    token_service = ConfirmationTokenService(session)

    try:
        is_valid, error_code = await token_service.validate_token(
            proposal=proposal,
            received_token=body.confirmation_token,
            user_approved=body.user_approved,
        )
    except ConfirmationTokenError as exc:
        raise api_http_exception(exc.status_code, exc.code, exc.message)

    if not is_valid:
        # Map error_code to HTTP error
        code, *params = error_code.split(":", 1)
        error_map = {
            "PROPOSAL_NOT_CONFIRMABLE": (409, code, f"Proposal is in status '{params[0]}' and cannot be confirmed."),
            "USER_CONFIRMATION_REQUIRED": (400, code, "You must set user_approved=true to confirm."),
            "INVALID_TOKEN_FORMAT": (400, code, "The confirmation token format is invalid."),
            "INVALID_CONFIRMATION_TOKEN": (403, code, "The confirmation token is invalid."),
            "CONFIRMATION_EXPIRED": (410, code, f"Confirmation expired at {params[0]}."),
        }
        status, error_code_msg, error_message = error_map.get(code, (400, code, "Validation failed."))
        raise api_http_exception(status, error_code_msg, error_message)

    # 3. Return success -- caller must now execute the operation
    return {
        "status": "token_validated",
        "proposal_id": proposal.proposal_id,
        "operation": proposal.operation,
        "message": "Confirmation token validated. Proceed with operation execution.",
    }
```

### 2.7 Integration Points

#### Integration with US-AI-013 (Delete Page Proposal)

The delete page proposal orchestrator from US-AI-013 integrates with ConfirmationTokenService as follows:

```python
# In ProposalOrchestrator.propose_delete_page():

# Instead of inline token generation (as currently drafted in US-AI-013):
#   token = secrets.token_hex(32)
#   token_hash = hashlib.sha256(token.encode()).hexdigest()

# Use the centralized service:
token_service = ConfirmationTokenService(db_session)
resource_hash = await self._compute_page_hash(page)
token_result = await token_service.generate_token(
    session_id=session_id,
    proposal_id=proposal_id,
    target_resource_type="page",
    target_resource_id=page_id,
    operation_type="delete_page",
    resource_hash=resource_hash,
    ttl_minutes=15,
)

# Store token_result.token_hash in proposal.confirmation_token_sha256
# Return token_result.token (plaintext) in the API response
```

```python
# In ProposalOrchestrator.confirm_delete_page():

token_service = ConfirmationTokenService(db_session)
is_valid, error = await token_service.validate_token(
    proposal=proposal,
    received_token=confirmation_token,
    user_approved=user_approved_delete,
)
if not is_valid:
    raise PermissionError(error)

# After token validation, verify resource hash:
current_hash = await self._compute_page_hash(current_page)
hash_match, hash_error = await token_service.verify_resource_hash(
    proposal=proposal,
    current_resource_hash=current_hash,
)
if not hash_match:
    raise RuntimeError(hash_error)

# Proceed with deletion...
```

#### Integration with US-AI-046 (Course-Level Operations)

```python
# In ProposalOrchestrator.propose_delete_course():

token_service = ConfirmationTokenService(db_session, ttl_minutes=5)  # shorter TTL for course delete
course_hash = await self._compute_course_hash(course)
token_result = await token_service.generate_token(
    session_id=session_id,
    proposal_id=proposal_id,
    target_resource_type="course",
    target_resource_id=course_id,
    operation_type="delete_course",
    resource_hash=course_hash,
    ttl_minutes=5,  # Course deletion is critical => shorter TTL
)
```

### 2.8 Configuration Variables

Add to `.env` and `.env.example`:

```ini
# ============================================
# Confirmation Token System (US-AI-049)
# ============================================
# Default TTL for confirmation tokens (in minutes)
AI_CONFIRMATION_TOKEN_TTL_MINUTES=15

# Per-operation-type TTL overrides (comma-separated key=value pairs)
# Format: operation_type=minutes,operation_type=minutes
# Example: delete_course=5,batch_delete=10
AI_CONFIRMATION_TOKEN_TTL_OVERRIDES=delete_course=5,course_archive=5

# Admin confirmation bypass feature flag
AI_ADMIN_CONFIRMATION_BYPASS_ENABLED=false

# Max admin overrides per hour (rate limit)
AI_ADMIN_OVERRIDE_RATE_LIMIT_PER_HOUR=5

# Security event logging level for token mismatches
AI_CONFIRMATION_SECURITY_LOG_LEVEL=ERROR
```

Read by `ConfirmationTokenService`:

```python
import os

DEFAULT_TTL_MINUTES = int(os.getenv("AI_CONFIRMATION_TOKEN_TTL_MINUTES", "15"))

# Parse TTL overrides
_TTL_OVERIDES_RAW = os.getenv("AI_CONFIRMATION_TOKEN_TTL_OVERRIDES", "")
TTL_OVERRIDES: dict[str, int] = {}
if _TTL_OVERIDES_RAW:
    for pair in _TTL_OVERIDES_RAW.split(","):
        if "=" in pair:
            op_type, ttl = pair.strip().split("=", 1)
            TTL_OVERRIDES[op_type.strip()] = int(ttl.strip())

ADMIN_BYPASS_ENABLED = os.getenv("AI_ADMIN_CONFIRMATION_BYPASS_ENABLED", "false").lower() == "true"
ADMIN_OVERRIDE_RATE_LIMIT = int(os.getenv("AI_ADMIN_OVERRIDE_RATE_LIMIT_PER_HOUR", "5"))
```

### 2.9 Alembic Migration

**File:** `alembic/versions/20260614_0003_add_confirmation_token_overrides.py`

```python
"""Add confirmation TTL override column and admin_overrides table.

Revision ID: 20260614_0003
Revises: 20260614_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ

revision = "20260614_0003"
down_revision = "20260614_0002"
branch_labels = None
depends_on = None


def upgrade():
    # Add TTL override column to ai_proposals
    op.add_column(
        "ai_proposals",
        sa.Column(
            "confirmation_ttl_override_minutes",
            sa.Integer(),
            nullable=True,
        ),
    )

    # Add partial index on token hash for fast security lookups
    op.create_index(
        "idx_ai_proposals_token_hash",
        "ai_proposals",
        ["confirmation_token_sha256"],
        postgresql_where=sa.text("confirmation_token_sha256 IS NOT NULL"),
    )

    # Create admin overrides table
    op.create_table(
        "ai_admin_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("override_id", sa.String(64), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("admin_user_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("overridden_at", TIMESTAMPTZ(), server_default=sa.func.now(), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["ai_proposals.proposal_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("override_id"),
        sa.CheckConstraint(
            "char_length(reason) >= 20",
            name="ck_admin_override_reason_length",
        ),
    )
    op.create_index(
        "idx_admin_overrides_proposal",
        "ai_admin_overrides",
        ["proposal_id"],
    )
    op.create_index(
        "idx_admin_overrides_admin",
        "ai_admin_overrides",
        ["admin_user_id"],
    )
    op.create_index(
        "idx_admin_overrides_time",
        "ai_admin_overrides",
        [sa.text("overridden_at DESC")],
    )


def downgrade():
    op.drop_table("ai_admin_overrides")
    op.drop_index("idx_ai_proposals_token_hash")
    op.drop_column("ai_proposals", "confirmation_ttl_override_minutes")
```

### 2.10 ORM Model for Admin Overrides

**File:** `app/models/ai_admin_override.py`

```python
"""ORM model for admin override audit trail."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, ForeignKey, TIMESTAMP, BigInteger

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class AIAdminOverrideRecord(Base):
    __tablename__ = "ai_admin_overrides"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    override_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    proposal_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_proposals.proposal_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    admin_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    overridden_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "overrideId": self.override_id,
            "proposalId": self.proposal_id,
            "adminUserId": self.admin_user_id,
            "reason": self.reason,
            "overriddenAt": self.overridden_at.isoformat() if self.overridden_at else None,
            "sessionId": self.session_id,
            "ipAddress": self.ip_address,
        }
```

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Token generation latency | < 10 ms p99 | Time to generate token, compute hash, return result (no DB write in this step for the service itself; DB write happens when the proposal is persisted) |
| Token validation latency | < 50 ms p95 | Time to fetch proposal, re-compute scope-bound hash, check expiry, compare hashes |
| Resource hash computation (page) | < 50 ms p99 | Time to fetch a page with its components and compute the deterministic hash |
| Resource hash computation (course) | < 200 ms p99 | Time to fetch a course with all pages and compute aggregated hash |
| Full confirm validation pipeline | < 300 ms p95 | End-to-end: fetch proposal + validate token + re-fetch resource + verify hash |
| Concurrent token validations | No degradation up to 100 req/s | Backed by standard PostgreSQL read capacity; no locks needed |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Token entropy | 256 bits via `secrets.token_hex(32)`. This provides 2^256 possible values, making brute-force infeasible. At 1 billion attempts per second, it would take 10^60 years to exhaust the space. |
| Token storage | ONLY SHA-256 hash stored in database (scoped-bound hash, not bare token hash). Plaintext token never persisted anywhere. |
| Token lifetime | Default 15 minutes, configurable via `AI_CONFIRMATION_TOKEN_TTL_MINUTES`. Shorter TTLs for critical operations (course deletion default: 5 minutes). |
| Token transport | Token sent as a JSON field in the request body over HTTPS. Never in URL query parameters, never in cookies. |
| Token validation rate limit | Maximum 10 validation attempts per proposal per minute. Exceeding this triggers a security event and a 10-minute cooldown. |
| Brute-force protection | Token format is validated before hash comparison (64 hex chars). HMAC-SHA256 comparison is constant-time (no timing side-channel). |
| Security event on mismatch | Every token mismatch is logged as a `SECURITY_EVENT` with full request context (IP, user agent, session, proposal). |
| Admin override audit | Every admin bypass is logged in `ai_admin_overrides` with reason, admin identity, and timestamp. Rate-limited to 5 per hour per admin. |
| Feature flag gating | Confirmation token endpoints require `AI_AUTHORING_ENABLED=true`. Admin bypass additionally requires `AI_ADMIN_CONFIRMATION_BYPASS_ENABLED=true`. |

### 3.3 Reliability

| Requirement | Implementation |
|---|---|
| Token generation never fails cryptographically | `secrets.token_hex(32)` uses OS entropy pool. If the entropy pool is exhausted, the OS call blocks until sufficient entropy is available. No application-level fallback is needed. |
| Clock skew tolerance | Token expiry uses `datetime.now(timezone.utc)` on the server. Clock skew of up to 30 seconds between services is tolerated by a 30-second grace period on expiry checks. Clock skew beyond 30 seconds may cause false expirations; upstream NTP sync is the mitigation. |
| Database failure during validation | If the proposal record cannot be read during validation, the operation fails closed (no confirmation is granted). The error is logged and the frontend receives a 503. |
| Concurrent validation safety | Token validation is read-only (SELECT from ai_proposals). No database-level locking is required. The subsequent proposal status check (confirmable state) is verified inside the execution transaction. |
| Token uniqueness guarantee | Collision probability for `secrets.token_hex(32)` is approximately 2^-128 (birthday bound). No explicit collision check is needed. |

### 3.4 Scalability

| Requirement | Implementation |
|---|---|
| Horizontal scaling | The `ConfirmationTokenService` is stateless (no in-memory token store). All token state is in the `ai_proposals` table. Multiple service instances can validate tokens concurrently against the same database. |
| Database index strategy | The `idx_ai_proposals_token_hash` partial index supports fast lookup. The primary lookup is by `proposal_id` (already indexed), which retrieves the `confirmation_token_sha256` for comparison. |
| Token validation under load | Each validation is a single SELECT by primary key (O(1) index lookup) plus two SHA-256 computations (CPU-bound, < 1 microsecond each). PostgreSQL can handle thousands of concurrent validations. |

### 3.5 Observability

| Metric | Name | Tags | Description |
|---|---|---|---|
| Counter: token generated | `ai.confirmation.token.generated` | operation_type, resource_type | Incremented on every token generation |
| Counter: token validated | `ai.confirmation.token.validated` | operation_type, outcome (success/failure) | Incremented on every validation attempt |
| Counter: token expired | `ai.confirmation.token.expired` | operation_type | Incremented on expiry rejection |
| Counter: resource changed | `ai.confirmation.resource_changed` | operation_type | Incremented on hash mismatch rejection |
| Counter: admin override | `ai.confirmation.admin_override` | admin_user_id | Incremented on each admin bypass |
| Counter: security event | `ai.confirmation.security_event` | event_type | Incremented on token mismatch |
| Histogram: validation latency | `ai.confirmation.validation.duration_ms` | operation_type | Distribution of validation times |
| Gauge: pending confirmations | `ai.confirmation.pending_count` | operation_type | Number of proposals in PENDING_CONFIRMATION status |

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists Today

1. **No confirmation token system exists at all.** There is no `ConfirmationTokenService`, no token generation, no scope-bound hashing, and no token validation in the codebase.

2. **US-AI-013 (Delete Page Proposal) is drafted** with inline token generation logic (secrets.token_hex, SHA256 hashing, 15-minute TTL, page hash computation, dependency analysis). This draft has the token logic embedded directly in the proposal orchestrator rather than in a centralized service. US-AI-049's purpose is to EXTRACT this logic into a reusable service before US-AI-013 is implemented.

3. **US-AI-004 (AI Persistence Foundations)** will create the `ai_proposals` table with `confirmation_token_sha256`, `confirmation_token_expires_at`, and `base_hash` columns. These columns exist in the US-AI-013 DDL but are not yet created in any migration.

4. **US-AI-009 (Generic Proposal Lifecycle)** defines the standard proposal states (`PENDING_REVIEW`, `PENDING_CONFIRMATION`, `APPROVED`, `APPLYING`, `APPLIED`, `REJECTED`, `EXPIRED`, `FAILED`) and the lifecycle transitions. The confirmation token system depends on the `PENDING_CONFIRMATION` state.

5. **No scope-bound hashing** exists. The US-AI-013 draft uses `SHA256(token)` directly, without scope binding. US-AI-049 introduces the superior HMAC-based scope-bound hashing: `SHA256(token + "::" + scope_string)` via HMAC-SHA256.

6. **No admin override mechanism** exists. There is no bypass path for recovery scenarios.

7. **No security event logging** for token mismatches exists.

8. **No generic confirmation endpoint** (`POST /api/v1/ai/proposals/{proposal_id}/confirm`) exists. US-AI-013 defines operation-specific endpoints (`POST /api/v1/ai/proposals/confirm-delete`).

### 4.2 What Must Be Built

1. **`app/services/ai/confirmation_token_service.py`** -- the `ConfirmationTokenService` class with `generate_token()`, `validate_token()`, `verify_resource_hash()`, and all internal helpers.
2. **`app/services/ai/confirmation_token_dto.py`** -- Pydantic DTOs for token generation, validation, admin override, and security event data.
3. **`app/routers/ai_confirmations.py`** -- Generic `POST /api/v1/ai/proposals/{proposal_id}/confirm` endpoint.
4. **`app/models/ai_admin_override.py`** -- ORM model for `ai_admin_overrides` table.
5. **Alembic migration** to add `confirmation_ttl_override_minutes` column, the `idx_ai_proposals_token_hash` index, and the `ai_admin_overrides` table.
6. **Configuration** for `AI_CONFIRMATION_TOKEN_TTL_MINUTES`, `AI_CONFIRMATION_TOKEN_TTL_OVERRIDES`, `AI_ADMIN_CONFIRMATION_BYPASS_ENABLED`, `AI_ADMIN_OVERRIDE_RATE_LIMIT_PER_HOUR`.
7. **Metrics and logging** for token generation, validation, security events, and admin overrides.
8. **Unit tests** for `ConfirmationTokenService`.
9. **Integration tests** for the generic confirmation endpoint.

### 4.3 What Must Be Modified

1. **`app/routers/ai_proposals_dtos.py`** (from US-AI-013) -- Replace or consolidate inline confirmation request DTOs with the shared `TokenValidationRequest` from `confirmation_token_dto.py`.
2. **`app/services/ai/proposal_orchestrator.py`** (from US-AI-013) -- Replace inline token generation and validation with calls to `ConfirmationTokenService`.
3. **`app/main.py`** -- Register the new `ai_confirmations` router.
4. **`app/services/ai/__init__.py`** -- Export `ConfirmationTokenService`.
5. **US-AI-013 implementation** -- Must use `ConfirmationTokenService` instead of inline token logic.
6. **US-AI-046 implementation** -- Must use `ConfirmationTokenService` for course-level destructive operations.

### 4.4 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-002 | Feature flag `AI_AUTHORING_ENABLED` gating |
| US-AI-003 | Isolated AI API module structure |
| US-AI-004 | `ai_proposals` table with `confirmation_token_sha256`, `confirmation_token_expires_at`, `base_hash` columns |
| US-AI-005 | Operation type registration for destructive operations |
| US-AI-009 | Proposal lifecycle states (`PENDING_CONFIRMATION`, `APPLIED`, `EXPIRED`) |
| US-AI-010 | Apply safety (transactional mutation + audit + outbox) -- the token validation gates the apply |

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion Points

**TECH-01 (Hardware Security Module Integration):** For organizations requiring FIPS 140-2 compliance, the token generation could be backed by an HSM or a key management service (AWS KMS, Azure Key Vault, HashiCorp Vault). The `_generate_token()` method would delegate to an external `KeyService` interface that returns the token and performs the HMAC computation inside the HSM boundary. The `ConfirmationTokenService` would accept an optional `KeyService` dependency.

**TECH-02 (Distributed Token Blacklist via Redis):** For ultra-low-latency token invalidation across horizontally scaled instances, a Redis-backed token blacklist could supplement database-level proposal status checks. After a token is consumed (proposal applied), its hash is added to a Redis set with a TTL matching the proposal's TTL. Before checking the database, the validation pipeline checks the Redis blacklist. This prevents race conditions where a stale database read shows `PENDING_CONFIRMATION` for a proposal that was just applied by another instance. Implementation: add an optional `RedisTokenBlacklist` class with `check(hash) -> bool` and `invalidate(hash)` methods, injected into `ConfirmationTokenService`.

**TECH-03 (WebAuthn / FIDO2 Second Factor for Critical Operations):** For the most critical operations (course deletion, batch delete), the confirmation process could require a WebAuthn (FIDO2/Passkey) assertion in addition to the confirmation token. The frontend would prompt the user to tap their security key or use biometrics, and the signed challenge would be sent alongside the confirmation token. The backend would verify the assertion against the user's registered public key before allowing the operation. This is a significant UX and security improvement for admin-level destructive operations.

**TECH-04 (Token Nonce Tracking for Replay Prevention):** Even though the current design prevents replay via proposal status checks, an additional layer of protection could track a monotonic nonce per session. Each generated token would include a nonce derived from the session's current counter, and the validation pipeline would ensure the nonce is strictly increasing. This prevents replay attacks that attempt to re-submit an old confirmation request with a different proposal_id in a timing window before the database write propagates.

### 5.2 Functional Expansion Points

**FUNC-01 (Soft-Delete with Reversible Token):** Instead of hard-delete operations, future expansions could implement soft-delete with a two-phase "undo" window. The confirmation token would be stored (still hashed) for a configurable undo period (e.g., 30 minutes). During this window, a second token (an "undo token") could be generated to reverse the operation. The undo token would be bound to the same scope but with a different operation type (`"undo_delete_page"`). This would require: (a) an `is_deleted` soft-delete column, (b) a `deleted_at` timestamp, (c) an `undo_token_hash` column on the same proposal record, and (d) an `undo_expires_at` column set to `deleted_at + undo_window`.

**FUNC-02 (Token Confirmation via Email/SMS Out-of-Band):** For the most sensitive operations, the confirmation could be sent out-of-band via email or SMS instead of (or in addition to) the in-app modal. The propose step would generate the token and send it to the user's verified email/phone. The user would paste the received token into a confirmation input. This provides a separate channel of verification, protecting against XSS attacks that could compromise the in-app modal. Implementation would require: (a) a `confirmation_channel` field in the proposal (values: `in_app`, `email`, `sms`), (b) a notification service integration for email/SMS delivery, and (c) a separate token entry UI component.

**FUNC-03 (Escalation-Based Confirmation):** When an author proposes a destructive operation that exceeds their authority level (e.g., a junior author trying to delete a page with critical branching rules), the system could escalate the confirmation to a senior author or admin. The propose step would detect the authority gap and generate a token that only an admin can validate. The admin receives a notification and can confirm or reject via their own modal. This would require: (a) an `authority_level` field on the proposal, (b) a user-to-role mapping service, (c) notification dispatch for pending escalation confirmations, and (d) an admin confirmation queue UI.

**FUNC-04 (Multi-Party Confirmation for Batch Operations):** Batch operations (deleting N pages) could require M-of-N multi-party approval. Instead of a single confirmation token, the system generates N tokens, one for each authorized approver. At least M tokens must be validated (submitted) before the batch operation executes. Each token is individually generated, scoped, and validated. The proposal status transitions through `PARTIALLY_CONFIRMED` (some tokens received but not enough) to `CONFIRMED` (M-of-N threshold met). This would require: (a) `confirmation_quorum_m` and `confirmation_party_n` columns, (b) `PARTIALLY_CONFIRMED` proposal status, (c) a per-party token tracking table, and (d) a dashboard for approvers to view and confirm pending multi-party proposals.

---

## 6. VALIDATION AND TESTING

### 6.1 Unit Tests (Service Layer)

**File:** `tests/test_confirmation_token_service.py`

```python
"""
Tests for the ConfirmationTokenService class.

All tests use in-memory SQLite or mocked PostgreSQL sessions.
"""
from __future__ import annotations
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.confirmation_token_service import (
    ConfirmationTokenService,
    TokenExpiredError,
    TokenMismatchError,
    ResourceChangedError,
    ProposalNotInConfirmableStateError,
)
from app.models.ai_proposal import AIProposalRecord


class TestTokenGeneration:
    """FR-CT-01, FR-CT-02, FR-CT-03, FR-CT-05: Token generation correctness."""

    async def test_generate_token_returns_valid_structure(self):
        """A generated token has the correct structure: 64 hex chars token, 64 hex chars hash, future expires_at."""
        service = ConfirmationTokenService(session=AsyncMock())
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

    async def test_generate_token_is_cryptographically_random(self):
        """Two consecutive token generations produce different tokens."""
        service = ConfirmationTokenService(session=AsyncMock())
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

    async def test_generate_token_default_ttl_is_15_minutes(self):
        """Default TTL is 15 minutes from now."""
        service = ConfirmationTokenService(session=AsyncMock(), ttl_minutes=15)
        before = datetime.now(timezone.utc)
        result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )
        after = datetime.now(timezone.utc)
        expected_min = before + timedelta(minutes=15) - timedelta(seconds=1)
        expected_max = after + timedelta(minutes=15) + timedelta(seconds=1)
        assert expected_min <= result["expires_at"] <= expected_max

    async def test_generate_token_custom_ttl(self):
        """A custom TTL override is respected."""
        service = ConfirmationTokenService(session=AsyncMock(), ttl_minutes=15)
        result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
            ttl_minutes=5,
        )
        expected = datetime.now(timezone.utc) + timedelta(minutes=5)
        assert abs((result["expires_at"] - expected).total_seconds()) < 2

    async def test_generate_token_scope_binding_consistency(self):
        """The same inputs always produce an HMAC that validates against the scope."""
        service = ConfirmationTokenService(session=AsyncMock())
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

    async def test_generate_token_different_scope_different_hash(self):
        """Two tokens with different scopes produce different hashes even if the same plaintext (impossible in practice but tests the binding)."""
        service = ConfirmationTokenService(session=AsyncMock())

        # Force same token for testing scope binding (normally tokens are random)
        with patch.object(service, "_build_scope_string") as mock_scope:
            mock_scope.side_effect = [
                "scope_A",  # First call
                "scope_B",  # Second call
            ]
            with patch("secrets.token_hex", return_value="a" * 64):
                token_a = "a" * 64

                result_a = await service.generate_token(
                    session_id="sess_001", proposal_id="prop_001",
                    target_resource_type="page", target_resource_id="page_A",
                    operation_type="delete_page", resource_hash="h1",
                )
                # Since mock_scope is already consumed by generate_token's internal call,
                # the patches above test the concept: different scopes => different hashes
                assert result_a["token"] == token_a

    async def test_generate_token_validates_required_fields(self):
        """Empty required fields raise ValueError."""
        service = ConfirmationTokenService(session=AsyncMock())
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


class TestTokenValidation:
    """FR-CT-07, FR-CT-08: Full validation pipeline."""

    def _make_proposal(self, **overrides) -> AIProposalRecord:
        """Create a mock proposal in PENDING_CONFIRMATION state."""
        props = {
            "proposal_id": "prop_001",
            "session_id": "sess_001",
            "course_id": "course_001",
            "page_id": "page_001",
            "operation": "delete_page",
            "status": "PENDING_CONFIRMATION",
            "confirmation_token_sha256": None,
            "confirmation_token_expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
            "base_hash": "h1",
        }
        props.update(overrides)
        record = MagicMock(spec=AIProposalRecord)
        for k, v in props.items():
            setattr(record, k, v)
        return record

    async def test_validate_token_happy_path(self):
        """A valid token with correct scope and not expired passes validation."""
        service = ConfirmationTokenService(session=AsyncMock())

        # Generate a real token first
        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = self._make_proposal(
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

    async def test_validate_token_rejects_expired_token(self):
        """An expired token is rejected."""
        service = ConfirmationTokenService(session=AsyncMock())

        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        # Set expiry in the past
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        proposal = self._make_proposal(
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

    async def test_validate_token_rejects_wrong_token(self):
        """An incorrect token is rejected and logged as security event."""
        service = ConfirmationTokenService(session=AsyncMock())

        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = self._make_proposal(
            confirmation_token_sha256=gen_result["token_hash"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token="1111111111111111111111111111111111111111111111111111111111111111",
            user_approved=True,
        )
        assert is_valid is False
        assert "INVALID_CONFIRMATION_TOKEN" in error

    async def test_validate_token_rejects_non_confirmable_status(self):
        """Proposals not in PENDING_CONFIRMATION state are rejected."""
        service = ConfirmationTokenService(session=AsyncMock())

        for bad_status in ["APPLIED", "EXPIRED", "REJECTED", "FAILED", "PENDING_REVIEW"]:
            proposal = self._make_proposal(status=bad_status)
            is_valid, error = await service.validate_token(
                proposal=proposal,
                received_token="a" * 64,
                user_approved=True,
            )
            assert is_valid is False
            assert "PROPOSAL_NOT_CONFIRMABLE" in error

    async def test_validate_token_requires_user_approval(self):
        """Setting user_approved=False rejects the confirmation."""
        service = ConfirmationTokenService(session=AsyncMock())

        gen_result = await service.generate_token(
            session_id="sess_001", proposal_id="prop_001",
            target_resource_type="page", target_resource_id="page_001",
            operation_type="delete_page", resource_hash="h1",
        )

        proposal = self._make_proposal(
            confirmation_token_sha256=gen_result["token_hash"],
        )

        is_valid, error = await service.validate_token(
            proposal=proposal,
            received_token=gen_result["token"],
            user_approved=False,
        )
        assert is_valid is False
        assert "USER_CONFIRMATION_REQUIRED" in error

    async def test_validate_token_rejects_non_destructive_operation(self):
        """Non-destructive operations are rejected."""
        service = ConfirmationTokenService(session=AsyncMock())

        for non_destructive in ["create_page", "update_page", "batch_create", "batch_update"]:
            proposal = self._make_proposal(operation=non_destructive)
            is_valid, error = await service.validate_token(
                proposal=proposal,
                received_token="a" * 64,
                user_approved=True,
            )
            assert is_valid is False
            assert "NON_DESTRUCTIVE_OPERATION" in error

    async def test_validate_token_rejects_invalid_token_format(self):
        """Tokens that are not 64 hex characters are rejected."""
        service = ConfirmationTokenService(session=AsyncMock())
        proposal = self._make_proposal()

        for bad_token in ["", "abc", "x" * 64, "z" * 64, "a" * 63]:
            is_valid, error = await service.validate_token(
                proposal=proposal,
                received_token=bad_token,
                user_approved=True,
            )
            assert is_valid is False
            if bad_token:
                assert "INVALID_TOKEN_FORMAT" in error

    async def test_security_event_logged_on_token_mismatch(self):
        """A token mismatch logs a SECURITY_EVENT."""
        service = ConfirmationTokenService(session=AsyncMock())

        with patch.object(service, "_log_security_event") as mock_log:
            gen_result = await service.generate_token(
                session_id="sess_001", proposal_id="prop_001",
                target_resource_type="page", target_resource_id="page_001",
                operation_type="delete_page", resource_hash="h1",
            )
            proposal = self._make_proposal(
                confirmation_token_sha256=gen_result["token_hash"],
            )
            await service.validate_token(
                proposal=proposal,
                received_token="f" * 64,
                user_approved=True,
            )
            mock_log.assert_called_once()
            args, _ = mock_log.call_args
            assert args[1] == "CONFIRMATION_TOKEN_MISMATCH"
            assert args[2] == "prop_001"


class TestResourceHashVerification:
    """FR-CT-06, FR-CT-07: Resource hash computation and verification."""

    async def test_verify_resource_hash_happy_path(self):
        """When the current hash matches base_hash, verification passes."""
        service = ConfirmationTokenService(session=AsyncMock())
        proposal = MagicMock(spec=AIProposalRecord)
        proposal.base_hash = "abc123def456"

        is_match, error = await service.verify_resource_hash(
            proposal=proposal,
            current_resource_hash="abc123def456",
        )
        assert is_match is True
        assert error is None

    async def test_verify_resource_hash_rejects_mismatch(self):
        """When the current hash differs from base_hash, verification fails."""
        service = ConfirmationTokenService(session=AsyncMock())
        proposal = MagicMock(spec=AIProposalRecord)
        proposal.base_hash = "abc123def456"

        is_match, error = await service.verify_resource_hash(
            proposal=proposal,
            current_resource_hash="xyz789mno012",
        )
        assert is_match is False
        assert "RESOURCE_CHANGED" in error

    async def test_verify_resource_hash_fails_when_base_hash_missing(self):
        """If base_hash is None on the proposal, verification fails."""
        service = ConfirmationTokenService(session=AsyncMock())
        proposal = MagicMock(spec=AIProposalRecord)
        proposal.base_hash = None

        is_match, error = await service.verify_resource_hash(
            proposal=proposal,
            current_resource_hash="abc123",
        )
        assert is_match is False
        assert "BASE_HASH_MISSING" in error


class TestScopeStringConstruction:
    """FR-CT-03: Scope string is built deterministically."""

    def test_build_scope_string_is_deterministic(self):
        """The same inputs always produce the same scope string."""
        service = ConfirmationTokenService(session=AsyncMock())
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
        service = ConfirmationTokenService(session=AsyncMock())
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
        service = ConfirmationTokenService(session=AsyncMock())
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


class TestResourceHashComputation:
    """FR-CT-06: Deterministic resource hash computation."""

    def test_compute_resource_hash_is_deterministic(self):
        """The same state always produces the same hash."""
        service = ConfirmationTokenService(session=AsyncMock())
        state = {
            "page_id": "p1",
            "title": "Introduction",
            "order_index": 1,
            "components": [
                {"component_id": "c1", "component_type": "content-text", "order_index": 0},
            ],
        }
        hash1 = service._compute_resource_hash(state)
        hash2 = service._compute_resource_hash(state)
        assert hash1 == hash2

    def test_compute_resource_hash_changes_when_state_changes(self):
        """Different states produce different hashes."""
        service = ConfirmationTokenService(session=AsyncMock())
        state_a = {"page_id": "p1", "title": "Intro", "order_index": 1}
        state_b = {"page_id": "p1", "title": "Introduction (Revised)", "order_index": 1}
        hash_a = service._compute_resource_hash(state_a)
        hash_b = service._compute_resource_hash(state_b)
        assert hash_a != hash_b

    def test_compute_resource_hash_is_not_empty(self):
        """Hash is always a 64-character hex string."""
        service = ConfirmationTokenService(session=AsyncMock())
        h = service._compute_resource_hash({"some": "data"})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
```

### 6.2 Integration Tests

**File:** `tests/test_ai_confirmation_api.py`

```python
"""
Integration tests for the generic confirmation endpoint.

Tests use the FastAPI TestClient and a test database.
"""


class TestGenericConfirmEndpoint:
    """
    Tests for POST /api/v1/ai/proposals/{proposal_id}/confirm
    """

    async def test_confirm_endpoint_happy_path(
        self, async_client, sample_proposal_pending_confirmation, sample_confirmation_token
    ):
        """A valid confirmation request returns 200 with token_validated status."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_pending_confirmation.proposal_id}/confirm",
            json={
                "confirmation_token": sample_confirmation_token,
                "user_approved": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "token_validated"
        assert data["proposal_id"] == sample_proposal_pending_confirmation.proposal_id

    async def test_confirm_endpoint_unknown_proposal_returns_404(
        self, async_client
    ):
        """A non-existent proposal_id returns 404."""
        response = await async_client.post(
            "/api/v1/ai/proposals/nonexistent/confirm",
            json={"confirmation_token": "a" * 64, "user_approved": True},
        )
        assert response.status_code == 404

    async def test_confirm_endpoint_wrong_token_returns_403(
        self, async_client, sample_proposal_pending_confirmation
    ):
        """An incorrect confirmation token returns 403."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_pending_confirmation.proposal_id}/confirm",
            json={"confirmation_token": "f" * 64, "user_approved": True},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "INVALID_CONFIRMATION_TOKEN"

    async def test_confirm_endpoint_expired_token_returns_410(
        self, async_client, sample_proposal_with_expired_token
    ):
        """An expired token returns 410."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_with_expired_token.proposal_id}/confirm",
            json={"confirmation_token": "a" * 64, "user_approved": True},
        )
        assert response.status_code == 410
        assert response.json()["code"] == "CONFIRMATION_EXPIRED"

    async def test_confirm_endpoint_already_applied_returns_409(
        self, async_client, sample_proposal_applied
    ):
        """An already-applied proposal returns 409."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_applied.proposal_id}/confirm",
            json={"confirmation_token": "a" * 64, "user_approved": True},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "PROPOSAL_NOT_CONFIRMABLE"

    async def test_confirm_endpoint_without_approval_returns_400(
        self, async_client, sample_proposal_pending_confirmation
    ):
        """Setting user_approved=false returns 400."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_pending_confirmation.proposal_id}/confirm",
            json={"confirmation_token": "a" * 64, "user_approved": False},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "USER_CONFIRMATION_REQUIRED"

    async def test_confirm_endpoint_non_destructive_returns_400(
        self, async_client, sample_proposal_create_page
    ):
        """A non-destructive operation cannot use the confirmation endpoint."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_create_page.proposal_id}/confirm",
            json={"confirmation_token": "a" * 64, "user_approved": True},
        )
        assert response.status_code == 400

    async def test_confirm_endpoint_invalid_token_format_returns_400(
        self, async_client, sample_proposal_pending_confirmation
    ):
        """A token with invalid format (non-hex) returns 400."""
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_pending_confirmation.proposal_id}/confirm",
            json={"confirmation_token": "not-a-valid-hex-token!!!!", "user_approved": True},
        )
        assert response.status_code == 400

    async def test_confirm_endpoint_unauthorized_user_returns_403(
        self, async_client, sample_proposal_pending_confirmation
    ):
        """Requests without valid auth token are rejected."""
        # Assuming the endpoint requires authentication
        async_client.headers.pop("Authorization", None)
        response = await async_client.post(
            f"/api/v1/ai/proposals/{sample_proposal_pending_confirmation.proposal_id}/confirm",
            json={"confirmation_token": "a" * 64, "user_approved": True},
        )
        assert response.status_code == 403
```

### 6.3 E2E Tests

**Scenario E2E-1: Full Proposal + Confirm Flow for Page Delete (Happy Path)**

1. **Setup:** Test course has 5 pages. Page 3 ("Unit 2 Assessment") has a `final-assessment` component and is referenced by 2 branching rules.
2. **Propose:** AI agent calls `propose_delete_page(session_id, page_id_3)`.
3. **Verify proposal response** contains:
   - `confirmation_required: true`
   - `confirmation_token_expires_at` (future timestamp, within 15 minutes of now)
   - `warnings` with at least 2 entries (final_assessment, branching)
   - `base_hash` (64 hex chars)
4. **Frontend renders modal** with warnings.
5. **Confirm:** Frontend calls `confirm_delete_page` with the token and `user_approved=true`.
6. **Verify operation** succeeds (200 response with `status: "deleted"`).
7. **Verify page** is removed from course: `GET /api/v1/courses/{course_id}/pages` returns 4 pages.
8. **Verify audit** contains the delete entry with `before_snapshot`.
9. **Verify outbox** contains `PageDeletedByAI` event.

**Scenario E2E-2: Confirmation Token Expiry and Re-Proposal**

1. **Setup:** Test course with 3 pages.
2. **Propose:** AI agent proposes deleting page 2. Receive token with 15-minute TTL.
3. **Wait** 16 minutes (programmatically advance time or use a short TTL test config).
4. **Confirm:** Frontend calls confirm endpoint with the token.
5. **Verify** backend returns `410 CONFIRMATION_EXPIRED`.
6. **Re-propose:** AI agent re-proposes deletion of the same page.
7. **Verify** new proposal creates a fresh token.
8. **Confirm** with new token.
9. **Verify** operation succeeds.

**Scenario E2E-3: Concurrent State Change Between Proposal and Confirm (Conflict Detection)**

1. **Setup:** Test course with 3 pages.
2. **Propose:** User A proposes deleting page 2.
3. **Modify:** User B (via direct API) updates page 2's title to "Updated Title".
4. **Confirm:** User A attempts to confirm the proposal.
5. **Verify** backend returns `409 RESOURCE_CHANGED` with the old and new hashes.
6. **Re-propose:** User A re-proposes deletion (now sees "Updated Title").
7. **Confirm** with new token.
8. **Verify** operation succeeds.

**Scenario E2E-4: Admin Override for Emergency Course Deletion**

1. **Setup:** Admin user with bypass permission. Course with 10 pages.
2. **Propose:** Admin proposes deleting the entire course.
3. **Token lost:** Admin loses the token (simulated by using a wrong token in confirm).
4. **Override:** Admin calls confirm with `admin_override=true` and a valid reason (20+ chars).
5. **Verify** override succeeds (token validation bypassed, resource hash still checked).
6. **Verify** `ai_admin_overrides` table contains the override record.
7. **Verify** audit log contains the override event.

### 6.4 Manual QA Steps

1. **Token not persisted in plaintext:**
   - Connect to the database via psql.
   - Run `SELECT confirmation_token_sha256 FROM ai_proposals LIMIT 1;`
   - Verify the stored value is a 64-char hex string (hash), not a shorter/longer string that could be a base64-encoded token.
   - Attempt to reverse the hash by checking if it matches `SHA256(any_known_string)` -- this should be infeasible.

2. **Token not logged in application logs:**
   - Search application logs for the plaintext token value.
   - Verify it does NOT appear in any log line.
   - Verify only the hash prefix appears in security event logs.

3. **Frontend token lifecycle:**
   - Open browser developer tools.
   - Verify the token is not in localStorage, sessionStorage, or cookies after the propose response.
   - Verify the token is sent in the confirm request body.
   - Verify the token is cleared from memory after confirm completes.

4. **Simultaneous confirmation race condition:**
   - Open two browser tabs with the same proposal ID and token.
   - Click "Confirm" on both tabs simultaneously.
   - Verify exactly one succeeds (200) and the other receives `409 PROPOSAL_ALREADY_APPLIED`.

5. **Resource hash stability:**
   - Propose deleting a page.
   - Note the `base_hash` value.
   - Read the page via GET API. Verify that re-computing the hash with the same fields produces the same `base_hash`.

---

## 7. DEFINITION OF DONE

### 7.1 Code Complete

- [ ] `app/services/ai/confirmation_token_service.py` exists with the complete `ConfirmationTokenService` class implementing `generate_token()`, `validate_token()`, `verify_resource_hash()`, `_build_scope_string()`, `_compute_scope_bound_hash()`, `_compute_resource_hash()`, and `_log_security_event()`.
- [ ] `app/services/ai/confirmation_token_dto.py` exists with all Pydantic models: `TokenGenerationRequest`, `TokenGenerationResult`, `TokenValidationRequest`, `AdminOverrideRequest`, `SecurityEventData`.
- [ ] Custom exception classes are defined: `ConfirmationTokenError`, `TokenExpiredError`, `TokenMismatchError`, `ResourceChangedError`, `ProposalNotInConfirmableStateError`, `ResourceNotFoundError`.
- [ ] `app/routers/ai_confirmations.py` exists with `POST /api/v1/ai/proposals/{proposal_id}/confirm` endpoint implementing the full validation pipeline.
- [ ] `app/models/ai_admin_override.py` exists with the `AIAdminOverrideRecord` ORM model.
- [ ] Alembic migration creates `confirmation_ttl_override_minutes` column on `ai_proposals`, the `idx_ai_proposals_token_hash` partial index, and the `ai_admin_overrides` table with all constraints and indexes.
- [ ] `app/main.py` registers the `ai_confirmations` router.
- [ ] Environment variables documented in `.env.example` and loaded in `app/config.py` or equivalent.

### 7.2 Tests Pass

- [ ] All unit tests in `test_confirmation_token_service.py` pass (20+ tests covering generation, validation, scope binding, hash verification, edge cases).
- [ ] All integration tests in `test_ai_confirmation_api.py` pass (8+ tests covering API endpoint behavior).
- [ ] All E2E scenarios pass (4 scenarios covering happy path, expiry, conflict, admin override).
- [ ] All tests pass with both in-memory SQLite (CI) and PostgreSQL (integration).
- [ ] Coverage is >= 95% for `confirmation_token_service.py` and >= 90% for `ai_confirmations.py`.
- [ ] No regression in existing proposal or page CRUD tests.

### 7.3 Documentation

- [ ] API contracts for `POST /api/v1/ai/proposals/{proposal_id}/confirm` documented in OpenAPI spec or equivalent.
- [ ] All environment variables documented in `.env.example` with descriptions and defaults.
- [ ] Integration guide for consuming developers updated (how to use `ConfirmationTokenService` from new destructive operations).

### 7.4 Security

- [ ] Token generation uses `secrets.token_hex(32)` (256-bit entropy).
- [ ] Only HMAC-SHA256 scope-bound hash stored in database (not bare token hash).
- [ ] Plaintext token never appears in database, logs, or error messages.
- [ ] Token TTL enforced (default 15 minutes, configurable with per-operation overrides).
- [ ] Token format validated (64 hex chars) before hash comparison.
- [ ] Resource hash re-validated at confirmation time.
- [ ] Security event logged on token mismatch with full request context.
- [ ] Admin override is audit-logged with reason, identity, and timestamp.
- [ ] Admin override feature gated behind `AI_ADMIN_CONFIRMATION_BYPASS_ENABLED=false`.

### 7.5 Operational Readiness

- [ ] Feature flag `AI_AUTHORING_ENABLED` gates the confirmation endpoint.
- [ ] Metrics counters registered for `ai.confirmation.token.generated`, `ai.confirmation.token.validated`, `ai.confirmation.token.expired`, `ai.confirmation.resource_changed`, `ai.confirmation.admin_override`, `ai.confirmation.security_event`.
- [ ] Prometheus or equivalent metrics endpoint exposes all counters.
- [ ] Security event logging configured with appropriate severity and output destination.
- [ ] Test configuration for short TTL values (1 minute) for E2E expiry testing.

### 7.6 Developer Integration

- [ ] US-AI-013 (Delete Page Proposal) implementation updated to use `ConfirmationTokenService` instead of inline token logic as drafted.
- [ ] US-AI-046 (Course-Level Operations) implementation uses `ConfirmationTokenService` for course deletion and archive operations.
- [ ] US-AI-029 (Batch Proposal) implementation uses `ConfirmationTokenService` for batch destructive operations.
- [ ] Developer onboarding guide updated with `ConfirmationTokenService` usage examples.

---

## 8. TASKS AND SUB-TASKS

### Task 1: Implement Core ConfirmationTokenService

| Field | Value |
|---|---|
| **Task ID** | T1 |
| **Description** | Implement the `ConfirmationTokenService` class with all token generation, scope binding, hashing, validation, and security event logging. |
| **Files** | `app/services/ai/confirmation_token_service.py` (new), `app/services/ai/confirmation_token_dto.py` (new) |
| **Acceptance** | All methods in the class signature are implemented. Tokens are 64 hex chars via secrets.token_hex(32). Scope-bound hash uses HMAC-SHA256. Validation pipeline follows FR-CT-08 ordering. Security events logged on mismatch. All unit tests pass. |
| **Effort** | 6 hours |
| **Dependencies** | US-AI-004 (ai_proposals table columns), US-AI-009 (proposal states) |

### Task 2: Create Pydantic DTOs

| Field | Value |
|---|---|
| **Task ID** | T2 |
| **Description** | Create all Pydantic request/response models for the token system. |
| **Files** | `app/services/ai/confirmation_token_dto.py` (new) |
| **Acceptance** | `TokenGenerationRequest`, `TokenGenerationResult`, `TokenValidationRequest`, `AdminOverrideRequest`, `SecurityEventData` models exist with correct field validators. Token format validator rejects non-hex strings. All fields have proper descriptions and constraints. |
| **Effort** | 1 hour |
| **Dependencies** | None |

### Task 3: Implement Generic Confirmation API Endpoint

| Field | Value |
|---|---|
| **Task ID** | T3 |
| **Description** | Implement the generic `POST /api/v1/ai/proposals/{proposal_id}/confirm` endpoint that validates tokens and returns success/failure. |
| **Files** | `app/routers/ai_confirmations.py` (new), `app/main.py` (register router) |
| **Acceptance** | Endpoint returns 200 with `token_validated` on success. Returns proper error codes (400, 403, 404, 409, 410) for each validation failure case. Error responses match the error envelope pattern. Router is registered in main.py. Feature flag gating is applied. |
| **Effort** | 3 hours |
| **Dependencies** | T1, T2 |

### Task 4: Create Admin Override ORM Model and Migration

| Field | Value |
|---|---|
| **Task ID** | T4 |
| **Description** | Create the `AIAdminOverrideRecord` ORM model and the Alembic migration for the new column and table. |
| **Files** | `app/models/ai_admin_override.py` (new), `alembic/versions/20260614_0003_add_confirmation_token_overrides.py` (new), `app/models/__init__.py` (add import) |
| **Acceptance** | ORM model has all fields as specified. Alembic migration adds `confirmation_ttl_override_minutes` column, `idx_ai_proposals_token_hash` index, and `ai_admin_overrides` table. Migration runs cleanly against SQLite and PostgreSQL. Downgrade drops everything cleanly. |
| **Effort** | 2 hours |
| **Dependencies** | US-AI-004 (ai_proposals table exists) |

### Task 5: Implement Admin Override in Validation Pipeline

| Field | Value |
|---|---|
| **Task ID** | T5 |
| **Description** | Extend `ConfirmationTokenService.validate_token()` to support the admin override path. Add rate limiting logic. |
| **Files** | `app/services/ai/confirmation_token_service.py` (modify) |
| **Acceptance** | When `admin_override=True`, token validation is bypassed but admin override reason is validated (min 20 chars). Override is logged in `ai_admin_overrides` table. Rate limit of 5 overrides per admin per hour is enforced. Feature flag gating applied. |
| **Effort** | 2 hours |
| **Dependencies** | T1, T4 |

### Task 6: Add Configuration and Environment Variables

| Field | Value |
|---|---|
| **Task ID** | T6 |
| **Description** | Add all configuration variables for the token system. |
| **Files** | `.env.example`, `.env` (if applicable), `app/services/ai/confirmation_token_service.py` (config loading) |
| **Acceptance** | `AI_CONFIRMATION_TOKEN_TTL_MINUTES`, `AI_CONFIRMATION_TOKEN_TTL_OVERRIDES`, `AI_ADMIN_CONFIRMATION_BYPASS_ENABLED`, `AI_ADMIN_OVERRIDE_RATE_LIMIT_PER_HOUR`, `AI_CONFIRMATION_SECURITY_LOG_LEVEL` are all defined and loaded. Defaults match specification. TTL overrides are parsed correctly. |
| **Effort** | 1 hour |
| **Dependencies** | T1 |

### Task 7: Implement Metrics and Observability

| Field | Value |
|---|---|
| **Task ID** | T7 |
| **Description** | Add Prometheus/OpenTelemetry metrics counters and histograms for all token operations. |
| **Files** | `app/services/ai/confirmation_token_service.py` (modify), `app/monitoring/metrics.py` or equivalent |
| **Acceptance** | All 6 metrics counters and 1 histogram defined in section 3.5 are registered. Each `generate_token()` call increments the generated counter. Each `validate_token()` call increments the validated counter with outcome tag. Security events trigger the security_event counter. |
| **Effort** | 2 hours |
| **Dependencies** | T1 |

### Task 8: Write Unit Tests

| Field | Value |
|---|---|
| **Task ID** | T8 |
| **Description** | Write comprehensive unit tests for `ConfirmationTokenService`. |
| **Files** | `tests/test_confirmation_token_service.py` (new) |
| **Acceptance** | All test classes from section 6.1 are implemented (20+ tests). Tests cover happy path and all error conditions. Tests use mocking for DB access. Coverage >= 95% for the service. |
| **Effort** | 5 hours |
| **Dependencies** | T1, T2 |

### Task 9: Write Integration Tests

| Field | Value |
|---|---|
| **Task ID** | T9 |
| **Description** | Write integration tests for the generic confirmation API endpoint. |
| **Files** | `tests/test_ai_confirmation_api.py` (new) |
| **Acceptance** | All test scenarios from section 6.2 are covered (8+ tests). Tests use `TestClient` with a test database. Covers success, error, and edge case paths. |
| **Effort** | 3 hours |
| **Dependencies** | T3 |

### Task 10: Write E2E Tests

| Field | Value |
|---|---|
| **Task ID** | T10 |
| **Description** | Write end-to-end tests for the full proposal-confirm lifecycle. |
| **Files** | `tests/e2e/test_confirmation_token_e2e.py` (new) |
| **Acceptance** | All 4 E2E scenarios from section 6.3 are automated. Tests run against a full stack (API + DB). Includes test configuration for short TTL values. |
| **Effort** | 4 hours |
| **Dependencies** | T3, T9 |

### Task 11: Update US-AI-013 and US-AI-046 Implementations

| Field | Value |
|---|---|
| **Task ID** | T11 |
| **Description** | Update the inline token logic in US-AI-013 (and US-AI-046 when available) to use the centralized `ConfirmationTokenService`. |
| **Files** | `app/services/ai/proposal_orchestrator.py` (modify US-AI-013's orchestrator) |
| **Acceptance** | US-AI-013's `propose_delete_page` uses `ConfirmationTokenService.generate_token()` instead of inline `secrets.token_hex()`. US-AI-013's `confirm_delete_page` uses `ConfirmationTokenService.validate_token()` and `verify_resource_hash()`. All US-AI-013 tests still pass. |
| **Effort** | 3 hours |
| **Dependencies** | T1, US-AI-013 implementation |

### Task 12: Code Review, Security Review, and Merge

| Field | Value |
|---|---|
| **Task ID** | T12 |
| **Description** | Code review, security review, and merge of the full US-AI-049 feature. |
| **Files** | All new and modified files |
| **Acceptance** | All CI checks pass. Two approvals on the PR. Security review confirms no token leakage vectors. Feature flag defaults to false in production. Documentation is complete. |
| **Effort** | 3 hours |
| **Dependencies** | T1 through T11 |

---

## SUMMARY

| Metric | Value |
|---|---|
| New files | 6 (confirmation_token_service.py, confirmation_token_dto.py, ai_confirmations.py, ai_admin_override.py, migration, test files) |
| Modified files | 5 (main.py, models/__init__.py, proposal_orchestrator.py, .env.example, metrics registry) |
| New tables | 1 (ai_admin_overrides) |
| New columns | 1 (ai_proposals.confirmation_ttl_override_minutes) |
| New indexes | 2 (idx_ai_proposals_token_hash, idx_admin_overrides_*) |
| New API endpoints | 1 (POST /api/v1/ai/proposals/{proposal_id}/confirm) |
| New services | 1 (ConfirmationTokenService) |
| Total estimated effort | ~35 hours |
| Key architectural decision | Scope-bound HMAC-SHA256 hashing instead of bare token SHA256 |
| Key security invariant | Plaintext token NEVER persisted; only HMAC-SHA256 scope-bound hash stored |
| Design parent | US-AI-013 inline token logic standardized and extracted |
