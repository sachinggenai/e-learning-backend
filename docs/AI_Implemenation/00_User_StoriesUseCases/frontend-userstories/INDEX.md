# Frontend AI User Stories — Index

**Total Frontend Stories:** 8
**Last Updated:** 2026-06-14

---

## Story ID Convention

- `US-FRNT-AI-XXX` — Frontend AI integration stories
- Each story pairs with a backend counterpart (`US-BKND-AI-XXX`) in [../backend-userstories/](../backend-userstories/)

---

## Frontend Stories

| Story ID | Title | Status | Priority | Backend Counterpart |
|---|---|---|---|---|
| [US-FRNT-AI-001](US-FRNT-AI-001_enriched.md) | Preserve Manual Authoring UI While Adding AI Entry Points | ✅ COMPLETE | MUST | US-BKND-AI-001 |
| US-FRNT-AI-013 | Destructive Delete Confirmation Modal UI | ❌ TODO | MUST | US-BKND-AI-013 |
| [US-FRNT-AI-014](US-FRNT-AI-014_enriched.md) | AI Chat Panel and Edit Scenario UI | ✅ COMPLETE | MUST | US-BKND-AI-014 |
| US-FRNT-AI-018 | Validation Report Display UI | ❌ TODO | SHOULD | US-BKND-AI-018 |
| US-FRNT-AI-022 | E2E Regression Test Suite (Frontend) | ❌ TODO | MUST | US-BKND-AI-022 |
| US-FRNT-AI-024 | Frontend AI Integration Layer | ❌ TODO | MUST | US-BKND-AI-003 |
| US-FRNT-AI-030 | AI Content Assembly into Course Editor UI | ❌ TODO | MUST | US-BKND-AI-030 |
| US-FRNT-AI-045 | Real-Time Job Status Notifications UI | ❌ TODO | SHOULD | US-BKND-AI-045 |
| US-FRNT-AI-047 | Multi-User Collaboration UI | ❌ TODO | COULD | US-BKND-AI-047 |

---

## Story Descriptions

### US-FRNT-AI-001 — Preserve Manual Authoring UI While Adding AI Entry Points
**Priority:** MUST | **Status:** ✅ COMPLETE

Conditionally render AI entry points ("Build with AI" button, AI chat panel) when feature flag is enabled. Manual course editor must render identically to pre-AI baseline regardless of flag state. AI panel is a sliding overlay that does not alter existing editor layout. Feature status fetched from `GET /api/v1/ai/feature-status`.

### US-FRNT-AI-013 — Destructive Delete Confirmation Modal UI
**Priority:** MUST | **Status:** ❌ TODO

Explicit confirmation modal for AI-proposed page deletions. Shows page title, template type, dependency warnings, and irreversible action messaging. Requires explicit user click on "Delete" button (not dismissible by clicking outside). Calls `confirm_delete_page` with `user_approved_delete=true` only after confirmation.

### US-FRNT-AI-014 — AI Chat Panel and Edit Scenario UI
**Priority:** MUST | **Status:** ✅ COMPLETE

Chat panel component with message history, tool call status indicators, proposal preview rendering, and approval/rejection buttons. Sends session auth header. Handles session expiry with redirect to restart AI mode. Displays diffs for update proposals, previews for create proposals. Mobile-responsive (full-screen overlay on < 768px).

### US-FRNT-AI-018 — Validation Report Display UI
**Priority:** SHOULD | **Status:** ❌ TODO

Renders validation errors and warnings with severity indicators, field paths, and remediation hints. Allows jumping from a validation issue to the affected page/component in the editor. Disables proposal apply button when blocking errors exist. Refreshable after manual edits.

### US-FRNT-AI-022 — E2E Regression Test Suite (Frontend)
**Priority:** MUST | **Status:** ❌ TODO

Cypress/Playwright test suite covering: feature flag on/off, manual course creation regression, AI session creation, proposal review flow, destructive confirmation, chat edit flow, file upload flow. Mock LLM responses for deterministic testing.

### US-FRNT-AI-024 — Frontend AI Integration Layer
**Priority:** MUST | **Status:** ❌ TODO

Dedicated `src/ai/` module with API client, session context provider, proposal rendering components, confirmation modals, upload review workflow. Session ID stored in sessionStorage. All AI API calls include `Authorization: Session {sessionId}` header. Handles session refresh on page reload.

### US-FRNT-AI-030 — AI Content Assembly into Course Editor UI
**Priority:** MUST | **Status:** ❌ TODO

After AI creates/updates pages, the existing course editor receives and renders the refreshed course state. AI-generated pages appear in page list with correct order. Clicking an AI page opens it in the existing page editor with all fields editable. Editor undo/redo works across AI-generated pages.

### US-FRNT-AI-045 — Real-Time Job Status Notifications UI
**Priority:** SHOULD | **Status:** ❌ TODO

Polling/SSE-based progress display for long-running AI jobs (file ingestion, batch generation). Shows phase-level progress, elapsed time, and estimated completion. Handles connection loss with auto-reconnect. Displays completion state with navigation to editor.

### US-FRNT-AI-047 — Multi-User Collaboration UI
**Priority:** COULD | **Status:** ❌ TODO

Presence indicators showing other users active in the same course. Lock indicators on pages being edited by other users. Collaborative chat where multiple users can interact with AI in the same session. Change attribution showing which user approved which AI proposal.

---

## Quick Stats

- ✅ **COMPLETE:** 2 stories
- ❌ **TODO:** 7 stories need writing
- **Total:** 9 frontend stories

---

## Related Documents

- [Backend Stories Index](../backend-userstories/INDEX.md) — Backend companion stories
- [Original USER_STORIES.md](../USER_STORIES.md) — Full dependency order and MVP recommendations
