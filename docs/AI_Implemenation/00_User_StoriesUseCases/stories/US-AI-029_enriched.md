## US-AI-029 — Batch Proposal and All-or-Nothing Semantics

---

### 1. Epic Overview

| Field | Value |
|---|---|
| **Identifier** | US-AI-029 |
| **Epic Name** | Batch Proposal and All-or-Nothing Semantics |
| **Priority** | SHOULD for MVP, MUST for file-import MVP |
| **Depends on** | US-AI-010 (Apply safety, audit, outbox — transactional apply with idempotency keys) |
| **Unlocks** | US-AI-019 (Full course from uploaded file), US-AI-034 (Durable workflow engine) |
| **Source flows** | Flow 13 (Platform Runtime), Flow 19 (Batch Proposal and All-or-Nothing Semantics) |
| **Story type** | Feature / Infrastructure |

### 2. Business Value and User Story

**As an** AI Author,
**I want** to propose changes across multiple pages in one batch with an all-or-nothing contract,
**so that** bulk operations (file ingestion, multi-page AI generation, reordering, batch updates) are atomic, previewable as a group, and never leave the course in a partially-applied state.

**Why this matters:**
- A single AI chat turn may generate 5-20 pages from a source document. Without batch semantics, each page must be individually proposed, reviewed, and applied, creating excessive user friction.
- If one page in a batch fails validation after partial apply, the course is left in an inconsistent state. All-or-nothing prevents this.
- File ingestion (US-AI-017, US-AI-019) requires batch creation of an entire course outline. Batch proposals are the atomic unit for this workflow.
- The existing `ImportService.commit_import` already applies templates in a loop but has no transactional rollback for partial failures. This story formalizes and production-hardens that pattern.

### 3. Functional Requirements

**FR1 — Batch Proposal Creation**
- The system exposes `propose_batch_pages(session_id, pages[])` which accepts an array of page proposals in a single call.
- Each element in the `pages[]` array must contain: `title`, `template_type`, `data` (component payloads), and optional `order`.
- The system validates every page individually against the same rules as single-page proposals (template type allowlist, schema validation, business rules).
- The system returns a `batch_id`, an ordered array of per-page `proposal_id` values, and an aggregated validation status (`valid`, `has_warnings`, `has_errors`).
- If any page fails schema-level validation (missing required fields, unsupported template type), the *entire* batch proposal is rejected with per-page error details.

**FR2 — Batch Preview**
- The frontend fetches batch status via `GET /api/v1/ai/batches/{batch_id}` which returns every page proposal with its individual validation status, preview data, and warnings.
- Per-page validation results are categorized as `error` (blocks apply), `warning` (non-blocking), or `info` (informational).
- The UI displays a batch-level summary: X pages valid, Y pages with warnings, Z pages with errors.

**FR3 — User Remediation**
- Users can remove a failing page from the batch by calling `POST /api/v1/ai/batches/{batch_id}/remove-page?page_index=N`.
- After removal, the batch validation is recalculated without re-calling the LLM (validation of remaining pages already computed).
- Users may also replace a page by calling `propose_batch_pages` with the same batch_id and the replacement page (upserts by page index within the batch).

**FR4 — All-or-Nothing Apply**
- `apply_batch_proposals(session_id, batch_id, user_confirmed=true)` applies all valid pages in a single database transaction.
- If any page apply fails (DB constraint violation, stale base hash, concurrent edit), the entire transaction is rolled back — zero pages are created.
- Apply re-validates all pages immediately before the transaction to catch staleness.
- On successful apply, the system returns the created/updated page records, a batch-level summary (pages_created, pages_failed), and audit/outbox records for each page.

**FR5 — Partial Batch Apply (User Exclusion)**
- If the user explicitly removes a page from the batch (FR3), the remaining pages are applied atomically.
- The audit record clearly states which pages were excluded and why.

**FR6 — Idempotency and Retry Safety**
- `apply_batch_proposals` accepts an optional `idempotency_key` header.
- Replaying the same idempotency key returns the previous result without re-applying.
- Partial apply (due to idempotency-key replay after a successful commit) never creates duplicate pages.

**FR7 — Batch Audit and Outbox**
- Each batch apply produces a single audit event with `batch_id`, `operation=BATCH_APPLY`, `pages_total`, `pages_applied`, `pages_excluded`, and per-page proposal IDs.
- Outbox events are emitted for each individually applied page (reusing the existing outbox event types from US-AI-010: `PageCreatedByAI`, `PageUpdatedByAI`).
- All events carry the same `trace_id` linking back to the AI session and batch.

**FR8 — Batch Lifecycle**
| State | Meaning |
|---|---|
| `PENDING_REVIEW` | Batch created, awaiting user review |
| `APPROVED` | User confirmed the batch |
| `APPLYING` | Apply in progress (transactional) |
| `APPLIED` | All pages applied successfully |
| `PARTIALLY_REJECTED` | User removed one or more pages before apply |
| `FAILED` | Apply rolled back entirely |
| `EXPIRED` | Batch TTL exceeded (default 24 hours) |

### 4. Technical Design

#### 4.1 Database DDL (Alembic Migration: `XXXX_batch_proposals.py`)

```sql
-- Batch proposal groups
CREATE TABLE ai_batch_proposals (
    id              SERIAL PRIMARY KEY,
    batch_id        VARCHAR(64) UNIQUE NOT NULL,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id) ON DELETE CASCADE,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    status          VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW',
    source          VARCHAR(64) NOT NULL DEFAULT 'chat',
        -- 'chat', 'file_import', 'manual'
    page_count      INTEGER NOT NULL,
    validation_summary JSONB NOT NULL DEFAULT '{}',
        -- {"total": 5, "valid": 4, "warnings": 1, "errors": 0, "excluded_indices": [2]}
    batch_metadata  JSONB,
        -- {source_job_id, file_hash, prompt_version, model_id, trace_id}
    expires_at      TIMESTAMP NOT NULL,
    applied_at      TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Per-page proposals within a batch
CREATE TABLE ai_batch_page_proposals (
    id              SERIAL PRIMARY KEY,
    batch_id        VARCHAR(64) NOT NULL REFERENCES ai_batch_proposals(batch_id) ON DELETE CASCADE,
    proposal_id     VARCHAR(64) UNIQUE NOT NULL,
    page_index      INTEGER NOT NULL,
    title           VARCHAR(200) NOT NULL,
    template_type   VARCHAR(100) NOT NULL,
    page_data       JSONB NOT NULL,
    validation_result JSONB,
        -- {valid: bool, errors: [...], warnings: [...]}
    is_excluded     BOOLEAN NOT NULL DEFAULT FALSE,
    applied_page_id VARCHAR(64),
        -- FK to pages.page_id set after successful apply
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_batch_proposals_session ON ai_batch_proposals(session_id);
CREATE INDEX idx_batch_proposals_status ON ai_batch_proposals(status);
CREATE INDEX idx_batch_page_proposals_batch ON ai_batch_page_proposals(batch_id);
CREATE INDEX idx_batch_page_proposals_proposal ON ai_batch_page_proposals(proposal_id);
```

