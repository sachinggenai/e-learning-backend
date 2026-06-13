# AI Authoring Use Case Flow Charts

## 1. AI Session Creation Flow
```mermaid
graph TD
  A[User clicks Build with AI] --> B[POST /api/v1/ai/sessions]
  B --> C[Validate user, course, organization]
  C --> D[Create AI session with course scope]
  D --> E[Return session_id and course state]
  E --> F[Frontend stores session_id]
```

## 2. Page List and Fetch Flow
```mermaid
graph TD
  A[AI agent needs current course state] --> B["list_pages(session_id)"]
  B --> C[Return page metadata for current course]
  C --> D[Choose page to inspect or edit]
  D --> E["fetch_page(session_id, page_id)"]
  E --> F[Return full page data and template details]
```

## 3. Create Page Proposal and Apply Flow
```mermaid
graph TD
  A[AI decides to add a new page] --> B["propose_create_page(session_id, title, template_type, data)"]
  B --> C[Validate schema and business rules]
  C --> D[Return proposal_id, preview, validation status]
  D --> E[Frontend shows preview to user]
  E --> F[User approves proposal]
  F --> G["apply_page_proposal(proposal_id, user_confirmed=true)"]
  G --> H[Create page in database]
  H --> I[Return success]
```

## 4. Update Page Proposal and Apply Flow
```mermaid
graph TD
  A[AI decides to modify an existing page] --> B["fetch_page(session_id, page_id)"]
  B --> C["propose_update_page(session_id, page_id, updated_data)"]
  C --> D[Validate updated template data]
  D --> E[Return proposal_id and diff preview]
  E --> F[Frontend shows diff to user]
  F --> G[User approves updates]
  G --> H["apply_update_proposal(proposal_id, user_confirmed=true)"]
  H --> I[Update page in database]
  I --> J[Return success]
```

## 5. Delete Page Proposal and Confirm Flow
```mermaid
graph TD
  A[AI decides to remove a page] --> B["propose_delete_page(session_id, page_id)"]
  B --> C[Flag as destructive operation]
  C --> D[Return delete proposal and warning]
  D --> E[Frontend asks for explicit user confirmation]
  E --> F["confirm_delete_page(session_id, page_id, confirmation_token)"]
  F --> G[Validate token and pending operation]
  G --> H[Delete page from database]
  H --> I[Return success]
```

## 6. Course Validation Flow
```mermaid
graph TD
  A[User or agent requests validation] --> B["validate_course(session_id)"]
  B --> C[Run schema validation for all pages]
  C --> D[Run business rules: SCORM, WCAG, required fields]
  D --> E[Compile validation messages]
  E --> F[Return validation result to frontend]
```

## 7. Similar Course Retrieval Flow
```mermaid
graph TD
  A[AI agent requests examples or tone references] --> B["query_similar_courses(session_id, query)"]
  B --> C[Search RAG store for similar courses]
  C --> D[Return pedagogical examples and style guidance]
```

## 8. File Ingestion / Document Import Flow
```mermaid
graph TD
  A[User uploads PDF/DOCX] --> B["analyze_document_for_import(session_id, file)"]
  B --> C[Deterministic extractor parses sections and headings]
  C --> D[LLM segmenter maps sections to templates]
  D --> E[Return proposed page breakdown to frontend]
  E --> F[User reviews and approves breakdown]
  F --> G[Create pages from approved breakdown]
  G --> H[Return imported course pages]
```

## 9. Simple Chat Edit Scenario Flow
```mermaid
graph TD
  A[User asks AI to refine a page] --> B[POST /api/v1/ai/chat]
  B --> C[Backend validates session and course scope]
  C --> D[Agent calls list_pages and fetch_page]
  D --> E[Agent proposes update_page changes]
  E --> F[Validation and preview gating]
  F --> G[User approves update]
  G --> H[apply_update_proposal executes DB change]
  H --> I[Audit log entry created]
```

## 10. Full Course from Uploaded File Scenario Flow
```mermaid
graph TD
  A[User uploads course outline file] --> B[POST /api/v1/files/upload]
  B --> C[Backend extracts sections deterministically]
  C --> D[LLM segments sections into template suggestions]
  D --> E[Return proposed course page plan to user]
  E --> F[User confirms recommended breakdown]
  F --> G[Backend generates page data and validates]
  G --> H[Apply create_page proposals for all pages]
  H --> I[Audit log and return final course]
```

## 11. Destructive Delete Scenario Flow
```mermaid
graph TD
  A[User asks AI to delete assessment section] --> B[AI calls propose_delete_page]
  B --> C[System flags destructive operation]
  C --> D[Frontend requires explicit confirmation]
  D --> E[User confirms deletion]
  E --> F[confirm_delete_page validates token]
  F --> G[Delete page from database]
  G --> H[Audit log record created]
```

## 12. Propose → Validate → Confirm → Apply Safety Flow
```mermaid
graph TD
  A[Intent to modify course] --> B[Propose change via tool]
  B --> C[Server-side validation]
  C --> D[Return preview and warnings]
  D --> E[User reviews and confirms]
  E --> F[Apply tool executes mutation]
  F --> G[Database update and audit log]
```
