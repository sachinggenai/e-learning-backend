# US-AI-032: Policy Engine for Auto-Apply Decisions

**As an** Admin, **I want** a policy engine that determines when AI proposals can be auto-applied based on risk level, user role, and operation type, **so that** low-risk changes do not require manual review while high-risk operations remain gated by explicit confirmation.

- **Priority:** COULD for MVP, SHOULD for production efficiency
- **Depends on:** US-AI-009 (Generic Proposal Lifecycle), US-AI-002 (Feature Flags), US-AI-010 (Apply Safety / Audit)
- **Unlocks:** US-AI-036 (Cost Tracking / Token Budget Enforcement — policy-driven cost gates), US-AI-040 (Versioning / Rollback — policy decides when rollback is auto-vs-manual)
- **Source flow:** 21 (Policy Engine for Auto-Apply Decisions), 12 (Propose-Validate-Confirm-Apply Safety Flow)
- **Epic Owner:** Technical Product Owner

---

## 1. Functional Specification

### 1.1 User Story

As an **Admin**, I want to configure risk-based auto-apply policies so that trusted users performing low-risk edits (typo fixes, content-text updates) skip the manual confirmation step, while high-risk operations (deletes, assessment changes, batch applies) always require explicit approval. Policies must be tenant-scoped, take effect without a server restart, and produce an audit trail of every decision.

As an **Author (trusted role)**, I want low-risk proposals to be applied automatically so that my workflow is not interrupted by confirmation dialogs for trivial changes. I still see a success notification with a brief summary of what was auto-applied.

As the **System**, I want every policy evaluation to be deterministic, logged, and overridable — so that safety is never compromised by automation.

### 1.2 Core Functional Requirements

**FR-POL-01 (Risk Classification):** Every proposal SHALL be assigned a risk level at creation time based on operation type, template type, change scope, and the number of pages/components affected.

**FR-POL-02 (Policy Evaluation):** Before returning a proposal to the frontend, the system SHALL evaluate applicable policies and return both the computed risk level and the required confirmation mode.

**FR-POL-03 (Confirmation Modes):** Four confirmation modes SHALL be supported:
| Mode | Behaviour | Typical Use |
|---|---|---|
| `auto_apply` | Proposal is applied immediately without user interaction. A success notification is shown. | Typo fix on content-text page by instructor |
| `soft_confirm` | Proposal preview is shown; user clicks one button to approve. No destructive-action modal. | Content update to an existing page |
| `hard_confirm` | Modal with explicit action required (checkbox + confirm button, 5-second delay). Destructive warning displayed. | Page deletion, assessment change, batch proposal |
| `block` | Proposal cannot be applied even with confirmation; an admin override reason is required. | Over-budget operation, cross-tenant change |

**FR-POL-04 (Tenant-Scoped Configuration):** Policy rules SHALL be configurable per organization/tenant with a fallback to system defaults. Overrides cascade: `system_default` < `tenant_default` < `user_role_override` < `per_operation_override`.

**FR-POL-05 (Hot-Reload):** Policy configuration changes SHALL take effect on the next proposal evaluation without a server restart. Maximum propagation delay: 60 seconds.

**FR-POL-06 (Audit Logging):** Every policy evaluation SHALL be logged with: proposal ID, computed risk score, matched rule(s), confirmation mode selected, override applied (if any), user role, and evaluation timestamp.

**FR-POL-07 (Admin Override):** An admin SHALL be able to temporarily override the confirmation mode for a specific proposal or operation type with a required reason string that is recorded in the audit log.

**FR-POL-08 (Policy Dry-Run):** The system SHALL expose a dry-run evaluation endpoint that returns the risk score and confirmation mode for a hypothetical proposal without creating it, so that admins can test policy changes.

**FR-POL-09 (Risk Score Factors):** The risk score SHALL be a weighted composite of:
| Factor | Weight | Data Source |
|---|---|---|
| Operation type (create=1, update=2, delete=5, batch=8) | 0.30 | Proposal metadata |
| Template type (content-text=1, tabs/accordion=2, mcq/scored=4, final-assessment=5) | 0.25 | Proposal metadata |
| Page count affected (1 page=1, 2-5=3, 6-20=5, 20+=8) | 0.20 | Proposal metadata |
| User role confidence (admin=-2, instructor=0, reviewer=2, author=3) | 0.15 | Auth context |
| Historical error rate per user (low=0, medium=1, high=3) | 0.10 | Aggregated from ai_audit_logs |

### 1.3 Edge Cases and Error Handling

| Scenario | Expected Behaviour |
|---|---|
| User role matches no explicit policy rule | Fall back to tenant default; if none, fall back to system default (`hard_confirm`) |
| Policy engine is unreachable or throws | Fail-safe to `hard_confirm`; log error; do not auto-apply |
| Policy config has conflicting rules (e.g., tenant says auto_apply, operation override says hard_confirm) | Most specific rule wins: `per_operation > user_role > tenant > system` |
| Admin disables auto-apply globally | All proposals evaluate to `hard_confirm` regardless of risk score |
| Proposal created by a non-human actor (API key, webhook) | Always requires `hard_confirm` unless explicitly overridden by admin |
| Risk score equals boundary value (e.g., threshold is 10, score is exactly 10) | Score >= threshold uses the stricter mode; document boundary behaviour |
| Policy config contains invalid JSON | At startup, reject the config and fall back to safe defaults; log the parse error |

---

## 2. Technical Specification

### 2.1 Database Schema (PostgreSQL DDL)

#### 2.1.1 `ai_policy_rules` Table

Stores per-tenant policy rule definitions. Rules are evaluated in priority order (lowest `priority` first); the first match wins.

```sql
CREATE TABLE IF NOT EXISTS ai_policy_rules (
    id                  BIGSERIAL PRIMARY KEY,
    rule_id             VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,

    -- Scope
    organization_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    user_role           VARCHAR(32),                -- NULL means "any role"
    operation           VARCHAR(32),                -- NULL means "any operation"
    template_type       VARCHAR(64),                -- NULL means "any template"
    min_risk_score      NUMERIC(5,2),               -- NULL = no floor; score >= min triggers this rule

    -- Decision
    confirmation_mode   VARCHAR(16) NOT NULL CHECK (confirmation_mode IN (
                            'auto_apply', 'soft_confirm', 'hard_confirm', 'block'
                        )),

    -- Metadata
    priority            INTEGER NOT NULL DEFAULT 100,
    description         TEXT NOT NULL DEFAULT '',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          VARCHAR(128) NOT NULL DEFAULT 'system',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Version for optimistic locking on hot-reload
    version             INTEGER NOT NULL DEFAULT 1
);

-- Indexes for efficient rule lookup
CREATE INDEX idx_policy_rules_org ON ai_policy_rules(organization_id);
CREATE INDEX idx_policy_rules_role_op ON ai_policy_rules(organization_id, user_role, operation);
CREATE INDEX idx_policy_rules_active_priority ON ai_policy_rules(organization_id, priority) WHERE is_active = TRUE;
```

#### 2.1.2 `ai_policy_decisions` Table

Immutable audit log of every policy evaluation.

```sql
CREATE TABLE IF NOT EXISTS ai_policy_decisions (
    id                  BIGSERIAL PRIMARY KEY,
    decision_id         VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,

    -- Evaluation context
    proposal_id         VARCHAR(64) NOT NULL,
    course_id           VARCHAR(64) NOT NULL,
    session_id          VARCHAR(64),
    user_id             VARCHAR(128) NOT NULL,
    organization_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    user_role           VARCHAR(32) NOT NULL,

    -- Computed risk
    risk_score          NUMERIC(5,2) NOT NULL,
    risk_factors        JSONB NOT NULL,  -- {"operationWeight": 0.3, "templateWeight": 0.25, ...}

    -- Policy decision
    confirmation_mode   VARCHAR(16) NOT NULL,
    matched_rule_id     VARCHAR(64),       -- NULL if no explicit rule matched (used fallback)
    matched_rule_desc   TEXT,
    override_applied    BOOLEAN NOT NULL DEFAULT FALSE,
    override_reason     TEXT,
    fallback_chain      JSONB,             -- ["system_default", "tenant_default", ...] which fallbacks were tried

    -- Outcome (after apply)
    applied_result      VARCHAR(16),        -- 'auto_applied', 'pending_confirmation', 'blocked', 'error'
    applied_at          TIMESTAMPTZ,

    -- Traceability
    trace_id            VARCHAR(64) NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_policy_decisions_proposal ON ai_policy_decisions(proposal_id);
CREATE INDEX idx_policy_decisions_org_created ON ai_policy_decisions(organization_id, created_at DESC);
CREATE INDEX idx_policy_decisions_user ON ai_policy_decisions(user_id, created_at DESC);
CREATE INDEX idx_policy_decisions_mode ON ai_policy_decisions(confirmation_mode);
CREATE INDEX idx_policy_decisions_risk ON ai_policy_decisions(risk_score);
```

#### 2.1.3 `ai_policy_overrides` Table

Temporary admin overrides that temporarily change the confirmation mode for a specific proposal or operation scope.

```sql
CREATE TABLE IF NOT EXISTS ai_policy_overrides (
    id                  BIGSERIAL PRIMARY KEY,
    override_id         VARCHAR(64) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,

    organization_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    proposal_id         VARCHAR(64),        -- NULL means "applies to all matching operations"
    operation           VARCHAR(32),        -- NULL if proposal_id is set

    override_mode       VARCHAR(16) NOT NULL CHECK (override_mode IN (
                            'auto_apply', 'soft_confirm', 'hard_confirm', 'block'
                        )),
    reason              TEXT NOT NULL,
    created_by          VARCHAR(128) NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_policy_overrides_org ON ai_policy_overrides(organization_id);
CREATE INDEX idx_policy_overrides_proposal ON ai_policy_overrides(proposal_id);
CREATE INDEX idx_policy_overrides_active ON ai_policy_overrides(organization_id, expires_at)
    WHERE expires_at > NOW();
```

### 2.2 ORM Models

**File:** `app/models/ai_policy.py`

