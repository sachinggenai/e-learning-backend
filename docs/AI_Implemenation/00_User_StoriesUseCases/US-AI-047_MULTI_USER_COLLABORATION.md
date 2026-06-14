# US-AI-047 -- Multi-User Collaboration on AI-Authored Course Content

**Priority:** COULD
**Depends on:** US-AI-006, US-AI-043
**Status:** Draft
**Target Release:** Phase 3
**Last Updated:** 2026-06-14

---

## 1. FUNCTIONAL SPECIFICATION

### User Story

As a Course Lead or Instructional Designer, I want to invite other authors to collaboratively author a course using the AI assistant, so that multiple subject-matter experts can contribute AI-generated content to the same course simultaneously with clear ownership, review workflows, and activity visibility. As an Admin, I want configurable collaboration policies (max collaborators per course, required review gates, role-based permissions) so that collaborative AI authoring remains governed and auditable.

### Functional Requirements

**FR-001 -- Collaboration-Aware Session Model:** When collaboration is enabled for a course, the system MUST relax the exclusive SESSION lock (defined in US-AI-043) to allow multiple concurrent AI sessions on the same course. Each session is owned by a different collaborator. Page-level WRITE locks from US-AI-043 remain exclusive: only one collaborator may hold a WRITE lock on a given page at any time. The system MUST distinguish between "course owner / lead author" (who sees all sessions) and "collaborator" (who sees only their own and explicitly shared state).

**FR-002 -- Course Collaborator Management:** Authorized course owners SHALL have endpoints to: (a) invite a user to collaborate on a course by email or user ID; (b) assign a role to each collaborator (`editor`, `reviewer`, `viewer`); (c) remove a collaborator; (d) list all collaborators with their roles, active session status, and last activity timestamp. Invitations SHALL expire after a configurable TTL (default 72 hours). A course SHALL have exactly one owner (the creator) and zero or more collaborators.

**FR-003 -- Collaboration Roles and Permissions Matrix:** The system SHALL enforce the following permissions per role on AI authoring operations:

| Operation | Owner | Editor | Reviewer | Viewer |
|---|---|---|---|---|
| Start AI session on course | Yes | Yes | No | No |
| Propose create/update/delete pages | Yes | Yes | No | No |
| Apply own proposals (auto-confirm) | Yes | Yes* | No | No |
| Apply proposals from other collaborators | Yes | No | No | No |
| Review and approve/reject proposals | Yes | No | Yes | No |
| View proposals and diffs | Yes | Yes | Yes | Yes |
| View course state and pages | Yes | Yes | Yes | Yes |
| Invite/remove collaborators | Yes | No | No | No |
| View activity feed | Yes | Yes | Yes | No |
| Release locks held by others | Yes | No | No | No |
| Delete course | Yes | No | No | No |

*Editors may auto-apply their own proposals ONLY if the proposal's risk score (from US-AI-032 policy engine) is below a configurable threshold. High-risk proposals (deletes, assessment changes) from editors REQUIRE owner or reviewer approval.

**FR-004 -- Collaborative Proposal Diffs with Ownership:** Every proposal created in a collaborative session SHALL carry a `collaboratorId` and `collaboratorName` field in its metadata, visible in the proposal preview UI. When an editor creates a proposal, it appears in a shared "Pending Review" queue visible to the course owner and assigned reviewers. The proposal preview SHALL display: (a) who created it; (b) which page is affected; (c) the before/after diff; (d) validation results; (e) reviewer comments if any; (f) approval status (pending / approved / rejected / applied).

**FR-005 -- Proposal Review and Approval Workflow:** Reviewers and the course owner SHALL have dedicated endpoints to: (a) list all proposals pending review for a course; (b) view the full proposal diff; (c) approve a proposal (making it eligible for apply by the original author or the owner); (d) reject a proposal with a required reason comment; (e) request changes with specific feedback. When a proposal is approved, the original author receives an in-session notification. When rejected, the author receives the rejection reason and can revise and resubmit.

**FR-006 -- Collaborative Real-Time Activity Feed:** The system SHALL maintain a real-time activity feed for each collaborative course, visible to all collaborators in their AI sidebar. Events recorded in the feed include: (a) collaborator joined/left; (b) collaborator started/ended AI session; (c) page locked by collaborator; (d) proposal created; (e) proposal approved/rejected; (f) proposal applied; (g) page unlocked; (h) collaborator added/removed by owner. The feed SHALL display the event type, user name, page title, and timestamp, with the most recent events first. The feed SHALL be persisted in the database and support polling (every 10 seconds) via a dedicated endpoint.

**FR-007 -- Session Handoff and Context Transfer:** If a collaborator's AI session ends (timeout, manual end, browser close) while they have pending (unapplied) proposals, the next time any collaborator opens an AI session on the same course, the system SHALL surface a notification: "Collaborator X has N pending proposals from their last session. You may review and apply them." The system SHALL NOT auto-apply proposals from another collaborator without explicit review. The session context (active proposals, lock status, recent activity) SHALL be durable and survive individual session expiry.

**FR-008 -- Collaboration Audit Trail:** Every collaborative action SHALL be recorded in the `ai_audit_logs` table with the following additional fields: `collaborator_id`, `collaborator_role`, `related_collaborator_id` (for actions that involve another user, e.g., approve or reject), and `collaboration_event_type`. Collaboration-specific event types SHALL include: `COLLABORATOR_INVITED`, `COLLABORATOR_JOINED`, `COLLABORATOR_REMOVED`, `PROPOSAL_REVIEWED_APPROVED`, `PROPOSAL_REVIEWED_REJECTED`, `PROPOSAL_APPLIED_BY_OTHER`, `SESSION_HANDOFF`, `LOCK_RELEASED_BY_OWNER`. These events SHALL be queryable in the admin audit dashboard alongside other AI events.

**FR-009 -- Collaboration Conflict Resolution UI:** When two collaborators hold WRITE locks on different pages but one attempts to apply a change that semantically conflicts with another collaborator's pending proposal (e.g., both edit the same component on different pages, or one deletes a page the other is editing), the system SHALL detect the semantic conflict at apply time and show a resolution dialog: "Your change conflicts with a pending proposal by Collaborator X on page Y. You may: (a) proceed and overwrite (last-writer-wins with notification to X); (b) wait for X to apply or withdraw their proposal; (c) consult with X via the activity feed." The conflict detection SHALL use a hash-based comparison of the affected page snapshot vs. the base snapshot used by each proposal.

**FR-010 -- Collaboration Configuration Per Organization:** The system SHALL support per-organization configuration for collaboration features: (a) `collaboration_enabled` (boolean, default false -- gated by the existing `collaboration` feature flag); (b) `max_collaborators_per_course` (integer, default 10); (c) `editor_auto_apply_allowed` (boolean, default false -- if true, editors can auto-apply low-risk proposals); (d) `review_required_for_editors` (boolean, default true -- if true, editor proposals require reviewer/owner approval); (e) `invitation_ttl_hours` (integer, default 72); (f) `activity_feed_retention_days` (integer, default 90).

### User Flow: Happy Path -- Two Editors Collaborating on a Course

1. Alice creates a new course and opens the AI chat panel. A session S-A is created. Alice is the course owner.
2. Alice types "Generate a first draft of this course with 5 pages." The AI proposes and applies 5 pages.
3. Alice opens the course Collaborators panel, enters Bob's email, and assigns role "Editor". Bob receives an invitation email with a link.
4. Bob clicks the link. The system validates the invitation (not expired, Bob has access to the organization). The invitation is consumed. Bob is added as an editor.
5. Bob navigates to the course and opens the AI chat panel. Session S-B is created. The system recognizes collaboration is enabled and allows the second session (no `COURSE_LOCKED` error).
6. Bob's AI sidebar shows the activity feed: "Alice generated page 1-5", "Alice invited Bob", "Bob joined". Bob sees that Alice has WRITE locks on pages 1-3.
7. Bob types "Add a new summary page for module 1." The AI calls `fetch_page(pageId=3)` (acquires READ lock -- succeeds), then `propose_create_page(...)` (creates proposal P-101 with `collaboratorId="Bob"`).
8. Since Bob is an editor and the system is configured with `review_required_for_editors=true`, proposal P-101 enters "Pending Review" status. It does NOT auto-apply.
9. Alice, still in her session S-A, sees a notification: "Bob has a pending proposal to create page 'Module 1 Summary'."
10. Alice opens the proposal review panel. She sees the diff, validation passes, and clicks "Approve".
11. Bob's session receives a notification: "Your proposal (create 'Module 1 Summary') was approved by Alice. You may now apply it."
12. Bob clicks "Apply" from the proposal preview. The page is created. The activity feed records: "Bob created page 'Module 1 Summary' (approved by Alice)."

### User Flow: Happy Path -- Reviewer Approves Editor Changes

1. Course C1 has Alice as Owner, Bob as Editor, and Carol as Reviewer.
2. Bob proposes updating the title of page "Introduction" to "Getting Started".
3. Since Bob is an Editor and `review_required_for_editors=true`, the proposal P-201 enters "Pending Review".
4. Carol (Reviewer) logs in. She cannot start an AI session (Reviewers cannot edit), but she sees a "Pending Reviews (1)" badge on the course.
5. Carol opens the review panel. She sees Bob's proposal with the before/after diff. She adds a comment: "Please also update the navigation label to match."
6. Bob sees Carol's comment and updates his proposal. Carol approves.
7. Bob applies the change. Audit records: `PROPOSAL_REVIEWED_APPROVED` by Carol, then `PageUpdatedByAI` by Bob.

### User Flow: Error Path -- Semantic Conflict on Apply

1. Alice holds a WRITE lock on page P-5 (Final Assessment) via session S-A. She has a pending proposal to change question 3.
2. Bob holds a WRITE lock on page P-4 via session S-B. He has a pending proposal to delete page P-5 (the final assessment) and replace it with a new structure.
3. Bob tries to apply his delete-proposal for page P-5. The system detects: (a) page P-5 is WRITE-locked by Alice using session S-A; (b) Alice has a pending proposal on P-5 that would conflict with deletion.
4. The system returns a `SEMANTIC_CONFLICT` error:
   ```json
   {
     "status": "error",
     "code": "SEMANTIC_CONFLICT",
     "message": "Cannot delete page 'Final Assessment' -- Alice has a pending proposal on this page and holds the write lock. You may request Alice to release the lock or wait.",
     "details": {
       "pageId": "P5",
       "pageTitle": "Final Assessment",
       "conflictingCollaboratorId": "user-alice-uuid",
       "conflictingCollaboratorName": "Alice",
       "conflictType": "pending_proposal_on_target",
       "conflictingProposalId": "uuid-proposal-alice",
       "resolutionOptions": ["request_release", "wait", "escalate_to_owner"]
     },
     "retryable": true
   }
   ```
