# AI Authoring Use Case Flow Charts

This index maps each AI authoring use case to the canonical production-grade Mermaid flow chart. The detailed diagrams align the proposed AI layer with the currently implemented FastAPI backend: course CRUD, page/component repositories, course validation, import jobs, template definitions, component registry, and SCORM/export validation.

## Canonical Diagram Files

| # | Use case | Production flow chart |
|---|---|---|
| 1 | AI Session Creation Flow | [AI_Session_Creation_Flow.mmd](AI_Session_Creation_Flow.mmd) |
| 2 | Page List and Fetch Flow | [Page_List_and_Fetch_Flow.mmd](Page_List_and_Fetch_Flow.mmd) |
| 3 | Create Page Proposal and Apply Flow | [Create Page Proposal and Apply Flow1.0.mmd](<Create Page Proposal and Apply Flow1.0.mmd>) and [Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd](<Create Page Proposal and Apply Flow - Platform Runtime and Operations1.1.mmd>) |
| 4 | Update Page Proposal and Apply Flow | [Update_Page_Proposal_and_Apply_Flow.mmd](Update_Page_Proposal_and_Apply_Flow.mmd) |
| 5 | Delete Page Proposal and Confirm Flow | [Delete_Page_Proposal_and_Confirm_Flow.mmd](Delete_Page_Proposal_and_Confirm_Flow.mmd) |
| 6 | Course Validation Flow | [Course_Validation_Flow.mmd](Course_Validation_Flow.mmd) |
| 7 | Similar Course Retrieval Flow | [Similar_Course_Retrieval_Flow.mmd](Similar_Course_Retrieval_Flow.mmd) |
| 8 | File Ingestion / Document Import Flow | [File_Ingestion_Document_Import_Flow.mmd](File_Ingestion_Document_Import_Flow.mmd) |
| 9 | Simple Chat Edit Scenario Flow | [Simple_Chat_Edit_Scenario_Flow.mmd](Simple_Chat_Edit_Scenario_Flow.mmd) |
| 10 | Full Course from Uploaded File Scenario Flow | [Full_Course_From_Uploaded_File_Scenario_Flow.mmd](Full_Course_From_Uploaded_File_Scenario_Flow.mmd) |
| 11 | Destructive Delete Scenario Flow | [Destructive_Delete_Scenario_Flow.mmd](Destructive_Delete_Scenario_Flow.mmd) |
| 12 | Propose, Validate, Confirm, Apply Safety Flow | [Propose_Validate_Confirm_Apply_Safety_Flow.mmd](Propose_Validate_Confirm_Apply_Safety_Flow.mmd) |

## Implementation Alignment Notes

- Existing source of truth: `CourseRecord`, `PageRecord`, `ComponentRecord`, `TemplateRecord`, `TemplateDefinition`, and `ImportJob`.
- Existing API adapters reused by the AI layer: `/api/v1/courses`, `/api/v1/courses/{courseId}/pages`, `/api/v1/courses/validate`, `/api/v1/imports/analyze`, `/api/v1/imports/jobs/{job_id}`, and `/api/v1/imports/jobs/{job_id}/commit`.
- The requested `/api/v1/files/upload` document-ingestion route is not implemented in the current backend; today, package ingestion is `/api/v1/imports/analyze` and media upload is `/api/v1/media/upload`.
- AI-specific routes such as `/api/v1/ai/chat`, `/api/v1/ai/sessions`, proposal storage, confirmation tokens, RAG retrieval, and audit/outbox persistence are architecture additions that should remain isolated from the existing manual authoring path.
- Every mutating AI use case follows the same invariant: fetch latest database state, propose without mutation, validate server-side, require explicit user approval, re-check staleness, apply through repositories, then audit and return refreshed state.