```python
"""ORM models for the policy engine — rules, decisions, and overrides."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, DateTime, JSONB, Text, BigInteger, Integer,
    Numeric, Boolean, CheckConstraint, Index, ForeignKey,
)

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class PolicyRule(Base):
    """A single policy rule mapping conditions to a confirmation mode."""

    __tablename__ = "ai_policy_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    operation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    template_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    min_risk_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    confirmation_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(
            "confirmation_mode IN ('auto_apply','soft_confirm','hard_confirm','block')",
            name="ck_policy_mode",
        ),
        Index("idx_policy_rules_active_priority", "organization_id", "priority"),
    )

    def to_dict(self) -> dict:
        return {
            "ruleId": self.rule_id,
            "organizationId": self.organization_id,
            "userRole": self.user_role,
            "operation": self.operation,
            "templateType": self.template_type,
            "minRiskScore": float(self.min_risk_score) if self.min_risk_score is not None else None,
            "confirmationMode": self.confirmation_mode,
            "priority": self.priority,
            "description": self.description,
            "isActive": self.is_active,
            "createdBy": self.created_by,
            "version": self.version,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class PolicyDecision(Base):
    """Immutable record of a policy evaluation outcome."""

    __tablename__ = "ai_policy_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    course_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_role: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    risk_factors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confirmation_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    matched_rule_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    matched_rule_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fallback_chain: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    applied_result: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "confirmation_mode IN ('auto_apply','soft_confirm','hard_confirm','block')",
            name="ck_decision_mode",
        ),
        CheckConstraint(
            "applied_result IN ('auto_applied','pending_confirmation','blocked','error')",
            name="ck_decision_result",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "decisionId": self.decision_id,
            "proposalId": self.proposal_id,
            "courseId": self.course_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "organizationId": self.organization_id,
            "userRole": self.user_role,
            "riskScore": float(self.risk_score),
            "riskFactors": self.risk_factors,
            "confirmationMode": self.confirmation_mode,
            "matchedRuleId": self.matched_rule_id,
            "matchedRuleDesc": self.matched_rule_desc,
            "overrideApplied": self.override_applied,
            "overrideReason": self.override_reason,
            "fallbackChain": self.fallback_chain,
            "appliedResult": self.applied_result,
            "appliedAt": self.applied_at.isoformat() if self.applied_at else None,
            "traceId": self.trace_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class PolicyOverride(Base):
    """Admin override for a specific proposal or operation scope."""

    __tablename__ = "ai_policy_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    override_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    proposal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    override_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "override_mode IN ('auto_apply','soft_confirm','hard_confirm','block')",
            name="ck_override_mode",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "overrideId": self.override_id,
            "organizationId": self.organization_id,
            "proposalId": self.proposal_id,
            "operation": self.operation,
            "overrideMode": self.override_mode,
            "reason": self.reason,
            "createdBy": self.created_by,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
```

### 2.3 Pydantic Request/Response Models

**File:** `app/models/ai_policy_dto.py`

```python
"""Pydantic DTOs for the Policy Engine API surface."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field, field_validator


ConfirmationMode = Literal["auto_apply", "soft_confirm", "hard_confirm", "block"]


# ── Policy Rules ───────────────────────────────────────────────────────────

class PolicyRuleCreate(BaseModel):
    """Request body for creating a new policy rule."""
    organization_id: str = Field(default="default", description="Tenant org ID")
    user_role: Optional[str] = Field(None, description="Target user role (NULL = any)")
    operation: Optional[str] = Field(None, description="Target operation type (NULL = any)")
    template_type: Optional[str] = Field(None, description="Target template type (NULL = any)")
    min_risk_score: Optional[float] = Field(None, ge=0, le=100, description="Minimum risk score threshold")
    confirmation_mode: ConfirmationMode = Field(..., description="Confirmation mode when rule matches")
    priority: int = Field(default=100, ge=0, le=10000, description="Evaluation priority (lower = first)")
    description: str = Field(default="", max_length=500)
    is_active: bool = Field(default=True)


class PolicyRuleUpdate(BaseModel):
    """Request body for updating a policy rule (partial)."""
    user_role: Optional[str] = None
    operation: Optional[str] = None
    template_type: Optional[str] = None
    min_risk_score: Optional[float] = None
    confirmation_mode: Optional[ConfirmationMode] = None
    priority: Optional[int] = Field(None, ge=0, le=10000)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class PolicyRuleOut(BaseModel):
    ruleId: str
    organizationId: str
    userRole: Optional[str] = None
    operation: Optional[str] = None
    templateType: Optional[str] = None
    minRiskScore: Optional[float] = None
    confirmationMode: str
    priority: int
    description: str
    isActive: bool
    createdBy: str
    version: int
    createdAt: str
    updatedAt: str

    model_config = {"from_attributes": True}


class PolicyRuleListOut(BaseModel):
    items: List[PolicyRuleOut]
    total: int


# ── Policy Decisions ───────────────────────────────────────────────────────

class PolicyDecisionOut(BaseModel):
    decisionId: str
    proposalId: str
    courseId: str
    sessionId: Optional[str] = None
    userId: str
    organizationId: str
    userRole: str
    riskScore: float
    riskFactors: dict
    confirmationMode: str
    matchedRuleId: Optional[str] = None
    matchedRuleDesc: Optional[str] = None
    overrideApplied: bool = False
    overrideReason: Optional[str] = None
    fallbackChain: Optional[list] = None
    appliedResult: Optional[str] = None
    appliedAt: Optional[str] = None
    traceId: str
    createdAt: str

    model_config = {"from_attributes": True}


class PolicyDecisionListOut(BaseModel):
    items: List[PolicyDecisionOut]
    total: int


class PolicyDecisionFilterParams(BaseModel):
    proposal_id: Optional[str] = Field(None, description="Filter by proposal ID")
    course_id: Optional[str] = Field(None, description="Filter by course ID")
    user_id: Optional[str] = Field(None, description="Filter by user ID")
    organization_id: Optional[str] = Field(None, description="Filter by tenant")
    confirmation_mode: Optional[str] = Field(None, description="Filter by confirmation mode")
    applied_result: Optional[str] = Field(None, description="Filter by apply result")
    date_from: Optional[datetime] = Field(None, description="Start of date range")
    date_to: Optional[datetime] = Field(None, description="End of date range")
    limit: int = Field(default=50, ge=1, le=200, description="Page size")


# ── Risk Evaluation ────────────────────────────────────────────────────────

class RiskEvaluationRequest(BaseModel):
    """Dry-run risk evaluation for a hypothetical proposal."""
    organization_id: str = Field(default="default")
    user_role: str = Field(..., description="User's role")
    operation: str = Field(..., description="Operation type")
    template_type: Optional[str] = Field(None, description="Template type for the proposal")
    page_count: int = Field(default=1, ge=1, le=100, description="Number of pages affected")


class RiskFactorDetail(BaseModel):
    factor: str
    weight: float
    score: float
    rationale: str


class RiskEvaluationOut(BaseModel):
    riskScore: float
    riskFactors: List[RiskFactorDetail]
    confirmationMode: str
    matchedRuleId: Optional[str] = None
    matchedRuleDesc: Optional[str] = None
    overrideApplied: bool = False
    overrideReason: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


# ── Overrides ──────────────────────────────────────────────────────────────

class PolicyOverrideCreate(BaseModel):
    organization_id: str = Field(default="default")
    proposal_id: Optional[str] = Field(None, description="Target specific proposal (takes precedence)")
    operation: Optional[str] = Field(None, description="Target operation type if no proposal_id")
    override_mode: ConfirmationMode = Field(...)
    reason: str = Field(..., min_length=10, max_length=1000, description="Required justification")
    expires_in_minutes: int = Field(default=1440, ge=5, le=43200, description="Override TTL in minutes (default 24h)")


class PolicyOverrideOut(BaseModel):
    overrideId: str
    organizationId: str
    proposalId: Optional[str] = None
    operation: Optional[str] = None
    overrideMode: str
    reason: str
    createdBy: str
    expiresAt: str
    createdAt: str

    model_config = {"from_attributes": True}


class PolicyOverrideListOut(BaseModel):
    items: List[PolicyOverrideOut]
    total: int


# ── Internal evaluation context (not exposed via API) ──────────────────────

class ProposalRiskContext(BaseModel):
    """Internal model representing the proposal dimensions used for risk scoring."""
    proposal_id: str
    course_id: str
    session_id: Optional[str] = None
    user_id: str
    organization_id: str
    user_role: str
    operation: str
    template_type: Optional[str] = None
    page_count: int = 1
    historical_error_rate: float = 0.0  # 0.0 to 1.0
```

### 2.4 API Contracts

All routes are under the existing `/api/v1/ai` prefix namespace with a `policy` sub-prefix. Policy management routes require admin authorization. The evaluation endpoint is called internally by the proposal service and also exposed for dry-run.

#### `GET /api/v1/ai/policy/rules`

