# User Stories & Use Cases — AI Authoring

## Personas
- Author: content creator who wants to generate or refine course pages and assets using AI.
- Reviewer: subject-matter expert who validates and edits AI-generated content.
- Admin: platform operator who configures AI settings, permissions, and audits activity.
- System: automated background processes (ingestion, validation, export) that enforce rules and run pipelines.

## Epics and User Stories

Epic: AI-Assisted Page Authoring
1. As an **Author**, I want to create a draft page by giving a short prompt so that I can rapidly generate learning content.
   - Acceptance Criteria: `propose_create_page` returns a structured proposal JSON (title, body, metadata); UI shows preview; author can accept, edit, or request refinements.
   - Priority: MUST
   - Example API: `POST /api/v1/ai/sessions/{session_id}/propose_create_page`

2. As an **Author**, I want manual course creation to remain available so I can choose AI only when I want assistance.
   - Acceptance Criteria: UI keeps the existing manual authoring path; AI creation is presented as an optional assisted workflow and does not replace the manual editor.
   - Priority: MUST

3. As an **Author**, I want to iterate on a proposed page (tone, length, add examples) so I can refine output until it's publish-ready.
   - Acceptance Criteria: `propose_update_page` accepts parameters (tone,length,examples) and returns new proposal with diff; versions are tracked.
   - Priority: MUST

4. As an **Author**, I want AI-generated drafts to use only approved templates so the course can render in the existing UI and stay within demo scope.
   - Acceptance Criteria: AI template planner selects from a whitelist of supported templates; proposals are rejected if unsupported templates are suggested.
   - Priority: MUST

5. As an **Author**, I want to apply an accepted proposal to create a saved page in my draft workspace so that it persists and becomes editable.
   - Acceptance Criteria: `apply_page_proposal` validates schema and creates `Page` record; response includes page id and status `draft`.
   - Priority: MUST

Epic: Review & Approval
6. As a **Reviewer**, I want to open an AI-generated draft, leave comments and request changes so I can ensure accuracy and pedagogical quality.
   - Acceptance Criteria: Reviewer comments attach to page sections; change requests trigger a new propose cycle; history is auditable.
   - Priority: MUST

7. As an **Author**, I want to send follow-up AI instructions to update an existing draft so I can refine specific sections without rebuilding the entire course.
   - Acceptance Criteria: Follow-up instructions produce an updated proposal or set of patch operations; change history is preserved and the author can approve the update.
   - Priority: MUST

8. As a **Reviewer**, I want the system to provide a validation report (WCAG, SCORM, factual-check highlights) so I can focus reviews on high-risk items.
   - Acceptance Criteria: `analyze_page` returns a JSON report with issues and severity; UI surfaces high/medium/low items.
   - Priority: SHOULD

Epic: Publishing & Export
9. As an **Author/Admin**, I want to export the approved content to SCORM or HTML packages so it can be consumed by LMSs.
   - Acceptance Criteria: `export_package` validates all pages, runs format transforms, and returns downloadable artifact; export job is queued and monitored.
   - Priority: MUST

10. As an **Author**, I want to preview final rendered content (including images and layout) before export so I can approve presentation.
   - Acceptance Criteria: Preview shows rendered HTML with assets; preview link valid for the session user; render matches exported package.
   - Priority: SHOULD

Epic: Admin & Monitoring
11. As an **Admin**, I want to configure AI provider settings (primary, fallback, rate limits, model allowlist) so the platform remains reliable and compliant.
   - Acceptance Criteria: Admin UI can update provider endpoints, keys, and allowed model options; changes are versioned; system uses fallback when primary fails and rejects unsupported models.
   - Priority: MUST

12. As an **Admin**, I want audit logs for propose/apply actions to meet compliance and rollback requirements.
   - Acceptance Criteria: Every `propose_*` and `apply_*` call is logged with user, session, timestamp, and tool schema used; logs are queryable.
   - Priority: MUST

Epic: System Automation
13. As the **System**, I must run deterministic ingestion for uploaded source files (PDF/DOCX) to produce canonical text chunks for AI prompting.
    - Acceptance Criteria: Ingestion produces chunked JSON with source references and confidence; failures are retried or flagged.
    - Priority: MUST

14. As the **System**, I must enforce propose→validate→confirm→apply gating so proposals cannot directly mutate production content without explicit apply.
    - Acceptance Criteria: `apply_*` will reject if `validate` step fails; UI prevents direct edits to published content without approval.
    - Priority: MUST

## Example Flows (concise)
- Create session: `POST /api/v1/ai/sessions` → returns `session_id`.
- Propose page: `POST /api/v1/ai/sessions/{session_id}/propose_create_page` with prompt → returns `proposal_id`.
- Analyze proposal: `POST /api/v1/ai/proposals/{proposal_id}/analyze` → returns validation report.
- Apply proposal: `POST /api/v1/ai/proposals/{proposal_id}/apply` → persists page as draft.

## Acceptance Criteria and Prioritization Rules
- MUST: required for MVP and safe operation (propose→apply gating, audit logs, export, provider fallback).
- SHOULD: important for UX and quality (validation reports, previews, iterative refine).
- CAN: nice-to-have features (auto-summarization, multilingual variants, advanced tuning UI).

## Dev Notes / API Contract Pointers
- Use tool schemas in `TOOL_SCHEMAS_CLAUDE_NATIVE.md` as the canonical request/response shapes for propose/apply operations.
- Ensure `propose_*` returns both human-readable preview and machine schema for `apply_*`.
- Maintain a strict template whitelist for AI-generated content and reject unsupported template suggestions before proposing.
- Preserve the existing manual authoring workflow as a parallel option to AI-assisted creation.
- All endpoints must return structured errors conforming to OpenAPI error schemas and include `validation_issues` when applicable.

---
Saved: draft User Stories to support architecture-led implementation. Please review and tell me which stories to expand or prioritize first.