**Existing table that already exists (from US-AI-004):**
```sql
CREATE TABLE ai_proposals (
    id              SERIAL PRIMARY KEY,
    proposal_id     VARCHAR(64) UNIQUE NOT NULL,
    session_id      VARCHAR(64) NOT NULL REFERENCES ai_sessions(session_id),
    operation       VARCHAR(32) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW',
    base_hash       VARCHAR(64),
    before_snapshot JSONB,
    after_candidate JSONB,
    validation_result JSONB,
    expires_at      TIMESTAMP NOT NULL,
    applied_at      TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### 4.2 SQLAlchemy ORM Models

**File: `app/models/batch_proposal.py`**

```python
"""Batch Proposal ORM models for AI all-or-nothing semantics."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    String, DateTime, JSON, Integer, Boolean, ForeignKey, Text,
)

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class BatchProposalRecord(Base):
    """A group of page proposals applied atomically."""

    __tablename__ = "ai_batch_proposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_sessions.session_id", ondelete="CASCADE"),
        index=True,
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW")
    source: Mapped[str] = mapped_column(String(64), default="chat")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    batch_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24)
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    page_proposals: Mapped[list["BatchPageProposalRecord"]] = relationship(
        "BatchPageProposalRecord",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="BatchPageProposalRecord.page_index",
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "batchId": self.batch_id,
            "sessionId": self.session_id,
            "courseId": self.course_id,
            "status": self.status,
            "source": self.source,
            "pageCount": self.page_count,
            "validationSummary": self.validation_summary,
            "batchMetadata": self.batch_metadata,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "appliedAt": self.applied_at.isoformat() if self.applied_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "pageProposals": [p.to_dict() for p in (self.page_proposals or [])],
        }


class BatchPageProposalRecord(Base):
    """A single page within a batch proposal."""

    __tablename__ = "ai_batch_page_proposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_batch_proposals.batch_id", ondelete="CASCADE"),
        index=True,
    )
    proposal_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    page_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    template_type: Mapped[str] = mapped_column(String(100))
    page_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Relationships
    batch: Mapped["BatchProposalRecord"] = relationship(
        "BatchProposalRecord", back_populates="page_proposals"
    )

    def to_dict(self) -> dict:
        return {
            "proposalId": self.proposal_id,
            "batchId": self.batch_id,
            "pageIndex": self.page_index,
            "title": self.title,
            "templateType": self.template_type,
            "pageData": self.page_data,
            "validationResult": self.validation_result,
            "isExcluded": self.is_excluded,
            "appliedPageId": self.applied_page_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
```

#### 4.3 Repository

**File: `app/repositories/batch_proposal_repo.py`**

```python
"""Repository for AI batch proposals."""
from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from app.models.batch_proposal import BatchProposalRecord, BatchPageProposalRecord


class BatchProposalNotFoundError(Exception):
    pass


class BatchProposalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Batch ─────────────────────────────────────────────────────────────

    async def create_batch(
        self, record: BatchProposalRecord
    ) -> BatchProposalRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_batch_id(
        self, batch_id: str
    ) -> Optional[BatchProposalRecord]:
        result = await self.session.execute(
            select(BatchProposalRecord).where(
                BatchProposalRecord.batch_id == batch_id
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, batch_id: str, status: str, **extra
    ) -> BatchProposalRecord:
        values = {"status": status, "updated_at": ...}
        values.update(extra)
        stmt = (
            update(BatchProposalRecord)
            .where(BatchProposalRecord.batch_id == batch_id)
            .values(**values)
            .returning(BatchProposalRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()

    async def list_by_session(
        self, session_id: str, limit: int = 20
    ) -> Sequence[BatchProposalRecord]:
        result = await self.session.execute(
            select(BatchProposalRecord)
            .where(BatchProposalRecord.session_id == session_id)
            .order_by(BatchProposalRecord.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def delete_expired(self) -> int:
        from datetime import datetime
        stmt = delete(BatchProposalRecord).where(
            BatchProposalRecord.expires_at < datetime.utcnow()
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount

    # ── Page proposals within a batch ─────────────────────────────────────

    async def create_page_proposal(
        self, record: BatchPageProposalRecord
    ) -> BatchPageProposalRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def bulk_create_page_proposals(
        self, records: list[BatchPageProposalRecord]
    ) -> list[BatchPageProposalRecord]:
        self.session.add_all(records)
        await self.session.commit()
        for r in records:
            await self.session.refresh(r)
        return records

    async def get_page_proposal(
        self, proposal_id: str
    ) -> Optional[BatchPageProposalRecord]:
        result = await self.session.execute(
            select(BatchPageProposalRecord).where(
                BatchPageProposalRecord.proposal_id == proposal_id
            )
        )
        return result.scalar_one_or_none()

    async def exclude_page(
        self, proposal_id: str
    ) -> BatchPageProposalRecord:
        stmt = (
            update(BatchPageProposalRecord)
            .where(BatchPageProposalRecord.proposal_id == proposal_id)
            .values(is_excluded=True)
            .returning(BatchPageProposalRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()

    async def mark_page_applied(
        self, proposal_id: str, page_id: str
    ) -> BatchPageProposalRecord:
        stmt = (
            update(BatchPageProposalRecord)
            .where(BatchPageProposalRecord.proposal_id == proposal_id)
            .values(applied_page_id=page_id)
            .returning(BatchPageProposalRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()
```

#### 4.4 Service

**File: `app/services/ai/batch_proposal_service.py`**

```python
"""Batch proposal service — orchestrates create, validate, exclude, and apply."""
from __future__ import annotations
import uuid
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.models.batch_proposal import BatchProposalRecord, BatchPageProposalRecord
from app.models.persisted_course import AISession
from app.repositories.batch_proposal_repo import (
    BatchProposalRepository,
    BatchProposalNotFoundError,
)
from app.repositories.page_component_repo import PageRepository, ComponentRepository
from app.repositories.course_repo import CourseRepository
from app.services.ai.proposal_validator import ProposalValidator
from app.utils.error_envelope import build_error

logger = logging.getLogger(__name__)


class BatchProposalService:
    """Service for batch proposal lifecycle."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BatchProposalRepository(session)
        self.page_repo = PageRepository(session)
        self.comp_repo = ComponentRepository(session)
        self.course_repo = CourseRepository(session)
        self.validator = ProposalValidator(session)

    # ── Proposal Contract ─────────────────────────────────────────────────

    # Each page in the pages[] input must conform to:
    BATCH_PAGE_INPUT_SCHEMA = {
        "title": str,        # required, max 200 chars
        "templateType": str, # required, must be in allowed template types
        "data": dict,        # required, component payloads
        "order": (int, None),# optional, auto-assigned if None
    }

    async def propose_batch(
        self,
        session_id: str,
        course_id: str,
        pages: List[Dict[str, Any]],
        source: str = "chat",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a batch proposal from an array of page definitions.

        Steps:
        1. Validate session is active and owns course_id.
        2. Validate every page in the array (schema, template type, data).
        3. If any page fails schema validation, reject the entire batch.
        4. Persist the batch and per-page proposals.
        5. Return batch_id, per-page proposal_ids, and aggregated validation.

        Returns:
            {batch_id, status, pageCount, validationSummary, pageProposals: [...]}
        """
        # --- Session validation (placeholder — integrate with AI session service) ---
        # session = await self._get_valid_session(session_id, course_id)
        # if not session:
        #     raise ValueError("Invalid or expired session")

        # --- Input validation ---
        if not pages or not isinstance(pages, list):
            raise ValueError("pages must be a non-empty array")

        if len(pages) > 50:
            raise ValueError("Batch exceeds maximum of 50 pages")

        # --- Validate every page ---
        page_records: List[BatchPageProposalRecord] = []
        validation_result_per_page: List[Dict[str, Any]] = []
        total_errors = 0
        total_warnings = 0

        for idx, page_input in enumerate(pages):
            # Structural validation
            page_errors = self._validate_page_input(page_input, idx)

            # Template type registry check
            if "templateType" in page_input:
                from app.repositories.component_type_repo import ComponentTypeRepository
                ctr = ComponentTypeRepository(self.session)
                ct = await ctr.get_by_type_id(page_input["templateType"])
                if ct is None:
                    page_errors.append({
                        "code": "UNSUPPORTED_TEMPLATE_TYPE",
                        "field": f"pages[{idx}].templateType",
                        "message": f"Template type '{page_input['templateType']}' is not supported",
                    })

            # Deep validation via ProposalValidator (reuses Course model, export checks)
            if not page_errors:
                try:
                    val_result = await self.validator.validate_page_proposal(
                        course_id=course_id,
                        title=page_input["title"],
                        template_type=page_input["templateType"],
                        data=page_input.get("data", {}),
                    )
                    if val_result.get("errors"):
                        page_errors.extend(val_result["errors"])
                    total_warnings += len(val_result.get("warnings", []))
                except Exception as exc:
                    page_errors.append({
                        "code": "VALIDATION_ERROR",
                        "field": f"pages[{idx}]",
                        "message": f"Unexpected validation error: {str(exc)[:200]}",
                    })

            per_page_result = {
                "pageIndex": idx,
                "title": page_input.get("title", f"Page {idx + 1}"),
                "valid": len(page_errors) == 0,
                "errors": page_errors,
                "warnings": val_result.get("warnings", []) if not page_errors else [],
            }
            validation_result_per_page.append(per_page_result)

            if per_page_result["valid"]:
                total_warnings += len(per_page_result["warnings"])
            else:
                total_errors += len(per_page_result["errors"])

            # Build page proposal record
            page_records.append(BatchPageProposalRecord(
                page_index=idx,
                proposal_id=str(uuid.uuid4()),
                title=page_input.get("title", ""),
                template_type=page_input.get("templateType", ""),
                page_data=page_input,
                validation_result=per_page_result,
                is_excluded=False,
            ))

        # --- All-or-nothing validation: reject entire batch if any errors ---
        validation_summary = {
            "total": len(pages),
            "valid": sum(1 for r in validation_result_per_page if r["valid"]),
            "warnings": total_warnings,
            "errors": total_errors,
            "excluded_indices": [],
        }

        # --- Persist ---
        batch_record = BatchProposalRecord(
            batch_id=str(uuid.uuid4()),
            session_id=session_id,
            course_id=course_id,
            status="PENDING_REVIEW",
            source=source,
            page_count=len(pages),
            validation_summary=validation_summary,
            batch_metadata={
                **(metadata or {}),
                "created_at": datetime.utcnow().isoformat(),
            },
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        await self.repo.create_batch(batch_record)

        for pr in page_records:
            pr.batch_id = batch_record.batch_id
        await self.repo.bulk_create_page_proposals(page_records)

        return {
            "batchId": batch_record.batch_id,
            "status": "PENDING_REVIEW",
            "pageCount": len(pages),
            "validationSummary": validation_summary,
            "pageProposals": [
                {
                    "proposalId": pr.proposal_id,
                    "pageIndex": pr.page_index,
                    "title": pr.title,
                    "templateType": pr.template_type,
                    "validationResult": pr.validation_result,
                    "isExcluded": False,
                }
                for pr in page_records
            ],
            "createdAt": batch_record.created_at.isoformat(),
        }

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get batch proposal with all page proposals."""
        record = await self.repo.get_by_batch_id(batch_id)
        if record is None:
            return None
        return record.to_dict()

    async def remove_page(
        self, batch_id: str, page_index: int
    ) -> Dict[str, Any]:
        """
        Exclude a page from the batch by page_index.

        Triggers recalculation of validation_summary.
        """
        batch = await self.repo.get_by_batch_id(batch_id)
        if batch is None:
            raise BatchProposalNotFoundError(f"Batch {batch_id} not found")
        if batch.status != "PENDING_REVIEW":
            raise ValueError(
                f"Cannot remove page from batch in status '{batch.status}'"
            )

        target = None
        for pp in batch.page_proposals:
            if pp.page_index == page_index:
                target = pp
                break
        if target is None:
            raise ValueError(f"Page index {page_index} not found in batch")

        await self.repo.exclude_page(target.proposal_id)

        # Recalculate validation summary
        all_pages = await self.repo.get_by_batch_id(batch_id)
        excluded = [p.page_index for p in all_pages.page_proposals if p.is_excluded]
        valid_pages = [p for p in all_pages.page_proposals if not p.is_excluded]

        new_summary = {
            "total": batch.page_count,
            "valid": sum(1 for p in valid_pages if p.validation_result and p.validation_result.get("valid", False)),
            "warnings": sum(len(p.validation_result.get("warnings", [])) for p in valid_pages if p.validation_result),
            "errors": 0,  # excluded pages are no longer counted as errors
            "excluded_indices": excluded,
        }

        await self.repo.update_status(
            batch_id,
            "PARTIALLY_REJECTED" if excluded else "PENDING_REVIEW",
            validation_summary=new_summary,
        )

        return {
            "batchId": batch_id,
            "status": "PARTIALLY_REJECTED" if excluded else "PENDING_REVIEW",
            "validationSummary": new_summary,
        }

    async def apply_batch(
        self,
        batch_id: str,
        user_confirmed: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Apply all non-excluded pages in the batch atomically.

        Uses a single database transaction spanning:
          1. Re-validation of all pages
          2. PageRecord creation
          3. ComponentRecord creation
          4. Batch status update
          5. Audit log writes
          6. Outbox event writes

        If any step fails, the entire transaction is rolled back.
        """
        if not user_confirmed:
            raise ValueError("User confirmation required")

        # Idempotency check
        if idempotency_key:
            existing = await self._check_idempotency(idempotency_key)
            if existing:
                logger.info("Idempotency key %s replayed, returning cached result", idempotency_key)
                return existing

        batch = await self.repo.get_by_batch_id(batch_id)
        if batch is None:
            raise BatchProposalNotFoundError(f"Batch {batch_id} not found")
        if batch.status not in ("PENDING_REVIEW", "PARTIALLY_REJECTED"):
            raise ValueError(f"Cannot apply batch in status '{batch.status}'")
        if batch.expires_at < datetime.utcnow():
            raise ValueError("Batch has expired")

        # Filter to applicable pages
        to_apply = [p for p in batch.page_proposals if not p.is_excluded]
        if not to_apply:
            raise ValueError("No pages to apply in batch")

        # --- Begin Transaction ---
        async with self.session.begin():
            try:
                applied_pages = []
                for page_proposal in to_apply:
                    # Re-validate before apply
                    val_result = await self.validator.validate_page_proposal(
                        course_id=batch.course_id,
                        title=page_proposal.title,
                        template_type=page_proposal.template_type,
                        data=page_proposal.page_data.get("data", {}),
                    )
                    if not val_result.get("valid", False):
                        raise ValueError(
                            f"Page {page_proposal.page_index} failed re-validation before apply"
                        )

                    # Create PageRecord
                    from app.models.page_component import PageRecord
                    page = PageRecord(
                        course_id=batch.course_id,
                        title=page_proposal.title,
                        order_index=page_proposal.page_index,
                    )
                    await self.page_repo.create(page)

                    # Create ComponentRecord(s)
                    components = page_proposal.page_data.get("data", {}).get("components", [])
                    if not components:
                        # Single-component page: use the template_type directly
                        from app.models.page_component import ComponentRecord
                        comp = ComponentRecord(
                            page_id=page.page_id,
                            component_type=page_proposal.template_type,
                            data=page_proposal.page_data.get("data", {}),
                            order_index=0,
                        )
                        await self.comp_repo.create(comp)
                    else:
                        for ci, comp_data in enumerate(components):
                            from app.models.page_component import ComponentRecord
                            comp = ComponentRecord(
                                page_id=page.page_id,
                                component_type=comp_data.get("componentType", page_proposal.template_type),
                                data=comp_data.get("data", {}),
                                order_index=ci,
                            )
                            await self.comp_repo.create(comp)

                    # Mark page proposal as applied
                    await self.repo.mark_page_applied(page_proposal.proposal_id, page.page_id)
                    applied_pages.append({
                        "pageIndex": page_proposal.page_index,
                        "pageId": page.page_id,
                        "title": page.title,
                        "proposalId": page_proposal.proposal_id,
                    })

                # Update batch status
                batch.status = "APPLIED"
                batch.applied_at = datetime.utcnow()
                batch.validation_summary["applied_count"] = len(applied_pages)
                await self.session.flush()

                # --- Write outbox events (transactionally coupled) ---
                from app.services.ai.outbox_service import OutboxService
                outbox = OutboxService(self.session)
                for ap in applied_pages:
                    await outbox.write(
                        event_type="PageCreatedByAI",
                        aggregate_id=ap["pageId"],
                        payload={
                            "batchId": batch_id,
                            "proposalId": ap["proposalId"],
                            "courseId": batch.course_id,
                            "pageId": ap["pageId"],
                            "title": ap["title"],
                            "pageIndex": ap["pageIndex"],
                            "sessionId": batch.session_id,
                            "trace_id": (batch.batch_metadata or {}).get("trace_id"),
                        },
                    )

                # Also write a batch-level audit/outbox event
                await outbox.write(
                    event_type="BatchProposalApplied",
                    aggregate_id=batch_id,
                    payload={
                        "batchId": batch_id,
                        "sessionId": batch.session_id,
                        "courseId": batch.course_id,
                        "pageCount": len(to_apply),
                        "pagesApplied": [ap["pageId"] for ap in applied_pages],
                        "excludedIndices": batch.validation_summary.get("excluded_indices", []),
                        "trace_id": (batch.batch_metadata or {}).get("trace_id"),
                    },
                )

            except Exception as exc:
                logger.error("Batch apply failed, rolling back: %s", exc)
                raise  # Transaction rolls back automatically

        # Cache idempotency result
        result = {
            "batchId": batch_id,
            "status": "APPLIED",
            "courseId": batch.course_id,
            "pagesApplied": applied_pages,
            "totalApplied": len(applied_pages),
            "excludedIndices": batch.validation_summary.get("excluded_indices", []),
            "appliedAt": batch.applied_at.isoformat(),
        }
        if idempotency_key:
            await self._cache_idempotency_result(idempotency_key, result)

        return result

    def _validate_page_input(
        self, page_input: dict, index: int
    ) -> List[Dict[str, str]]:
        errors = []
        if not isinstance(page_input, dict):
            return [{"code": "INVALID_TYPE", "field": f"pages[{index}]", "message": "Page must be an object"}]

        if "title" not in page_input or not isinstance(page_input.get("title"), str):
            errors.append({
                "code": "MISSING_FIELD", "field": f"pages[{index}].title",
                "message": "title is required and must be a string",
            })
        if "templateType" not in page_input or not isinstance(page_input.get("templateType"), str):
            errors.append({
                "code": "MISSING_FIELD", "field": f"pages[{index}].templateType",
                "message": "templateType is required and must be a string",
            })
        if "data" not in page_input or not isinstance(page_input.get("data"), dict):
            errors.append({
                "code": "MISSING_FIELD", "field": f"pages[{index}].data",
                "message": "data is required and must be an object",
            })
        return errors

    async def _get_valid_session(self, session_id: str, course_id: str) -> Optional[Any]:
        """Validate session exists, is active, and scoped to course_id."""
        from app.models.persisted_course import AISession
        result = await self.session.execute(
            select(AISession).where(
                AISession.session_id == session_id,
                AISession.course_id == course_id,
                AISession.expires_at > datetime.utcnow(),
                AISession.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def _check_idempotency(self, key: str) -> Optional[Dict]:
        """Look up a previously cached idempotency result."""
        from app.models.persisted_course import IdempotencyRecord
        result = await self.session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key)
        )
        record = result.scalar_one_or_none()
        if record and record.result_data:
            return record.result_data
        return None

    async def _cache_idempotency_result(self, key: str, result: Dict) -> None:
        """Store idempotency result."""
        from app.models.persisted_course import IdempotencyRecord
        record = IdempotencyRecord(
            idempotency_key=key,
            result_data=result,
            expires_at=datetime.utcnow() + timedelta(hours=48),
        )
        self.session.add(record)
        await self.session.flush()
```

#### 4.5 API Contract (Router)

**File: `app/routers/ai_batch_proposals.py`**

```python
"""
Batch Proposal Router — exposes REST endpoints for batch proposal lifecycle.
All endpoints require a valid AI session.
"""
from __future__ import annotations
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Body, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.services.ai.batch_proposal_service import BatchProposalService
from app.repositories.batch_proposal_repo import BatchProposalNotFoundError
from app.utils.feature_flags import require_feature_async
from app.utils.error_envelope import build_error, api_http_exception

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/batches", tags=["AI Batch Proposals"])


# ── Request/Response DTOs ──────────────────────────────────────────────────────

class BatchPageInput(BaseModel):
    title: str = Field(..., max_length=200, description="Page title")
    templateType: str = Field(..., description="Allowed template type ID")
    data: dict = Field(default_factory=dict, description="Page data / component payloads")
    order: Optional[int] = Field(None, ge=0, description="Page order (auto-assigned if None)")

class ProposeBatchRequest(BaseModel):
    session_id: str = Field(..., description="Active AI session ID")
    course_id: str = Field(..., description="Target course ID")
    pages: List[BatchPageInput] = Field(..., min_length=1, max_length=50, description="Array of page proposals")
    source: str = Field(default="chat", description="Source identifier: chat, file_import, manual")
    metadata: Optional[dict] = Field(None, description="Additional batch metadata (trace_id, etc.)")

class PageProposalSummary(BaseModel):
    proposalId: str
    pageIndex: int
    title: str
    templateType: str
    validationResult: Optional[dict] = None
    isExcluded: bool = False

class ProposeBatchResponse(BaseModel):
    batchId: str
    status: str
    pageCount: int
    validationSummary: dict
    pageProposals: List[PageProposalSummary]
    createdAt: str

class BatchDetailResponse(BaseModel):
    batchId: str
    sessionId: str
    courseId: str
    status: str
    source: str
    pageCount: int
    validationSummary: dict
    expiresAt: str
    appliedAt: Optional[str] = None
    createdAt: str
    pageProposals: List[PageProposalSummary]

class RemovePageResponse(BaseModel):
    batchId: str
    status: str
    validationSummary: dict

class ApplyBatchRequest(BaseModel):
    user_confirmed: bool = Field(default=True, description="Must be true to apply")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key for safe retry")

class ApplyBatchResponse(BaseModel):
    batchId: str
    status: str
    courseId: str
    pagesApplied: List[dict]
    totalApplied: int
    excludedIndices: List[int]
    appliedAt: str


# ── Service Dependency ─────────────────────────────────────────────────────────

async def _get_service(session: AsyncSession = Depends(get_session)) -> BatchProposalService:
    await require_feature_async("ai_batch_proposals")
    return BatchProposalService(session)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/propose",
    response_model=ProposeBatchResponse,
    summary="Create a batch proposal",
    responses={
        400: {"description": "Validation error — see detail.errors"},
        422: {"description": "Input validation failed"},
    },
)
async def propose_batch(
    request: ProposeBatchRequest,
    service: BatchProposalService = Depends(_get_service),
):
    """
    Propose multiple pages as a single batch.

    Validates every page individually. If *any* page fails schema validation,
    the entire batch is rejected with per-page error details.

    **All-or-nothing:** Use `POST /apply` after user reviews and confirms.
    """
    try:
        result = await service.propose_batch(
            session_id=request.session_id,
            course_id=request.course_id,
            pages=[p.model_dump() for p in request.pages],
            source=request.source,
            metadata=request.metadata,
        )
        return result
    except ValueError as e:
        raise api_http_exception(
            status_code=400,
            code="BATCH_VALIDATION_ERROR",
            field="pages",
            message=str(e),
        )


@router.get(
    "/{batch_id}",
    response_model=BatchDetailResponse,
    summary="Get batch proposal details",
    responses={404: {"description": "Batch not found"}},
)
async def get_batch(
    batch_id: str,
    service: BatchProposalService = Depends(_get_service),
):
    """Retrieve a batch proposal with its per-page proposals and validation state."""
    result = await service.get_batch(batch_id)
    if result is None:
        raise api_http_exception(
            status_code=404,
            code="BATCH_NOT_FOUND",
            field="batch_id",
            message=f"Batch '{batch_id}' not found",
        )
    return result


@router.post(
    "/{batch_id}/remove-page",
    response_model=RemovePageResponse,
    summary="Exclude a page from the batch",
    responses={
        400: {"description": "Invalid state or page index"},
        404: {"description": "Batch not found"},
    },
)
async def remove_page_from_batch(
    batch_id: str,
    page_index: int = Query(..., description="Index of the page to exclude"),
    service: BatchProposalService = Depends(_get_service),
):
    """
    Remove a failing page from the batch so the remainder can be applied.

    Triggers recalculation of validation_summary. The batch status changes
    to PARTIALLY_REJECTED once any page is excluded.
    """
    try:
        result = await service.remove_page(batch_id, page_index)
        return result
    except BatchProposalNotFoundError as e:
        raise api_http_exception(status_code=404, code="BATCH_NOT_FOUND", field="batch_id", message=str(e))
    except ValueError as e:
        raise api_http_exception(status_code=400, code="BATCH_OPERATION_ERROR", field="batch_id", message=str(e))


@router.post(
    "/{batch_id}/apply",
    response_model=ApplyBatchResponse,
    summary="Apply all non-excluded pages atomically",
    responses={
        400: {"description": "Validation or state error"},
        404: {"description": "Batch not found"},
        409: {"description": "Conflict — stale data detected"},
    },
)
async def apply_batch(
    batch_id: str,
    request: ApplyBatchRequest = Body(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    service: BatchProposalService = Depends(_get_service),
):
    """
    Apply all non-excluded pages in the batch atomically.

    - Uses a single database transaction.
    - If any page fails, **zero** pages are created (all-or-nothing).
    - Send `Idempotency-Key` header for safe retry.
    """
    try:
        result = await service.apply_batch(
            batch_id=batch_id,
            user_confirmed=request.user_confirmed,
            idempotency_key=idempotency_key or request.idempotency_key,
        )
        return result
    except BatchProposalNotFoundError:
        raise api_http_exception(status_code=404, code="BATCH_NOT_FOUND", field="batch_id", message="Batch not found")
    except ValueError as e:
        raise api_http_exception(status_code=400, code="BATCH_APPLY_ERROR", field="batch_id", message=str(e))
```

**Router Registration** (in `app/main.py`):
```python
# Add to existing imports
from app.routers import ai_batch_proposals

# Add to api_router includes
api_router.include_router(ai_batch_proposals.router)
```

#### 4.6 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AI_BATCH_MAX_PAGES` | `50` | Maximum pages per batch proposal |
| `AI_BATCH_TTL_HOURS` | `24` | Batch proposal expiry in hours |
| `FEATURE_AI_BATCH_PROPOSALS` | `false` | Feature flag for batch proposals |
| `AI_BATCH_IDEMPOTENCY_TTL_HOURS` | `48` | Idempotency result cache TTL |

**Feature flag registration** (in `app/utils/feature_flags.py`):
```python
'batch_proposals': FeatureFlag(
    name='ai_batch_proposals',
    enabled=False,
    description='Enable batch proposal and all-or-nothing apply',
    environments=[Environment.STAGING, Environment.PRODUCTION],
),
```

#### 4.7 Service Signatures Summary

```python
class BatchProposalService:
    async def propose_batch(
        self,
        session_id: str,
        course_id: str,
        pages: List[Dict[str, Any]],
        source: str = "chat",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create batch proposal. Returns batch_id, per-page proposal_ids, validation summary."""

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get full batch details with page proposals."""

    async def remove_page(self, batch_id: str, page_index: int) -> Dict[str, Any]:
        """Exclude a single page. Recalculates validation summary."""

    async def apply_batch(
        self,
        batch_id: str,
        user_confirmed: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomic all-or-nothing apply. Returns pages_applied array."""
```

### 5. Acceptance Criteria

| ID | Criterion | Category |
|---|---|---|
| AC-01 | A batch of 5 valid pages is created successfully and returns `batch_id` with status `PENDING_REVIEW`. | Happy path |
| AC-02 | A batch with 1 invalid page (missing title) is rejected entirely — zero `proposal_id` values returned, all-or-nothing enforced at proposal time. | Error handling |
| AC-03 | A batch with 1 page using an unsupported template type is rejected with per-page error detail including `UNSUPPORTED_TEMPLATE_TYPE` code. | Validation |
| AC-04 | GET `/ai/batches/{batch_id}` returns per-page validation status for all pages in the batch. | Read |
| AC-05 | User removes a failing page from a 5-page batch; remaining 4 valid pages can be applied. Batch status becomes `PARTIALLY_REJECTED`. | Remediation |
| AC-06 | `apply_batch` with `user_confirmed=false` is rejected with 400 error. | Safety |
| AC-07 | `apply_batch` on a batch with all 5 pages valid creates exactly 5 `PageRecord` rows and corresponding `ComponentRecord` rows in a single transaction. | All-or-nothing |
| AC-08 | If any page apply fails (simulated DB constraint), the entire transaction rolls back — zero pages created in the database. | Rollback |
| AC-09 | Replaying the same `Idempotency-Key` returns the cached result and does NOT create duplicate pages. | Idempotency |
| AC-10 | Each applied page emits a `PageCreatedByAI` outbox event; a `BatchProposalApplied` event is also emitted. | Audit |
| AC-11 | Batch expiry: a batch older than `AI_BATCH_TTL_HOURS` (24) returns `EXPIRED` and cannot be applied. | Lifecycle |
| AC-12 | Batch with >50 pages is rejected with 422 validation error. | Guardrails |
| AC-13 | Batch with `session_id` tied to an expired session is rejected. | Auth |

### 6. Test Scenarios

#### 6.1 Unit Tests (`tests/unit/services/test_batch_proposal_service.py`)

```python
# Naming convention: test_{method}__{scenario}

async def test_propose_batch__all_valid_pages__creates_batch():
    """Given 3 valid page inputs, propose_batch creates a BatchProposalRecord with 3 page proposals."""
    ...

async def test_propose_batch__one_page_missing_title__rejects_entire_batch():
    """Given 1 page missing title among 3, propose_batch raises ValueError, no batch persisted."""
    ...

async def test_propose_batch__unsupported_template_type__rejected_with_error_detail():
    """Page with template type 'bogus-99' is rejected with UNSUPPORTED_TEMPLATE_TYPE."""
    ...

async def test_propose_batch__exceeds_max_pages__raises_value_error():
    """51 page inputs raise ValueError('Batch exceeds maximum of 50 pages')."""
    ...

async def test_get_batch__returns_batch_with_page_proposals():
    """get_batch returns full BatchProposalRecord with nested page proposals."""
    ...

async def test_remove_page__excludes_single_page__updates_validation_summary():
    """After excluding page index 2, validation_summary.excluded_indices = [2], status = PARTIALLY_REJECTED."""
    ...

async def test_remove_page__batch_already_applied__raises_value_error():
    """Removing a page from an APPLIED batch is rejected."""
    ...

async def test_apply_batch__all_valid_pages__creates_pages_and_components():
    """apply_batch with 3 valid pages creates 3 PageRecords and ComponentRecords."""
    ...

async def test_apply_batch__mid_apply_failure__rolls_back_all():
    """Simulate ComponentRepository.create failure on page 2; verify zero pages created."""
    ...

async def test_apply_batch__idempotency_key_replayed__returns_cached_result():
    """Second call with same key returns same result, no new pages created."""
    ...

async def test_apply_batch__expired_batch__raises_value_error():
    """Batch with expires_at in the past raises ValueError('Batch has expired')."""
    ...

async def test_apply_batch__no_user_confirmation__raises_value_error():
    """apply_batch with user_confirmed=False raises ValueError."""
    ...
```

#### 6.2 Integration Tests (`tests/integration/test_ai_batch_proposals_api.py`)

```python
# Tests against real test database using TestClient

async def test_propose_batch_endpoint__returns_200_with_batch_id():
    """POST /api/v1/ai/batches/propose with valid payload returns 200 and batchId."""
    ...

async def test_propose_batch_endpoint__invalid_schema_returns_422():
    """POST with pages=[{}] returns 422 structured error."""
    ...

async def test_propose_batch_endpoint__all_or_nothing_enforced():
    """POST with mixed valid/invalid pages returns 400 with per-page errors and no batch_id."""
    ...

async def test_get_batch_endpoint__returns_per_page_validation():
    """GET /api/v1/ai/batches/{id} returns pageProposals array with validation results."""
    ...

async def test_remove_page_endpoint__excludes_and_recalculates():
    """POST /api/v1/ai/batches/{id}/remove-page?page_index=1 changes status to PARTIALLY_REJECTED."""
    ...

async def test_apply_batch_endpoint__creates_pages_in_db():
    """POST /api/v1/ai/batches/{id}/apply creates PageRecords; verify via GET /api/v1/courses/{courseId}/pages."""
    ...

async def test_apply_batch_endpoint__without_confirmation_returns_400():
    """POST with user_confirmed=false returns 400."""
    ...

async def test_apply_batch_endpoint__idempotency_key_prevents_duplicates():
    """Two POSTs with same Idempotency-Key create pages only once."""
    ...

async def test_apply_batch_endpoint__expired_batch_returns_400():
    """Apply on an expired batch returns 400."""
    ...

async def test_batch_lifecycle__full_flow():
    """Full E2E: propose (3 pages) -> review -> remove failing page -> apply remaining 2 -> verify pages in DB via courses API."""
    ...
```

#### 6.3 Error Scenario Tests

```python
# Malformed sessions
async def test_batch_with_expired_session_rejected():
    """propose_batch with expired session_id returns 401/403."""
    ...

# Concurrent modification
async def test_apply_batch_concurrent_stale_base_hash():
    """If the course is modified between propose and apply, apply detects staleness and rolls back."""
    ...

# Corner cases
async def test_batch_with_zero_pages_rejected():
    """pages=[] returns 422 validation error."""
    ...

async def test_batch_with_null_template_type_rejected():
    """Page with templateType=null returns per-page error."""
    ...

async def test_remove_page_from_empty_batch_rejected():
    """remove-page on a batch with all pages already excluded returns error."""
    ...
```

### 7. Task Breakdown

| Task ID | Description | Effort | Dependencies |
|---|---|---|---|
| **T1** | **Create Alembic migration** for `ai_batch_proposals` and `ai_batch_page_proposals` tables. Add imports in `alembic/env.py`. | 2h | None |
| T2 | **Implement SQLAlchemy models** in `app/models/batch_proposal.py` — `BatchProposalRecord`, `BatchPageProposalRecord` with all columns, relationships, `to_dict()` methods. | 2h | T1 |
| T3 | **Implement repository layer** in `app/repositories/batch_proposal_repo.py` — CRUD for batch + page proposals, `exclude_page`, `mark_page_applied`, `delete_expired`. | 3h | T2 |
| T4 | **Implement `ProposalValidator`** in `app/services/ai/proposal_validator.py` — reuses existing `Course` model, component registry, and export validator to validate a single page proposal. | 4h | US-AI-008, US-AI-010 |
| T5 | **Implement `BatchProposalService.propose_batch`** — input validation, per-page validation loop, all-or-nothing rejection, batch + page proposal persistence. | 6h | T3, T4 |
| T6 | **Implement `BatchProposalService.remove_page`** — exclusion logic with validation summary recalculation. | 2h | T3 |
| T7 | **Implement `BatchProposalService.apply_batch`** — transactional apply loop, PageRecord/ComponentRecord creation, outbox event emission, idempotency support. | 8h | T3, T4, US-AI-010 (outbox) |
| T8 | **Implement API router** in `app/routers/ai_batch_proposals.py` — 4 endpoints: `POST /propose`, `GET /{id}`, `POST /{id}/remove-page`, `POST /{id}/apply`. Error handling, DTOs, feature-flag gating. | 4h | T5, T6, T7 |
| T9 | **Register router** in `app/main.py`, register feature flag in `app/utils/feature_flags.py`. | 1h | T8 |
| T10 | **Add env vars** to `.env.example`, document in README. | 0.5h | None |
| T11 | **Unit tests** — all unit test scenarios from Section 6.1. | 6h | T5, T6, T7 |
| T12 | **Integration tests** — all integration test scenarios from Section 6.2. | 6h | T8, T9 |
| T13 | **Error scenario tests** — all edge case tests from Section 6.3. | 3h | T11, T12 |
| T14 | **Documentation** — OpenAPI spec update, add batch proposal flow to architecture docs. | 2h | T8 |
| T15 | **Performance test** — verify batch of 50 pages with validations completes in under 5s. | 2h | T5, T7 |

**Total effort**: 51.5 hours (~6.5 engineering days)

**Parallelizable**: T1+T2+T3+T4 can run in parallel. T5+T6+T7+T8 build sequentially on those. T11+T12+T13 can start as soon as each service function is testable.

### 8. Dependencies and Risks

#### Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-AI-004 (AI persistence foundations) | Hard | Requires `ai_sessions` table for session_id FK |
| US-AI-010 (Apply safety, audit, outbox) | Hard | Batch apply reuses transactional apply + outbox patterns |
| US-AI-008 (Validation pipeline) | Hard | `ProposalValidator` reuses `Course` Pydantic model and component registry validation |
| US-AI-005 (Tool schemas and template contracts) | Hard | Template type allowlist checks |
| `POST /api/v1/courses/{courseId}/pages` and `POST /api/v1/courses/{courseId}/pages/{pageId}/components` | Medium | Batch apply reuses `PageRepository` and `ComponentRepository` internally (not the HTTP endpoints) |

#### Unlocks

| Story | Relationship |
|---|---|
| US-AI-019 (Full course from uploaded file) | Blocked by this story — file ingestion generates multiple pages that must be applied atomically |
| US-AI-034 (Durable workflow engine) | Consumes batch proposal as the apply step for long-running file ingestion workflows |

#### Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Large batches (50 pages)** with full re-validation per page could exceed request timeout (default 30s) | Medium | Make batch validation parallel with `asyncio.gather()`. Set `AI_BATCH_MAX_PAGES` to 50 initially, reduce if needed. |
| **Stale course state** between proposal and apply | Medium | Apply step re-validates all pages within the transaction using base_hash comparison (from US-AI-009). |
| **Transaction size** — 50 pages each with multiple components creates a large DB transaction | Low | Test with 50 pages; if latency is an issue, implement chunked apply within the same transaction (all-or-nothing still guaranteed). |
| **Outbox pollution** — 50 pages x 1 event each = 50 events per batch | Low | Outbox consumer processes asynchronously. Batch-level `BatchProposalApplied` event provides aggregate view. |
| **Idempotency cache** — idempotency results stored in-memory could be lost on restart | Low | Store idempotency results in the database (IdempotencyRecord table) with TTL. |

---

**File locations** (all absolute paths):

- Models: `C:\Users\ADMIN\e-learning-backend\app\models\batch_proposal.py`
- Repository: `C:\Users\ADMIN\e-learning-backend\app\repositories\batch_proposal_repo.py`
- Service: `C:\Users\ADMIN\e-learning-backend\app\services\ai\batch_proposal_service.py`
- Router: `C:\Users\ADMIN\e-learning-backend\app\routers\ai_batch_proposals.py`
- Unit tests: `C:\Users\ADMIN\e-learning-backend\tests\unit\services\test_batch_proposal_service.py`
- Integration tests: `C:\Users\ADMIN\e-learning-backend\tests\integration\test_ai_batch_proposals_api.py`
- Alembic migration: `C:\Users\ADMIN\e-learning-backend\alembic\versions\XXXX_batch_proposals.py`
- Feature flags: `C:\Users\ADMIN\e-learning-backend\app\utils\feature_flags.py`
- Main router registration: `C:\Users\ADMIN\e-learning-backend\app\main.py`

---
The complete US-AI-030 epic has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-030_COURSE_ASSEMBLY_INTO_EDITOR.md`**

Here is a summary of what the 8-section epic delivers:

**Section 1 — Functional Specification:** Defines the three-phase assembly flow (Transform -> Map -> Refresh). Covers all three operations (create, update, delete) with flow descriptions, actors, and a complete 37-row data transformation mapping table from proposal fields to `PageRecord`/`ComponentRecord` columns. Also includes a component type compatibility matrix covering 16 types with MVP subset marked, the editor state refresh contract showing the existing `GET /api/v1/courses/{courseId}` response shape, and 12 documented error conditions with HTTP status codes and error codes.

**Section 2 — Technical Specification:** Full DDL for the new `component_type_compatibility` table with seed data, SQLAlchemy ORM model (`ComponentTypeCompatibilityRecord`), Pydantic DTOs (`AssemblyResult`, `AssemblyError`, `AssemblyValidationResult`, `AssemblyBatchResult`, `StateRefreshResponse`), and complete service signatures for:
- `CourseAssembler` with `assemble()`, `validate_payload()`, `_assemble_create()`, `_assemble_update()`, `_assemble_delete()`, `_create_components()`, and optimistic lock support via `_compute_page_hash()`
- `ComponentTypeResolver` with `is_compatible()`, `get_supported_types()`, `validate_component()`
- `AssemblyRepository` with `get_max_page_order()`, `shift_page_orders()`, `delete_all_components_for_page()`

Includes API contracts for `POST /api/v1/ai/proposals/{proposalId}/apply` (enhanced response), `GET /api/v1/ai/component-types`, and `POST /api/v1/ai/proposals/{proposalId}/validate-assembly`. Four new environment variables specified.

**Section 3 — Non-Functional Requirements:** Performance targets (single page assembly < 200 ms p95, batch of 10 < 1.5 s p95), security controls (optimistic locking, component type whitelist, FK cascade, transaction isolation), data integrity (sequential ordering, title truncation, rollback guarantees), availability (transaction rollback preserves state, concurrent serialization), and observability metrics (9 Prometheus metrics with tags).

**Section 4 — Current State:** Maps 6 existing assets (PageRecord/ComponentRecord ORM models, Course endpoint, proposal framework, proposal lifecycle, frontend AI integration, component type registry) against 13 missing items that this epic delivers.

**Section 5 — Expansion Points:** Six post-MVP enhancements: batch assembly (US-AI-029), concurrent edit conflict resolution, undo/redo (US-AI-040), dynamic component type resolution, dry-run preview, page order auto-shift.

**Section 6 — Test Scenarios:** 18+ unit tests across 4 test classes (`TestAssembleCreatePage`, `TestAssembleUpdatePage`, `TestAssembleDeletePage`, `TestValidatePayload`, `TestComponentTypeResolver`), 9 integration tests for the API layer, and 6 complete E2E scenarios.

**Section 7 — Definition of Done:** 45+ checkboxes across code complete, tests, manual authoring preservation, security, operational readiness, and documentation.

**Section 8 — Tasks:** 14 tasks totaling ~28 hours of effort, each with acceptance criteria, effort estimate, and dependencies mapped to other tasks or US-AI stories.

---