5. Bob clicks "Notify Alice" in the conflict dialog. Alice's session receives: "Bob wants to delete page 'Final Assessment' which conflicts with your pending proposal."
6. Alice reviews Bob's intent. She withdraws her proposal and releases her lock.
7. Bob receives notification that the lock is released. He retries the apply. This time it succeeds.

### UI/UX Requirements

- **Collaborators Panel:** A dedicated panel in the course overview showing all collaborators with their roles, online/active status (green dot if they have an active AI session on this course), and a "Remove" button for the owner. Includes an "Invite Collaborator" button that opens an email/username input dialog.
- **Activity Feed Panel:** A scrollable list in the AI sidebar showing recent collaboration events. Each event shows: user avatar/name, action description, relative timestamp ("2 min ago"), and a clickable link to the affected page if applicable. The feed auto-updates via polling every 10 seconds.
- **Collaborator Lock Indicators:** Extends the US-AI-043 lock indicators to show the collaborator's role badge (Owner crown icon, Editor pencil icon, Reviewer checkmark icon) next to their name in the lock tooltip.
- **Pending Review Badge:** A counter badge on the course card and in the AI sidebar showing the number of proposals awaiting review. Visible to owners and reviewers.
- **Proposal Review Dialog:** A dedicated modal for reviewing a collaborator's proposal, showing: proposer name and role, page title, before/after diff, validation results, a comment text area, and "Approve" / "Request Changes" / "Reject" buttons. If the current user is the proposer, shows "Apply" button instead (only when approved).
- **Conflict Resolution Dialog:** When a semantic conflict is detected, a dialog explaining the conflict in plain language with resolution options: "Notify Collaborator", "Wait (recheck in 30s)", "Escalate to Owner" (if current user is not the owner).
- **Invitation Workflow UI:** An invitation dialog with email input, role dropdown (Editor / Reviewer / Viewer), and an optional message field. After sending, the dialog shows "Invitation sent to bob@example.com (expires in 72 hours)" with a "Resend" link.
- **Collaboration Configuration UI:** Admin settings page with toggle for `collaboration_enabled`, numeric inputs for max collaborators, auto-apply settings, and review requirements.

---

## 2. TECHNICAL SPECIFICATION

### API Contracts

#### 2.1 Collaborator Management API

**POST /api/v1/ai/collaborations/{courseId}/invitations**
Invite a collaborator to a course. Owner only.

Request:
```json
{
  "inviteeEmail": "bob@example.com",
  "role": "editor",
  "message": "Please help me build out the assessment section!",
  "ttlHours": 72
}
```

Response (201):
```json
{
  "invitationId": "uuid-invitation",
  "courseId": "course-C1",
  "courseTitle": "Data Science Fundamentals",
  "inviteeEmail": "bob@example.com",
  "invitedByUserId": "user-alice-uuid",
  "invitedByUserName": "Alice",
  "role": "editor",
  "status": "pending",
  "expiresAt": "2026-06-17T10:30:00Z",
  "createdAt": "2026-06-14T10:30:00Z"
}
```

Error (403):
```json
{
  "status": "error",
  "code": "NOT_COURSE_OWNER",
  "message": "Only the course owner can invite collaborators.",
  "retryable": false
}
```

Error (409):
```json
{
  "status": "error",
  "code": "COLLABORATOR_LIMIT_REACHED",
  "message": "This course has reached the maximum of 10 collaborators.",
  "details": { "maxCollaborators": 10, "currentCount": 10 },
  "retryable": false
}
```

**POST /api/v1/ai/collaborations/invitations/{invitationId}/accept**
Accept a collaboration invitation. Authenticated user must match the invitee email.

Request:
```json
{
  "userId": "user-bob-uuid"
}
```

Response (200):
```json
{
  "status": "accepted",
  "courseId": "course-C1",
  "role": "editor",
  "joinedAt": "2026-06-14T11:00:00Z"
}
```

Error (410):
```json
{
  "status": "error",
  "code": "INVITATION_EXPIRED",
  "message": "This invitation expired on 2026-06-17T10:30:00Z. Please ask the course owner to resend.",
  "retryable": false
}
```

**GET /api/v1/ai/collaborations/{courseId}/collaborators**
List all collaborators for a course. Visible to any collaborator.

Response (200):
```json
{
  "courseId": "course-C1",
  "owner": {
    "userId": "user-alice-uuid",
    "userName": "Alice",
    "email": "alice@example.com",
    "role": "owner",
    "hasActiveSession": true,
    "lastActivityAt": "2026-06-14T11:30:00Z"
  },
  "collaborators": [
    {
      "userId": "user-bob-uuid",
      "userName": "Bob",
      "email": "bob@example.com",
      "role": "editor",
      "hasActiveSession": true,
      "lastActivityAt": "2026-06-14T11:25:00Z",
      "activeLockCount": 2
    },
    {
      "userId": "user-carol-uuid",
      "userName": "Carol",
      "email": "carol@example.com",
      "role": "reviewer",
      "hasActiveSession": false,
      "lastActivityAt": "2026-06-13T15:00:00Z",
      "activeLockCount": 0
    }
  ],
  "total": 3,
  "maxCollaborators": 10
}
```

**DELETE /api/v1/ai/collaborations/{courseId}/collaborators/{userId}**
Remove a collaborator from a course. Owner only. Requires reason.

Request:
```json
{
  "reason": "Bob has completed his section. Removing to free up a slot."
}
```

Response (200):
```json
{
  "status": "removed",
  "userId": "user-bob-uuid",
  "userName": "Bob",
  "removedAt": "2026-06-14T12:00:00Z",
  "releasedLocksCount": 1,
  "invalidatedProposalsCount": 2
}
```

#### 2.2 Proposal Review API

**GET /api/v1/ai/collaborations/{courseId}/reviews/pending**
List all proposals pending review. Visible to owner and reviewers.

Query parameters: `?page=C4&status=pending&limit=20&offset=0`

Response (200):
```json
{
  "pendingProposals": [
    {
      "proposalId": "uuid-proposal",
      "pageId": "P42",
      "pageTitle": "Introduction",
      "proposerUserId": "user-bob-uuid",
      "proposerName": "Bob",
      "proposerRole": "editor",
      "operation": "update",
      "createdAt": "2026-06-14T11:00:00Z",
      "validationStatus": "valid",
      "validationMessages": [],
      "reviewStatus": "pending",
      "commentCount": 0
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**GET /api/v1/ai/collaborations/{courseId}/reviews/{proposalId}**
Get full proposal details for review.

Response (200):
```json
{
  "proposalId": "uuid-proposal",
  "pageId": "P42",
  "pageTitle": "Introduction",
  "operation": "update",
  "proposer": {
    "userId": "user-bob-uuid",
    "userName": "Bob",
    "role": "editor"
  },
  "diff": {
    "before": { "title": "Introduction", "data": { "content": "Old content..." } },
    "after": { "title": "Getting Started", "data": { "content": "New content..." } },
    "changedFields": ["title", "data.content"]
  },
  "validation": {
    "status": "valid",
    "messages": []
  },
  "lock": {
    "lockId": "uuid-lock",
    "heldBy": "Bob",
    "acquiredAt": "2026-06-14T11:00:00Z",
    "ttlSecondsRemaining": 450
  },
  "reviewHistory": [
    {
      "reviewId": "uuid-review-1",
      "reviewerUserId": "user-carol-uuid",
      "reviewerName": "Carol",
      "decision": "changes_requested",
      "comment": "Please update the navigation label to match the new title.",
      "createdAt": "2026-06-14T11:15:00Z"
    }
  ],
  "reviewStatus": "pending"
}
```

**POST /api/v1/ai/collaborations/{courseId}/reviews/{proposalId}/approve**
Approve a pending proposal. Owner or reviewer only.

Request:
```json
{
  "comment": "Looks good. Approved for apply."
}
```

Response (200):
```json
{
  "reviewId": "uuid-review-2",
  "proposalId": "uuid-proposal",
  "decision": "approved",
  "reviewerUserId": "user-carol-uuid",
  "reviewerName": "Carol",
  "comment": "Looks good. Approved for apply.",
  "approvedAt": "2026-06-14T11:20:00Z",
  "proposalStatus": "approved"
}
```

**POST /api/v1/ai/collaborations/{courseId}/reviews/{proposalId}/reject**
Reject a pending proposal with required reason.

Request:
```json
{
  "reason": "This change would duplicate the content on page 3. Please consolidate.",
  "requestChanges": "Merge the new content with the existing page 3 summary."
}
```

Response (200):
```json
{
  "reviewId": "uuid-review-3",
  "proposalId": "uuid-proposal",
  "decision": "rejected",
  "reviewerUserId": "user-alice-uuid",
  "reviewerName": "Alice",
  "reason": "This change would duplicate the content on page 3. Please consolidate.",
  "requestedChanges": "Merge the new content with the existing page 3 summary.",
  "rejectedAt": "2026-06-14T11:25:00Z",
  "proposalStatus": "rejected"
}
```

**POST /api/v1/ai/collaborations/{courseId}/reviews/{proposalId}/request-changes**
Request changes on a pending proposal (soft rejection with guidance).

Request:
```json
{
  "comment": "Please add a concrete example after the second paragraph."
}
```

Response (200):
```json
{
  "reviewId": "uuid-review-4",
  "decision": "changes_requested",
  "comment": "Please add a concrete example after the second paragraph.",
  "createdAt": "2026-06-14T11:30:00Z"
}
```

**POST /api/v1/ai/collaborations/{courseId}/reviews/{proposalId}/revise**
Submit a revised version of a previously rejected or changes-requested proposal. Original author only.

Request:
```json
{
  "revisedPatch": {
    "title": "Getting Started",
    "data": {
      "content": "New content with example..."
    }
  },
  "respondsToReviewId": "uuid-review-4",
  "changeNote": "Added concrete example as requested."
}
```

Response (200):
```json
{
  "proposalId": "uuid-proposal",
  "status": "pending",
  "revisionNumber": 2,
  "updatedDiff": { "...": "..." },
  "respondsToReviewId": "uuid-review-4"
}
```

#### 2.3 Activity Feed API

**GET /api/v1/ai/collaborations/{courseId}/activity**
Get the activity feed for a collaborative course.

Query parameters: `?since=2026-06-14T10:00:00Z&limit=50&offset=0&event_types=collaborator_joined,proposal_created`

Response (200):
```json
{
  "courseId": "course-C1",
  "activities": [
    {
      "activityId": "uuid-activity-1",
      "eventType": "proposal_applied",
      "userId": "user-bob-uuid",
      "userName": "Bob",
      "role": "editor",
      "pageId": "P42",
      "pageTitle": "Introduction",
      "description": "Bob applied proposal to update 'Introduction' (approved by Carol)",
      "metadata": {
        "proposalId": "uuid-proposal",
        "approverUserId": "user-carol-uuid",
        "approverName": "Carol"
      },
      "occurredAt": "2026-06-14T11:35:00Z"
    },
    {
      "activityId": "uuid-activity-2",
      "eventType": "proposal_approved",
      "userId": "user-carol-uuid",
      "userName": "Carol",
      "role": "reviewer",
      "pageId": "P42",
      "pageTitle": "Introduction",
      "description": "Carol approved Bob's proposal to update 'Introduction'",
      "metadata": {
        "proposalId": "uuid-proposal",
        "targetUserId": "user-bob-uuid",
        "targetName": "Bob"
      },
      "occurredAt": "2026-06-14T11:20:00Z"
    },
    {
      "activityId": "uuid-activity-3",
      "eventType": "collaborator_joined",
      "userId": "user-bob-uuid",
      "userName": "Bob",
      "role": "editor",
      "description": "Bob joined as editor",
      "occurredAt": "2026-06-14T10:45:00Z"
    }
  ],
  "total": 3,
  "limit": 50,
  "hasMore": false
}
```

#### 2.4 Collaboration-Aware Session Creation (Modification to US-AI-006)

**POST /api/v1/ai/sessions** -- Modified to support collaborative courses.

Request (NEW field: `collaborationMode`):
```json
{
  "userId": "user-bob-uuid",
  "courseId": "course-C1",
  "organizationId": "org-1",
  "collaborationMode": "auto"
}
```

Response (200) -- Modified to include collaboration info:
```json
{
  "sessionId": "uuid-session-S-B",
  "userId": "user-bob-uuid",
  "courseId": "course-C1",
  "expiresAt": "2026-06-15T10:30:00Z",
  "collaboration": {
    "enabled": true,
    "role": "editor",
    "courseOwnerName": "Alice",
    "activeCollaboratorCount": 2,
    "pendingReviewCount": 1,
    "recentActivityCount": 15
  },
  "activeLocks": [
    {
      "pageId": "P1",
      "pageTitle": "Introduction",
      "heldBy": "Alice",
      "lockType": "write",
      "ttlSecondsRemaining": 600
    }
  ]
}
```

#### 2.5 Collaboration Configuration API

**GET /api/v1/ai/collaborations/config**
Get collaboration configuration for the current organization.

Response (200):
```json
{
  "collaborationEnabled": true,
  "maxCollaboratorsPerCourse": 10,
  "editorAutoApplyAllowed": false,
  "reviewRequiredForEditors": true,
  "invitationTtlHours": 72,
  "activityFeedRetentionDays": 90,
  "canOwnerOverrideReview": true
}
```

**PUT /api/v1/ai/collaborations/config**
Update collaboration configuration. Admin only.

Request:
```json
{
  "collaborationEnabled": true,
  "maxCollaboratorsPerCourse": 20,
  "editorAutoApplyAllowed": false,
  "reviewRequiredForEditors": true
}
```

Response (200):
```json
{
  "status": "updated",
  "updatedFields": ["maxCollaboratorsPerCourse"]
}
```

### Database Schema DDL

#### New Table: `ai_course_collaborators`

```sql
CREATE TABLE ai_course_collaborators (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id               VARCHAR(64) NOT NULL,
    organization_id         UUID NOT NULL,
    user_id                 UUID NOT NULL,
    role                    VARCHAR(16) NOT NULL CHECK (role IN ('owner', 'editor', 'reviewer', 'viewer')),
    invited_by_user_id      UUID,
    joined_at               TIMESTAMPTZ,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    last_activity_at        TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_collaborator_course_user UNIQUE (course_id, user_id),
    CONSTRAINT chk_single_owner CHECK (
        NOT (role = 'owner' AND EXISTS (
            SELECT 1 FROM ai_course_collaborators AS cc
            WHERE cc.course_id = course_id AND cc.role = 'owner' AND cc.is_active = TRUE
            AND cc.id != id
        ))
    )
);