List policy rules for the current tenant.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `organization_id` | string | No | Filter by org (default: caller's org) |
| `is_active` | boolean | No | Filter by active/inactive |
| `limit` | integer | No | Page size (1-200, default 50) |

**Response `200 OK`:**
```json
{
  "items": [
    {
      "ruleId": "rule-001",
      "organizationId": "default",
      "userRole": "instructor",
      "operation": "page_updated",
      "templateType": "content-text",
      "minRiskScore": null,
      "confirmationMode": "auto_apply",
      "priority": 10,
      "description": "Auto-apply content-text updates by instructors",
      "isActive": true,
      "createdBy": "admin-1",
      "version": 3,
      "createdAt": "2026-06-14T10:00:00+00:00",
      "updatedAt": "2026-06-14T12:00:00+00:00"
    }
  ],
  "total": 12
}
```

#### `POST /api/v1/ai/policy/rules`

Create a new policy rule.

**Request Body:**
```json
{
  "organization_id": "default",
  "user_role": "instructor",
  "operation": "page_updated",
  "template_type": "content-text",
  "confirmation_mode": "auto_apply",
  "priority": 10,
  "description": "Auto-apply content-text typo fixes by instructors"
}
```

**Response `201 Created`:**
```json
{
  "ruleId": "rule-001",
  "organizationId": "default",
  "userRole": "instructor",
  "operation": "page_updated",
  "templateType": "content-text",
  "minRiskScore": null,
  "confirmationMode": "auto_apply",
  "priority": 10,
  "description": "Auto-apply content-text typo fixes by instructors",
  "isActive": true,
  "createdBy": "admin-1",
  "version": 1,
  "createdAt": "2026-06-14T12:00:00+00:00",
  "updatedAt": "2026-06-14T12:00:00+00:00"
}
```

**Error Responses:**
- `422` — Validation failure (e.g., `confirmation_mode` not in allowed list, `priority` out of range)
- `409` — Conflicting rule already exists with same org + role + operation + template combination

#### `PUT /api/v1/ai/policy/rules/{rule_id}`

Update an existing policy rule (partial update). Uses optimistic locking via `version` field.

**Request Body:**
```json
{
  "confirmation_mode": "soft_confirm",
  "priority": 5,
  "version": 3
}
```

**Response `200 OK`:**
```json
{
  "ruleId": "rule-001",
  "confirmationMode": "soft_confirm",
  "priority": 5,
  "version": 4,
  "updatedAt": "2026-06-14T12:30:00+00:00"
}
```

**Error Responses:**
- `404` — Rule not found
- `409` — Version conflict (rule was modified by another admin; retry with refreshed version)
- `422` — Invalid field values

#### `DELETE /api/v1/ai/policy/rules/{rule_id}`

Soft-delete a policy rule (sets `is_active = False`). Hard-delete is not permitted for audit reasons.

**Response `200 OK`:**
```json
{
  "ruleId": "rule-001",
  "isActive": false,
  "updatedAt": "2026-06-14T12:35:00+00:00"
}
```

**Error Responses:**
- `404` — Rule not found

#### `POST /api/v1/ai/policy/evaluate`

Evaluate a proposal (or dry-run hypothetical) against the policy engine. This endpoint is called by the proposal service internally and exposed for admin dry-run testing.

**Request Body:**
```json
{
  "organization_id": "default",
  "user_role": "instructor",
  "operation": "page_updated",
  "template_type": "content-text",
  "page_count": 1
}
```

**Response `200 OK`:**
```json
{
  "riskScore": 2.5,
  "riskFactors": [
    {
      "factor": "operation",
      "weight": 0.3,
      "score": 0.6,
      "rationale": "page_updated has weight 2 * factor 0.3 = 0.6"
    },
    {
      "factor": "template_type",
      "weight": 0.25,
      "score": 0.25,
      "rationale": "content-text has weight 1 * factor 0.25 = 0.25"
    },
    {
      "factor": "page_count",
      "weight": 0.2,
      "score": 0.2,
      "rationale": "1 page has weight 1 * factor 0.2 = 0.2"
    },
    {
      "factor": "user_role",
      "weight": 0.15,
      "score": 0.0,
      "rationale": "instructor has confidence modifier 0, risk contribution 0.0"
    },
    {
      "factor": "historical_error_rate",
      "weight": 0.1,
      "score": 0.0,
      "rationale": "error rate 0.02 is below low threshold, contribution 0.0"
    }
  ],
  "confirmationMode": "auto_apply",
  "matchedRuleId": "rule-001",
  "matchedRuleDesc": "Auto-apply content-text updates by instructors",
  "overrideApplied": false,
  "overrideReason": null,
  "warnings": []
}
```

**Error Responses:**
- `422` — Missing required fields or invalid enum values

#### `GET /api/v1/ai/policy/decisions`

Query the policy decision audit log.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `proposal_id` | string | No | Filter by proposal ID |
| `course_id` | string | No | Filter by course ID |
| `user_id` | string | No | Filter by user ID |
| `organization_id` | string | No | Filter by org |
| `confirmation_mode` | string | No | Filter by mode |
| `applied_result` | string | No | Filter by result |
| `date_from` | ISO8601 | No | Start of date range |
| `date_to` | ISO8601 | No | End of date range |
| `limit` | integer | No | Page size (1-200, default 50) |

**Response `200 OK`:**
```json
{
  "items": [
    {
      "decisionId": "dec-001",
      "proposalId": "prop-007",
      "courseId": "course-alpha",
      "userId": "user-42",
      "userRole": "instructor",
      "riskScore": 2.5,
      "riskFactors": {"operationWeight": 0.3, "templateWeight": 0.25},
      "confirmationMode": "auto_apply",
      "matchedRuleId": "rule-001",
      "overrideApplied": false,
      "appliedResult": "auto_applied",
      "traceId": "trace-abc-123",
      "createdAt": "2026-06-14T12:00:00+00:00"
    }
  ],
  "total": 1
}
```

#### `POST /api/v1/ai/policy/overrides`

Create an admin override for a specific proposal or operation scope.

**Request Body:**
```json
{
  "organization_id": "default",
  "proposal_id": "prop-007",
  "override_mode": "auto_apply",
  "reason": "Instructor requested expedited review. Urgent content fix for live course.",
  "expires_in_minutes": 60
}
```

**Response `201 Created`:**
```json
{
  "overrideId": "ovr-001",
  "organizationId": "default",
  "proposalId": "prop-007",
  "operation": null,
  "overrideMode": "auto_apply",
  "reason": "Instructor requested expedited review. Urgent content fix for live course.",
  "createdBy": "admin-1",
  "expiresAt": "2026-06-14T13:00:00+00:00",
  "createdAt": "2026-06-14T12:00:00+00:00"
}
```

**Error Responses:**
- `422` — Reason too short, or override mode invalid

#### `GET /api/v1/ai/policy/overrides`

List active overrides for the tenant.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `organization_id` | string | No | Filter by org |
| `include_expired` | boolean | No | Include expired overrides (default false) |
| `limit` | integer | No | Page size |

#### `DELETE /api/v1/ai/policy/overrides/{override_id}`

Cancel an override before it expires.

**Response `200 OK`:**
```json
{
  "status": "cancelled",
  "overrideId": "ovr-001"
}
```

### 2.5 Service Signatures

**File:** `app/services/ai/policy_engine.py`

```python
"""Policy Engine — risk scoring, rule matching, and confirmation mode resolution.

This service is the core of US-AI-032. It is called by the proposal creation
service (US-AI-009) and by the apply safety service (US-AI-010) to determine
whether a proposal may be auto-applied or requires user confirmation.
"""
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_policy_dto import (
    PolicyRuleCreate, PolicyRuleUpdate, PolicyRuleOut,
    RiskEvaluationRequest, RiskEvaluationOut, RiskFactorDetail,
    ProposalRiskContext,
)


class PolicyEngine:
    """Evaluates proposals against configurable rules to determine confirmation mode.

    The engine is stateless with respect to policy rules — it loads the active
    rule set for the tenant on each evaluation. This ensures hot-reload: changes
    to `ai_policy_rules` are reflected on the next evaluation.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Core evaluation ─────────────────────────────────────────────────────

    async def evaluate(
        self,
        context: ProposalRiskContext,
        *,
        trace_id: str,
        dry_run: bool = False,
    ) -> RiskEvaluationOut:
        """Evaluate a proposal against the policy engine.

        Steps:
        1. Compute raw risk score from weighted factors.
        2. Load active rules for the tenant, ordered by priority.
        3. Match rules: first rule where ALL conditions (role, operation,
           template_type, min_risk_score) match wins.
        4. Check for admin overrides (proposal-specific first, then operation-wide).
        5. If override exists and is not expired, use override mode.
        6. If no rule matched, apply fallback chain: tenant_default -> system_default.
        7. If no fallback defined, default to `hard_confirm`.
        8. Log the decision to `ai_policy_decisions`.
        9. Return RiskEvaluationOut with the resolved confirmation mode.

        When dry_run=True, skip the decision audit log write.
        When dry_run=False, write the decision record and return.
        """
        ...

    async def compute_risk_score(self, context: ProposalRiskContext) -> Tuple[float, List[RiskFactorDetail]]:
        """Compute weighted risk score from proposal dimensions.

        Weights (from FR-POL-09):
        - operation: 0.30
        - template_type: 0.25
        - page_count: 0.20
        - user_role: 0.15
        - historical_error_rate: 0.10

        Returns (total_score, factor_details).
        """
        ...

    async def match_rule(
        self,
        context: ProposalRiskContext,
        risk_score: float,
    ) -> Tuple[Optional[dict], List[str]]:
        """Find the first matching active rule for the tenant.

        Returns (matched_rule_dict, fallback_chain) where fallback_chain
        is a list of fallback levels tried after no explicit match.
        """
        ...

    async def check_override(
        self,
        organization_id: str,
        proposal_id: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> Optional[dict]:
        """Check for an active admin override.

        Proposal-specific overrides take precedence over operation-wide ones.
        Expired overrides are ignored.
        """
        ...

    # ── Rule CRUD ───────────────────────────────────────────────────────────

    async def create_rule(self, data: PolicyRuleCreate, created_by: str) -> PolicyRuleOut:
        """Create a new policy rule. Checks for conflicting rules."""
        ...

    async def update_rule(
        self, rule_id: str, data: PolicyRuleUpdate, expected_version: int
    ) -> PolicyRuleOut:
        """Update a rule with optimistic locking. Raises on version conflict."""
        ...

    async def deactivate_rule(self, rule_id: str) -> PolicyRuleOut:
        """Soft-delete a rule (is_active = False)."""
        ...

    async def list_rules(
        self,
        organization_id: str,
        is_active: Optional[bool] = None,
        limit: int = 50,
    ) -> Tuple[List[PolicyRuleOut], int]:
        """List rules for a tenant."""
        ...

    async def get_rule(self, rule_id: str) -> Optional[PolicyRuleOut]:
        """Get a single rule by ID."""
        ...

    # ── Decision audit ──────────────────────────────────────────────────────

    async def list_decisions(
        self,
        *,
        proposal_id: Optional[str] = None,
        course_id: Optional[str] = None,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        confirmation_mode: Optional[str] = None,
        applied_result: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
    ) -> Tuple[List[dict], int]:
        """Query the policy decision audit log."""
        ...

    async def record_decision(
        self,
        context: ProposalRiskContext,
        risk_score: float,
        risk_factors: list,
        confirmation_mode: str,
        matched_rule_id: Optional[str],
        matched_rule_desc: Optional[str],
        override_applied: bool,
        override_reason: Optional[str],
        fallback_chain: Optional[list],
        trace_id: str,
    ) -> str:
        """Record a policy decision. Returns decision_id."""
        ...

    async def update_decision_result(
        self,
        proposal_id: str,
        applied_result: str,
    ) -> None:
        """Update the applied_result field after the proposal is acted on.

        Called by the apply service after the proposal is applied or rejected.
        This allows the decision audit log to reflect the actual outcome.
        """
        ...

    # ── Overrides ───────────────────────────────────────────────────────────

    async def create_override(
        self,
        *,
        organization_id: str,
        proposal_id: Optional[str],
        operation: Optional[str],
        override_mode: str,
        reason: str,
        created_by: str,
        expires_in_minutes: int = 1440,
    ) -> dict:
        """Create an admin override. Validates that reason is provided."""
        ...

    async def list_overrides(
        self,
        organization_id: str,
        include_expired: bool = False,
        limit: int = 50,
    ) -> Tuple[List[dict], int]:
        """List overrides for a tenant."""
        ...

    async def cancel_override(self, override_id: str) -> None:
        """Cancel an override (DELETE)."""
        ...

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _get_historical_error_rate(
        self,
        user_id: str,
        organization_id: str,
        days: int = 30,
    ) -> float:
        """Query ai_audit_logs for the user's error rate over the last N days.

        error_rate = failed_applies / total_applies
        Returns 0.0 if no history.
        """
        ...

    @staticmethod
    def _operation_weight(op: str) -> float:
        """Map operation type to weight value."""
        weights = {
            "page_created": 1,
            "page_updated": 2,
            "page_deleted": 5,
            "batch_applied": 8,
            "course_created": 3,
            "course_updated": 3,
            "component_updated": 2,
        }
        return float(weights.get(op, 2))

    @staticmethod
    def _template_weight(template_type: Optional[str]) -> float:
        """Map template type to weight value."""
        if template_type is None:
            return 2.0
        weights = {
            "content-text": 1,
            "welcome": 1,
            "summary": 1,
            "content-video": 2,
            "video": 2,
            "tabs": 2,
            "accordion": 2,
            "mcq": 4,
            "quiz": 4,
            "final-assessment": 5,
        }
        return float(weights.get(template_type, 2))

    @staticmethod
    def _page_count_weight(count: int) -> float:
        """Map page count to weight value."""
        if count <= 1:
            return 1.0
        if count <= 5:
            return 3.0
        if count <= 20:
            return 5.0
        return 8.0

    @staticmethod
    def _role_confidence(role: str) -> float:
        """Map user role to confidence offset (negative = lower risk)."""
        offsets = {
            "admin": -2.0,
            "instructor": 0.0,
            "reviewer": 2.0,
            "author": 3.0,
        }
        return offsets.get(role, 2.0)
```

### 2.6 Repository

**File:** `app/repositories/ai_policy_repo.py`

```python
"""Repository for policy rules, decisions, and overrides."""
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.models.ai_policy import PolicyRule, PolicyDecision, PolicyOverride


class PolicyRuleRepository:
    """DB access for ai_policy_rules table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(
        self, organization_id: str,
    ) -> List[PolicyRule]:
        """Load all active rules for a tenant, ordered by priority."""
        q = (
            select(PolicyRule)
            .where(
                PolicyRule.organization_id == organization_id,
                PolicyRule.is_active == True,
            )
            .order_by(PolicyRule.priority)
        )
        rows = await self.session.execute(q)
        return list(rows.scalars().all())

    async def list_with_filters(
        self,
        organization_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
    ) -> Tuple[List[PolicyRule], int]:
        conditions = []
        if organization_id:
            conditions.append(PolicyRule.organization_id == organization_id)
        if is_active is not None:
            conditions.append(PolicyRule.is_active == is_active)

        q = select(PolicyRule)
        if conditions:
            q = q.where(and_(*conditions))

        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.session.execute(count_q)).scalar() or 0

        q = q.order_by(PolicyRule.priority).limit(limit)
        rows = await self.session.execute(q)
        return list(rows.scalars().all()), total

    async def get_by_rule_id(self, rule_id: str) -> Optional[PolicyRule]:
        q = select(PolicyRule).where(PolicyRule.rule_id == rule_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def find_conflict(
        self,
        organization_id: str,
        user_role: Optional[str],
        operation: Optional[str],
        template_type: Optional[str],
        exclude_rule_id: Optional[str] = None,
    ) -> Optional[PolicyRule]:
        """Find a conflicting rule with the same dimensions."""
        conditions = [
            PolicyRule.organization_id == organization_id,
            PolicyRule.user_role == user_role,
            PolicyRule.operation == operation,
            PolicyRule.template_type == template_type,
            PolicyRule.is_active == True,
        ]
        if exclude_rule_id:
            conditions.append(PolicyRule.rule_id != exclude_rule_id)
        q = select(PolicyRule).where(and_(*conditions))
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, rule: PolicyRule) -> PolicyRule:
        self.session.add(rule)
        await self.session.commit()
        await self.session.refresh(rule)
        return rule

    async def update(self, rule: PolicyRule) -> PolicyRule:
        await self.session.commit()
        await self.session.refresh(rule)
        return rule


class PolicyDecisionRepository:
    """DB access for ai_policy_decisions table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, decision: PolicyDecision) -> PolicyDecision:
        self.session.add(decision)
        await self.session.commit()
        await self.session.refresh(decision)
        return decision

    async def update_result(
        self, proposal_id: str, applied_result: str
    ) -> None:
        q = (
            select(PolicyDecision)
            .where(PolicyDecision.proposal_id == proposal_id)
            .order_by(PolicyDecision.created_at.desc())
            .limit(1)
        )
        decision = (await self.session.execute(q)).scalar_one_or_none()
        if decision:
            decision.applied_result = applied_result
            decision.applied_at = datetime.utcnow()
            await self.session.commit()

    async def list_with_filters(
        self,
        *,
        proposal_id: Optional[str] = None,
        course_id: Optional[str] = None,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        confirmation_mode: Optional[str] = None,
        applied_result: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
    ) -> Tuple[List[PolicyDecision], int]:
        conditions = []
        if proposal_id:
            conditions.append(PolicyDecision.proposal_id == proposal_id)
        if course_id:
            conditions.append(PolicyDecision.course_id == course_id)
        if user_id:
            conditions.append(PolicyDecision.user_id == user_id)
        if organization_id:
            conditions.append(PolicyDecision.organization_id == organization_id)
        if confirmation_mode:
            conditions.append(PolicyDecision.confirmation_mode == confirmation_mode)
        if applied_result:
            conditions.append(PolicyDecision.applied_result == applied_result)
        if date_from:
            conditions.append(PolicyDecision.created_at >= date_from)
        if date_to:
            conditions.append(PolicyDecision.created_at <= date_to)

        q = select(PolicyDecision)
        if conditions:
            q = q.where(and_(*conditions))

        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.session.execute(count_q)).scalar() or 0

        q = q.order_by(PolicyDecision.created_at.desc()).limit(limit)
        rows = await self.session.execute(q)
        return list(rows.scalars().all()), total

    async def get_by_proposal_id(
        self, proposal_id: str
    ) -> Optional[PolicyDecision]:
        q = (
            select(PolicyDecision)
            .where(PolicyDecision.proposal_id == proposal_id)
            .order_by(PolicyDecision.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(q)).scalar_one_or_none()


class PolicyOverrideRepository:
    """DB access for ai_policy_overrides table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_active(
        self,
        organization_id: str,
        proposal_id: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> Optional[PolicyOverride]:
        """Find an active override. Proposal-specific takes precedence."""
        now = datetime.utcnow()
        conditions = [
            PolicyOverride.organization_id == organization_id,
            PolicyOverride.expires_at > now,
        ]
        if proposal_id:
            # Check proposal-specific first
            q = (
                select(PolicyOverride)
                .where(
                    and_(
                        *conditions,
                        PolicyOverride.proposal_id == proposal_id,
                    )
                )
                .limit(1)
            )
            result = (await self.session.execute(q)).scalar_one_or_none()
            if result:
                return result

        if operation:
            q = (
                select(PolicyOverride)
                .where(
                    and_(
                        *conditions,
                        PolicyOverride.proposal_id.is_(None),
                        PolicyOverride.operation == operation,
                    )
                )
                .limit(1)
            )
            return (await self.session.execute(q)).scalar_one_or_none()

        return None

    async def list_with_filters(
        self,
        organization_id: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 50,
    ) -> Tuple[List[PolicyOverride], int]:
        conditions = []
        if organization_id:
            conditions.append(PolicyOverride.organization_id == organization_id)
        if not include_expired:
            conditions.append(PolicyOverride.expires_at > datetime.utcnow())

        q = select(PolicyOverride)
        if conditions:
            q = q.where(and_(*conditions))

        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.session.execute(count_q)).scalar() or 0

        q = q.order_by(PolicyOverride.created_at.desc()).limit(limit)
        rows = await self.session.execute(q)
        return list(rows.scalars().all()), total

    async def create(self, override: PolicyOverride) -> PolicyOverride:
        self.session.add(override)
        await self.session.commit()
        await self.session.refresh(override)
        return override

    async def delete(self, override_id: str) -> bool:
        q = select(PolicyOverride).where(PolicyOverride.override_id == override_id)
        override = (await self.session.execute(q)).scalar_one_or_none()
        if not override:
            return False
        await self.session.delete(override)
        await self.session.commit()
        return True
```

### 2.7 Router

**File:** `app/routers/ai_policy.py`

```python
"""Policy engine API routes.

All routes are prefixed with /api/v1/ai/policy and require admin-level
authorization for management endpoints. The evaluate endpoint is also
called internally by the proposal service.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.services.ai.policy_engine import PolicyEngine
from app.models.ai_policy_dto import (
    PolicyRuleCreate, PolicyRuleUpdate, PolicyRuleOut, PolicyRuleListOut,
    RiskEvaluationRequest, RiskEvaluationOut,
    PolicyDecisionOut, PolicyDecisionListOut, PolicyDecisionFilterParams,
    PolicyOverrideCreate, PolicyOverrideOut, PolicyOverrideListOut,
)
from app.utils.error_envelope import api_http_exception

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/policy", tags=["AI Policy Engine"])


# ── Dependencies ─────────────────────────────────────────────────────────────

async def _require_admin():
    """Placeholder for admin authorization.

    In production, verify 'admin' or 'policy_admin' role from JWT claims.
    Reuses the same dependency pattern as app/routers/ai_admin.py.
    """
    return True


async def _get_policy_engine(
    session: AsyncSession = Depends(get_session),
) -> PolicyEngine:
    return PolicyEngine(session)


# ── Rule CRUD ────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=PolicyRuleListOut)
async def list_policy_rules(
    organization_id: Optional[str] = Query(None, description="Filter by org"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=200),
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """List policy rules for the tenant."""
    items, total = await engine.list_rules(
        organization_id=organization_id or "default",
        is_active=is_active,
        limit=limit,
    )
    return PolicyRuleListOut(items=items, total=total)


@router.post("/rules", status_code=201, response_model=PolicyRuleOut)
async def create_policy_rule(
    body: PolicyRuleCreate,
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """Create a new policy rule."""
    try:
        rule = await engine.create_rule(body, created_by="admin")
    except ValueError as exc:
        # Conflict with existing rule
        raise api_http_exception(409, "POLICY_RULE_CONFLICT", str(exc))
    return rule


@router.put("/rules/{rule_id}", response_model=PolicyRuleOut)
async def update_policy_rule(
    rule_id: str,
    body: PolicyRuleUpdate,
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """Update a policy rule (partial). Uses optimistic locking."""
    try:
        rule = await engine.update_rule(rule_id, body, expected_version=body.version)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise api_http_exception(404, "POLICY_RULE_NOT_FOUND", str(exc))
        raise api_http_exception(409, "POLICY_RULE_CONFLICT", str(exc))
    return rule


@router.delete("/rules/{rule_id}", response_model=dict)
async def delete_policy_rule(
    rule_id: str,
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """Soft-delete a policy rule."""
    try:
        rule = await engine.deactivate_rule(rule_id)
    except ValueError as exc:
        raise api_http_exception(404, "POLICY_RULE_NOT_FOUND", str(exc))
    return {"ruleId": rule.ruleId, "isActive": False, "updatedAt": rule.updatedAt}


# ── Evaluation ───────────────────────────────────────────────────────────────

@router.post("/evaluate", response_model=RiskEvaluationOut)
async def evaluate_risk(
    body: RiskEvaluationRequest,
    engine: PolicyEngine = Depends(_get_policy_engine),
    admin: bool = Depends(_require_admin),
):
    """Dry-run evaluate a hypothetical proposal against the policy engine.

    This endpoint is also called internally by the proposal service
    during proposal creation (US-AI-009).
    """
    # Build internal context from request
    from app.models.ai_policy_dto import ProposalRiskContext
    context = ProposalRiskContext(
        proposal_id="dry-run",
        course_id="dry-run",
        user_id="dry-run",
        organization_id=body.organization_id,
        user_role=body.user_role,
        operation=body.operation,
        template_type=body.template_type,
        page_count=body.page_count,
    )
    result = await engine.evaluate(context, trace_id="dry-run", dry_run=True)
    return result


# ── Decision Audit ───────────────────────────────────────────────────────────

@router.get("/decisions", response_model=PolicyDecisionListOut)
async def list_policy_decisions(
    params: PolicyDecisionFilterParams = Depends(),
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """Query the policy decision audit log."""
    items, total = await engine.list_decisions(
        proposal_id=params.proposal_id,
        course_id=params.course_id,
        user_id=params.user_id,
        organization_id=params.organization_id,
        confirmation_mode=params.confirmation_mode,
        applied_result=params.applied_result,
        date_from=params.date_from,
        date_to=params.date_to,
        limit=params.limit,
    )
    return PolicyDecisionListOut(
        items=[PolicyDecisionOut(**item) for item in items],
        total=total,
    )


# ── Overrides ────────────────────────────────────────────────────────────────

@router.post("/overrides", status_code=201, response_model=PolicyOverrideOut)
async def create_override(
    body: PolicyOverrideCreate,
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """Create an admin override for a proposal or operation."""
    override = await engine.create_override(
        organization_id=body.organization_id,
        proposal_id=body.proposal_id,
        operation=body.operation,
        override_mode=body.override_mode,
        reason=body.reason,
        created_by="admin",
        expires_in_minutes=body.expires_in_minutes,
    )
    return PolicyOverrideOut(**override)


@router.get("/overrides", response_model=PolicyOverrideListOut)
async def list_overrides(
    organization_id: Optional[str] = Query(None),
    include_expired: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """List active overrides."""
    items, total = await engine.list_overrides(
        organization_id=organization_id or "default",
        include_expired=include_expired,
        limit=limit,
    )
    return PolicyOverrideListOut(
        items=[PolicyOverrideOut(**item) for item in items],
        total=total,
    )


@router.delete("/overrides/{override_id}", response_model=dict)
async def cancel_override(
    override_id: str,
    admin: bool = Depends(_require_admin),
    engine: PolicyEngine = Depends(_get_policy_engine),
):
    """Cancel an override before expiry."""
    try:
        await engine.cancel_override(override_id)
    except ValueError as exc:
        raise api_http_exception(404, "OVERRIDE_NOT_FOUND", str(exc))
    return {"status": "cancelled", "overrideId": override_id}
```

### 2.8 Alembic Migration

**File:** `alembic/versions/20260614_0002_add_policy_engine_tables.py`

```python
"""Add ai_policy_rules, ai_policy_decisions, ai_policy_overrides tables.

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260614_0002"
down_revision: Union[str, None] = "20260614_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ai_policy_rules ─────────────────────────────────────────────────────
    op.create_table(
        "ai_policy_rules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("user_role", sa.String(32), nullable=True),
        sa.Column("operation", sa.String(32), nullable=True),
        sa.Column("template_type", sa.String(64), nullable=True),
        sa.Column("min_risk_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("confirmation_mode", sa.String(16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="system"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id"),
    )
    op.create_check_constraint(
        "ck_policy_mode",
        "ai_policy_rules",
        "confirmation_mode IN ('auto_apply','soft_confirm','hard_confirm','block')",
    )
    op.create_index("idx_policy_rules_org", "ai_policy_rules", ["organization_id"])
    op.create_index("idx_policy_rules_role_op", "ai_policy_rules", ["organization_id", "user_role", "operation"])
    op.create_index(
        "idx_policy_rules_active_priority",
        "ai_policy_rules",
        ["organization_id", "priority"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # Seed system-default rules
    op.execute("""
        INSERT INTO ai_policy_rules (rule_id, organization_id, user_role, operation, template_type,
                                      confirmation_mode, priority, description, created_by)
        VALUES
        ('sys-auto-content-text-update', 'default', 'instructor', 'page_updated', 'content-text',
         'auto_apply', 10, 'Auto-apply content-text page updates by instructors', 'system'),
        ('sys-auto-content-text-update-admin', 'default', 'admin', 'page_updated', 'content-text',
         'auto_apply', 10, 'Auto-apply content-text page updates by admins', 'system'),
        ('sys-soft-tabs-update', 'default', 'instructor', 'page_updated', 'tabs',
         'soft_confirm', 20, 'Soft confirm for tab component updates by instructors', 'system'),
        ('sys-soft-accordion-update', 'default', 'instructor', 'page_updated', 'accordion',
         'soft_confirm', 20, 'Soft confirm for accordion updates by instructors', 'system'),
        ('sys-hard-delete', 'default', NULL, 'page_deleted', NULL,
         'hard_confirm', 5, 'Page deletions always require hard confirmation', 'system'),
        ('sys-hard-assessment', 'default', NULL, 'page_updated', 'final-assessment',
         'hard_confirm', 15, 'Assessment changes always require hard confirmation', 'system'),
        ('sys-hard-batch', 'default', NULL, 'batch_applied', NULL,
         'hard_confirm', 5, 'Batch operations always require hard confirmation', 'system'),
        ('sys-block-unknown-role', 'default', 'anonymous', NULL, NULL,
         'block', 1, 'Block all operations from unauthenticated or unknown roles', 'system'),
        ('sys-default-fallback', 'default', NULL, NULL, NULL,
         'hard_confirm', 9999, 'Default fallback: hard confirm for all unmatched operations', 'system')
    """)

    # ── ai_policy_decisions ─────────────────────────────────────────────────
    op.create_table(
        "ai_policy_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("user_role", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("risk_factors", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confirmation_mode", sa.String(16), nullable=False),
        sa.Column("matched_rule_id", sa.String(64), nullable=True),
        sa.Column("matched_rule_desc", sa.Text(), nullable=True),
        sa.Column("override_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("fallback_chain", postgresql.JSONB(), nullable=True),
        sa.Column("applied_result", sa.String(16), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_check_constraint(
        "ck_decision_mode",
        "ai_policy_decisions",
        "confirmation_mode IN ('auto_apply','soft_confirm','hard_confirm','block')",
    )
    op.create_check_constraint(
        "ck_decision_result",
        "ai_policy_decisions",
        "applied_result IN ('auto_applied','pending_confirmation','blocked','error')",
    )
    op.create_index("idx_policy_decisions_proposal", "ai_policy_decisions", ["proposal_id"])
    op.create_index("idx_policy_decisions_org_created", "ai_policy_decisions", ["organization_id", sa.text("created_at DESC")])
    op.create_index("idx_policy_decisions_user", "ai_policy_decisions", ["user_id", sa.text("created_at DESC")])
    op.create_index("idx_policy_decisions_mode", "ai_policy_decisions", ["confirmation_mode"])
    op.create_index("idx_policy_decisions_risk", "ai_policy_decisions", ["risk_score"])

    # ── ai_policy_overrides ─────────────────────────────────────────────────
    op.create_table(
        "ai_policy_overrides",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("override_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("proposal_id", sa.String(64), nullable=True),
        sa.Column("operation", sa.String(32), nullable=True),
        sa.Column("override_mode", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("override_id"),
    )
    op.create_check_constraint(
        "ck_override_mode",
        "ai_policy_overrides",
        "override_mode IN ('auto_apply','soft_confirm','hard_confirm','block')",
    )
    op.create_index("idx_policy_overrides_org", "ai_policy_overrides", ["organization_id"])
    op.create_index("idx_policy_overrides_proposal", "ai_policy_overrides", ["proposal_id"])
    op.create_index(
        "idx_policy_overrides_active",
        "ai_policy_overrides",
        ["organization_id", "expires_at"],
        postgresql_where=sa.text("expires_at > NOW()"),
    )


def downgrade() -> None:
    op.drop_table("ai_policy_overrides")
    op.drop_table("ai_policy_decisions")
    op.drop_table("ai_policy_rules")
```

### 2.9 Integration Points

#### Register the Router in `app/main.py`

```python
# Add to existing imports
from app.routers import ai_policy  # new

# Add to the api_router include block (after ai_admin)
api_router.include_router(ai_policy.router)
```

#### Register ORM Models in `alembic/env.py`

```python
# Add to existing model imports near the top
import app.models.ai_policy  # noqa: F401
```

#### Register in `app/models/__init__.py`

```python
# Add to existing imports
from app.models.ai_policy import PolicyRule, PolicyDecision, PolicyOverride

# Add to __all__
__all__ += ["PolicyRule", "PolicyDecision", "PolicyOverride"]
```

#### Call the Policy Engine from Proposal Service

The policy engine evaluation MUST be integrated into the proposal creation flow (US-AI-009). When `propose_create_page`, `propose_update_page`, or `propose_delete_page` is called, the proposal service calls `PolicyEngine.evaluate()` before returning the proposal to the frontend.

```python
# Integration point: app/services/ai/proposal_service.py (US-AI-009)
# Inside the proposal creation method:

async def _create_proposal_with_policy_check(self, ...):
    # ... existing proposal creation logic ...

    # NEW: Evaluate policy
    risk_context = ProposalRiskContext(
        proposal_id=proposal.proposal_id,
        course_id=session.course_id,
        session_id=session.session_id,
        user_id=user_id,
        organization_id=organization_id,
        user_role=user_role,
        operation=operation,
        template_type=proposal.template_type,
        page_count=page_count,
        historical_error_rate=await policy_engine._get_historical_error_rate(user_id, organization_id),
    )

    policy_result = await policy_engine.evaluate(
        context=risk_context,
        trace_id=trace_id,
        dry_run=False,
    )

    # Attach policy result to the proposal response
    proposal.confirmation_mode = policy_result.confirmationMode
    proposal.risk_score = policy_result.riskScore
    proposal.policy_decision_id = policy_result.decisionId  # store if needed

    if policy_result.confirmationMode == "auto_apply":
        # Auto-apply: call apply service directly (bypasses frontend confirmation)
        await self.apply_service.apply_proposal(
            proposal_id=proposal.proposal_id,
            user_confirmed=True,
            auto_applied=True,
            trace_id=trace_id,
        )
        # The response to the frontend will indicate auto_apply was used
    ```

#### Update the Apply Service (US-AI-010)

When a proposal IS auto-applied, the apply service must:

1. Call `PolicyEngine.update_decision_result(proposal_id, "auto_applied")` on success.
2. Call `PolicyEngine.update_decision_result(proposal_id, "error")` on failure.

### 2.10 Environment Variables

```bash
# ── Policy Engine Configuration ──────────────────────────────────────────────

# Feature flag: enable/disable the policy engine.
# When disabled, ALL proposals require hard_confirm (safe fallback).
FEATURE_AI_POLICY_ENGINE=true

# Default confirmation mode when no rule matches and no fallback is configured.
# Must be one of: auto_apply, soft_confirm, hard_confirm, block
AI_POLICY_DEFAULT_CONFIRMATION=hard_confirm

# Number of days of historical audit data to consult for user error rate.
AI_POLICY_HISTORICAL_LOOKBACK_DAYS=30

# Maximum risk score threshold for auto_apply without an explicit rule match.
# Scores at or below this value MAY be auto-applied if no rule matches.
# Set to -1 to disable (force rule matching for auto_apply).
AI_POLICY_AUTO_APPLY_MAX_RISK=5.0

# Cache TTL for loaded policy rules (in seconds).
# Rules are cached in memory to avoid DB round-trips on every evaluation.
# Set to 0 to disable caching (always read from DB).
AI_POLICY_RULE_CACHE_TTL_SECONDS=30

# Policy engine evaluation timeout in milliseconds.
# If evaluation exceeds this, fail-safe to hard_confirm and log error.
AI_POLICY_EVALUATION_TIMEOUT_MS=500
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Policy evaluation p95 latency | < 50ms (cached rules), < 150ms (cold start) | Application metrics |
| Risk score computation p95 | < 10ms | Application metrics |
| Rule matching (100 active rules) p95 | < 5ms | Application metrics |
| Concurrent evaluations supported | 100/second per tenant | Load test |
| Policy config propagation delay | < 60s (cache TTL based) | Integration test |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Admin-only rule management | All CRUD endpoints require `admin` or `policy_admin` role |
| Tenant isolation | Rules and decisions are scoped by `organization_id` |
| Fail-safe default | If the engine throws an exception, fall back to `hard_confirm` — never auto-apply |
| Decision audit immutability | `ai_policy_decisions` is INSERT-only. No UPDATE/DELETE at application level except the `applied_result` field which is set by the apply service |
| Override auditing | Every override requires a reason string (min 10 chars) and is logged |

### 3.3 Data Retention

| Data | Retention | Action |
|---|---|---|
| ai_policy_rules | Indefinite (config) | Soft-delete (is_active=false) |
| ai_policy_decisions | 365 days | Archive to cold storage, then purge |
| ai_policy_overrides | 90 days after expiry | Auto-purge via scheduled job |

### 3.4 Availability

| Requirement | Target |
|---|---|
| Policy engine availability | Same as core API (99.9%) |
| Degraded mode | If policy engine is unreachable, default to `hard_confirm` and continue |
| Rule cache refresh | Background refresh, never blocking the evaluation path |

### 3.5 Observability

- Every policy evaluation emits a metric: `ai.policy.evaluation.count` with tags `mode`, `matched`, `overridden`
- Evaluation latency tracked as `ai.policy.evaluation.latency` (histogram)
- Rule cache hit/miss ratio: `ai.policy.rule_cache.hit_ratio`
- Override creation events: `ai.policy.override.created`
- Failed evaluations (exceptions) counted in `ai.policy.evaluation.error`
- All metrics use the same OpenTelemetry tracer as US-AI-021 observability infrastructure

---

## 4. Current State Assessment

### 4.1 What Exists

The codebase at `C:\Users\ADMIN\e-learning-backend` currently has:

1. **No policy engine tables exist.** The models in `app/models/` cover courses, pages, components, templates, themes, scoring, interaction events, branching, social, and AI audit (US-AI-020) — but no `ai_policy_rules`, `ai_policy_decisions`, or `ai_policy_overrides` tables.

2. **No policy engine service exists.** The AI services directory at `app/services/ai/` has no `policy_engine.py`. The proposal service (US-AI-009) currently hard-codes `confirmation_required=true` for all proposals — there is no risk-based decision logic.

3. **Existing proposal lifecycle** in `app/models/ai_proposal.py` (US-AI-009) provides `confirmation_required` and `confirmation_mode` fields on proposals. The policy engine will populate these fields dynamically instead of hard-coding them.

4. **Existing feature flag pattern** in `app/utils/feature_flags.py` defines the `FeatureFlagService` with environment-based toggles. A new `FEATURE_AI_POLICY_ENGINE` flag will be added here.

5. **Existing error envelope** in `app/utils/error_envelope.py` defines `build_error()` and `api_http_exception()` — the policy router will reuse these.

6. **Existing audit pattern** in `app/services/ai/audit_service.py` (US-AI-020) provides the `create_audit_entry()` method that the policy engine will reuse for logging policy decisions to the combined audit trail when applicable.

7. **The branching model** at `app/models/branching.py` shows the existing pattern for rule-based evaluation (conditions, priority, target) which the policy engine rule matching generalizes.

8. **The analytics router** at `app/routers/analytics.py` provides the reference pattern for read-only filtered list endpoints with `Depends(get_session)` that the policy decision list endpoint follows.

### 4.2 What Needs to Be Built

| Component | Description | Reference Pattern |
|---|---|---|
| `app/models/ai_policy.py` | ORM models for policy rules, decisions, overrides | `app/models/ai_audit.py` (US-AI-020) |
| `app/models/ai_policy_dto.py` | Pydantic DTOs for policy API surface | `app/models/ai_audit_dto.py` (US-AI-020) |
| `app/repositories/ai_policy_repo.py` | Repository with rule matching, decision write, override queries | `app/repositories/ai_audit_repo.py` (US-AI-020) |
| `app/services/ai/policy_engine.py` | Core risk scoring, rule matching, override resolution | `app/services/ai/audit_service.py` (US-AI-020) |
| `app/routers/ai_policy.py` | REST API for policy rule CRUD, evaluation, decisions, overrides | `app/routers/ai_admin.py` (US-AI-020) |
| Alembic migration | Add three policy tables with seed data | `alembic/versions/20260614_0002_add_policy_engine_tables.py` |
| Integration into proposal service | Call `PolicyEngine.evaluate()` during proposal creation | `app/services/ai/proposal_service.py` (US-AI-009) |
| Integration into apply service | Call `update_decision_result()` after proposal outcome | `app/services/ai/apply_service.py` (US-AI-010) |
| Tests | Unit, integration, and performance tests | See Section 6 |

### 4.3 Key Assumptions

- The `ai_policy_rules` table is seeded with sensible defaults (provided in the migration) — tenants can override
- Admin authorization middleware (`_require_admin`) exists and is shared across AI admin routers
- The proposal service (US-AI-009) is the primary consumer of `evaluate()` — it passes the `ProposalRiskContext` from proposal metadata
- Rule caching TTL of 30 seconds is acceptable for hot-reload; admins understand that changes propagate within 1 minute
- The `historical_error_rate` calculation queries `ai_audit_logs` (US-AI-020) — this story depends on audit tables existing
- The proposal's `confirmation_mode` field already exists on the proposal record (from US-AI-009) — the policy engine populates it

---

## 5. Expansion Points

### 5.1 Phase 2: Time-Based Policies

- **Scheduled rules**: Rules that activate only during specific hours or days (e.g., "auto_apply only during business hours")
- **Quarantine period**: Auto-applied changes enter a short quarantine (e.g., 15 minutes) during which an admin can reverse them without rollback

### 5.2 Phase 3: ML-Enhanced Risk Scoring

- **Adaptive risk model**: Use historical acceptance rates, user satisfaction scores, and edit distances to dynamically adjust risk weights per user
- **Anomaly detection**: Flag proposals with risk scores that deviate significantly from the user's historical baseline

### 5.3 Phase 4: Policy as Code

- **GitOps for policies**: Manage policy rules in a Git repository with CI/CD validation (similar to OPA/Gatekeeper)
- **Policy testing framework**: Automated test suite for policy rules with mock proposals and expected outcomes
- **Policy dry-run in CI**: Evaluate policy changes against a replay of recent proposals to measure impact before deploying

### 5.4 Phase 5: Federated Policy

- **Cross-tenant policy inheritance**: Parent org policies cascade to child orgs with optional override
- **Policy marketplace**: Share and import policy templates across tenants (similar to AWS Config rules)

---

## 6. Validation Strategy

### 6.1 Unit Tests

**File:** `tests/unit/ai/test_policy_engine.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_risk_score_content_text_update` | Instructor updating content-text, 1 page | Score = 2.5 (low risk) |
| `test_risk_score_assessment_delete` | Author deleting final-assessment page | Score = 15.5 (high risk) |
| `test_risk_score_batch_20_pages` | Admin batch-applying 20 pages | Score = 9.6 (high risk) |
| `test_risk_score_anonymous_role` | Anonymous user, any operation | Role confidence -2.0? No, max role risk |
| `test_risk_score_zero_page_count` | Edge: 0 pages (should clamp to 1) | Score computed with page_count=1 |
| `test_match_rule_exact_match` | Rule matches role+op+template exactly | Returns matched rule |
| `test_match_rule_wildcard_role` | Rule has user_role=NULL (any role) | Rule matches |
| `test_match_rule_wildcard_operation` | Rule has operation=NULL (any op) | Rule matches |
| `test_match_rule_priority_order` | Two rules could match; lower priority first | Returns lower priority rule |
| `test_match_rule_no_match` | No rule matches any condition | Returns None, fallback chain populated |
| `test_match_rule_min_risk_score` | Rule has min_risk_score=10, score=8 | Rule does not match |
| `test_override_proposal_specific` | Override exists for exact proposal_id | Override mode wins |
| `test_override_operation_wide` | Override exists for operation (no proposal_id) | Override mode wins |
| `test_override_expired` | Override has expires_at in the past | Override ignored |
| `test_evaluate_auto_apply` | Low risk + matching auto_apply rule | Returns auto_apply, no warning |
| `test_evaluate_hard_confirm_delete` | Delete operation + hard_confirm rule | Returns hard_confirm |
| `test_evaluate_block_anonymous` | Anonymous role + block rule | Returns block |
| `test_evaluate_fallback_to_system_default` | No rules match | Returns hard_confirm (system default) |
| `test_evaluate_engine_exception` | DB throws during evaluation | Returns hard_confirm, error logged |
| `test_create_rule_conflict` | Rule with same dimensions exists | Raises ValueError (conflict) |
| `test_update_rule_version_mismatch` | expected_version < actual version | Raises ValueError (stale) |
| `test_calculate_historical_error_rate` | User has 5 fails out of 100 applies | Returns 0.05 |
| `test_calculate_historical_error_rate_no_data` | User has no audit entries | Returns 0.0 |

### 6.2 API Integration Tests

**File:** `tests/integration/ai/test_policy_api.py`

| Test | Scenario | HTTP | Expected |
|---|---|---|---|
| `test_list_rules_empty` | No rules for tenant | GET | 200, items=[], total=0 |
| `test_list_rules_with_seed` | 9 seed rules exist | GET | 200, total=9 |
| `test_create_rule` | Valid rule payload | POST | 201, ruleId returned |
| `test_create_rule_conflict` | Duplicate dimensions | POST | 409 |
| `test_create_rule_invalid_mode` | Bad confirmation_mode | POST | 422 |
| `test_update_rule` | Change mode, valid version | PUT | 200, version incremented |
| `test_update_rule_version_conflict` | Stale version | PUT | 409 |
| `test_delete_rule` | Soft-delete | DELETE | 200, isActive=false |
| `test_delete_rule_not_found` | Non-existent rule_id | DELETE | 404 |
| `test_evaluate_dry_run` | Valid request | POST | 200, riskScore and mode returned |
| `test_evaluate_dry_run_invalid_role` | Unknown role | POST | 200 (graceful default) |
| `test_list_decisions_empty` | No decisions | GET | 200, items=[] |
| `test_list_decisions_with_data` | Seed 5 decisions | GET | 200, total=5 |
| `test_list_decisions_filter_proposal` | Filter by proposal_id | GET | 200, filtered |
| `test_create_override` | Valid override | POST | 201 |
| `test_create_override_short_reason` | Reason < 10 chars | POST | 422 |
| `test_list_overrides` | Active overrides | GET | 200 |
| `test_cancel_override` | By override_id | DELETE | 200, status=cancelled |
| `test_cancel_override_not_found` | Non-existent | DELETE | 404 |
| `test_policy_engine_disabled` | FEATURE_AI_POLICY_ENGINE=false | ALL | 404 |
| `test_non_admin_cannot_manage_rules` | No admin role | POST/PUT/DELETE | 403 |
| `test_evaluate_with_override` | Override exists for operation | POST | 200, overrideApplied=true |

### 6.3 Integration Tests for Proposal Flow (End-to-End)

**File:** `tests/integration/ai/test_proposal_with_policy.py`

| Test | Scenario | Expected |
|---|---|---|
| `test_propose_update_content_text_auto_applies` | Instructor updates content-text page | Proposal created AND applied in same call; response shows auto_apply=true |
| `test_propose_delete_page_requires_hard_confirm` | Author proposes delete | Proposal created with confirmation_mode=hard_confirm; NOT auto-applied |
| `test_propose_assessment_change_hard_confirm` | Any role changes assessment | confirmation_mode=hard_confirm |
| `test_policy_decision_recorded_on_proposal` | Any proposal creation | Policy decision row exists in ai_policy_decisions |
| `test_auto_apply_skips_frontend_confirmation` | auto_apply proposal | Apply service called; no confirmation token required |
| `test_auto_apply_still_audited` | Auto-applied proposal | Audit entry created with outcome "auto_applied" |
| `test_admin_override_forces_auto_apply` | Override overrides hard_confirm rule | Proposal auto-applied despite rule saying hard_confirm |

### 6.4 Security Tests

| Test | Scenario | Expected |
|---|---|---|
| `test_non_admin_cannot_list_decisions` | Regular user queries decisions | 403 |
| `test_cross_tenant_decision_isolation` | Org A cannot see Org B's decisions | Empty results or 403 |
| `test_override_reason_required` | Override without reason | 422 |
| `test_failsafe_on_engine_crash` | Policy engine raises exception | Proposal still created with hard_confirm |
| `test_auto_apply_disabled_when_flag_off` | FEATURE_AI_POLICY_ENGINE=false | All proposals hard_confirm |

### 6.5 Performance Tests

| Test | Scenario | Expected |
|---|---|---|
| `test_evaluate_100_rules` | 100 active rules, worst-case matching (last rule) | p95 < 50ms |
| `test_risk_score_bulk` | 1000 risk score computations | p95 < 10ms per computation |
| `test_concurrent_evaluations` | 50 simultaneous evaluations | No DB pool exhaustion |

---

## 7. Definition of Done

### 7.1 Acceptance Criteria

1. Policy rules can be created, read, updated, and soft-deleted via dedicated admin API endpoints
2. Every proposal creation calls the policy engine and receives a `confirmation_mode` based on risk
3. Low-risk operations (instructor updating content-text) are auto-applied without frontend confirmation
4. High-risk operations (delete page, assessment change, batch apply) always require hard confirmation
5. Admin overrides can bypass the policy engine for a specific proposal or operation type with a logged reason
6. Policy decisions are recorded in `ai_policy_decisions` and queryable by admin
7. Policy configuration changes propagate within 60 seconds (rule cache TTL)
8. When `FEATURE_AI_POLICY_ENGINE=false`, all proposals default to `hard_confirm`
9. When the policy engine throws an exception, the system fails safe to `hard_confirm`
10. Seed rules provide sensible defaults out of the box
11. Tenant isolation: Org A's rules do not affect Org B's evaluations
12. Alembic migration is reversible (`downgrade` drops all three tables)
13. Existing test suite passes with no regressions

### 7.2 Quality Gates

- [ ] All unit tests pass (coverage > 85% for new code)
- [ ] All API integration tests pass
- [ ] Proposal service integration tests (auto_apply flow and hard_confirm flow) pass
- [ ] `FEATURE_AI_POLICY_ENGINE=false` defaults all proposals to `hard_confirm`
- [ ] OpenAPI spec renders correctly with "AI Policy Engine" route tag
- [ ] Flake8/Pylint passes with no new issues
- [ ] Type annotations present on all new function signatures
- [ ] Migration tested both `upgrade()` and `downgrade()` — seed data verified after upgrade
- [ ] Performance benchmark meets p95 targets: evaluation < 50ms cached, < 150ms cold
- [ ] Security review: no privilege escalation possible via policy overrides

### 7.3 Signoff Checklist

| Role | Signoff Criteria |
|---|---|
| Product Owner | Acceptance criteria met; demo shows auto_apply for typo fix and hard_confirm for delete |
| Security Lead | Fail-safe behaviour verified; override requires reason; tenant isolation confirmed |
| QA Lead | All test levels pass; performance benchmarks met; edge cases covered |
| Operations | Migration script tested; env vars documented; rollback plan exists |
| Tech Lead | Code review clean; architecture documented; integration with US-AI-009 and US-AI-010 verified |

---

## 8. Task Breakdown

### Task Group A: Foundation (5 SP)

**A-1: Create ORM Models and Alembic Migration** (2 SP)
- Files: `app/models/ai_policy.py`, `alembic/versions/20260614_0002_add_policy_engine_tables.py`
- Details:
  - Implement `PolicyRule` model with all columns from section 2.1.1
  - Implement `PolicyDecision` model with all columns from section 2.1.2
  - Implement `PolicyOverride` model with all columns from section 2.1.3
  - Register models in `app/models/__init__.py`
  - Register model import in `alembic/env.py`
  - Generate and test the Alembic migration (both upgrade and downgrade)
  - Verify seed data is inserted correctly on upgrade
  - Verify `Base.metadata.create_all` picks up the new tables

**A-2: Create Pydantic DTOs** (1 SP)
- File: `app/models/ai_policy_dto.py`
- Details:
  - Implement all request/response DTOs from section 2.3
  - Implement `ProposalRiskContext` internal model
  - Implement `RiskFactorDetail` with factor, weight, score, rationale
  - Validate field constraints, descriptions, type annotations

**A-3: Create Policy Repositories** (2 SP)
- Files: `app/repositories/ai_policy_repo.py`
- Details:
  - Implement `PolicyRuleRepository` with `list_active()`, `list_with_filters()`, `get_by_rule_id()`, `find_conflict()`, `create()`, `update()`
  - Implement `PolicyDecisionRepository` with `create()`, `update_result()`, `list_with_filters()`, `get_by_proposal_id()`
  - Implement `PolicyOverrideRepository` with `find_active()`, `list_with_filters()`, `create()`, `delete()`
  - Unit test: all repo methods with mocked session

### Task Group B: Policy Engine Core (8 SP)

**B-1: Implement Risk Score Computation** (2 SP)
- File: `app/services/ai/policy_engine.py`
- Details:
  - Implement `compute_risk_score()` with weighted composite from FR-POL-09
  - Implement `_operation_weight()`, `_template_weight()`, `_page_count_weight()`, `_role_confidence()`
  - Implement `_get_historical_error_rate()` query against `ai_audit_logs`
  - Return `(total_score, factor_details)` with per-factor rationale strings
  - Unit test with all template types, operation types, and edge cases

**B-2: Implement Rule Matching Engine** (2 SP)
- File: `app/services/ai/policy_engine.py`
- Details:
  - Implement `match_rule()` with priority-ordered matching
  - Support wildcards: `user_role=NULL`, `operation=NULL`, `template_type=NULL` all match any value
  - Support `min_risk_score` threshold check
  - Build fallback chain tracking: which fallback levels were tried and why
  - Implement rule caching with configurable TTL (`AI_POLICY_RULE_CACHE_TTL_SECONDS`)
  - Unit test: wildcard matching, priority ordering, fallback chain population

**B-3: Implement Override Resolution** (1 SP)
- File: `app/services/ai/policy_engine.py`
- Details:
  - Implement `check_override()`: proposal-specific first, then operation-wide
  - Implement `create_override()`, `list_overrides()`, `cancel_override()`
  - Expiry enforcement: ignore overrides where `expires_at < NOW()`
  - Unit test: override precedence, expiry, cancellation

**B-4: Implement Core Evaluate Method** (3 SP)
- File: `app/services/ai/policy_engine.py`
- Details:
  - Implement `evaluate()` orchestrating the full pipeline: compute risk -> match rules -> check overrides -> resolve mode -> handle fallback -> record decision -> return result
  - Implement `record_decision()` writes to `ai_policy_decisions`
  - Implement `update_decision_result()` called by apply service
  - Fail-safe: wrap evaluation in try/except, log error, return `hard_confirm`
  - Dry-run mode: skip decision write when `dry_run=True`
  - Integration test: full evaluation pipeline with seeded rules and overrides

### Task Group C: Policy API (5 SP)

**C-1: Create Policy Admin Router** (2 SP)
- File: `app/routers/ai_policy.py`
- Details:
  - Implement rule CRUD endpoints (list, create, update, delete)
  - Implement evaluation endpoint (dry-run)
  - Implement decision audit list endpoint
  - Implement override management endpoints (create, list, cancel)
  - Add admin authorization dependency injection
  - Add feature flag gating (`FEATURE_AI_POLICY_ENGINE`)
  - Register router in `app/main.py`
  - Integration test: all endpoints with seeded data

**C-2: Integrate Policy Engine into Proposal Service** (2 SP)
- File: `app/services/ai/proposal_service.py` (US-AI-009)
- Details:
  - Add `PolicyEngine.evaluate()` call inside proposal creation methods
  - Build `ProposalRiskContext` from proposal metadata, session context, and user information
  - Attach `confirmation_mode`, `risk_score`, and `policy_decision_id` to the proposal response
  - Implement auto-apply shortcut: if mode is `auto_apply`, call apply service immediately
  - Ensure the frontend receives `autoAppplied: true` flag in the response when auto-apply happens
  - Integration test: proposal creation with auto-apply flow and hard-confirm flow

**C-3: Integrate Policy Engine Reporting into Apply Service** (1 SP)
- File: `app/services/ai/apply_service.py` (US-AI-010)
- Details:
  - After successful apply, call `PolicyEngine.update_decision_result(proposal_id, "auto_applied")`
  - On apply failure, call `PolicyEngine.update_decision_result(proposal_id, "error")`
  - For proposals that pass through confirmation (non-auto), call `update_decision_result(proposal_id, "pending_confirmation")` at creation, then update on confirmation/apply
  - Unit test: apply service integration with decision result updates

### Task Group D: Configuration and Seed Data (2 SP)

**D-1: Feature Flags and Environment Configuration** (1 SP)
- Files: `app/utils/feature_flags.py`, `.env.example`
- Details:
  - Add `FEATURE_AI_POLICY_ENGINE` flag to feature flag service
  - Add all env vars from section 2.10 to `.env.example`
  - Wire feature flag into router registration: when false, policy routes return 404
  - Wire feature flag into proposal service: when false, skip policy evaluation, use `hard_confirm`

**D-2: Seed Data and Migration Verification** (1 SP)
- File: `alembic/versions/20260614_0002_add_policy_engine_tables.py`
- Details:
  - Verify the 9 seed rules in the migration are correct and comprehensive
  - Write a test that verifies seed data exists after migration upgrade
  - Write a test that verifies seed data is removed after migration downgrade
  - Document the seed rules in operations runbook

### Task Group E: Testing (5 SP)

**E-1: Unit Tests** (2 SP)
- Files: `tests/unit/ai/test_policy_engine.py`
- Details:
  - Mock SQLAlchemy session for repository tests
  - Test all risk score combinations (section 6.1 matrix)
  - Test all rule matching scenarios (exact, wildcard, priority, no-match, threshold)
  - Test override resolution (proposal-specific, operation-wide, expired)
  - Test full evaluation pipeline with mocked dependencies
  - Test fail-safe behaviour on engine exception
  - Test historical error rate calculation

**E-2: API Integration Tests** (1.5 SP)
- Files: `tests/integration/ai/test_policy_api.py`, `tests/integration/ai/test_proposal_with_policy.py`
- Details:
  - Seed test database with policy rules, decisions, overrides
  - Test all CRUD endpoints with real HTTP client
  - Test dry-run evaluation endpoint
  - Test proposal creation with policy evaluation end-to-end
  - Test auto-apply flow: proposal + apply in one transaction
  - Test hard-confirm flow: proposal created, not auto-applied
  - Test feature flag gating
  - Test authorization enforcement
  - Test tenant isolation

**E-3: Performance Benchmark** (1 SP)
- File: `tests/performance/test_policy_engine_perf.py`
- Details:
  - Seed 100 policy rules with varying specificity
  - Run evaluation 1000 times and measure p50/p95/p99 latency
  - Run cached vs uncached evaluation comparison
  - Run concurrent evaluation (50 concurrent callers)
  - Verify results against p95 targets from section 3.1

**E-4: Security Tests** (0.5 SP)
- File: `tests/security/test_policy_security.py`
- Details:
  - Verify non-admin cannot manage rules
  - Verify cross-tenant isolation
  - Verify override reason requirement
  - Verify fail-safe on engine crash
  - Verify feature flag disabled state

### Task Group F: Documentation (1 SP)

**F-1: API Documentation** (0.5 SP)
- Details:
  - Verify OpenAPI spec renders all new routes with correct schemas under "AI Policy Engine" tag
  - Add route summaries and descriptions matching section 2.4
  - Document admin authorization requirements
  - Document policy evaluation flow for frontend developers

**F-2: Operations Runbook** (0.5 SP)
- Details:
  - Document how to create, update, and delete policy rules
  - Document how to create admin overrides and when to use them
  - Document the seed rules and their intended behaviour
  - Document troubleshooting: policy not applying as expected, cache propagation delay
  - Document monitoring: decision audit log query patterns, common failure modes
  - Document migration rollback procedure

---

### Summary: Total Effort Estimate

| Task Group | Story Points | Dependencies |
|---|---|---|
| A: Foundation (Models, DTOs, Repos, Migration) | 5 | US-AI-004 (existing persistence patterns), US-AI-020 (audit tables for error rate) |
| B: Policy Engine Core (Risk, Matching, Overrides, Evaluate) | 8 | A completed |
| C: Policy API + Proposal Service Integration | 5 | B completed, US-AI-009 (proposal lifecycle), US-AI-010 (apply service) |
| D: Configuration and Seed Data | 2 | A completed |
| E: Testing | 5 | A-D completed |
| F: Documentation | 1 | E completed |
| **Total** | **26 SP** | |

### Dependencies on Other Stories

| Story | Dependency | Notes |
|---|---|---|
| US-AI-009 | Required | Proposal lifecycle must exist to integrate policy evaluation |
| US-AI-010 | Required | Apply service must exist to handle auto-apply and report outcomes |
| US-AI-002 | Required | Feature flags infra for `FEATURE_AI_POLICY_ENGINE` |
| US-AI-020 | Required | `ai_audit_logs` must exist for historical error rate calculation |
| US-AI-003 | Required | AI module isolation pattern for `app/services/ai/policy_engine.py` |
| US-AI-036 | Related | Policy engine can enforce cost-based gates (future) |
| US-AI-040 | Related | Policy decides whether rollback is auto or manual (future) |
