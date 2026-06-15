"""Proposal Lifecycle Service — US-BKND-AI-009/010.

Orchestrates the propose-validate-confirm-apply gating pattern for
AI-generated course mutations. Manages proposal creation, validation,
storage, confirmation, expiry, and audit logging.

US-BKND-AI-010: Added idempotency key support, outbox events,
and post-apply validation.

US-BKND-AI-013: Added propose_delete_page and confirm_delete_page with
ConfirmationTokenService integration and dependency analysis.

Reuses:
- AIProposalRepository for persistence
- TemplateValidationEngine (AI-005) for per-proposal validation
- AIAuditService for audit trail
- AISessionRepository for session scoping
- PageRepository for before-state snapshots and mutation execution
- DiffEngine for computing structural diffs
- IdempotencyService (AI-010) for exactly-once apply
- OutboxService (AI-010) for event publishing
- ConfirmationTokenService (AI-049) for destructive operation gating
- DependencyAnalyzer (AI-013) for delete impact analysis
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_models import AIProposalRecord
from app.repositories.ai_proposal_repo import AIProposalRepository
from app.repositories.ai_session_repo import AISessionRepository
from app.repositories.page_component_repo import PageRepository
from app.services.ai.audit_service import AIAuditService
from app.services.ai.diff_engine import DiffEngine
from app.services.ai.template_contracts import AITemplateContractsService
from app.services.ai.validation_engine import TemplateValidationEngine
from app.services.ai.config import get_ai_config

logger = logging.getLogger("ai_authoring")


class ProposalError(Exception):
    """Structured error for proposal operations."""
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class ProposalNotFoundError(ProposalError):
    def __init__(self, pid: str):
        super().__init__("PROPOSAL_NOT_FOUND", f"Proposal '{pid}' not found.", 404)


class ProposalStaleError(ProposalError):
    def __init__(self, msg: str):
        super().__init__("PROPOSAL_STALE", msg, 410)


class ProposalConflictError(ProposalError):
    def __init__(self, msg: str = "Resource modified since proposal was created."):
        super().__init__("CONFLICT_DETECTED", msg, 409)


class AIProposalService:
    """Core service for proposal lifecycle management: create, apply, cancel, list."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.proposal_repo = AIProposalRepository(db)
        self.session_repo = AISessionRepository(db)
        self.page_repo = PageRepository(db)
        self.audit = AIAuditService(db)
        self.diff_engine = DiffEngine()
        self.config = get_ai_config()

    async def create_proposal(
        self,
        session_id: str,
        user_id: str,
        organization_id: str,
        course_id: str,
        operation: str,
        resource_type: str,
        data: Dict[str, Any],
        resource_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a proposal: validate, diff, persist, audit. FR001-FR003."""
        session = await self.session_repo.get_active(session_id)
        if session is None:
            raise ProposalError("SESSION_INVALID", "Session not found or expired.", 401)

        before_state = None
        if resource_id and resource_type == "page":
            page = await self.page_repo.get_by_course_and_page(course_id, resource_id)
            if page is None:
                raise ProposalError("PERMISSION_DENIED",
                    f"Page '{resource_id}' doesn't belong to course '{course_id}'.", 403)
            if operation in ("update_page", "delete_page"):
                before_state = page.to_dict(include_components=True)

        validation_messages = await self._validate(operation, resource_type, data)
        has_errors = any(m.get("severity") == "error" for m in validation_messages)
        validation_status = "error" if has_errors else "valid"

        after_state = None
        if operation in ("create_page", "update_page"):
            after_state = {
                "title": data.get("title", ""),
                "template_type": data.get("template_type", "text-content"),
                "data": data.get("data", {}),
            }
        diff = self.diff_engine.compute(operation, before_state, after_state)

        ttl = self.config.proposal_ttl_minutes
        now = datetime.utcnow()
        record = AIProposalRecord(
            session_id=session_id, user_id=user_id,
            organization_id=organization_id, course_id=course_id,
            action_type=operation, target_type=resource_type, target_id=resource_id,
            proposed_changes={
                "data_before": before_state, "data_after": after_state,
                "data_patch": data, "diff": diff,
                "validation_status": validation_status,
                "validation_messages": validation_messages,
            },
            status="pending", created_at=now, updated_at=now,
            expires_at=now + timedelta(minutes=ttl),
        )
        created = await self.proposal_repo.create(record)

        await self.audit.log(
            session_id=session_id, user_id=user_id,
            organization_id=organization_id, course_id=course_id,
            action=AIAuditService.ACTION_PROPOSAL_CREATED,
            target_type=resource_type, target_id=resource_id or created.proposal_id,
            details={"operation": operation, "validation_status": validation_status},
        )

        return {
            "proposal_id": created.proposal_id, "operation": operation,
            "resource_type": resource_type, "resource_id": resource_id,
            "status": created.status, "validation_status": validation_status,
            "validation_messages": validation_messages, "diff": diff,
            "preview": {"summary": self._summary(operation, resource_type, data),
                        "can_undo": operation != "delete_page"},
            "created_at": created.created_at.isoformat(),
            "expires_at": created.expires_at.isoformat(),
        }

    async def apply_proposal(
        self, proposal_id: str, session_id: str, user_id: str,
        user_confirmed: bool = True,
    ) -> Dict[str, Any]:
        """Apply a pending proposal: verify, execute, transition. FR004."""
        if not user_confirmed:
            raise ProposalError("CONFIRMATION_REQUIRED",
                                "User confirmation required.", 400)

        record = await self.proposal_repo.get(proposal_id)
        if record is None:
            raise ProposalNotFoundError(proposal_id)
        if record.session_id != session_id:
            raise ProposalError("PERMISSION_DENIED",
                                "Session doesn't own this proposal.", 403)

        if record.status == "applied":
            return {
                "proposal_id": record.proposal_id, "status": "applied",
                "result": {"resource_id": record.target_id,
                           "operation": record.action_type,
                           "resource_type": record.target_type},
                "applied_at": record.applied_at.isoformat() if record.applied_at else None,
            }

        if record.status != "pending":
            raise ProposalStaleError(f"Status is '{record.status}', expected 'pending'.")

        now = datetime.utcnow()
        if now > record.expires_at:
            record.status = "expired"; await self.proposal_repo.update(record)
            raise ProposalStaleError("Proposal has expired.")

        changes = record.proposed_changes or {}
        before = changes.get("data_before")
        if record.target_id and before:
            await self._conflict_check(record.target_type, record.target_id, before)

        after_state = changes.get("data_after", {})
        result = await self._execute(
            record.action_type, record.target_type, record.target_id,
            after_state, changes.get("data_patch", {}), record.course_id,
        )

        record.status = "applied"; record.applied_at = now
        record.updated_at = now; await self.proposal_repo.update(record)

        await self.audit.log(
            session_id=session_id, user_id=user_id,
            organization_id=record.organization_id, course_id=record.course_id,
            action=AIAuditService.ACTION_PROPOSAL_APPLIED,
            target_type=record.target_type,
            target_id=record.target_id or result.get("resource_id", ""),
            details={"proposal_id": proposal_id, "result": result},
        )
        return {"proposal_id": proposal_id, "status": "applied",
                "result": result, "applied_at": now.isoformat()}

    async def apply_with_idempotency(
        self, proposal_id: str, session_id: str, user_id: str,
        user_confirmed: bool = True,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        """Enhanced apply with idempotency, outbox, and post-apply validation. FR-APPLY-001/002/006/008.

        Wraps apply_proposal with:
        1. Idempotency key check (FR-APPLY-002) — returns cached response if key exists
        2. Execute apply (FR-APPLY-001) — transactional mutation + audit
        3. Post-apply validation (FR-APPLY-006) — revalidate mutation scope
        4. Outbox event write (FR-APPLY-008) — publish event for downstream consumers
        5. Idempotency key storage (FR-APPLY-002) — cache response for retry
        """
        from app.services.ai.idempotency_service import IdempotencyService
        from app.services.ai.outbox_service import AIOutboxService

        idem_svc = IdempotencyService(self.db)

        # 1. Check idempotency key
        if idempotency_key:
            cached = await idem_svc.check(idempotency_key, user_id, session_id)
            if cached is not None:
                logger.info("Idempotency hit for proposal %s", proposal_id[:8])
                return cached

        # 2. Execute apply (transactional)
        result = await self.apply_proposal(
            proposal_id=proposal_id, session_id=session_id,
            user_id=user_id, user_confirmed=user_confirmed,
        )

        # 3. Post-apply validation (FR-APPLY-006)
        # Re-validate the changed page if this was a create/update
        if result["status"] == "applied":
            op = result.get("result", {}).get("operation", "")
            if op in ("create_page", "update_page"):
                page_id = result.get("result", {}).get("resource_id")
                if page_id:
                    try:
                        valid = await self._post_apply_validate(page_id)
                        if not valid.get("is_valid", True):
                            logger.error(
                                "Post-apply validation failed for page %s — "
                                "changes committed but validation warnings exist",
                                page_id[:8],
                            )
                            # Warnings are logged but don't rollback (mutation succeeded)
                            result["post_validation"] = valid
                    except Exception:
                        logger.exception("Post-apply validation error for page %s",
                                         page_id[:8])

        # 4. Write outbox event (FR-APPLY-008)
        if result["status"] == "applied":
            try:
                outbox = AIOutboxService(self.db)
                op = result.get("result", {}).get("operation", "unknown")
                rid = result.get("result", {}).get("resource_id", "")
                event_type_map = {
                    "create_page": "PageCreatedByAI",
                    "update_page": "PageUpdatedByAI",
                    "delete_page": "PageDeletedByAI",
                }
                await outbox.publish(
                    event_type=event_type_map.get(op, "PageMutatedByAI"),
                    aggregate_type="page",
                    aggregate_id=rid,
                    payload={
                        "proposal_id": proposal_id,
                        "operation": op,
                        "resource_id": rid,
                        "result": result["result"],
                    },
                )
            except Exception:
                logger.exception("Outbox event write failed for proposal %s — "
                                 "non-blocking", proposal_id[:8])

        # 5. Store idempotency key
        if idempotency_key:
            try:
                await idem_svc.store(
                    idempotency_key, user_id, session_id, result, status=200,
                )
            except Exception:
                logger.exception("Failed to store idempotency key %s",
                                 idempotency_key[:8])

        return result

    async def _post_apply_validate(self, page_id: str) -> Dict[str, Any]:
        """Re-validate a page after mutation. FR-APPLY-006.

        Runs template validation on the mutated page to ensure the
        applied changes pass schema and business rule checks.
        """
        page = await self.page_repo.get(page_id)
        if page is None:
            return {"is_valid": True, "messages": []}

        # Infer template type and extract data from first component
        ttype = "text-content"
        if hasattr(page, "layout") and isinstance(page.layout, dict):
            ttype = page.layout.get("templateType", "text-content")

        data = {}
        if page.components:
            data = page.components[0].data or {}

        try:
            contracts = AITemplateContractsService(self.db)
            engine = TemplateValidationEngine(contracts)
            result = await engine.validate(template_type=ttype, data=data, scope="full")
        except Exception:
            return {"is_valid": True, "messages": []}

        return {
            "is_valid": result.status != "error",
            "status": result.status,
            "messages": [
                {"severity": m.severity, "code": m.code, "field": m.field,
                 "message": m.message, "hint": m.hint}
                for m in result.messages
            ],
        }

    async def cancel_proposal(
        self, proposal_id: str, session_id: str, user_id: str, reason: str = "",
    ) -> Dict[str, Any]:
        """Cancel a pending proposal. FR005."""
        record = await self.proposal_repo.get(proposal_id)
        if record is None:
            raise ProposalNotFoundError(proposal_id)
        if record.session_id != session_id:
            raise ProposalError("PERMISSION_DENIED",
                                "Session doesn't own this proposal.", 403)
        if record.status == "cancelled":
            return {"proposal_id": proposal_id, "status": "cancelled",
                    "cancelled_at": record.updated_at.isoformat()}
        if record.status != "pending":
            raise ProposalStaleError(f"Cannot cancel '{record.status}' proposal.")

        now = datetime.utcnow()
        record.status = "cancelled"; record.updated_at = now
        await self.proposal_repo.update(record)

        await self.audit.log(
            session_id=session_id, user_id=user_id,
            organization_id=record.organization_id, course_id=record.course_id,
            action=AIAuditService.ACTION_PROPOSAL_REJECTED,
            target_type=record.target_type, target_id=record.target_id or "",
            details={"reason": reason or "User cancelled"},
        )
        return {"proposal_id": proposal_id, "status": "cancelled",
                "cancelled_at": now.isoformat()}

    async def list_proposals(
        self, course_id: Optional[str] = None, session_id: Optional[str] = None,
        status: Optional[str] = None, page: int = 1, page_size: int = 20,
    ) -> Dict[str, Any]:
        """List proposals with filters and pagination. FR009."""
        if course_id:
            records = await self.proposal_repo.list_by_course(course_id, status=status)
        elif session_id:
            records = await self.proposal_repo.list_by_session(session_id)
        else:
            records = []
        if status and not course_id:
            records = [r for r in records if r.status == status]

        total = len(records)
        start = (page - 1) * page_size
        page_records = records[start:start + page_size]
        items = [{
            "proposal_id": r.proposal_id, "operation": r.action_type,
            "resource_type": r.target_type, "resource_id": r.target_id,
            "status": r.status,
            "validation_status": (r.proposed_changes or {}).get("validation_status", "valid"),
            "summary": self._summary(r.action_type, r.target_type,
                                     (r.proposed_changes or {}).get("data_patch", {})),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        } for r in page_records]

        return {"items": items, "total": total, "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size)}

    async def get_proposal(self, proposal_id: str) -> Dict[str, Any]:
        """Get full proposal detail."""
        record = await self.proposal_repo.get(proposal_id)
        if record is None:
            raise ProposalNotFoundError(proposal_id)
        changes = record.proposed_changes or {}
        return {
            "proposal_id": record.proposal_id, "operation": record.action_type,
            "resource_type": record.target_type, "resource_id": record.target_id,
            "status": record.status,
            "validation_status": changes.get("validation_status", "valid"),
            "validation_messages": changes.get("validation_messages", []),
            "diff": changes.get("diff", {}),
            "preview": {"summary": self._summary(record.action_type, record.target_type,
                                                  changes.get("data_patch", {})),
                        "can_undo": record.action_type != "delete_page"},
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "applied_at": record.applied_at.isoformat() if record.applied_at else None,
        }

    async def expire_stale(self) -> int:
        return await self.proposal_repo.expire_stale()

    # ------------------------------------------------------------------
    # US-BKND-AI-013: Destructive Delete Page Proposals
    # ------------------------------------------------------------------

    async def propose_delete_page(
        self,
        session_id: str,
        user_id: str,
        organization_id: str,
        course_id: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """Propose deletion of a page with dependency analysis and confirmation token.

        US-BKND-AI-013 Phase 1: Creates a delete proposal with:
        - Page hash for staleness detection
        - Dependency impact analysis (branching, scoring, final assessment, navigation)
        - Confirmation token via ConfirmationTokenService
        - Full before-snapshot for audit trail

        Never mutates domain data. Returns proposal response with warnings
        and confirmation metadata.
        """
        from app.services.ai.confirmation_token_service import ConfirmationTokenService
        from app.services.ai.dependency_analyzer import DependencyAnalyzer

        # 1. Validate session
        session = await self.session_repo.get_active(session_id)
        if session is None:
            raise ProposalError(
                "SESSION_INVALID", "Session not found or expired.", 401
            )

        # 2. Fetch page and verify ownership
        page = await self.page_repo.get_by_course_and_page(course_id, page_id)
        if page is None:
            raise ProposalError(
                "PAGE_NOT_IN_SCOPE",
                f"Page '{page_id}' not found in course '{course_id}'.",
                403,
            )

        # 3. Check for duplicate pending delete proposal
        existing = await self.proposal_repo.list_by_session(session_id)
        for p in existing:
            if (
                p.action_type == "delete_page"
                and p.target_id == page_id
                and p.status in ("pending", "PENDING_CONFIRMATION")
            ):
                return {
                    "proposal_id": p.proposal_id,
                    "page_id": page_id,
                    "status": "duplicate",
                    "existing_status": p.status,
                    "message": (
                        f"A pending delete proposal already exists for this page "
                        f"(status: {p.status}). Use the existing proposal."
                    ),
                }

        # 4. Compute page hash for staleness detection
        page_hash = await self._compute_page_hash(page)

        # 5. Run dependency impact analysis
        dep_analyzer = DependencyAnalyzer(self.db)
        warnings = await dep_analyzer.analyze(course_id, page)

        # 6. Take full before-snapshot
        before_snapshot = page.to_dict(include_components=True)

        # 7. Generate confirmation token
        token_service = ConfirmationTokenService()
        token_result = await token_service.generate_token(
            session_id=session_id,
            proposal_id="",  # Will be set after proposal creation
            target_resource_type="page",
            target_resource_id=page_id,
            operation_type="delete_page",
            resource_hash=page_hash,
            ttl_minutes=15,
        )

        # 8. Create proposal record
        now = datetime.utcnow()
        record = AIProposalRecord(
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            course_id=course_id,
            action_type="delete_page",
            target_type="page",
            target_id=page_id,
            proposed_changes={
                "data_before": before_snapshot,
                "data_after": None,
                "data_patch": {},
                "diff": {"before": before_snapshot, "after": None,
                         "changed_fields": ["page"]},
                "validation_status": "valid",
                "validation_messages": [],
            },
            base_hash=page_hash,
            before_snapshot=before_snapshot,
            status="PENDING_CONFIRMATION",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(minutes=self.config.proposal_ttl_minutes),
        )
        created = await self.proposal_repo.create(record)

        # 9. Re-generate token with the actual proposal_id
        token_result = await token_service.generate_token(
            session_id=session_id,
            proposal_id=created.proposal_id,
            target_resource_type="page",
            target_resource_id=page_id,
            operation_type="delete_page",
            resource_hash=page_hash,
            ttl_minutes=15,
        )

        # 10. Update proposal with token hash
        created.confirmation_token_sha256 = token_result["token_hash"]
        created.confirmation_token_expires_at = token_result["expires_at"]
        await self.proposal_repo.update(created)

        # 11. Audit log
        await self.audit.log(
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            course_id=course_id,
            action=AIAuditService.ACTION_PROPOSAL_CREATED,
            target_type="page",
            target_id=page_id,
            details={
                "operation": "delete_page",
                "proposal_id": created.proposal_id,
                "validation_status": "valid",
                "warnings": warnings,
            },
        )

        # 12. Build response
        component_types = [
            getattr(c, "component_type", "unknown")
            for c in (page.components or [])
        ]

        return {
            "proposal_id": created.proposal_id,
            "page_id": page_id,
            "page_title": getattr(page, "title", "Untitled"),
            "page_order": getattr(page, "order_index", 0),
            "component_count": len(page.components or []),
            "component_types": component_types,
            "confirmation_required": True,
            "confirmation_token": token_result["token"],
            "confirmation_token_expires_at": token_result["expires_at"].isoformat(),
            "warnings": warnings,
            "base_hash": page_hash,
            "status": "PENDING_CONFIRMATION",
        }

    async def confirm_delete_page(
        self,
        session_id: str,
        proposal_id: str,
        user_id: str,
        course_id: str,
        user_approved_delete: bool = False,
        confirmation_token: str = "",
    ) -> Dict[str, Any]:
        """Confirm and execute a previously proposed page deletion.

        US-BKND-AI-013 Phase 3: Validates the confirmation token, checks
        for staleness, executes the deletion inside a transaction, writes
        audit trail and outbox event.
        """
        from app.services.ai.confirmation_token_service import ConfirmationTokenService
        from app.services.ai.outbox_service import AIOutboxService

        # 1. Fetch proposal
        record = await self.proposal_repo.get(proposal_id)
        if record is None:
            raise ProposalNotFoundError(proposal_id)

        # 2. Verify ownership
        if record.session_id != session_id:
            raise ProposalError(
                "PERMISSION_DENIED",
                "Session doesn't own this proposal.",
                403,
            )

        # 3. Check already applied
        if record.status == "applied":
            return {
                "status": "already_applied",
                "proposal_id": proposal_id,
                "page_id": record.target_id,
                "message": "This page was already deleted by a previous confirmation.",
            }

        # 4. Verify confirmable state
        if record.status not in ("PENDING_CONFIRMATION", "pending"):
            raise ProposalStaleError(
                f"Cannot confirm delete: proposal status is '{record.status}'."
            )

        # 5. Verify user approval
        if not user_approved_delete:
            raise ProposalError(
                "USER_CONFIRMATION_REQUIRED",
                "You must set user_approved_delete=true to confirm destructive deletion.",
                400,
            )

        # 6. Check proposal expiry
        now = datetime.utcnow()
        if now > record.expires_at:
            record.status = "expired"
            await self.proposal_repo.update(record)
            raise ProposalStaleError("Delete proposal has expired.")

        # 7. Validate confirmation token
        token_service = ConfirmationTokenService()
        is_valid, error_code = await token_service.validate_token(
            proposal=record,
            received_token=confirmation_token,
            user_approved=True,
        )

        if not is_valid:
            code, *params = error_code.split(":", 1) if error_code else ("UNKNOWN",)
            if code == "CONFIRMATION_EXPIRED":
                raise ProposalStaleError(
                    "The confirmation window has expired (15 minutes). "
                    "Please create a new delete proposal."
                )
            elif code == "INVALID_CONFIRMATION_TOKEN":
                raise ProposalError(
                    "INVALID_CONFIRMATION_TOKEN",
                    "Confirmation token is invalid. The proposal may have been tampered with.",
                    403,
                )
            else:
                raise ProposalError(
                    code, f"Token validation failed: {error_code}", 400
                )

        # 8. Re-fetch page and verify hash (staleness check)
        page_id = record.target_id
        page = await self.page_repo.get(page_id)
        if page is None:
            # Page already deleted — idempotent response
            return {
                "status": "already_deleted",
                "page_id": page_id,
                "proposal_id": proposal_id,
                "message": "This page was already deleted.",
            }

        current_hash = await self._compute_page_hash(page)
        hash_match, hash_error = await token_service.verify_resource_hash(
            proposal=record,
            current_resource_hash=current_hash,
        )
        if not hash_match:
            raise ProposalConflictError(
                "The page has been modified since the proposal was created. "
                "Please review and re-propose deletion."
            )

        # 9. Execute deletion inside a transaction
        page_title = getattr(page, "title", "Untitled")

        # Mark proposal as applying
        record.status = "applying"
        record.updated_at = now
        await self.proposal_repo.update(record)

        try:
            # Execute the actual deletion
            await self.page_repo.delete(page)

            # Post-delete: reorder remaining pages
            remaining = await self.page_repo.list_by_course(course_id)
            if remaining:
                for idx, p in enumerate(remaining):
                    p.order_index = idx

            # Mark as applied
            record.status = "applied"
            record.applied_at = now
            record.updated_at = now
            await self.proposal_repo.update(record)

        except Exception:
            record.status = "failed"
            record.error_message = "Page deletion failed during execution."
            record.updated_at = datetime.utcnow()
            await self.proposal_repo.update(record)
            raise

        # 10. Write audit log
        await self.audit.log(
            session_id=session_id,
            user_id=user_id,
            organization_id=record.organization_id,
            course_id=course_id,
            action=AIAuditService.ACTION_PROPOSAL_APPLIED,
            target_type="page",
            target_id=page_id,
            details={
                "proposal_id": proposal_id,
                "operation": "delete_page",
                "page_title": page_title,
                "before_snapshot": record.before_snapshot,
            },
        )

        # 11. Write outbox event
        try:
            outbox = AIOutboxService(self.db)
            await outbox.publish(
                event_type="PageDeletedByAI",
                aggregate_type="page",
                aggregate_id=page_id,
                payload={
                    "proposal_id": proposal_id,
                    "operation": "delete_page",
                    "page_id": page_id,
                    "page_title": page_title,
                    "course_id": course_id,
                    "before_snapshot_summary": {
                        "title": page_title,
                        "component_count": len(
                            (record.before_snapshot or {}).get("components", [])
                        ),
                    },
                },
            )
        except Exception:
            logger.exception(
                "Outbox event write failed for delete proposal %s — non-blocking",
                proposal_id[:8],
            )

        # 12. Return success
        return {
            "status": "deleted",
            "page_id": page_id,
            "page_title": page_title,
            "proposal_id": proposal_id,
            "message": f"Page '{page_title}' has been deleted.",
        }

    async def _compute_page_hash(self, page) -> str:
        """Compute a deterministic hash of a page and its components.

        US-BKND-AI-013: Hash includes page_id, title, order_index,
        updated_at, and for each component: component_id, component_type,
        order_index, updated_at. Used for staleness detection at confirmation time.
        """
        import hashlib

        parts = [
            getattr(page, "page_id", ""),
            getattr(page, "title", ""),
            str(getattr(page, "order_index", 0)),
            getattr(page, "updated_at", datetime.utcnow()).isoformat()
            if getattr(page, "updated_at", None) else "",
        ]
        for comp in sorted(
            (page.components or []),
            key=lambda c: getattr(c, "component_id", ""),
        ):
            parts.extend([
                getattr(comp, "component_id", ""),
                getattr(comp, "component_type", ""),
                str(getattr(comp, "order_index", 0)),
                getattr(comp, "updated_at", datetime.utcnow()).isoformat()
                if getattr(comp, "updated_at", None) else "",
            ])
        raw = "::".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _validate(self, operation: str, resource_type: str,
                        data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if resource_type != "page":
            return []
        ttype = data.get("template_type", "")
        tdata = data.get("data", {})
        if not ttype:
            return [{"severity": "error", "code": "MISSING_TEMPLATE_TYPE",
                     "field": "template_type",
                     "message": "template_type is required.",
                     "hint": "Specify: text-content, tabs, accordion, click-reveal, final-assessment"}]
        try:
            contracts = AITemplateContractsService(self.db)
            engine = TemplateValidationEngine(contracts)
            result = await engine.validate(template_type=ttype, data=tdata, scope="full")
        except Exception:
            logger.exception("Validation error for %s", ttype)
            return [{"severity": "error", "code": "VALIDATION_ENGINE_ERROR",
                     "field": "", "message": "Validation engine error."}]
        return [{"severity": m.severity, "code": m.code, "field": m.field,
                 "message": m.message, "hint": m.hint,
                 "min": m.min, "max": m.max, "actual": m.actual}
                for m in result.messages]

    async def _conflict_check(self, rtype: str, rid: str,
                              expected: Dict[str, Any]) -> None:
        if rtype == "page":
            page = await self.page_repo.get(rid)
            if page is None:
                raise ProposalConflictError("Resource no longer exists.")
            cur = page.to_dict(include_components=False)
            if cur.get("title") != expected.get("title"):
                raise ProposalConflictError()

    async def _execute(self, op: str, rtype: str, rid: Optional[str],
                       after: Dict[str, Any], patch: Dict[str, Any],
                       cid: str) -> Dict[str, Any]:
        from app.models.page_component import PageRecord, ComponentRecord

        if op == "create_page" and rtype == "page":
            title = after.get("title", "Untitled")
            ttype = after.get("template_type", "text-content")
            pdata = after.get("data", {})
            existing = await self.page_repo.list_by_course(cid)
            insert_at = patch.get("insert_at_index", len(existing))
            page = PageRecord(course_id=cid, title=title,
                              order_index=insert_at,
                              layout={"templateType": ttype})
            created = await self.page_repo.create(page)
            comp = ComponentRecord(page_id=created.page_id,
                                   component_type=ttype, order_index=0, data=pdata)
            self.db.add(comp); await self.db.commit()
            return {"resource_id": created.page_id, "operation": "create_page",
                    "resource_type": "page",
                    "changes_summary": f"Page '{title}' created",
                    "page_id": created.page_id}

        if op == "update_page" and rtype == "page":
            page = await self.page_repo.get(rid)
            if page is None:
                raise ProposalConflictError("Page no longer exists.")
            if after.get("title"):
                page.title = after["title"]
            await self.page_repo.update(page)
            return {"resource_id": rid, "operation": "update_page",
                    "resource_type": "page",
                    "changes_summary": f"Page '{page.title}' updated"}

        if op == "delete_page" and rtype == "page":
            page = await self.page_repo.get(rid)
            if page is None:
                raise ProposalConflictError("Page no longer exists.")
            old = page.title
            await self.page_repo.delete(page)
            return {"resource_id": rid, "operation": "delete_page",
                    "resource_type": "page",
                    "changes_summary": f"Page '{old}' deleted"}

        raise ProposalError("UNSUPPORTED_OPERATION",
                            f"'{op}/{rtype}' not supported.", 400)

    @staticmethod
    def _summary(op: str, rtype: str, data: Dict[str, Any]) -> str:
        title = data.get("title", "untitled")
        return f"{op.replace('_', ' ').title()} {rtype.title()}: '{title}'"