CREATE INDEX idx_ai_collaborators_course ON ai_course_collaborators(course_id, is_active);
CREATE INDEX idx_ai_collaborators_user ON ai_course_collaborators(user_id, is_active);
CREATE INDEX idx_ai_collaborators_role ON ai_course_collaborators(course_id, role);
```

#### New Table: `ai_collaboration_invitations`

```sql
CREATE TABLE ai_collaboration_invitations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id           VARCHAR(64) NOT NULL,
    organization_id     UUID NOT NULL,
    invitee_email       VARCHAR(255) NOT NULL,
    invitee_user_id     UUID,  -- Set when the user accepts
    invited_by_user_id  UUID NOT NULL,
    role                VARCHAR(16) NOT NULL CHECK (role IN ('editor', 'reviewer', 'viewer')),
    message             TEXT,
    status              VARCHAR(16) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted', 'declined', 'expired', 'cancelled')),
    expires_at          TIMESTAMPTZ NOT NULL,
    accepted_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_invitations_email ON ai_collaboration_invitations(invitee_email, status);
CREATE INDEX idx_ai_invitations_course ON ai_collaboration_invitations(course_id, status);
```

#### New Table: `ai_collaboration_activity`

```sql
CREATE TABLE ai_collaboration_activity (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id           VARCHAR(64) NOT NULL,
    organization_id     UUID NOT NULL,
    event_type          VARCHAR(64) NOT NULL,
    user_id             UUID NOT NULL,
    user_name           VARCHAR(255),
    user_role           VARCHAR(16),
    page_id             VARCHAR(64),
    page_title          VARCHAR(255),
    proposal_id         UUID,
    related_user_id     UUID,
    related_user_name   VARCHAR(255),
    description         TEXT NOT NULL,
    metadata            JSONB DEFAULT '{}'::jsonb,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_activity_course FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE
);

CREATE INDEX idx_ai_activity_course_time ON ai_collaboration_activity(course_id, occurred_at DESC);
CREATE INDEX idx_ai_activity_event_type ON ai_collaboration_activity(course_id, event_type);
CREATE INDEX idx_ai_activity_user ON ai_collaboration_activity(user_id);
-- Partition by month for retention management; drop old partitions after retention_days
```

#### New Table: `ai_collaboration_config` (per-organization)

```sql
CREATE TABLE ai_collaboration_config (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id             UUID NOT NULL UNIQUE,
    collaboration_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
    max_collaborators_per_course INTEGER NOT NULL DEFAULT 10,
    editor_auto_apply_allowed   BOOLEAN NOT NULL DEFAULT FALSE,
    review_required_for_editors BOOLEAN NOT NULL DEFAULT TRUE,
    invitation_ttl_hours        INTEGER NOT NULL DEFAULT 72,
    activity_feed_retention_days INTEGER NOT NULL DEFAULT 90,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### Modifications to Existing Tables

**`ai_proposals` table (from US-AI-004):**
```sql
ALTER TABLE ai_proposals ADD COLUMN collaborator_id UUID;
ALTER TABLE ai_proposals ADD COLUMN collaborator_name VARCHAR(255);
ALTER TABLE ai_proposals ADD COLUMN review_status VARCHAR(16) DEFAULT 'none'
    CHECK (review_status IN ('none', 'pending', 'approved', 'rejected', 'changes_requested'));
ALTER TABLE ai_proposals ADD COLUMN review_decision_by UUID;
ALTER TABLE ai_proposals ADD COLUMN review_decision_at TIMESTAMPTZ;
ALTER TABLE ai_proposals ADD COLUMN review_comment TEXT;
ALTER TABLE ai_proposals ADD COLUMN revision_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE ai_proposals ADD COLUMN base_snapshot_hash VARCHAR(64);  -- For semantic conflict detection
```

**`ai_review_comments` table (new, supporting FR-005):**
```sql
CREATE TABLE ai_review_comments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     UUID NOT NULL REFERENCES ai_proposals(id) ON DELETE CASCADE,
    reviewer_id     UUID NOT NULL,
    reviewer_name   VARCHAR(255),
    decision        VARCHAR(16) NOT NULL CHECK (decision IN ('approved', 'rejected', 'changes_requested', 'comment')),
    comment         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_review_comments_proposal ON ai_review_comments(proposal_id, created_at);
```

**`ai_sessions` table (from US-AI-006):**
```sql
ALTER TABLE ai_sessions ADD COLUMN collaboration_role VARCHAR(16);
ALTER TABLE ai_sessions ADD COLUMN session_label VARCHAR(255);  -- Optional user-set label like "Bob's editing session"
```

**`ai_locks` table (from US-AI-043):**
```sql
ALTER TABLE ai_locks ADD COLUMN collaborator_role VARCHAR(16);
-- The SESSION lock on course is now conditional: if collaboration is enabled, multiple sessions allowed.
-- Add flag to distinguish collaborative vs exclusive session lock:
ALTER TABLE ai_locks ADD COLUMN is_collaborative BOOLEAN NOT NULL DEFAULT FALSE;
```

**`ai_audit_logs` table (from US-AI-004):**
```sql
ALTER TABLE ai_audit_logs ADD COLUMN collaborator_id UUID;
ALTER TABLE ai_audit_logs ADD COLUMN collaborator_role VARCHAR(16);
ALTER TABLE ai_audit_logs ADD COLUMN related_collaborator_id UUID;
ALTER TABLE ai_audit_logs ADD COLUMN collaboration_event_type VARCHAR(64);
```

### Service / Module Design

#### Module: `app/services/ai/collaboration_service.py`

```python
"""
Collaboration Service

Manages multi-user collaboration on AI-authored courses.
Handles collaborator management, invitations, proposal review workflows,
activity feeds, role-based permissions, and semantic conflict detection.
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import uuid

from sqlalchemy.ext.asyncio import AsyncSession


class CollaboratorRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    COMMENT = "comment"


class ActivityEventType(str, Enum):
    COLLABORATOR_JOINED = "collaborator_joined"
    COLLABORATOR_LEFT = "collaborator_left"
    COLLABORATOR_REMOVED = "collaborator_removed"
    COLLABORATOR_INVITED = "collaborator_invited"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    PAGE_LOCKED = "page_locked"
    PAGE_UNLOCKED = "page_unlocked"
    PROPOSAL_CREATED = "proposal_created"
    PROPOSAL_REVISED = "proposal_revised"
    PROPOSAL_APPROVED = "proposal_approved"
    PROPOSAL_REJECTED = "proposal_rejected"
    PROPOSAL_CHANGES_REQUESTED = "proposal_changes_requested"
    PROPOSAL_APPLIED = "proposal_applied"
    PROPOSAL_WITHDRAWN = "proposal_withdrawn"
    CONFLICT_DETECTED = "conflict_detected"
    LOCK_RELEASED_BY_OWNER = "lock_released_by_owner"
    COURSE_PUBLISHED = "course_published"


class CollaborationService:
    """
    CollaborationService is the central service for multi-user collaboration.

    Responsibilities:
    1. Manage course collaborators (add, remove, list, role management).
    2. Handle invitations (create, accept, decline, expire).
    3. Enforce role-based permissions for AI authoring operations.
    4. Manage proposal review workflows (approve, reject, request changes).
    5. Maintain and serve the real-time activity feed.
    6. Detect semantic conflicts between concurrent proposals.
    7. Integrate with the LockManager (US-AI-043) for collaboration-aware locking.
    """

    def __init__(self, db_session: AsyncSession, lock_manager=None):
        self.db = db_session
        self.lock_manager = lock_manager  # US-AI-043 LockManager instance

    async def is_collaboration_enabled(self, course_id: str, organization_id: str) -> bool:
        """Check if collaboration is enabled for this course/organization."""
        ...

    async def get_user_role(self, course_id: str, user_id: str) -> Optional[CollaboratorRole]:
        """Get the user's role in this course, or None if not a collaborator."""
        ...

    async def check_permission(
        self, course_id: str, user_id: str, required_role: CollaboratorRole
    ) -> bool:
        """Check if a user has at least the required role level.
        
        Hierarchy: owner > editor > reviewer > viewer
        Returns True if the user's role is >= required_role.
        """
        ...

    async def add_collaborator(
        self,
        course_id: str,
        owner_user_id: str,
        invitee_email: str,
        role: CollaboratorRole,
        message: Optional[str] = None,
        ttl_hours: int = 72,
    ) -> dict:
        """
        Create a collaboration invitation. Validates:
        - Inviter is the course owner.
        - Invitee is not already a collaborator.
        - Max collaborators not reached.
        - Role is not 'owner' (only one owner per course).
        Returns the invitation record.
        """
        ...

    async def accept_invitation(
        self, invitation_id: str, user_id: str, user_email: str
    ) -> dict:
        """
        Accept a collaboration invitation. Validates:
        - Invitation status is 'pending'.
        - Invitation has not expired.
        - Authenticated user email matches invitee_email.
        Creates ai_course_collaborators record.
        Writes COLLABORATOR_JOINED activity event.
        """
        ...

    async def remove_collaborator(
        self,
        course_id: str,
        owner_user_id: str,
        collaborator_user_id: str,
        reason: str,
    ) -> dict:
        """
        Remove a collaborator from the course. Owner only.
        Releases any active locks held by the removed user on this course.
        Invalidates any pending proposals by the removed user.
        Writes COLLABORATOR_REMOVED activity event.
        """
        ...

    async def list_collaborators(
        self, course_id: str, requesting_user_id: str
    ) -> List[dict]:
        """List all collaborators with roles, active session status, and lock counts."""
        ...

    async def get_pending_reviews(
        self,
        course_id: str,
        reviewer_user_id: str,
        page_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[dict], int]:
        """
        Get all proposals pending review for this course.
        Only accessible by owner and reviewers.
        Filters by page_id if provided.
        """
        ...

    async def approve_proposal(
        self,
        course_id: str,
        proposal_id: str,
        reviewer_user_id: str,
        reviewer_name: str,
        comment: Optional[str] = None,
    ) -> dict:
        """
        Approve a pending proposal. Owner or reviewer only.
        Sets review_status = 'approved'.
        Records review decision in ai_review_comments.
        Notifies the original proposer via their session.
        Writes PROPOSAL_APPROVED activity event.
        """
        ...

    async def reject_proposal(
        self,
        course_id: str,
        proposal_id: str,
        reviewer_user_id: str,
        reviewer_name: str,
        reason: str,
        requested_changes: Optional[str] = None,
    ) -> dict:
        """
        Reject a pending proposal with required reason.
        Sets review_status = 'rejected'.
        Notifies the original proposer with the rejection reason.
        """
        ...

    async def request_changes(
        self,
        course_id: str,
        proposal_id: str,
        reviewer_user_id: str,
        reviewer_name: str,
        comment: str,
    ) -> dict:
        """
        Request changes on a proposal (soft rejection).
        Sets review_status = 'changes_requested'.
        The original author can submit a revision via revise_proposal().
        """
        ...

    async def revise_proposal(
        self,
        course_id: str,
        proposal_id: str,
        author_user_id: str,
        revised_patch: dict,
        responds_to_review_id: str,
        change_note: Optional[str] = None,
    ) -> dict:
        """
        Submit a revised version of a proposal after changes were requested.
        Increments revision_number.
        Resets review_status to 'pending' for re-review.
        Writes PROPOSAL_REVISED activity event.
        """
        ...

    async def record_activity(
        self,
        course_id: str,
        organization_id: str,
        event_type: ActivityEventType,
        user_id: str,
        user_name: Optional[str] = None,
        user_role: Optional[str] = None,
        page_id: Optional[str] = None,
        page_title: Optional[str] = None,
        proposal_id: Optional[str] = None,
        related_user_id: Optional[str] = None,
        related_user_name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Record an activity event in the activity feed.
        Asynchronously written (fire-and-forget in the same transaction
        as the triggering operation for consistency).
        """
        ...

    async def get_activity_feed(
        self,
        course_id: str,
        user_id: str,
        since: Optional[datetime] = None,
        event_types: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[dict], int, bool]:
        """
        Get the activity feed for a course.
        Accessible by owner, editors, and reviewers.
        Returns activities sorted by occurred_at DESC.
        """
        ...

    async def detect_semantic_conflict(
        self,
        course_id: str,
        proposal_id: str,
        page_id: str,
        base_snapshot_hash: str,
    ) -> Optional[dict]:
        """
        Detect semantic conflicts between the given proposal and other
        pending proposals on related pages.

        Compares base_snapshot_hash of this proposal against:
        1. The current page snapshot hash in the database.
        2. Base snapshot hashes of other pending proposals on the same page.

        Returns conflict details if a conflict is detected, None otherwise.
        """
        ...

    async def resolve_conflict(
        self,
        course_id: str,
        conflict_id: str,
        resolving_user_id: str,
        resolution: str,  # 'overwrite', 'wait', 'escalate'
    ) -> dict:
        """
        Resolve a detected semantic conflict.
        - 'overwrite': Proceed with last-writer-wins; notify the other collaborator.
        - 'wait': The current user defers; retry logic on the frontend.
        - 'escalate': Notify the course owner for manual resolution.
        Writes CONFLICT_DETECTED and resolution activity events.
        """
        ...

    async def get_or_create_collaboration_config(
        self, organization_id: str
    ) -> "CollaborationConfig":
        """Get or create collaboration configuration for an organization."""
        ...

    async def update_collaboration_config(
        self, organization_id: str, config: "CollaborationConfig"
    ) -> "CollaborationConfig":
        """Update collaboration configuration for an organization."""
        ...

    async def cleanup_expired_invitations(self) -> int:
        """
        Background task: mark invitations with expires_at < now()
        as status = 'expired'. Runs every 15 minutes.
        """
        ...

    async def cleanup_old_activity(self, retention_days: int = 90) -> int:
        """
        Background task: delete activity records older than retention_days.
        Runs daily. Uses partition drop if the table is partitioned by month.
        """
        ...


@dataclass
class CollaborationConfig:
    """Per-organization collaboration configuration."""

    collaboration_enabled: bool = False
    max_collaborators_per_course: int = 10
    editor_auto_apply_allowed: bool = False
    review_required_for_editors: bool = True
    invitation_ttl_hours: int = 72
    activity_feed_retention_days: int = 90
```

#### Module: `app/services/ai/collaboration_middleware.py`

```python
"""
Collaboration Middleware

Decorators and dependencies for enforcing role-based permissions
on AI tool endpoints in collaborative courses.
"""
from __future__ import annotations
from functools import wraps
from typing import Callable, Optional

from app.services.ai.collaboration_service import (
    CollaborationService,
    CollaboratorRole,
)


def require_collaborator_role(required_role: CollaboratorRole):
    """
    Decorator for tool handler functions that require a minimum
    collaborator role in a collaborative course.

    Usage:
        @router.post("/ai/tools/propose_update_page")
        @require_collaborator_role(CollaboratorRole.EDITOR)
        async def propose_update_page(...):
            ...

    Checks:
    1. Is collaboration enabled for the course? (config check)
    2. If yes, is the user a collaborator with >= required_role?
    3. If no, falls back to US-AI-006 single-user session behavior.
    """
    ...


def with_review_access():
    """
    Decorator for proposal review endpoints. Ensures the requesting
    user is the course owner or has reviewer role.
    """
    ...


def with_owner_access():
    """
    Decorator for collaborator management endpoints.
    Ensures the requesting user is the course owner.
    """
    ...
```

#### Module: `app/services/ai/collaboration_notifier.py`

```python
"""
Collaboration Notifier

Handles real-time notifications for collaboration events.
Uses the event outbox (US-AI-033) to deliver notifications
to active sessions via polling endpoints.

For real-time delivery, future enhancement could use WebSocket or SSE.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime

from app.services.ai.collaboration_service import ActivityEventType


class CollaborationNotifier:
    """
    Manages notifications for collaboration events.

    Current implementation: outbox-based polling.
    Future: WebSocket push for real-time delivery.

    Notification types:
    - proposal_pending_review: "Bob proposed updating 'Introduction'"
    - proposal_approved: "Your proposal was approved by Carol"
    - proposal_rejected: "Your proposal was rejected by Alice: reason"
    - changes_requested: "Carol requested changes on your proposal"
    - lock_released: "The lock on 'Introduction' has been released"
    - conflict_detected: "Your proposal conflicts with Bob's changes"
    - collaborator_joined: "Bob joined as editor"
    """

    def __init__(self, db_session):
        self.db = db_session

    async def notify_user(
        self,
        user_id: str,
        course_id: str,
        notification_type: str,
        title: str,
        body: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Create a notification for a specific user.
        Stored in memory for active sessions, or in the outbox for offline users.
        Returns the notification ID.
        """
        ...

    async def get_pending_notifications(
        self, user_id: str, course_id: str, since: Optional[datetime] = None
    ) -> list:
        """
        Get pending notifications for a user in a course.
        Called by the frontend polling endpoint.
        """
        ...

    async def mark_read(self, notification_id: str, user_id: str) -> bool:
        """Mark a notification as read."""
        ...
```

#### Integration: Lock Manager (US-AI-043)

The `LockManager` from US-AI-043 MUST be modified to support collaborative mode:

1. **Session Lock Relaxation:** When `collaboration_service.is_collaboration_enabled(course_id)` returns True, the `acquire_lock(SESSION, COURSE, courseId)` method SHALL allow multiple concurrent SESSION locks on the same course (one per collaborator). The `is_collaborative` flag on the lock record distinguishes collaborative sessions.

2. **Lock Metadata:** When a lock is acquired by a collaborator, the `collaborator_role` field is populated from the user's role on the course. This role is included in lock conflict responses so the UI can display role badges.

3. **Owner Lock Override:** The `force_release_by_admin` method SHALL also be callable by the course owner for any lock on their course, with `release_reason = 'COLLABORATOR_REMOVED'` or `'LOCK_RELEASED_BY_OWNER'`. Owner force-release does not require the `X-Admin-Override` header, only proof of course ownership.

#### Integration: Proposal Lifecycle (US-AI-009 / US-AI-010)

The proposal lifecycle MUST be modified:

1. **Review Gating:** After `propose_*` creates a proposal, if the session's `collaboration_role` is `editor` and `review_required_for_editors` is True, the proposal is created with `review_status = 'pending'`. The `apply_*` endpoints MUST check `review_status` and reject with `REVIEW_REQUIRED` if the proposal has not been approved.

2. **Owner Auto-Apply:** If the session's `collaboration_role` is `owner`, proposals are created with `review_status = 'none'` and can be applied immediately (existing behavior).

3. **Editor Auto-Apply (Low Risk):** If `editor_auto_apply_allowed` is True and the risk score (US-AI-032 policy engine) is below threshold, editor proposals are auto-applied. The policy engine is consulted during the proposal lifecycle.

#### Integration: Activity Feed with Outbox (US-AI-033)

Activity events SHALL be written to `ai_collaboration_activity` table in the same database transaction as the triggering operation. For events that need to reach frontend in real-time, a dedicated outbox event type `CollaborationActivity` is emitted via US-AI-033's outbox mechanism.

### Configuration Variables

```python
# In app/core/config.py or environment variables:

# Collaboration feature toggle (supplements feature flag)
AI_COLLABORATION_ENABLED: bool = False
AI_COLLABORATION_MAX_PER_COURSE: int = 10
AI_COLLABORATION_EDITOR_AUTO_APPLY: bool = False
AI_COLLABORATION_REVIEW_REQUIRED: bool = True
AI_COLLABORATION_INVITATION_TTL_HOURS: int = 72
AI_COLLABORATION_ACTIVITY_RETENTION_DAYS: int = 90
AI_COLLABORATION_FEED_POLL_INTERVAL_SECONDS: int = 10
AI_COLLABORATION_CONFLICT_RETRY_INTERVAL_SECONDS: int = 30
```

### Integration Points

| Integration | Description | Status |
|---|---|---|
| US-AI-006 (Session Creation) | Add `collaborationMode` field; relax SESSION lock for collaborative courses; return collaboration metadata in session response | Modify |
| US-AI-043 (Concurrency Control) | Support multiple SESSION locks per course when collaboration enabled; add `is_collaborative` and `collaborator_role` to lock records; owner lock override | Modify |
| US-AI-009 (Proposal Lifecycle) | Add `collaborator_id`, `review_status`, `revision_number` to proposals; gate apply on review approval | Modify |
| US-AI-010 (Apply Safety) | Check `review_status` before allowing apply; check collaborator role for apply permission | Modify |
| US-AI-032 (Policy Engine) | Consult policy engine for editor auto-apply decisions; add collaboration risk rules | Modify |
| US-AI-033 (Event Outbox) | Emit `CollaborationActivity` events for real-time feed delivery | New |
| US-AI-024 (Frontend AI Layer) | Add Collaborators Panel, Activity Feed, Proposal Review Dialog, Conflict Resolution Dialog, Invitation UI | New |
| Feature Flags | Gate collaboration behind existing `collaboration` feature flag | Existing |
| US-AI-004 (AI Persistence) | Add new tables and modify existing tables as specified in DDL | Modify |

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### Performance Targets

- Activity feed query (`GET /api/v1/ai/collaborations/{courseId}/activity`) MUST return in under 100 milliseconds p95 for feeds with up to 500 events.
- Activity feed ingestion (writing an event) MUST add no more than 5 milliseconds overhead to the triggering operation.
- Collaborator list query MUST return in under 50 milliseconds p95 for courses with up to 50 collaborators.
- Pending reviews query MUST return in under 100 milliseconds p95 for up to 200 pending proposals.
- Semantic conflict detection MUST complete in under 50 milliseconds per proposal.
- Invitation creation and acceptance MUST complete in under 200 milliseconds p95.
- The collaboration service MUST NOT add more than 10 milliseconds overhead to any existing tool call when collaboration is disabled for the course.

### Security Requirements

- All collaboration endpoints MUST authenticate the requesting user via the existing `Authorization: Session {sessionId}` header.
- Role-based access control MUST be enforced server-side for every collaboration operation. The frontend may hide UI elements based on role, but the backend MUST independently verify permissions.
- Invitation acceptance MUST verify that the authenticated user's email matches the `invitee_email` on the invitation record. If the user is authenticated via SSO, the email claim MUST be trusted.
- When a collaborator is removed from a course, the system MUST immediately invalidate their active session (if any), release their locks, and invalidate their pending proposals. The session expiry SHALL be triggered asynchronously within 30 seconds.
- Activity feed visibility MUST respect the user's role: viewers see only non-sensitive events (proposal applied, course published); editors and above see all events.
- Cross-organization isolation MUST be enforced: collaboration data for Organization A MUST NOT be visible to users in Organization B, even if the same course ID exists in both orgs.
- Invitation links MUST contain a cryptographically random token (not just the invitation UUID) to prevent enumeration attacks.

### Reliability Requirements

- Collaboration state (who is a collaborator, their role, pending reviews) MUST survive backend restarts. All data is persisted in PostgreSQL.
- The invitation expiry checker background task MUST run every 15 minutes to mark expired invitations.
- The activity feed cleanup task MUST run daily to remove records older than the retention period.
- If the CollaborationService is temporarily unavailable, existing non-collaborative AI authoring MUST continue to function without degradation.
- If a user's session expires while they have pending proposals, those proposals MUST remain in the database and be visible to reviewers. The proposals SHALL be associated with the user's ID, not the session ID, for durability.

### Scalability Requirements

- The collaboration system MUST support up to 50 collaborators per course and up to 500 courses with collaboration enabled across an organization.
- The activity feed MUST support up to 10,000 events per course before performance degradation. Partitioning by month is recommended for courses exceeding this threshold.
- The pending reviews system MUST support up to 200 concurrent pending proposals per course.
- The collaboration system MUST handle up to 1,000 concurrent collaboration session pairs (2,000 total sessions) across the platform.

---

## 4. CURRENT STATE ASSESSMENT

### What Exists

1. **US-AI-006 (Session Creation):** Creates single-user, single-course AI sessions. No concept of course ownership, collaboration, or multi-session-per-course support. Sessions are strictly one-per-course due to the SESSION lock mechanism planned in US-AI-043.

2. **US-AI-043 (Concurrency Control):** Defines page-level WRITE/READ locks and course-level SESSION locks. The SESSION lock currently prevents any second session on the same course. No support for multiple simultaneous sessions from different collaborators. Lock conflict responses do not include collaborator role information.

3. **Feature Flag (`collaboration`):** The `FeatureFlagService` in `app/utils/feature_flags.py` already has a `collaboration` flag (default disabled) with environments `[QA, STAGING, PRODUCTION]`. No code behind this flag exists yet.

4. **Social/Collaborative Models (`app/models/social.py`):** The existing social models cover student-facing collaboration (discussions, peer reviews, polls, teams) but do not cover author-facing AI collaboration. These are separate domains.

5. **`CourseRecord` / `Course` Pydantic Model:** The course model has a single `author` field (string). No concept of multiple authors, collaborators, or roles. The `course_id` is used as the scoping identifier for sessions and proposals.

6. **User/Organization Models:** The codebase does not contain explicit User or Organization ORM models visible in the `app/models/` directory. User identity appears to be represented as string UUIDs passed from the frontend or authentication layer. For this story, we assume a `users` table exists with at minimum `user_id` (UUID), `email` (varchar), and `name` (varchar). If no users table exists, the collaboration system will track users by opaque `user_id` strings with a separate `user_name` lookup mechanism (configurable per deployment).

7. **Proposal Lifecycle (US-AI-009, US-AI-010):** Proposals currently have no concept of ownership beyond being tied to a session. There is no review workflow, no approval status, and no multi-user visibility. After apply, proposals are considered consumed.

8. **Proposal Apply (US-AI-010):** The apply pipeline currently checks base_hash for staleness but does not check collaborator role or review approval status before allowing apply.

### What Must Be Built

1. **Four new database tables:** `ai_course_collaborators`, `ai_collaboration_invitations`, `ai_collaboration_activity`, `ai_collaboration_config`, `ai_review_comments` (DDL provided in Section 2).

2. **Collaboration Service** (`app/services/ai/collaboration_service.py`): Full implementation with collaborator CRUD, invitation management, proposal review workflow, activity feed management, semantic conflict detection, and configuration management.

3. **Collaboration Middleware** (`app/services/ai/collaboration_middleware.py`): Decorators for role-based access control on tool endpoints.

4. **Collaboration Notifier** (`app/services/ai/collaboration_notifier.py`): Notification management for pending reviews, approvals, rejections, and conflict notifications.

5. **Collaboration API routes:** Invitation management, collaborator management, proposal review, activity feed, configuration endpoints.

6. **Cleanup background tasks:** Expired invitation cleanup (every 15 min), old activity feed cleanup (daily).

7. **Frontend components:** Collaborators Panel, Invitation Dialog, Activity Feed Panel, Proposal Review Dialog, Conflict Resolution Dialog, Collaboration Configuration UI.

### What Must Be Modified

1. **`ai_sessions` table** -- add `collaboration_role` and `session_label` columns.
2. **`ai_proposals` table** -- add `collaborator_id`, `collaborator_name`, `review_status`, `review_decision_by`, `review_decision_at`, `review_comment`, `revision_number`, `base_snapshot_hash` columns.
3. **`ai_locks` table** -- add `collaborator_role` and `is_collaborative` columns (from US-AI-043).
4. **`ai_audit_logs` table** -- add collaborator-related audit columns.
5. **`POST /api/v1/ai/sessions`** -- accept `collaborationMode` parameter; if collaboration enabled, relax SESSION lock; return collaboration metadata.
6. **`LockManager.acquire_lock` (US-AI-043)** -- allow multiple SESSION locks on same course when collaboration enabled.
7. **`LockManager.force_release_by_admin`** -- also allow course owner to force-release locks without `X-Admin-Override`.
8. **All `propose_*` tool handlers** -- attach `collaborator_id` and `review_status` to proposals; trigger review workflow for editors.
9. **All `apply_*` tool handlers** -- check `review_status` before allowing apply; check collaborator role for apply permission.
10. **Policy Engine (US-AI-032)** -- add collaboration risk rules for editor auto-apply decisions.
11. **Event Outbox (US-AI-033)** -- add `CollaborationActivity` event type for real-time feed push.
12. **Frontend AI Integration Layer (US-AI-024)** -- add collaboration UI components and polling.
13. **Feature Flag Service** -- wire the existing `collaboration` flag to the new collaboration endpoints.

---

## 5. EXPANSION POINTS

### Technical Expansion Points

**TXP-01 -- Real-Time WebSocket/SSE Activity Feed:** Replace the polling-based activity feed (every 10 seconds) with a WebSocket or Server-Sent Events (SSE) connection for sub-second delivery of collaboration events. Each active session subscribes to the course's activity channel. The backend pushes events as they occur, eliminating polling overhead and reducing latency from ~10 seconds to ~500 milliseconds. This requires a lightweight pub/sub mechanism (Redis Pub/Sub, Postgres LISTEN/NOTIFY, or in-process asyncio queues for single-instance deployments).

**TXP-02 -- External User Directory Integration:** Replace the email-based invitation flow with integration to an external user directory (LDAP, Azure AD, Okta) for user search and auto-provisioning. Collaborators could be selected from a directory search rather than manually entered by email. This requires a `UserDirectoryProvider` abstract interface with implementations for different directory backends.

**TXP-03 -- Activity Feed Elasticsearch/OpenSearch Indexing:** For organizations with very high collaboration activity (100,000+ events per course), move the activity feed from PostgreSQL to Elasticsearch or OpenSearch for faster full-text search, filtering, and aggregation. The `ai_collaboration_activity` table becomes a write-only log, with an indexer consuming outbox events to populate the search index. Activity feed queries then hit the search index instead of the database.

**TXP-04 -- Proposal Review SLA Enforcement:** Add configurable SLA targets for proposal review (e.g., "All editor proposals must be reviewed within 4 business hours"). If a proposal remains in `pending` status beyond the SLA, automatic escalation occurs: the proposal is surfaced to the course owner, and if still unreviewed, to the organization admin. SLA breach events are logged and visible in the admin dashboard.

### Functional Expansion Points

**FXP-01 -- Asynchronous Review Notifications (Email/Digest):** When a collaborator is offline and receives a pending review notification or a proposal approval, send an email digest (or instant email for priority events). Configurable per user: "Notify me immediately when X happens" vs. "Send daily digest of collaboration activity." This extends the `CollaborationNotifier` to support email delivery alongside in-session polling.

**FXP-02 -- Collaborative Page Editing (Component-Level):** Extend collaboration from page-level WRITE locks (US-AI-043) to component-level locks within a page. Two editors could simultaneously edit different components on the same page (e.g., one edits the text content while the other edits the assessment). This requires changes to the proposal system to scope proposals to individual components, and changes to the lock manager to support component-level resources.

**FXP-03 -- Proposal Merge and Squash Workflow:** Allow a reviewer or owner to combine multiple pending proposals from different collaborators into a single batch proposal. For example, if Bob and Carol both have approved proposals on different pages, the owner could create a batch "Release v1.2" that applies both proposals atomically. This extends the batch proposal concept from US-AI-029 with merge capabilities.

**FXP-04 -- Collaboration Templates and Presets:** Allow organizations to define collaboration templates that pre-configure roles, permissions, and review requirements for common workflows. Example presets: "Peer Review" (all editors require review), "Rapid Prototyping" (editors auto-apply, no review), "Client Review" (external viewer role for stakeholders). Templates are selectable when enabling collaboration on a course.

**FXP-05 -- Lock Ownership Transfer:** Allow a collaborator who holds a WRITE lock to transfer it to another collaborator. For example, if Alice is stuck on page 3 and Bob is free, Alice can transfer her lock to Bob so he can continue without waiting for the lock to expire. The transfer requires the receiving collaborator to accept. This extends the lock manager's `release_lock` and `acquire_lock` flow with an atomic transfer operation.

---

## 6. VALIDATION AND TESTING

### Unit Tests (5+)

**UT-01 -- Collaboration Invitation Lifecycle:**
Test that an invitation can be created, accepted, and that duplicate acceptance is prevented.

```python
async def test_invitation_lifecycle(collab_service: CollaborationService, db_session):
    # Create invitation
    invitation = await collab_service.add_collaborator(
        course_id="course-C1",
        owner_user_id="user-alice",
        invitee_email="bob@example.com",
        role=CollaboratorRole.EDITOR,
    )
    assert invitation["status"] == "pending"
    assert invitation["role"] == "editor"
    assert invitation["inviteeEmail"] == "bob@example.com"

    # Accept invitation
    result = await collab_service.accept_invitation(
        invitation_id=invitation["invitationId"],
        user_id="user-bob",
        user_email="bob@example.com",
    )
    assert result["status"] == "accepted"
    assert result["role"] == "editor"

    # Verify collaborator exists
    collabs = await collab_service.list_collaborators("course-C1", "user-alice")
    assert any(c["userId"] == "user-bob" for c in collabs)

    # Attempt duplicate acceptance should fail
    with pytest.raises(ValueError, match="already a collaborator"):
        await collab_service.accept_invitation(
            invitation_id=invitation["invitationId"],
            user_id="user-bob",
            user_email="bob@example.com",
        )
```

**UT-02 -- Role-Based Permission Enforcement:**
Test that role hierarchy is correctly enforced: owner > editor > reviewer > viewer.

```python
async def test_role_permissions(collab_service: CollaborationService, db_session):
    # Set up collaborators
    await collab_service._add_collaborator_direct("course-C1", "user-alice", "owner")
    await collab_service._add_collaborator_direct("course-C1", "user-bob", "editor")
    await collab_service._add_collaborator_direct("course-C1", "user-carol", "reviewer")
    await collab_service._add_collaborator_direct("course-C1", "user-dave", "viewer")

    # Owner can do everything
    assert await collab_service.check_permission("course-C1", "user-alice", CollaboratorRole.OWNER) is True
    assert await collab_service.check_permission("course-C1", "user-alice", CollaboratorRole.EDITOR) is True
    assert await collab_service.check_permission("course-C1", "user-alice", CollaboratorRole.VIEWER) is True

    # Editor has editor privileges but not owner
    assert await collab_service.check_permission("course-C1", "user-bob", CollaboratorRole.EDITOR) is True
    assert await collab_service.check_permission("course-C1", "user-bob", CollaboratorRole.OWNER) is False

    # Reviewer cannot edit
    assert await collab_service.check_permission("course-C1", "user-carol", CollaboratorRole.REVIEWER) is True
    assert await collab_service.check_permission("course-C1", "user-carol", CollaboratorRole.EDITOR) is False

    # Viewer is read-only
    assert await collab_service.check_permission("course-C1", "user-dave", CollaboratorRole.VIEWER) is True
    assert await collab_service.check_permission("course-C1", "user-dave", CollaboratorRole.REVIEWER) is False

    # Non-collaborator gets nothing
    assert await collab_service.get_user_role("course-C1", "user-eve") is None
    assert await collab_service.check_permission("course-C1", "user-eve", CollaboratorRole.VIEWER) is False
```

**UT-03 -- Proposal Review Approve/Reject Cycle:**
Test that an editor's proposal can be reviewed (approved/rejected) and that the proposal status is updated correctly.

```python
async def test_proposal_review_cycle(collab_service: CollaborationService, db_session):
    # Create a proposal with review_status = pending (editor)
    proposal_id = await collab_service._create_test_proposal(
        page_id="P42",
        author_id="user-bob",
        author_role="editor",
        review_status="pending",
    )

    # Approve the proposal
    approval = await collab_service.approve_proposal(
        course_id="course-C1",
        proposal_id=proposal_id,
        reviewer_user_id="user-carol",
        reviewer_name="Carol",
        comment="Looks good!",
    )
    assert approval["decision"] == "approved"
    assert approval["reviewerName"] == "Carol"

    # Verify proposal status
    proposal = await collab_service._get_proposal(proposal_id)
    assert proposal["reviewStatus"] == "approved"
    assert proposal["reviewDecisionBy"] == "user-carol"

    # Verify activity event was recorded
    feed = await collab_service.get_activity_feed("course-C1", "user-bob", limit=10)
    assert any(
        e["eventType"] == "proposal_approved" and e["metadata"]["proposalId"] == proposal_id
        for e in feed[0]
    )
```

**UT-04 -- Semantic Conflict Detection:**
Test that two proposals on the same page with different base hashes trigger a conflict.

```python
async def test_semantic_conflict_detection(collab_service: CollaborationService, db_session):
    # Create first proposal with known base hash
    proposal_1 = await collab_service._create_test_proposal(
        page_id="P42",
        author_id="user-bob",
        author_role="editor",
        base_snapshot_hash="hash-v1",
    )

    # Create second proposal with different base hash (stale)
    proposal_2 = await collab_service._create_test_proposal(
        page_id="P42",
        author_id="user-alice",
        author_role="owner",
        base_snapshot_hash="hash-v0",  # Stale -- current DB hash is hash-v1
    )

    # Detect conflict on the stale proposal
    conflict = await collab_service.detect_semantic_conflict(
        course_id="course-C1",
        proposal_id=proposal_2["proposalId"],
        page_id="P42",
        base_snapshot_hash="hash-v0",
    )
    assert conflict is not None
    assert conflict["conflictType"] == "stale_base_version"
    assert conflict["conflictingProposalId"] == proposal_1["proposalId"]

    # No conflict on the current proposal
    no_conflict = await collab_service.detect_semantic_conflict(
        course_id="course-C1",
        proposal_id=proposal_1["proposalId"],
        page_id="P42",
        base_snapshot_hash="hash-v1",
    )
    assert no_conflict is None
```

**UT-05 -- Collaborator Removal Cleanup:**
Test that removing a collaborator releases their locks and invalidates their proposals.

```python
async def test_collaborator_removal_cleanup(
    collab_service: CollaborationService,
    lock_manager,
    db_session,
):
    # Set up collaborator with active lock and pending proposal
    await collab_service._add_collaborator_direct("course-C1", "user-bob", "editor")
    lock = await lock_manager.acquire_lock(
        lock_type=LockType.WRITE,
        resource_type=ResourceType.PAGE,
        resource_id="P42",
        session_id="session-bob",
        user_id="user-bob",
        organization_id="org-1",
        course_id="course-C1",
    )
    assert lock.acquired is True
    proposal_id = await collab_service._create_test_proposal(
        page_id="P42", author_id="user-bob", author_role="editor", review_status="pending"
    )

    # Remove collaborator
    result = await collab_service.remove_collaborator(
        course_id="course-C1",
        owner_user_id="user-alice",
        collaborator_user_id="user-bob",
        reason="Completed work",
    )
    assert result["releasedLocksCount"] >= 1
    assert result["invalidatedProposalsCount"] >= 1

    # Verify lock is released
    active_lock = await lock_manager.get_active_lock(
        resource_type=ResourceType.PAGE, resource_id="P42"
    )
    assert active_lock is None

    # Verify collaborator is removed
    collabs = await collab_service.list_collaborators("course-C1", "user-alice")
    assert not any(c["userId"] == "user-bob" for c in collabs)
```

**UT-06 -- Activity Feed Retention and Pagination:**
Test that the activity feed returns events in correct order and respects pagination.

```python
async def test_activity_feed_pagination(collab_service: CollaborationService, db_session):
    # Create 5 activity events
    for i in range(5):
        await collab_service.record_activity(
            course_id="course-C1",
            organization_id="org-1",
            event_type=ActivityEventType.PROPOSAL_CREATED,
            user_id=f"user-{i}",
            description=f"Activity {i}",
        )

    # Fetch with limit=2
    events, total, has_more = await collab_service.get_activity_feed(
        "course-C1", "user-alice", limit=2, offset=0
    )
    assert len(events) == 2
    assert total == 5
    assert has_more is True
    assert events[0]["description"] == "Activity 4"  # Most recent first

    # Fetch next page
    events2, _, has_more2 = await collab_service.get_activity_feed(
        "course-C1", "user-alice", limit=2, offset=2
    )
    assert len(events2) == 2
    assert events2[0]["description"] == "Activity 2"
```

### Integration Tests (3+)

**IT-01 -- Full Collaboration Workflow via API:**
Test the complete collaboration flow: invite collaborator -> accept invitation -> create session -> propose page -> reviewer approves -> apply.

```python
async def test_full_collaboration_workflow_via_api(
    async_client, auth_headers, sample_course, db_session
):
    # Step 1: Alice creates a session (owner by default if first user)
    resp_alice = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-alice", "courseId": sample_course.course_id,
        "organizationId": "org-1",
    })
    session_alice = resp_alice.json()
    assert session_alice["sessionId"]

    # Step 2: Alice invites Bob
    resp_invite = await async_client.post(
        f"/api/v1/ai/collaborations/{sample_course.course_id}/invitations",
        headers={"Authorization": f"Session {session_alice['sessionId']}"},
        json={"inviteeEmail": "bob@example.com", "role": "editor"},
    )
    assert resp_invite.status_code == 201
    invitation_id = resp_invite.json()["invitationId"]

    # Step 3: Bob accepts the invitation (simulate different auth context)
    resp_accept = await async_client.post(
        f"/api/v1/ai/collaborations/invitations/{invitation_id}/accept",
        json={"userId": "user-bob"},
    )
    assert resp_accept.status_code == 200
    assert resp_accept.json()["status"] == "accepted"

    # Step 4: Bob creates a session (should succeed, collaboration enabled)
    resp_bob_session = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-bob", "courseId": sample_course.course_id,
        "organizationId": "org-1", "collaborationMode": "auto",
    })
    assert resp_bob_session.status_code == 200
    session_bob = resp_bob_session.json()
    assert session_bob["collaboration"]["enabled"] is True
    assert session_bob["collaboration"]["role"] == "editor"

    # Step 5: Bob proposes an update (creates review_status=pending proposal)
    resp_propose = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers={"Authorization": f"Session {session_bob['sessionId']}"},
        json={"sessionId": session_bob["sessionId"],
              "input": {"pageId": "page-1", "patch": {"title": "New Title"}}},
    )
    assert resp_propose.status_code == 200
    proposal_id = resp_propose.json()["proposalId"]
    assert resp_propose.json()["reviewStatus"] == "pending"

    # Step 6: Alice (owner) reviews and approves
    resp_approve = await async_client.post(
        f"/api/v1/ai/collaborations/{sample_course.course_id}/reviews/{proposal_id}/approve",
        headers={"Authorization": f"Session {session_alice['sessionId']}"},
        json={"comment": "Approved."},
    )
    assert resp_approve.status_code == 200

    # Step 7: Bob applies the approved proposal
    resp_apply = await async_client.post(
        "/api/v1/ai/tools/apply_update_proposal",
        headers={"Authorization": f"Session {session_bob['sessionId']}"},
        json={"sessionId": session_bob["sessionId"],
              "input": {"proposalId": proposal_id, "userConfirmed": True}},
    )
    assert resp_apply.status_code == 200

    # Step 8: Verify activity feed contains all events
    resp_feed = await async_client.get(
        f"/api/v1/ai/collaborations/{sample_course.course_id}/activity",
        headers={"Authorization": f"Session {session_alice['sessionId']}"},
    )
    events = resp_feed.json()["activities"]
    event_types = [e["eventType"] for e in events]
    assert "collaborator_joined" in event_types
    assert "proposal_created" in event_types
    assert "proposal_approved" in event_types
    assert "proposal_applied" in event_types
```

**IT-02 -- Concurrent Session on Collaborative Course:**
Test that two collaborators can have concurrent AI sessions on the same course.

```python
async def test_concurrent_collaborative_sessions(
    async_client, auth_headers, sample_course, db_session
):
    # Setup: Alice (owner) and Bob (editor) are collaborators

    # Alice starts a session
    resp_a = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-alice", "courseId": sample_course.course_id, "organizationId": "org-1",
    })
    assert resp_a.status_code == 200

    # Bob starts a session on the same course (should succeed in collaborative mode)
    resp_b = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-bob", "courseId": sample_course.course_id,
        "organizationId": "org-1", "collaborationMode": "auto",
    })
    assert resp_b.status_code == 200  # No COURSE_LOCKED error

    # Bob's page proposal succeeds (page-level locking still applies)
    resp_propose = await async_client.post(
        "/api/v1/ai/tools/propose_update_page",
        headers={"Authorization": f"Session {resp_b.json()['sessionId']}"},
        json={"sessionId": resp_b.json()["sessionId"],
              "input": {"pageId": "page-2", "patch": {"title": "Bob's Update"}}},
    )
    assert resp_propose.status_code == 200
    assert "lock" in resp_propose.json()

    # Verify both sessions appear in active locks / collaborator list
    collabs = await async_client.get(
        f"/api/v1/ai/collaborations/{sample_course.course_id}/collaborators",
        headers={"Authorization": f"Session {resp_a.json()['sessionId']}"},
    )
    alice_entry = next(c for c in collabs.json()["collaborators"] if c["userId"] == "user-alice")
    assert alice_entry["hasActiveSession"] is True
```

**IT-03 -- Editor Cannot Apply Without Review Approval:**
Test that an editor's proposal cannot be applied until it has been approved.

```python
async def test_editor_apply_blocked_without_approval(
    async_client, auth_headers, sample_course, db_session
):
    # Setup: Alice (owner), Bob (editor) with review_required_for_editors=True

    bob_session = await async_client.post("/api/v1/ai/sessions", json={
        "userId": "user-bob", "courseId": sample_course.course_id,
        "organizationId": "org-1", "collaborationMode": "auto",
    })
    bob_sid = bob_session.json()["sessionId"]

    # Bob proposes a page creation (review_status = pending)
    resp_propose = await async_client.post(
        "/api/v1/ai/tools/propose_create_page",
        headers={"Authorization": f"Session {bob_sid}"},
        json={"sessionId": bob_sid,
              "input": {"title": "New Page", "templateType": "content-text",
                        "data": {"content": "Hello"}}},
    )
    assert resp_propose.status_code == 200
    proposal_id = resp_propose.json()["proposalId"]

    # Bob tries to apply directly (should be rejected)
    resp_apply = await async_client.post(
        "/api/v1/ai/tools/apply_page_proposal",
        headers={"Authorization": f"Session {bob_sid}"},
        json={"sessionId": bob_sid,
              "input": {"proposalId": proposal_id, "userConfirmed": True}},
    )
    assert resp_apply.status_code == 403
    assert resp_apply.json()["code"] == "REVIEW_REQUIRED"
    assert "pending" in resp_apply.json()["message"].lower()
```

### End-to-End Tests (2+)

**E2E-01 -- Full Collaborative Authoring Session:**
1. Alice opens AI chat panel for Course C1. The system creates session S-A. The Collaborators Panel shows "You are the owner. Add collaborators to get started."
2. Alice clicks "Invite Collaborator" in the panel, enters "bob@example.com", assigns role "Editor", clicks "Send Invitation".
3. Alice types "Create a 3-page course on Data Science." The AI generates and Alice applies all 3 pages.
4. Bob receives the invitation email. Bob clicks the link, is redirected to the course. The UI shows "You've joined as Editor on Course C1."
5. Bob opens the AI chat panel. The activity feed shows: "Alice created page 1", "Alice created page 2", "Alice created page 3", "Alice invited Bob", "Bob joined".
6. Bob types "Add a quiz page to module 2." The AI proposes a new page. Since Bob is an Editor and review is required, the proposal enters "Pending Review" state.
7. Alice's session shows a badge: "Pending Reviews (1)". Alice opens the review panel, sees Bob's proposal, clicks "Approve".
8. Bob's session shows a notification: "Your proposal was approved by Alice." Bob clicks "Apply". The quiz page is created.
9. The activity feed now shows: "Bob created page 4 (approved by Alice)".
10. Bob exports the course. The export includes all 4 pages.

**E2E-02 -- Semantic Conflict Resolution Between Collaborators:**
1. Alice and Bob are both Editors on Course C1. Alice has an active session S-A with a WRITE lock on page P-2 (Content Text). Bob has an active session S-B.
2. Alice proposes a substantial rewrite of P-2's content. The proposal P-A1 is pending review.
3. Bob, not seeing Alice's pending changes (because he fetched the page before Alice's proposal), proposes a different update to P-2. Proposal P-B1 is also pending review.
4. Carol (Reviewer) reviews P-A1 first and approves it. Alice applies P-A1, releasing the lock on P-2.
5. Carol then reviews P-B1. The system detects that P-B1 was based on a stale version of P-2 (base hash mismatch). Carol sees a warning: "Bob's proposal is based on an older version of this page. Alice has already applied changes. Bob may need to revise."
6. Carol requests changes on P-B1: "Please rebase your changes on the current version of the page."
7. Bob receives the notification, re-fetches page P-2 (now with Alice's changes), revises his proposal, and resubmits.
8. Carol approves the revised proposal. Bob applies it. The page now contains both Alice's and Bob's changes.

### Manual QA Steps

1. **Invitation Flow:** As owner, send an invitation to a user. Verify the invitation appears in the collaborators panel with status "Pending". Accept the invitation as the invitee. Verify the status changes to "Accepted" and the collaborator appears in the list.
2. **Expired Invitation:** Create an invitation with a 1-minute TTL. Wait 2 minutes. Verify the invitation status changes to "Expired" automatically. Attempt to accept it; verify it's rejected with `INVITATION_EXPIRED`.
3. **Collaborator Removal Cleanup:** As owner, add a collaborator. Have the collaborator start a session, acquire a lock, and create a pending proposal. Remove the collaborator as owner. Verify: (a) the collaborator is removed from the list; (b) their active session is terminated; (c) their locks are released; (d) their proposals are invalidated.
4. **Role Enforcement:** As a Viewer, attempt to start an AI session. Verify it's rejected with `ROLE_INSUFFICIENT`. As an Editor, attempt to add a collaborator. Verify it's rejected with `NOT_COURSE_OWNER`.
5. **Review Workflow:** As an Editor, create 3 proposals. As a Reviewer, navigate to the Pending Reviews view. Verify all 3 are visible with correct details. Approve one, reject one with a reason, and request changes on the third. Verify the Editor sees the correct notifications and status updates for each.
6. **Activity Feed Visibility:** As a Viewer, open the activity feed. Verify only non-sensitive events are visible (e.g., "proposal_applied" but not "proposal_created" or review details). As an Editor, verify all events are visible.
7. **Collaboration Configuration:** As an Admin, navigate to the Collaboration Settings page. Toggle `collaboration_enabled` off. Verify that collaboration endpoints return `COLLABORATION_DISABLED` errors. Toggle it back on and verify the endpoints work again.
8. **Export with Collaboration Metadata:** Generate a course with multiple collaborators. Export the course as SCORM. Verify the export completes successfully and includes all pages from all collaborators. Verify the audit log contains collaboration events linked to the export operation.

---

## 7. DEFINITION OF DONE

1. `ai_course_collaborators`, `ai_collaboration_invitations`, `ai_collaboration_activity`, `ai_collaboration_config`, and `ai_review_comments` tables exist in the database with the correct schema, indexes, foreign key relationships, and constraints (including single-owner constraint).
2. All database migrations are created, reviewed by DBA, and applied to staging without errors. Rollback scripts are verified.
3. `CollaborationService` is fully implemented with all methods: `add_collaborator`, `accept_invitation`, `remove_collaborator`, `list_collaborators`, `get_user_role`, `check_permission`, `get_pending_reviews`, `approve_proposal`, `reject_proposal`, `request_changes`, `revise_proposal`, `record_activity`, `get_activity_feed`, `detect_semantic_conflict`, `resolve_conflict`, `get_or_create_collaboration_config`, `update_collaboration_config`, `cleanup_expired_invitations`, `cleanup_old_activity`.
4. `CollaborationNotifier` is implemented with pending notification support for active sessions.
5. All 6 unit tests in Section 6 pass with >90% code coverage for the `collaboration_service.py` module.
6. All 3 integration tests in Section 6 pass against a real PostgreSQL database with seeded test data.
7. Both E2E tests in Section 6 are passing in the CI environment with mocked LLM responses.
8. Session creation (`POST /api/v1/ai/sessions`) accepts `collaborationMode` parameter and returns collaboration metadata when collaboration is enabled. Multiple sessions on the same course are allowed for collaborators.
9. The `LockManager.acquire_lock` (US-AI-043) supports multiple SESSION locks on the same course when collaboration is enabled. The `is_collaborative` flag is set on lock records.
10. The `LockManager.force_release_by_admin` also accepts a course owner (verified via `CollaborationService.get_user_role`) and releases locks without `X-Admin-Override` header.
11. Proposal lifecycle enforces review status: editor proposals are created with `review_status='pending'`; apply is blocked for proposals with `review_status != 'approved'` (unless `editor_auto_apply_allowed` is true and risk is low).
12. The proposal review workflow (approve, reject, request changes, revise) is fully functional via API endpoints.
13. The activity feed is populated with all collaboration events and queryable via API with pagination and event-type filtering.
14. The invitation lifecycle (create, accept, expire, cancel) is fully functional with TTL enforcement.
15. Collaborator removal correctly releases all locks and invalidates all pending proposals for the removed user.
16. The cleanup background tasks (expired invitations every 15 minutes, old activity daily) are implemented and running.
17. Role-based permissions are enforced server-side for all collaboration endpoints: invite/remove (owner only), propose/apply (owner and editor only), review (owner and reviewer only), view feed (all collaborators).
18. Semantic conflict detection is implemented: comparing base snapshot hashes across proposals on the same page.
19. Resolution dialog options (notify, wait, escalate) are functional via the API.
20. The existing `collaboration` feature flag in `app/utils/feature_flags.py` is wired to the collaboration endpoints. When disabled, endpoints return `COLLABORATION_DISABLED`.
21. All manual QA steps in Section 6 are verified and signed off by QA.
22. Audit trail includes collaboration-specific event types with `collaborator_id`, `collaborator_role`, and `related_collaborator_id` fields.
23. Cross-organization isolation is verified: collaborators from Org A cannot see or interact with courses in Org B.
24. Security review completed: invitation token validation, role enforcement, session invalidation on removal, audit logging.
25. Performance load test passed: 50 collaborators, 200 pending proposals, 10,000 activity events -- all queries return within p95 targets.
26. No regression in existing AI authoring: all pre-existing US-AI-001 through US-AI-043 tests still pass with collaboration disabled and enabled.
27. API documentation (OpenAPI) is updated to include all new collaboration endpoints with request/response schemas and error codes.
28. Feature is gated behind the `collaboration` feature flag and the `AI_COLLABORATION_ENABLED` config variable. Both must be enabled for collaboration to function.

---

## 8. TASKS AND SUB-TASKS

| Task ID | Task Description | Estimated Effort | Dependencies | Assigned To |
|---|---|---|---|---|
| T-047-01 | **Create database tables and migrations** -- Write Alembic migration for `ai_course_collaborators`, `ai_collaboration_invitations`, `ai_collaboration_activity`, `ai_collaboration_config`, and `ai_review_comments` tables. Add columns to `ai_proposals`, `ai_sessions`, `ai_locks`, and `ai_audit_logs` as specified in DDL. Apply, verify, create rollback. | 6 hours | US-AI-004 (ai_proposals, ai_sessions, ai_audit_logs tables), US-AI-043 (ai_locks table) | Backend Engineer |
| T-047-02 | **Implement CollaborationService** -- Write `app/services/ai/collaboration_service.py` with collaborator CRUD, invitation management, role-based permission checks, proposal review workflow (approve/reject/request-changes/revise), activity feed management, semantic conflict detection, configuration management, and cleanup background tasks. | 24 hours | T-047-01 | Backend Engineer |
| T-047-03 | **Implement CollaborationNotifier** -- Write `app/services/ai/collaboration_notifier.py` with pending notification storage, polling endpoint support, and notification delivery for proposal status changes, lock releases, and conflict events. | 8 hours | T-047-02 | Backend Engineer |
| T-047-04 | **Implement collaboration API routes** -- Implement invitation endpoints (POST create, POST accept, GET status), collaborator management endpoints (GET list, DELETE remove), proposal review endpoints (GET pending, GET detail, POST approve/reject/request-changes/revise), activity feed endpoint (GET with pagination and filters), and collaboration config endpoints (GET/PUT). | 12 hours | T-047-02, T-047-03 | Backend Engineer |
| T-047-05 | **Integrate collaboration into session creation** -- Modify `POST /api/v1/ai/sessions` to accept `collaborationMode`, load the user's role via CollaborationService, relax the SESSION lock check for collaborative courses, and return collaboration metadata in the session response. | 4 hours | T-047-02, T-047-04, US-AI-006, US-AI-043 | Backend Engineer |
| T-047-06 | **Integrate collaboration into LockManager** -- Modify US-AI-043 LockManager to: (a) allow multiple SESSION locks on same course when `is_collaborative=True`; (b) set `collaborator_role` and `is_collaborative` on lock records; (c) allow course owner to force-release locks (verify via CollaborationService). | 6 hours | T-047-02, US-AI-043 | Backend Engineer |
| T-047-07 | **Integrate collaboration into proposal lifecycle** -- Modify `propose_*` tool handlers to set `collaborator_id` and `collaborator_name` on proposals. Set `review_status='pending'` for editor proposals when review is required. Modify `apply_*` handlers to check `review_status` and collaborator role before allowing apply. Return `REVIEW_REQUIRED` error when blocked. | 8 hours | T-047-02, T-047-05, US-AI-009, US-AI-010 | Backend Engineer |
| T-047-08 | **Integrate collaboration into audit and outbox** -- Modify `ai_audit_logs` write operations to include `collaborator_id`, `collaborator_role`, and `related_collaborator_id`. Add `CollaborationActivity` event type to the outbox (US-AI-033) for real-time feed delivery. Wire the existing `collaboration` feature flag to the collaboration endpoints. | 4 hours | T-047-02, T-047-04, US-AI-020, US-AI-033 | Backend Engineer |
| T-047-09 | **Write unit tests** -- Write 6+ unit tests covering invitation lifecycle, role-based permissions, proposal review cycle, semantic conflict detection, collaborator removal cleanup, and activity feed pagination. | 8 hours | T-047-02 | QA Engineer |
| T-047-10 | **Write integration tests** -- Write 3+ integration tests covering full collaboration workflow via API, concurrent collaborative sessions, and editor apply blocked without approval. | 8 hours | T-047-04, T-047-05, T-047-06, T-047-07 | QA Engineer |
| T-047-11 | **Write E2E tests** -- Write 2+ E2E tests covering full collaborative authoring session (invite -> propose -> review -> apply) and semantic conflict resolution between collaborators. | 8 hours | All backend tasks above | QA Engineer |
| T-047-12 | **Implement frontend Collaborators Panel** -- Build UI component showing course collaborators with roles, active session status, last activity timestamps. Include "Invite Collaborator" button with email/role/message dialog. Include "Remove" button for owner. Add role badge icons. | 8 hours | T-047-04 | Frontend Engineer |
| T-047-13 | **Implement frontend Activity Feed Panel** -- Build scrollable activity feed component in the AI sidebar. Auto-polls every 10 seconds. Shows event type icons, user names, page links, and relative timestamps. Supports infinite scroll pagination. | 6 hours | T-047-04 | Frontend Engineer |
| T-047-14 | **Implement frontend Proposal Review Dialog** -- Build proposal review modal showing proposer info, before/after diff, validation results, comment thread, and Approve/Request Changes/Reject buttons. For the proposer, show Apply button when approved. Show "Pending Review" badge on course card. | 8 hours | T-047-04, T-047-07 | Frontend Engineer |
| T-047-15 | **Implement frontend Conflict Resolution UI** -- Build conflict dialog that explains semantic conflicts in plain language. Show resolution options: "Notify Collaborator", "Wait (retry in 30s)", "Escalate to Owner". Show notification toast when resolved. | 6 hours | T-047-04, T-047-06 | Frontend Engineer |
| T-047-16 | **Implement frontend Collaboration Configuration UI** -- Build admin settings page for collaboration configuration: toggle for enabled, numeric inputs for max collaborators and TTL, checkboxes for auto-apply and review requirements. Wire to GET/PUT configuration endpoints. | 4 hours | T-047-04 | Frontend Engineer |
| T-047-17 | **Performance and load testing** -- Run load test with 50 collaborators per course, 200 pending proposals, 10,000 activity events. Verify p95 latency targets for all collaboration endpoints. Test stale lock scanner with collaborator-owned locks. | 8 hours | All backend tasks above | QA Engineer |
| T-047-18 | **Security review** -- Review all collaboration endpoints for proper authorization (role enforcement, invitation token validation, cross-org isolation, session invalidation on collaborator removal). Verify audit logging captures all collaboration events. Document collaboration configuration for deployment guide. | 4 hours | All backend tasks above | Security Engineer |
| T-047-19 | **Regression test suite** -- Run full AI authoring regression suite with collaboration disabled (verify no regression) and with collaboration enabled (verify existing flows still work). Test with single-user (non-collaborative) courses to ensure backward compatibility. | 4 hours | All tasks above | QA Engineer |
