# US-AI-017 -- Extract Documents and Review Proposed Page Breakdown

**Title:** As an Author, I want the system to extract a document and propose a page breakdown for review, so that I can control course structure before AI generates content.

**Source Flow:** 8. File Ingestion / Document Import Flow (Phase 1: Deterministic Extraction, Phase 2: AI Segmentation and Page Plan, Phase 3: Human Review Checkpoint).

**Priority:** MUST for file-import MVP.

**Depends on:** US-AI-016 (File upload and ingestion job foundation), US-AI-008 (Unified course/page/schema/export/accessibility validation).

---

## 1. Functional Specification

### 1.1 User Workflow

1. The author uploads a supported document (PDF, DOCX) via the AI ingestion endpoint (post-US-AI-016). The upload is validated for file type, size, malware, and stored to the configured storage backend.
2. A background ingestion job is created with status `extracting`. The frontend polls `GET /api/v1/ai/ingestions/{job_id}` for progress.
3. The **Deterministic Extractor** runs synchronously (for sub-10 MB files) or asynchronously (for larger files) to parse the document:
   - PDF extractor: uses PyMuPDF / pdfplumber to extract text sections with heading levels, page numbers, table boundaries, and embedded image references.
   - DOCX extractor: uses python-docx to extract heading hierarchy (Heading 1/2/3), paragraphs, tables, and embedded media references.
   - Both extractors produce a normalized `ExtractedDocument` structure with stable source offsets (page number + character index ranges). Extraction warnings (e.g., "Image at offset 4210 could not be extracted") are stored on the job.
4. The **LLM Segmenter** is invoked against the normalized extraction to map sections to allowed template types:
   - The segmentation prompt is constructed from: the document extraction (truncated to fit model context), the **Template Capability Registry** (the set of template types from `TemplateTypeRepository.list(active_only=True)` filtered to MVP types: `content-text`, `tabs`, `accordion`, `click-reveal`, `content-video`, `mcq`, `final-assessment`, `summary`, `welcome`), and segmentation rules (no section left unmapped, no duplicate source ranges, max 50 pages).
   - The LLM returns a structured JSON array of `PageProposalItem` objects.
5. The backend validates the segmentation result:
   - Source coverage: every extracted section is mapped to at least one page.
   - No duplicate source offsets across pages.
   - Every proposed `template_type` is in the allowed template whitelist.
   - Total proposed page count is within limits (default max 50, configurable via `AI_PAGE_PLAN_MAX_PAGES`).
6. On validation success, the segmentation result is stored as an `AcquiredPagePlan` on the ingestion job record, and the job status transitions to `plan_ready`.
7. The frontend polls to `plan_ready` status and displays the proposed page breakdown in the **Page Plan Review UI**:
   - Each proposed page shows: proposed title, suggested template type with icon, rationale text, source sections referenced (with clickable backlinks into the original document preview).
   - The user can: **merge** two proposed pages into one, **split** a proposed page into two, **reorder** pages by drag-and-drop, **retitle** any page, or **change the suggested template type** (subject to the same whitelist).
   - The UI also shows extraction warnings (e.g., unsupported content types, ambiguous media refs) and validation messages.
8. The user clicks "Approve Plan" or "Cancel". Cancel returns the job to `staged` status (no data lost). Approve locks the plan and transitions the job to `plan_approved`, unlocking downstream US-AI-019 (content generation).
9. If auto-approval policies are configured (US-AI-032), low-risk documents (single section, content-text only, author is trusted role) may skip the review checkpoint.

### 1.2 Input / Output Contracts

**Input: ingestion job ID** (from US-AI-016 upload)

**Output: AcquiredPagePlan** (stored on job, retrievable via status endpoint)

### 1.3 Data Structures

```python
# ---- Document Extraction (Deterministic) ----

class ExtractedSection(BaseModel):
    section_id: str               # deterministic hash of source range
    heading: str                  # section heading text (or "" for untitled)
    heading_level: int            # 0=title, 1=Heading1, 2=Heading2, 3=Heading3, 4=body block
    body_text: str                # section body (plain text)
    page_number: int              # 1-indexed source page
    source_start_offset: int      # character offset in original document
    source_end_offset: int        # character end offset
    has_table: bool               # whether a table is present in this section
    table_data: Optional[list[dict]]  # extracted rows if has_table and table extraction succeeded
    media_refs: list[ExtractedMediaRef]

class ExtractedMediaRef(BaseModel):
    ref_type: Literal["image", "video_ref", "embed"]
    alt_text: Optional[str]
    source_location: str          # page number or paragraph index
    extraction_status: Literal["extracted", "unsupported", "ambiguous"]

class ExtractedDocument(BaseModel):
    source_filename: str
    source_type: Literal["pdf", "docx"]
    file_size_bytes: int
    total_pages: int
    total_sections: int
    sections: list[ExtractedSection]
    warnings: list[str]           # non-fatal extraction issues
    extracted_at: datetime

# ---- AI Segmentation (LLM-generated) ----

class PageProposalItem(BaseModel):
    """One proposed page from the LLM segmenter."""
    proposed_title: str           # max 200 chars
    suggested_template_type: str  # must be in ALLOWED_MVP_TEMPLATE_TYPES
    rationale: str                # why this template was chosen (max 500 chars)
    source_section_ids: list[str] # which ExtractedSection.section_id values map here
    order: int                    # proposed order within the course

# ---- Segmentation Validation Result ----

class SegmentationValidation(BaseModel):
    valid: bool
    errors: list[SegmentationError]
    warnings: list[str]
    coverage: float               # proportion of source sections mapped (0.0-1.0)

class SegmentationError(BaseModel):
    code: str                     # UNMAPPED_SECTION, UNSUPPORTED_TEMPLATE, DUPLICATE_SOURCE, PAGE_COUNT_EXCEEDED
    field: str                    # dotted path to offending item
    message: str

# ---- Enriched job record extension ----

# The existing ImportJob.result_data is extended with:
# {
#   "extraction": <ExtractedDocument>,
#   "page_plan": {
#       "proposed_pages": [<PageProposalItem>, ...],
#       "validation": <SegmentationValidation>,
#       "user_edits": null | {  # set when user edits and re-saves
#           "merged": [...],
#           "split": [...],
#           "reordered": [...],
#           "retitled": {...},
#           "template_changes": {...}
#       },
#       "status": "pending_review" | "approved" | "rejected"
#   }
# }
```

---

## 2. Technical Specification

### 2.1 New Files to Create

```
app/services/ai/
  __init__.py
  extractors/
    __init__.py
    base.py              # Abstract base extractor
    pdf_extractor.py     # PDF deterministic extraction
    docx_extractor.py    # DOCX deterministic extraction
  segmenter.py           # LLM segmenter orchestration
  page_plan_service.py   # Orchestrator: extract -> segment -> validate -> store
  page_plan_validator.py # Segmentation validation logic
```

### 2.2 Files to Modify

```
app/routers/imports.py                       # Add page plan status/approve/edit endpoints, or create new router
app/models/persisted_course.py               # Add page_plan_status etc. to ImportJob or create ingestion-specific model
app/repositories/import_job_repository.py    # Add page plan update methods
app/main.py                                  # Register new AI ingestion router if separate
app/utils/validation.py                      # Add page plan validation integration
docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md  # Mark story enriched
```

### 2.3 Router Signatures

**Option A -- Extend existing `/api/v1/imports` router** (preferred for minimal new surfaces):

```python
# --- Get extraction + page plan preview ---
GET /api/v1/imports/jobs/{job_id}/plan
Response 200: {
    "jobId": str,
    "status": "extracting" | "segmenting" | "plan_ready" | "plan_approved" | "failed",
    "extraction": ExtractedDocument | null,
    "pagePlan": {
        "proposedPages": list[PageProposalItem],
        "validation": SegmentationValidation,
        "userEdits": dict | null,
        "status": str
    },
    "progress": float
}
Response 404: Job not found

# --- Approve the page plan (advance to US-AI-019) ---
POST /api/v1/imports/jobs/{job_id}/plan/approve
Request body: {
    "edits": {                          # optional user modifications
        "reorder": [str, ...],          # ordered list of proposed page identifiers
        "retitle": {"page_idx": str},   # map of index -> new title
        "template_changes": {"page_idx": str},  # map of index -> alternate template type
        "merges": [{"into": int, "sources": [int, ...]}],  # merge source pages into target
        "splits": [{"source": int, "new_titles": [str, str]}]  # split one page into two
    }
}
Response 200: {
    "jobId": str,
    "status": "plan_approved",
    "pagePlan": { ... }     # final approved plan
}
Response 409: Plan already approved or expired
Response 422: Edit validation errors (e.g., template type not in whitelist)

# --- Reject the page plan ---
POST /api/v1/imports/jobs/{job_id}/plan/reject
Request body: {
    "reason": Optional[str]
}
Response 200: {"jobId": str, "status": "plan_rejected"}
```

**Option B -- New `/api/v1/ai/ingestions` router** (for cleaner separation once AI module exists per US-AI-003):

```python
POST   /api/v1/ai/ingestions/{job_id}/plan  (trigger re-segmentation)
GET    /api/v1/ai/ingestions/{job_id}/plan
POST   /api/v1/ai/ingestions/{job_id}/plan/approve
POST   /api/v1/ai/ingestions/{job_id}/plan/reject
```

### 2.4 Service Signatures

```python
# --- app/services/ai/extractors/base.py ---

class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, file_path: str) -> ExtractedDocument:
        """Deterministically extract sections from a document.
        Args:
            file_path: Absolute path to the uploaded document file.
        Returns:
            Normalized ExtractedDocument with sections, warnings, metadata.
        Raises:
            ExtractionError: On unrecoverable extraction failure.
        """

class ExtractionError(Exception):
    def __init__(self, code: str, message: str, recoverable: bool = False):
        self.code = code          # UNSUPPORTED_FORMAT, CORRUPT_FILE, ENCRYPTED, etc.
        self.recoverable = recoverable
        self.message = message


# --- app/services/ai/extractors/pdf_extractor.py ---

class PdfExtractor(BaseExtractor):
    """Extracts structured content from PDF files.
    
    Uses PyMuPDF (fitz) for text extraction with positional layout awareness
    and pdfplumber for table extraction as a secondary pass.
    """
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100 MB
    MAX_PAGES: int = 200

    async def extract(self, file_path: str) -> ExtractedDocument:
        # 1. Validate file size and page count
        # 2. Open with fitz.open()
        # 3. For each page: extract text blocks with font size/weight for heading detection
        #    - Font size > 14pt + bold = Heading 1
        #    - Font size > 12pt + bold = Heading 2
        #    - Font size > 11pt = Heading 3
        #    - Default = body_text
        # 4. Run pdfplumber on each page for table detection
        # 5. Detect inline images via fitz.Page.get_images()
        # 6. Build ExtractedSection list grouped by heading hierarchy
        # 7. Return ExtractedDocument with precise source offsets
        ...


# --- app/services/ai/extractors/docx_extractor.py ---

class DocxExtractor(BaseExtractor):
    """Extracts structured content from DOCX files.
    
    Uses python-docx to access the XML document model directly
    (paragraph styles, heading levels, tables, inline images).
    """
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50 MB
    MAX_PARAGRAPHS: int = 5000

    async def extract(self, file_path: str) -> ExtractedDocument:
        # 1. Validate file size and paragraph count
        # 2. Open with docx.Document()
        # 3. Iterate document.body:
        #    - Paragraph with style "Heading 1" -> section boundary, heading_level=1
        #    - Paragraph with style "Heading 2" -> section boundary, heading_level=2
        #    - Paragraph with style "Heading 3" -> section boundary, heading_level=3
        #    - Paragraph with style "Normal" or no style -> body text, appended to current section
        #    - Table -> detect if within a heading section, extract rows to table_data
        #    - Inline shape / image -> add to media_refs
        # 4. Build ExtractedSection list
        # 5. Return ExtractedDocument
        ...


# --- app/services/ai/segmenter.py ---

class DocumentSegmenter:
    """Uses the configured LLM to map extracted sections to a course page plan.
    
    This is the ONLY non-deterministic step in the extraction pipeline.
    All outputs are validated against strict rules before storage.
    """

    ALLOWED_TEMPLATE_TYPES: set[str] = {
        "welcome", "content-text", "content-video", "summary",
        "tabs", "accordion", "mcq", "final-assessment"
    }

    MAX_PROPOSED_PAGES: int = 50
    MAX_RATIONALE_LENGTH: int = 500

    def __init__(
        self,
        model_router: Optional[ModelRouter] = None,
        template_repo: Optional[TemplateTypeRepository] = None,
        max_pages: int = 50,
    ):
        self.model_router = model_router
        self.template_repo = template_repo
        self.max_pages = max_pages

    async def segment(
        self,
        document: ExtractedDocument,
        session_id: str,
    ) -> tuple[list[PageProposalItem], SegmentationValidation]:
        """Run the LLM segmenter and validate results.
        
        Args:
            document: The normalized extracted document.
            session_id: Active AI session for traceability.
            
        Returns:
            (proposed_pages, validation_result)
            
        Raises:
            SegmenterError: If the LLM call fails or output is unparseable.
        """
        # 1. Build segmentation prompt from document + template allowlist
        prompt = self._build_segmentation_prompt(document)
        
        # 2. Call LLM via model router with structured output constraint
        llm_output = await self.model_router.complete(
            prompt=prompt,
            output_schema=PageProposalItem,  # structured extraction
            session_id=session_id,
        )
        
        # 3. Parse and validate LLM output
        proposed_pages = self._parse_llm_output(llm_output)
        validation = await self._validate_segmentation(proposed_pages, document)
        
        return proposed_pages, validation

    def _build_segmentation_prompt(self, document: ExtractedDocument) -> str:
        """Build a prompt from the extracted document sections and allowed templates.
        
        The prompt is truncated to fit within model context window.
        If the document exceeds context, sections from the beginning and end
        are preserved with a summary of omitted middle sections.
        """
        ...

    async def _validate_segmentation(
        self,
        pages: list[PageProposalItem],
        document: ExtractedDocument,
    ) -> SegmentationValidation:
        """Validate LLM output against extraction and business rules."""
        errors: list[SegmentationError] = []
        warnings: list[str] = []
        
        # Check 1: All proposed template types are in the allowlist
        for idx, page in enumerate(pages):
            if page.suggested_template_type not in self.ALLOWED_TEMPLATE_TYPES:
                errors.append(SegmentationError(
                    code="UNSUPPORTED_TEMPLATE",
                    field=f"proposed_pages[{idx}].suggested_template_type",
                    message=f"Template type '{page.suggested_template_type}' is not in the allowed list",
                ))
        
        # Check 2: Every source section is mapped at least once
        mapped_section_ids = set()
        for page in pages:
            for sid in page.source_section_ids:
                mapped_section_ids.add(sid)
        all_section_ids = {s.section_id for s in document.sections}
        unmapped = all_section_ids - mapped_section_ids
        if unmapped:
            warnings.append(f"{len(unmapped)} section(s) not mapped to any page: {list(unmapped)[:5]}...")
        
        # Check 3: No duplicate source section mappings (a section mapped to >1 page)
        section_page_counts: dict[str, int] = {}
        for page in pages:
            for sid in page.source_section_ids:
                section_page_counts[sid] = section_page_counts.get(sid, 0) + 1
        duplicates = {k: v for k, v in section_page_counts.items() if v > 1}
        if duplicates:
            errors.append(SegmentationError(
                code="DUPLICATE_SOURCE",
                field="proposed_pages",
                message=f"{len(duplicates)} section(s) mapped to multiple pages",
            ))
        
        # Check 4: Page count within limit
        if len(pages) > self.max_pages:
            errors.append(SegmentationError(
                code="PAGE_COUNT_EXCEEDED",
                field="proposed_pages",
                message=f"Proposed {len(pages)} pages exceeds maximum of {self.max_pages}",
            ))
        
        coverage = len(mapped_section_ids) / len(all_section_ids) if all_section_ids else 1.0
        
        return SegmentationValidation(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            coverage=coverage,
        )


# --- app/services/ai/page_plan_service.py ---

class PagePlanService:
    """Orchestrates the document extraction -> segmentation -> plan lifecycle."""
    
    def __init__(self, db_session: AsyncSession, storage_service: StorageService):
        self.session = db_session
        self.job_repo = ImportJobRepository(db_session)
        self.storage = storage_service
        self.extractors: dict[str, BaseExtractor] = {
            "pdf": PdfExtractor(),
            "docx": DocxExtractor(),
        }
        self.segmenter = DocumentSegmenter(
            template_repo=TemplateTypeRepository(db_session),
        )
    
    async def extract_and_segment(self, job_id: str) -> dict:
        """Run extraction and segmentation for a staged ingestion job.
        
        Called by a background task worker after upload completes.
        
        Args:
            job_id: The ingestion job ID.
            
        Returns:
            Updated job metadata dict with extraction + page plan.
            
        Raises:
            FileNotFoundError: Uploaded file not found in storage.
            ExtractionError: If neither extractor can process the file.
            SegmenterError: If LLM segmentation fails after retries.
        """
        # 1. Load job and validate status
        job = await self.job_repo.get_by_id(job_id)
        if not job or job.status not in ("uploaded", "analyzing"):
            raise ValueError(f"Job {job_id} not in extractable state")
        
        await self.job_repo.update_status(job_id, "extracting", progress=0.1)
        
        # 2. Resolve extractor by file type
        source_path = job.source_file_path
        file_ext = os.path.splitext(source_path)[1].lower().lstrip(".")
        extractor = self.extractors.get(file_ext)
        if not extractor:
            raise ExtractionError(
                code="UNSUPPORTED_FORMAT",
                message=f"No extractor for .{file_ext} files",
            )
        
        # 3. Extract document
        document = await extractor.extract(source_path)
        await self.job_repo.update_status(job_id, "extracting", progress=0.5)
        
        # 4. Run LLM segmentation
        await self.job_repo.update_status(job_id, "segmenting", progress=0.7)
        proposed_pages, validation = await self.segmenter.segment(
            document=document,
            session_id=job.course_id or "",  # placeholder until AI session linkage
        )
        
        # 5. Build page plan payload
        page_plan = {
            "proposed_pages": [p.model_dump() for p in proposed_pages],
            "validation": validation.model_dump(),
            "user_edits": None,
            "status": "pending_review" if validation.valid else "validation_failed",
        }
        
        # 6. Merge into existing job result_data
        result_data = dict(job.result_data or {})
        result_data["extraction"] = document.model_dump()
        result_data["page_plan"] = page_plan
        
        await self.job_repo.update_result(job_id, result_data)
        new_status = "plan_ready" if validation.valid else "plan_validation_failed"
        await self.job_repo.update_status(job_id, new_status, progress=1.0)
        
        return result_data
    
    async def get_page_plan(self, job_id: str) -> Optional[dict]:
        """Retrieve the current page plan for an ingestion job."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            return None
        return (job.result_data or {}).get("page_plan")
    
    async def approve_plan(
        self,
        job_id: str,
        edits: Optional[dict] = None,
        user_id: str = "system",
    ) -> dict:
        """Approve the page plan, optionally with user edits.
        
        Validates edits, applies them to the plan, transitions job to plan_approved.
        
        Args:
            job_id: Ingestion job ID.
            edits: Optional user modifications to the proposed plan.
            user_id: User who approved (for audit).
            
        Returns:
            Updated page plan.
            
        Raises:
            ValueError: If job not found or not in plan_ready state.
            ValidationError: If edits fail validation.
        """
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.status != "plan_ready":
            raise ValueError(f"Job status is {job.status}, expected plan_ready")
        
        result_data = dict(job.result_data or {})
        page_plan = dict(result_data.get("page_plan", {}))
        proposed = page_plan.get("proposed_pages", [])
        
        # Apply user edits
        if edits:
            page_plan["user_edits"] = edits
            proposed = self._apply_edits(proposed, edits)
            page_plan["proposed_pages"] = proposed
        
        # Re-validate after edits
        document = ExtractedDocument(**result_data["extraction"])
        new_validation = await self.segmenter._validate_segmentation(
            [PageProposalItem(**p) for p in proposed],
            document,
        )
        if not new_validation.valid:
            raise ValidationError("Edited plan failed validation", new_validation.errors)
        
        page_plan["validation"] = new_validation.model_dump()
        page_plan["status"] = "approved"
        result_data["page_plan"] = page_plan
        
        await self.job_repo.update_result(job_id, result_data)
        await self.job_repo.update_status(job_id, "plan_approved", progress=1.0)
        
        return page_plan
    
    def _apply_edits(self, proposed: list[dict], edits: dict) -> list[dict]:
        """Apply user edits to a proposed page plan.
        
        Supports: reorder, retitle, template_changes, merges, splits.
        """
        # Logic to apply each edit type
        ...
```

### 2.5 Database Schema Changes

Add a dedicated AI ingestion table rather than overloading the existing `import_jobs` table (which is SCORM-specific). This clean separation follows the pattern from US-AI-003 (isolated AI module).

**New table: `ai_ingestion_jobs`** (Alembic migration required):

```sql
CREATE TABLE ai_ingestion_jobs (
    id              SERIAL PRIMARY KEY,
    job_id          VARCHAR(64) UNIQUE NOT NULL,
    ai_session_id   VARCHAR(64),                     -- FK to ai_sessions (US-AI-004)
    course_id       VARCHAR(64),                     -- target course
    source_filename VARCHAR(500) NOT NULL,
    source_type     VARCHAR(10) NOT NULL,             -- 'pdf' | 'docx'
    source_size_bytes BIGINT NOT NULL,
    storage_path    VARCHAR(1000) NOT NULL,           -- path in storage backend
    
    -- Status machine
    status          VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    progress        FLOAT NOT NULL DEFAULT 0.0,
    
    -- Extraction output (normalized document structure)
    extracted_data  JSONB,                            -- ExtractedDocument
    
    -- Page plan data
    plan_proposed_pages JSONB,                        -- list[PageProposalItem]
    plan_validation     JSONB,                        -- SegmentationValidation
    plan_user_edits     JSONB,                        -- user modifications
    plan_status         VARCHAR(32),                  -- pending_review | approved | rejected
    
    -- Error handling
    error_message   TEXT,
    error_code      VARCHAR(64),
    
    -- Traceability
    trace_id        VARCHAR(64),
    created_by      VARCHAR(100),
    
    -- Timestamps
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    CONSTRAINT fk_ai_session
        FOREIGN KEY (ai_session_id) REFERENCES ai_sessions(session_id)
        ON DELETE SET NULL
);

CREATE INDEX idx_ai_ingestion_jobs_status ON ai_ingestion_jobs(status);
CREATE INDEX idx_ai_ingestion_jobs_session ON ai_ingestion_jobs(ai_session_id);
CREATE INDEX idx_ai_ingestion_jobs_course ON ai_ingestion_jobs(course_id);
```

**Note:** This table can be defined in `app/models/ai_ingestion.py` following the pattern of `app/models/persisted_course.py`. If the team prefers to defer new tables and reuse `import_jobs`, the page plan data is stored in `result_data` (JSON) and a `page_plan_status` enum column  is added to `import_jobs`.

### 2.6 Environment Variables

```python
# New env vars for US-AI-017
AI_EXTRACTION_MAX_FILE_SIZE_MB: int = 100        # max upload size for extraction
AI_EXTRACTION_MAX_PAGES: int = 200                # max pages to extract
AI_EXTRACTION_ENABLE_PDF: bool = True             # toggle PDF extraction
AI_EXTRACTION_ENABLE_DOCX: bool = True            # toggle DOCX extraction
AI_PAGE_PLAN_MAX_PAGES: int = 50                  # max pages in a proposed plan
AI_PAGE_PLAN_MAX_RATIONALE_LENGTH: int = 500      # max chars per rationale text
AI_PAGE_PLAN_AUTO_APPROVE_ROLES: str = "admin,instructor"  # comma-separated roles
```

These are added to `app/services/ai/settings.py` (new) mirroring the pattern in `app/db/config.py`.

### 2.7 Dependencies

Add to `requirements.txt` or `pyproject.toml`:

```toml
# Document extraction
PyMuPDF >= 1.23.0           # PDF extraction (fitz)
python-docx >= 1.1.0        # DOCX extraction
pdfplumber >= 0.10.0        # Table extraction from PDFs (supplementary)
```

### 2.8 Background Processing Integration

If the durable workflow engine from US-AI-034 is available, the extract-and-segment pipeline runs as a `FileIngestionWorkflow` with checkpointed phases:
1. `download_from_storage`
2. `extract_document` (runs extraction worker)
3. `segment_with_llm` (calls LLM via model router)
4. `validate_segmentation` (deterministic)
5. `wait_for_human_review` (pauses workflow until approve/reject endpoint is hit)

If US-AI-034 is not yet implemented, the pipeline runs synchronously (for files under 10 MB) or via a simple Celery/ARQ background task.

---

## 3. Non-Functional Requirements

| Category | Requirement | Target | Measurement |
|---|---|---|---|
| **Performance** | Extraction time for a 50-page PDF | < 5 seconds | Timer in extraction service |
| **Performance** | LLM segmentation latency (P95) | < 15 seconds | APM trace on segmenter call |
| **Performance** | Page plan approval/edits API | < 500 ms (P99) | API response time monitoring |
| **Reliability** | Extraction failure rate | < 1% for valid PDF/DOCX | Error counting in extraction service |
| **Reliability** | LLM segmentation retries on parse failure | 2 retries before failing the job | Retry counter in segmenter |
| **Scalability** | Concurrent extractions per node | 4 | Worker pool sizing in settings |
| **Storage** | Extracted document JSON in DB | < 1 MB per job | Result_data size cap check |
| **Security** | Uploaded files scanned | 100% before extraction | Malware scan integration |
| **Security** | File type enforcement | Reject non-PDF/DOCX/ZIP | Content-type + magic bytes check |
| **Observability** | Extraction + segmentation traced | 100% of jobs | Trace ID in logs + APM |
| **Observability** | LLM token usage per segmentation | Tracked and emitted | Cost tracker integration (US-AI-036) |

---

## 4. Current State Analysis

### 4.1 What Exists Today

The repository at `C:\Users\ADMIN\e-learning-backend` has:

- **SCORM import path** (`/api/v1/imports/analyze` -> `ImportService` in `app/services/import_service.py`): Handles ZIP/SCORM packages via `StrategyRegistry`, `HeuristicParser`, `SchemaInferenceEngine`, and `AssetRewriter`. Outputs a flat `templates[]` list. Does **not** support PDF/DOCX, does **not** produce a structured section-level page plan.

- **`ImportJob` table** (`app/models/persisted_course.py`): Tracks SCORM imports. Uses `result_data` JSON column for staged course data. No page plan status fields.

- **`ImportJobRepository`** (`app/repositories/import_job_repository.py`): CRUD with `create`, `update_status`, `update_result`, `get_by_id`. No page-plan-specific methods.

- **`TemplateTypeRepository`** (`app/repositories/template_type_repo.py`): Provides `list(active_only=True)`, `get_by_template_id`. Ready to supply the template allowlist.

- **`ExportValidator`** (`app/services/export_validator.py`): Validates component types against the renderer manifest. Can be reused for segmentation validation.

- **`CourseRepository`** (`app/repositories/course_repo.py`): Standard CRUD. Pages live in the PageRecord/ComponentRecord model (pages + components tables).

- **`FeatureFlagService`** (`app/utils/feature_flags.py`): Enables feature gating for AI. Currently no AI-specific ingestion flag.

- **No PDF or DOCX extraction code exists** in the repository today.

- **No AI-specific routers** exist yet (US-AI-003 not implemented). The plan-surface can be added to `app/routers/imports.py` as interim.

- **No AI session persistence** exists (US-AI-004 not implemented). Traceability will use job_id + user_id as fallback until sessions are available.

### 4.2 Gaps This Story Fills

1. Zero document extraction capability for non-SCORM sources.
2. No structured section-level output from ingestion (current ImportService produces flat template lists).
3. No human review checkpoint between file upload and content generation.
4. No page-plan data model, validation rules, or edit semantics.
5. No background processing pipeline for extraction (currently synchronous upload-analyze).

---

## 5. Expansion Points

| Feature | Triggered By | Dependencies | Notes |
|---|---|---|---|
| DOCX table extraction enhancement | User feedback on table quality | None | Upgrade python-docx parsing to extract merged cells, nested tables |
| OCR fallback for image-based PDFs | PDF with no selectable text | Tesseract integration | Add TesseractOCR extractor as secondary pass |
| PPTX extraction | User demand for PowerPoint imports | New extractor class | Implement `PptxExtractor(BaseExtractor)` |
| HTML/document URL extraction | Workflow automation requests | New extractor class + download service | Accept URL, download, extract |
| Multi-document merging | Users uploading multiple files per course | US-AI-029 (batch proposals) | Merge multiple extractions into one page plan |
| Auto-approve for trusted documents | Admin efficiency requirements | US-AI-032 (policy engine), US-AI-002 (flags) | Deterministic rules skip human review |
| Extraction preview in frontend without LLM | Author wants to see raw sections first | Frontend AI integration (US-AI-024) | Show ExtractedDocument before segmentation |
| Re-segmentation with different prompt | Author dislikes initial template suggestions | None | POST to re-run segmenter with override prompt |
| Custom template type overrides per section | Advanced authors | US-AI-005 (tool contracts) | Allow manual template assignment during review |

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (in `tests/test_ai_extraction.py`)

```python
# --- PDF Extraction ---

async def test_pdf_extractor_simple_document():
    """A well-structured PDF with Heading 1/2/3 produces correct ExtractedDocument."""
    extractor = PdfExtractor()
    result = await extractor.extract("tests/fixtures/simple_course.pdf")
    assert result.total_pages == 10
    assert result.total_sections == 5
    assert result.sections[0].heading_level == 1
    assert len(result.warnings) == 0

async def test_pdf_extractor_encrypted_file():
    """Encrypted PDF raises ExtractionError with recoverable=False."""
    extractor = PdfExtractor()
    with pytest.raises(ExtractionError) as exc:
        await extractor.extract("tests/fixtures/encrypted.pdf")
    assert exc.value.code == "ENCRYPTED"
    assert exc.value.recoverable is False

async def test_pdf_extractor_image_only():
    """Scanned/image-only PDF returns empty sections with warning."""
    extractor = PdfExtractor()
    result = await extractor.extract("tests/fixtures/scanned.pdf")
    assert len(result.sections) == 0
    assert any("no selectable text" in w for w in result.warnings)

async def test_pdf_extractor_tables():
    """Table extraction returns valid table_data for pages with tables."""
    ...

# --- DOCX Extraction ---

async def test_docx_extractor_heading_hierarchy():
    """DOCX heading styles correctly map to heading_level."""
    extractor = DocxExtractor()
    result = await extractor.extract("tests/fixtures/structured.docx")
    assert result.sections[0].heading_level == 1
    assert result.sections[0].heading == "Introduction"
    assert result.sections[1].heading_level == 2

async def test_docx_extractor_embedded_images():
    """DOCX with embedded images produces media_refs."""
    ...

async def test_docx_extractor_exceeds_paragraph_limit():
    """DOCX exceeding MAX_PARAGRAPHS raises ExtractionError."""
    ...

# --- Segmentation ---

async def test_segmenter_valid_output():
    """Valid LLM output produces valid PageProposalItems with full coverage."""
    document = load_fixture_document()
    segmenter = DocumentSegmenter(max_pages=50)
    pages, validation = await segmenter.segment(document, session_id="test")
    assert validation.valid is True
    assert validation.coverage == 1.0
    assert all(p.suggested_template_type in ALLOWED_TEMPLATES for p in pages)

async def test_segmenter_unmapped_sections():
    """LLM output that misses sections produces coverage < 1.0 with warning."""
    ...

async def test_segmenter_unsupported_template():
    """LLM output using unapproved template type produces validation error."""
    ...

async def test_segmenter_duplicate_source_mappings():
    """Same section mapped to 2 pages produces validation error."""
    ...

async def test_segmenter_page_count_exceeded():
    """LLM output > max_pages produces validation error."""
    ...

async def test_segmenter_truncated_prompt():
    """Document exceeding model context is truncated gracefully."""
    ...

# --- Page Plan Service ---

async def test_page_plan_service_extract_and_segment():
    """End-to-end: stored ingestion job transitions to plan_ready."""
    service = PagePlanService(db_session, storage_service)
    result = await service.extract_and_segment("test-job-1")
    assert result["page_plan"]["status"] == "pending_review"

async def test_page_plan_service_approve_no_edits():
    """Approval without edits transitions job to plan_approved."""
    plan = await service.approve_plan("test-job-1")
    assert plan["status"] == "approved"

async def test_page_plan_service_approve_with_retitle():
    """Approval with retitle edits produces updated page titles."""
    edits = {"retitle": {"0": "Updated Title"}}
    plan = await service.approve_plan("test-job-1", edits=edits)
    assert plan["proposed_pages"][0]["proposed_title"] == "Updated Title"

async def test_page_plan_service_approve_with_merge():
    """Approval with merge edits combines pages correctly."""
    ...

async def test_page_plan_service_approve_stale_job():
    """Approval of job in wrong status raises ValueError."""
    with pytest.raises(ValueError):
        await service.approve_plan("committed-job-1")

async def test_page_plan_service_reject():
    """Rejection transitions job to plan_rejected."""
    ...
```

### 6.2 Integration Tests (in `tests/test_ai_ingestion_api.py`)

```python
async def test_get_plan_after_upload():
    """After upload completes, GET /plan returns extraction + page_plan."""
    # Upload a small PDF
    upload_resp = await client.post("/api/v1/imports/analyze", ...)
    job_id = upload_resp.json()["jobId"]
    
    # Wait for extraction (poll)
    plan_resp = await client.get(f"/api/v1/imports/jobs/{job_id}/plan")
    assert plan_resp.status_code == 200
    data = plan_resp.json()
    assert data["status"] in ("plan_ready", "plan_validation_failed")
    if data["status"] == "plan_ready":
        assert "pagePlan" in data
        assert len(data["pagePlan"]["proposedPages"]) > 0

async def test_approve_plan_endpoint():
    """Approving a plan returns plan_approved and locks the plan."""
    job_id = await upload_and_wait_for_plan()
    resp = await client.post(f"/api/v1/imports/jobs/{job_id}/plan/approve", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "plan_approved"

async def test_approve_plan_with_edits():
    """Approving with retitle edits returns updated plan."""
    job_id = await upload_and_wait_for_plan()
    resp = await client.post(
        f"/api/v1/imports/jobs/{job_id}/plan/approve",
        json={"edits": {"retitle": {"0": "My Custom Title"}}}
    )
    assert resp.status_code == 200
    assert resp.json()["pagePlan"]["proposedPages"][0]["proposedTitle"] == "My Custom Title"

async def test_approve_plan_invalid_edit():
    """Changing template to unsupported type returns 422."""
    resp = await client.post(
        f"/api/v1/imports/jobs/{job_id}/plan/approve",
        json={"edits": {"template_changes": {"0": "unsupported-template-type"}}}
    )
    assert resp.status_code == 422

async def test_double_approve_rejected():
    """Approving an already-approved plan returns 409."""
    ...

async def test_reject_plan():
    """Plan rejection transitions job correctly."""
    ...

async def test_plan_for_nonexistent_job():
    """GET /plan for unknown job returns 404."""
    resp = await client.get("/api/v1/imports/jobs/nonexistent/plan")
    assert resp.status_code == 404
```

### 6.3 Edge Cases

| Scenario | Expected Behavior |
|---|---|
| PDF with no selectable text (scanned) | `ExtractedDocument.sections` is empty, warning generated. Segmenter returns validation with `coverage: 0.0` and error. Job status `plan_validation_failed`. |
| DOCX with 5000+ paragraphs | Extraction error with `code=TOO_LARGE`. User sees actionable message. |
| PDF embedded fonts causing garbled text | Text is extracted but may be low quality. Warning added. Segmenter may produce poor page plan but does not block. |
| LLM output is valid JSON but hallucinates non-existent template types | Validation catches them with `UNSUPPORTED_TEMPLATE`. Plan status `plan_validation_failed`. |
| LLM segmenter returns no pages (empty array) | Validation catches with coverage = 0. Error. |
| User uploads corrupt PDF (0 bytes, no header) | Extractor raises `ExtractionError(code="CORRUPT_FILE")`. Job marked failed. |
| User attempts to approve without any proposed pages | `approve_plan` raises validation error. |
| Network failure during LLM segmenter call | Retry 2 times with exponential backoff. On final failure, job marked `failed` with `error_code=LLM_SEGMENTATION_FAILED`. |
| Concurrent approval requests | First succeeds, second returns 409 (optimistic locking via plan_status check). |

### 6.4 Non-Function Test Scenarios

| Scenario | Tool | Pass Criteria |
|---|---|---|
| Extract 50-page PDF under 5 seconds | `locust` extraction benchmark | P95 extraction time < 5s |
| Segment a 40-section document < 15 seconds | APM trace on segmenter | P95 LLM call time < 15s |
| 10 concurrent upload+extract requests | `locust` load test on `/analyze` | No 5xx, all complete within 60s |
| Plan approval endpoint under 500ms P99 | `locust` on `/plan/approve` | P99 < 500ms |
| Upload 150MB file | Manual test | 413 response, not 500 |

---

## 7. Definition of Done

1. **PDF Extraction** -- `PdfExtractor` produces `ExtractedDocument` with correct sections, headings (font-size/weight detection), page numbers, and inline image references for valid PDFs. Extraction errors for encrypted, corrupt, or image-only PDFs are handled with typed `ExtractionError` and sensible user-facing messages.

2. **DOCX Extraction** -- `DocxExtractor` produces `ExtractedDocument` mapping Heading 1/2/3 styles to section boundaries. Tables are extracted as `table_data`. Embedded images produce `media_refs`.

3. **LLM Segmenter** -- `DocumentSegmenter` maps extracted sections to a proposed page plan using the configured model. The segmenter validates its own output for template type allowlist, source coverage, duplicate offsets, and page count limits. Failed segmentation or unrecoverable LLM errors transition the job to a terminal failure state with a clear error code.

4. **Segmentation Validation** -- `PageProposalItem` and `SegmentationValidation` models are implemented exactly as specified in section 1.3. Validation covers: template allowlist (only `ALLOWED_MVP_TEMPLATE_TYPES`), source section coverage (every section mapped -> coverage=1.0, sections with coverage < 1.0 produce a warning but do not block), no duplicate source ranges, page count limit.

5. **Page Plan API** -- Three endpoints are implemented and tested: `GET /plan` (returns extraction + page plan), `POST /plan/approve` (with optional edits), and `POST /plan/reject`. All respond with the normalized error envelope from `app/utils/error_envelope.py`.

6. **User Edits on Approval** -- The approval endpoint accepts and validates: `reorder` (drag-and-drop ordering of proposed pages), `retitle` (per-page title overrides), `template_changes` (alternate template type subject to the same allowlist), `merges` (combine source pages into one target), and `splits` (split one page into two with new titles). All edits are validated before the plan is locked.

7. **Background Processing** -- Extraction runs in a background worker (either US-AI-034 durable workflow or simple background task). Job status progresses through `uploaded -> extracting -> segmenting -> plan_ready | plan_validation_failed`. Frontend polls the job endpoint for status updates.

8. **Database Migration** -- Either the new `ai_ingestion_jobs` table defined in section 2.5 is added via Alembic migration, or the existing `import_jobs` table gains `page_plan_status` and the extraction data is stored in `result_data` JSON. Either way, the migration is backward-compatible and no existing SCORM import data is affected.

9. **Tests** -- All unit test scenarios in section 6.1 pass. All integration test scenarios in section 6.2 pass. Extraction test fixtures (small PDF, small DOCX) exist in `tests/fixtures/`. Code coverage for new extraction and segmentation code is > 85%.

10. **Observability** -- Every extraction and segmentation call is logged with `job_id`, `trace_id`, duration, and token usage (for LLM step). Failures are logged with error code and stack trace. Extraction and segmentation metrics are emitted.

11. **Configuration** -- All env vars in section 2.6 are documented in a new `app/services/ai/settings.py` module. Sensible defaults are provided. Settings are loaded at service initialization.

12. **API Documentation** -- OpenAPI schemas for the new endpoints include all request/response models, error codes, and example payloads. A new OpenAPI tag `AI Ingestion` is added (or the endpoints are tagged under `Imports` if using the interim path).

---

## 8. Task Breakdown

### Task 1: Implement PDF Extractor
**File:** `app/services/ai/extractors/pdf_extractor.py`
**Acceptance:** `PdfExtractor.extract()` returns `ExtractedDocument` for test PDFs. Extracts headings, body text, tables, and image refs. Raises `ExtractionError` for encrypted/corrupt/image-only PDFs.
**Sub-tasks:**
- [ ] Install PyMuPDF and pdfplumber dependencies
- [ ] Implement `PdfExtractor` class with `extract()` method
- [ ] Implement heading detection via font size + weight heuristics
- [ ] Implement table extraction via pdfplumber secondary pass
- [ ] Implement inline image reference detection
- [ ] Add error handling for encrypted, corrupt, and empty PDFs
- [ ] Add file size and page count guards
- [ ] Write unit tests (5+ scenarios)

### Task 2: Implement DOCX Extractor
**File:** `app/services/ai/extractors/docx_extractor.py`
**Acceptance:** `DocxExtractor.extract()` returns `ExtractedDocument` for test DOCX files. Maps Heading 1/2/3 styles correctly. Extracts tables and embedded images.
**Sub-tasks:**
- [ ] Install python-docx dependency
- [ ] Implement `DocxExtractor` class with `extract()` method
- [ ] Implement heading hierarchy mapping (Heading 1/2/3 -> section boundaries)
- [ ] Implement table extraction
- [ ] Implement embedded image reference detection
- [ ] Add paragraph count guard and file size guard
- [ ] Write unit tests (5+ scenarios)

### Task 3: Implement Extraction Data Models
**File:** `app/services/ai/extractors/base.py`, `app/services/ai/segmenter.py` (models section)
**Acceptance:** `ExtractedDocument`, `ExtractedSection`, `ExtractedMediaRef`, `ExtractionError` are defined, exported, and importable. All extractors conform to the `BaseExtractor` abstract interface.
**Sub-tasks:**
- [ ] Define `BaseExtractor` abstract base class
- [ ] Define `ExtractedDocument`, `ExtractedSection`, `ExtractedMediaRef` Pydantic models
- [ ] Define `ExtractionError` exception hierarchy
- [ ] Define `PageProposalItem`, `SegmentationValidation`, `SegmentationError` Pydantic models
- [ ] Extract model constants (`ALLOWED_MVP_TEMPLATE_TYPES`, defaults)

### Task 4: Implement LLM Segmenter
**File:** `app/services/ai/segmenter.py`
**Acceptance:** `DocumentSegmenter.segment()` takes an `ExtractedDocument`, builds a prompt, calls the LLM, parses the result, validates it, and returns `(list[PageProposalItem], SegmentationValidation)`.
**Sub-tasks:**
- [ ] Implement prompt construction from extraction data + template allowlist
- [ ] Implement context window truncation strategy (keep first + last sections, summarize middle)
- [ ] Integrate with model router (ModelRouter from US-AI-026 or direct provider call)
- [ ] Implement LLM output parsing (expect JSON array of PageProposalItem)
- [ ] Implement segmentation validation rules (template allowlist, coverage, duplicates, page count)
- [ ] Add retry logic with exponential backoff (max 2 retries)
- [ ] Write unit tests for validation rules and prompt construction

### Task 5: Implement Page Plan Service
**File:** `app/services/ai/page_plan_service.py`
**Acceptance:** `PagePlanService` orchestrates the full extract -> segment -> validate -> store pipeline. `approve_plan` applies user edits, re-validates, and locks the plan. `get_page_plan` returns current state.
**Sub-tasks:**
- [ ] Implement `extract_and_segment()` orchestrator workflow
- [ ] Implement `get_page_plan()` retrieval
- [ ] Implement `approve_plan()` with edit application logic
- [ ] Implement edit validation (reorder, retitle, template_changes, merges, splits)
- [ ] Implement `reject_plan()`
- [ ] Integrate `ImportJobRepository` / `AiIngestionJobRepository`
- [ ] Write unit tests (8+ scenarios covering success, errors, edge cases)

### Task 6: Create Database Table / Migration
**File:** `alembic/versions/YYYYMMDD_HHMMSS_add_ai_ingestion_jobs.py`
**Acceptance:** New migration creates `ai_ingestion_jobs` table (or extends `import_jobs`). Down migration is clean. Migration is backward-compatible with existing SCORM import data.
**Sub-tasks:**
- [ ] Define SQLAlchemy model `AiIngestionJob` in `app/models/ai_ingestion.py` (or extend `ImportJob`)
- [ ] Generate Alembic migration with `alembic revision --autogenerate`
- [ ] Review and adjust migration script
- [ ] Test migration up/down on a copy of production data
- [ ] Add repository class for new table (`AiIngestionJobRepository`) following `ImportJobRepository` pattern

### Task 7: Implement API Endpoints
**File:** `app/routers/imports.py` (extend) or new `app/routers/ai_ingestion.py`
**Acceptance:** `GET /imports/jobs/{job_id}/plan`, `POST /imports/jobs/{job_id}/plan/approve`, `POST /imports/jobs/{job_id}/plan/reject` are implemented, documented in OpenAPI, and return the expected response shapes.
**Sub-tasks:**
- [ ] Add `GET /imports/jobs/{job_id}/plan` endpoint
- [ ] Add `POST /imports/jobs/{job_id}/plan/approve` endpoint with edit body validation
- [ ] Add `POST /imports/jobs/{job_id}/plan/reject` endpoint
- [ ] Add request/response Pydantic DTOs for all endpoints
- [ ] Wire error responses through `app/utils/error_envelope.py`
- [ ] Add OpenAPI tags and descriptions
- [ ] Register router in `app/main.py`
- [ ] Write integration tests (8+ scenarios)

### Task 8: Background Task Integration
**File:** `app/services/ai/page_plan_service.py` (extract_and_segment invocation)
**Acceptance:** After file upload completes, the extraction + segmentation pipeline runs in a background task (or workflow). Job status progresses correctly. The frontend can poll for progress.
**Sub-tasks:**
- [ ] Integrate with US-AI-034 durable workflow engine if available, or implement a simple asyncio background task
- [ ] Wire the upload endpoint to trigger `extract_and_segment` after file storage
- [ ] Ensure the background task catches all exceptions and transitions job to `failed` with error details
- [ ] Add progress reporting (0.1 extraction, 0.5 segmenting, 0.9 validating, 1.0 done)
- [ ] Write integration test for the full upload-to-plan flow

### Task 9: Configuration and Environment Setup
**File:** `app/services/ai/settings.py`
**Acceptance:** All env vars documented, loaded at service init, with sensible defaults.
**Sub-tasks:**
- [ ] Create `app/services/ai/settings.py` with `@dataclass` settings class
- [ ] Wire env vars with `os.getenv()` defaults as specified in section 2.6
- [ ] Validate required settings at service initialization
- [ ] Update `.env.example` with new variables
- [ ] Update `docs/DEPLOYMENT.md` with new configuration

### Task 10: End-to-End Testing and Documentation
**Acceptance:** Full E2E flow works end-to-end. All test scenarios pass. Developer documentation updated.
**Sub-tasks:**
- [ ] Prepare test fixture files (5-page PDF, 10-page DOCX, scanned PDF, encrypted PDF)
- [ ] Run full integration test suite against a test database
- [ ] Run non-functional tests (extraction benchmark, concurrent load)
- [ ] Verify OpenAPI docs render all new endpoints correctly
- [ ] Update `docs/AI_Implemenation/00_User_StoriesUseCases/USER_STORIES.md` to mark US-AI-017 as enriched
- [ ] Update `docs/API.md` with the new endpoints
- [ ] Verify all new models and services are importable in a Python shell

---
Now I have a thorough understanding of the codebase. Let me write the complete enriched epic.

---

# User Story US-AI-018: Display Course Validation Reports to Authors and Reviewers

## 1. Functional Specification

### 1.1 Summary
As a **Reviewer**, I want a validation report linked to affected pages/components, so that I can quickly resolve issues before apply or export.

### 1.2 Source Flow
Flow 6 (Course Validation Flow). See `docs/AI_Implemenation/01_SystemArchitecture/Course_Validation_Flow.mmd` for the canonical diagram.

### 1.3 Priority
SHOULD (MVP scope). Depends on US-AI-008 (validation pipeline).

### 1.4 Actors
- **Author**: triggers validation from the AI chat panel or manual edit view
- **Reviewer**: reviews validation reports before approving proposals
- **System**: orchestrates validation and returns structured results
- **Frontend**: renders the report with navigation links to affected items

### 1.5 Functional Requirements

**FR-01: Trigger validation on demand**
- User clicks "Validate" from course-level toolbar, page-level editor, or proposal review panel.
- Backend accepts `POST /api/v1/courses/{courseId}/validate` (DB-backed) and `POST /api/v1/courses/validate` (ad-hoc payload).
- Result returned synchronously for courses under ~200 pages; larger courses return a `jobId` for polling (see FR-06).

**FR-02: Categorized validation findings**
Every validation finding includes:
- `id` — stable unique error code (e.g., `page-3-mcq-no-correct-answer`)
- `field` — deterministic dot-path to the offending field (e.g., `pages[2].components[0].data.options`)
- `category` — one of `schema`, `business`, `template`, `export`, `accessibility`
- `message` — human-readable English description
- `level` — `error` (blocks apply/export), `warning` (advisory), `info` (hint)
- `context` — optional map with remediation hints, expected values, or validator name
- `pageId` — the affected page UUID (null if course-level)
- `componentId` — the affected component UUID (null if page-level)

**FR-03: Blocking errors block proposal apply**
- The proposal apply button is disabled when any `level=error` finding exists.
- Warnings do not block apply but are visually distinct (yellow/amber).
- The LLM receives a structured error feed when validation fails so it can self-correct within the chat turn.

**FR-04: Navigation from issue to source**
- Each finding carries `pageId` and `componentId` so the frontend can anchor-scroll to the offending element.
- Clicking a finding navigates to the course outline (page-level) or component editor (component-level).

**FR-05: Report metadata**
Each validation response includes:
- `timestamp` — ISO 8601 UTC when validation ran
- `valid` — boolean shorthand (`true` when zero errors)
- `errorCount`, `warningCount`, `infoCount` — aggregates
- `schemaVersion` — the schema version used to validate
- `courseHash` — stable SHA-256 of the course state at validation time
- `durationMs` — wall-clock time for the validation run

**FR-06: Async validation for large courses**
- Courses with >200 pages or >500 components return HTTP 202 with a `jobId`.
- Frontend polls `GET /api/v1/validation/jobs/{jobId}` until status is `completed` or `failed`.
- Job progress tracks through phases: `fetching` -> `validating` -> `export-check` -> `done`.

**FR-07: Re-validate after manual edits**
- Frontend auto-triggers re-validation when the user saves a page or component.
- The validation report refreshes in place without a full page reload.
- Debounced (300ms) to avoid flooding the backend on rapid edits.

**FR-08: Validation on export gate**
- The export endpoint (`POST /api/v1/export/scorm/{courseId}`) runs validation before generating the ZIP.
- Export-blocking errors return HTTP 422 with the full validation report.

---

## 2. Technical Specification

### 2.1 New Files to Create

```
app/routers/validation.py          # Validation router (separate from courses.py)
app/services/validation/__init__.py
app/services/validation/pipeline.py # Orchestrator for multi-phase validation
app/services/validation/schema.py   # Schema/Pydantic-model checks
app/services/validation/business.py # Business rule checks per template
app/services/validation/export.py   # Export-readiness checks (delegates to ExportValidator)
app/services/validation/accessibility.py  # WCAG 2.1 AA checks
app/repositories/validation_repo.py # Persistence for validation jobs and results
app/models/validation.py            # SQLAlchemy model for validation_jobs table
```

### 2.2 New API Endpoints

```
VALIDATION_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "valid": {"type": "boolean"},
        "findings": {
            "type": "array",
            "items": {"$ref": "#/definitions/ValidationFinding"}
        },
        "errorCount": {"type": "integer"},
        "warningCount": {"type": "integer"},
        "infoCount": {"type": "integer"},
        "timestamp": {"type": "string", "format": "date-time"},
        "schemaVersion": {"type": "string"},
        "courseHash": {"type": "string"},
        "durationMs": {"type": "integer"}
    },
    "required": ["valid", "findings", "errorCount", "warningCount", "infoCount"]
}

ValidationFinding = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "field": {"type": "string"},
        "category": {"type": "string", "enum": ["schema","business","template","export","accessibility"]},
        "message": {"type": "string"},
        "level": {"type": "string", "enum": ["error","warning","info"]},
        "pageId": {"type": "string"},
        "componentId": {"type": "string"},
        "context": {"type": "object"}
    },
    "required": ["id", "field", "category", "message", "level"]
}
```

#### `POST /api/v1/courses/{courseId}/validate`
Validate a persisted course from the database.

**Request**: (no body — validates current DB state)

**Response 200**:
```json
{
  "valid": false,
  "findings": [
    {
      "id": "page-abc123-mcq-no-correct-answer",
      "field": "pages[2].components[3].data.options",
      "category": "business",
      "message": "MCQ 'Question 3' on page 'Knowledge Check' must have at least one correct answer selected",
      "level": "error",
      "pageId": "abc123",
      "componentId": "comp-456",
      "context": {
        "questionIndex": 2,
        "optionCount": 4,
        "remediation": "Set isCorrect=true on exactly one option"
      }
    },
    {
      "id": "page-def456-image-missing-alt",
      "field": "pages[1].components[0].data.altText",
      "category": "accessibility",
      "message": "Image component 'diagram.png' is missing alt text",
      "level": "warning",
      "pageId": "def456",
      "componentId": "comp-789",
      "context": {
        "remediation": "Add a descriptive altText attribute to the component data"
      }
    }
  ],
  "errorCount": 1,
  "warningCount": 1,
  "infoCount": 0,
  "timestamp": "2026-06-14T12:00:00Z",
  "schemaVersion": "1.0",
  "courseHash": "a1b2c3d4e5f6...",
  "durationMs": 87
}
```

**Response 202** (async — large course):
```json
{
  "jobId": "job-valid-xxx",
  "status": "processing",
  "pollUrl": "/api/v1/validation/jobs/job-valid-xxx"
}
```

#### `POST /api/v1/ai/proposals/{proposalId}/validate`
Validate only the changed scope of a proposal (delta validation).

**Request**: (none — reads proposal record)

**Response 200**: Same `ValidationReport` schema.

#### `POST /api/v1/courses/validate` (existing, extended)
Keep backward compatibility with the existing endpoint at `courses.py` lines 465-751. Extend it to return the new finding schema format. Add a `mode` query parameter:
- `mode=full` (default) — validates entire course data
- `mode=delta` — validates only the fields present in the request body (partial update validation)

#### `GET /api/v1/validation/jobs/{jobId}`
Poll async validation job status.

**Response 200**:
```json
{
  "jobId": "job-valid-xxx",
  "status": "completed",
  "progress": 1.0,
  "result": { "... full ValidationReport ..." },
  "createdAt": "2026-06-14T12:00:00Z",
  "completedAt": "2026-06-14T12:00:05Z"
}
```

### 2.3 New Database Table: `validation_jobs`

```sql
-- PostgreSQL DDL
CREATE TABLE validation_jobs (
    id              SERIAL PRIMARY KEY,
    job_id          VARCHAR(64) UNIQUE NOT NULL,
    course_id       VARCHAR(64) NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    scope           VARCHAR(32) NOT NULL DEFAULT 'full'
                    CHECK (scope IN ('full', 'delta', 'proposal')),
    proposal_id     VARCHAR(64),          -- nullable; only when scope='proposal'
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','completed','failed')),
    progress        REAL NOT NULL DEFAULT 0.0,
    result_data     JSONB,                -- full ValidationReport if completed
    error_message   TEXT,
    page_count      INTEGER NOT NULL DEFAULT 0,
    component_count INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_validation_jobs_status ON validation_jobs(status);
CREATE INDEX idx_validation_jobs_course ON validation_jobs(course_id);
```

### 2.4 Service Signatures

```python
# app/services/validation/pipeline.py

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import datetime

class FindingCategory(str, Enum):
    SCHEMA = "schema"
    BUSINESS = "business"
    TEMPLATE = "template"
    EXPORT = "export"
    ACCESSIBILITY = "accessibility"

class FindingLevel(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class ValidationFinding:
    id: str
    field: str
    category: FindingCategory
    message: str
    level: FindingLevel
    page_id: Optional[str] = None
    component_id: Optional[str] = None
    context: dict = field(default_factory=dict)

@dataclass
class ValidationReport:
    valid: bool
    findings: List[ValidationFinding]
    error_count: int
    warning_count: int
    info_count: int
    timestamp: str
    schema_version: str
    course_hash: str
    duration_ms: int


class ValidationPipeline:
    """
    Orchestrates multi-phase validation over a course's current DB state.

    Phases (in order):
    1. Structural schema checks (Pydantic Course model + JSON Schema)
    2. Page shape checks (required fields, ordering)
    3. Template/Component schema checks (dynamic type lookup, renderer required fields)
    4. Business rule checks (MCQ answers, welcome titles, content bodies)
    5. Export readiness checks (ExportValidator + RendererManifest)
    6. Accessibility checks (alt text, aria hints, heading hierarchy)
    """
    def __init__(self, db_session: AsyncSession):
        self.session = db_session
        self.findings: List[ValidationFinding] = []

    async def validate_course(self, course_id: str) -> ValidationReport:
        """Full course validation from DB. Fetches CourseRecord + Pages + Components."""
        ...

    async def validate_proposal(self, proposal_id: str) -> ValidationReport:
        """Delta validation: validates only the changed scope in a proposal."""
        ...

    async def validate_payload(self, course_data: dict, scope: str = "full") -> ValidationReport:
        """Ad-hoc validation on a raw dict payload (used by legacy POST /courses/validate)."""
        ...

    async def _phase1_schema(self, course_data: dict) -> None:
        """Phase 1: Structural schema compliance using Pydantic Course model."""

    async def _phase2_pages(self, course_data: dict) -> None:
        """Phase 2: Page-level checks — required fields, ordering."""

    async def _phase3_components(self, course_data: dict) -> None:
        """Phase 3: Component-level checks — type registry, renderer required fields."""

    async def _phase4_business(self, course_data: dict) -> None:
        """Phase 4: Template-specific business rules (MCQ, welcome, assessment, tabs, accordion)."""

    async def _phase5_export(self, course_data: dict) -> None:
        """Phase 5: Export readiness — delegate to ExportValidator."""

    async def _phase6_accessibility(self, course_data: dict) -> None:
        """Phase 6: Accessibility checks — alt text, heading hierarchy, aria hints."""

    def _add_finding(
        self, category: FindingCategory, level: FindingLevel,
        field: str, message: str,
        page_id: Optional[str] = None, component_id: Optional[str] = None,
        context: Optional[dict] = None
    ) -> str:
        """Create a finding with stable deterministic ID. Returns the ID."""
        finding_id = self._make_finding_id(category, level, field, page_id, component_id)
        self.findings.append(ValidationFinding(
            id=finding_id,
            field=field,
            category=category,
            message=message,
            level=level,
            page_id=page_id,
            component_id=component_id,
            context=context or {}
        ))
        return finding_id

    @staticmethod
    def _make_finding_id(category, level, field, page_id, component_id) -> str:
        """Deterministic hash for stable error IDs across identical inputs."""
        import hashlib
        raw = f"{category}:{level}:{field}:{page_id}:{component_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]
```

```python
# app/repositories/validation_repo.py

class ValidationRepository:
    """Persistence for validation jobs."""

    async def create_job(self, course_id: str, scope: str, proposal_id: Optional[str] = None) -> ValidationJob:
        ...

    async def update_job_result(self, job_id: str, report: ValidationReport) -> None:
        ...

    async def get_job(self, job_id: str) -> Optional[ValidationJob]:
        ...

    async def get_latest_report(self, course_id: str, max_findings: int = 100) -> Optional[ValidationReport]:
        """Return the most recent completed validation report for a course."""
        ...
```

```python
# app/services/validation/business.py

class BusinessRuleValidator:
    """
    Template-specific business rule validation.
    Each method returns a list of ValidationFinding objects.
    """

    async def validate_mcq(self, component_data: dict, page_id: str, component_id: str, index: int) -> List[ValidationFinding]:
        """Validate MCQ: questions present, options >= 2, exactly one correct, option text non-empty."""

    async def validate_final_assessment(self, component_data: dict, page_id: str, component_id: str) -> List[ValidationFinding]:
        """Validate final assessment: passingScore in [0,100], at least 1 question, mixed types OK."""

    async def validate_content_text(self, component_data: dict, page_id: str, component_id: str) -> List[ValidationFinding]:
        """Warn if body/content is empty."""

    async def validate_welcome(self, component_data: dict, page_id: str, component_id: str) -> List[ValidationFinding]:
        """Error if title/content is missing."""

    async def validate_tabs(self, component_data: dict, page_id: str, component_id: str) -> List[ValidationFinding]:
        """Validate tabs: at least 1 tab, each tab has title and body."""

    async def validate_accordion(self, component_data: dict, page_id: str, component_id: str) -> List[ValidationFinding]:
        """Validate accordion: at least 1 panel, each panel has title and body."""

    async def validate_video(self, component_data: dict, component_id: str) -> List[ValidationFinding]:
        """Validate video: videoAssetId or videoUrl present, valid URL."""

    async def validate_scoring(self, component_data: dict, component_type: str, page_id: str, component_id: str) -> List[ValidationFinding]:
        """Validate scoring config: score within acceptable range per component type."""
```

```python
# app/services/validation/accessibility.py

class AccessibilityValidator:
    """
    WCAG 2.1 AA validation checks for course content.
    Non-blocking (warnings only) but surfaced prominently in the validation report.
    """

    async def check_image_alt_text(self, course_data: dict) -> List[ValidationFinding]:
        """Every image/content-image component must have altText in its data or accessibilityConfig."""

    async def check_heading_hierarchy(self, course_data: dict) -> List[ValidationFinding]:
        """Page titles should form a logical H1->H2 hierarchy."""

    async def check_aria_labels(self, course_data: dict) -> List[ValidationFinding]:
        """Interactive components (tabs, accordion, mcq) should have ariaLabel in accessibilityConfig."""

    async def check_assessment_accessibility(self, course_data: dict) -> List[ValidationFinding]:
        """Assessment instructions should be screen-reader compatible."""

    async def check_contrast_hints(self, course_data: dict) -> List[ValidationFinding]:
        """Color references in styleConfig should include contrast notes for text-on-background."""
```

### 2.5 Router Implementation Sketch

```python
# app/routers/validation.py

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.services.validation.pipeline import ValidationPipeline, ValidationReport
from app.repositories.validation_repo import ValidationRepository

router = APIRouter(prefix="/api/v1", tags=["Validation"])

@router.post("/courses/{courseId}/validate", response_model=ValidationReport)
async def validate_persisted_course(
    courseId: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Validate a persisted course from DB. Returns 200 with report or 202 with jobId."""
    repo = ValidationRepository(session)
    course_repo = CourseRepository(session)

    try:
        course = await course_repo.get_by_course_id(courseId)
    except CourseNotFoundError:
        raise HTTPException(404, detail="Course not found")

    # Count pages for sync/async decision
    from app.repositories.page_component_repo import PageRepository
    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)
    page_count = len(pages)
    component_count = sum(len(p.components or []) for p in pages)

    if page_count > 200 or component_count > 500:
        # Async path
        job = await repo.create_job(courseId, scope="full")
        background_tasks.add_task(_run_async_validation, job.job_id, courseId)
        return JSONResponse(
            status_code=202,
            content={"jobId": job.job_id, "status": "processing", "pollUrl": f"/api/v1/validation/jobs/{job.job_id}"}
        )

    # Sync path
    pipeline = ValidationPipeline(session)
    report = await pipeline.validate_course(courseId)
    return JSONResponse(status_code=200, content=_report_to_dict(report))


@router.get("/validation/jobs/{jobId}")
async def get_validation_job(
    jobId: str,
    session: AsyncSession = Depends(get_session)
):
    repo = ValidationRepository(session)
    job = await repo.get_job(jobId)
    if not job:
        raise HTTPException(404, detail="Validation job not found")
    return job.to_dict()
```

### 2.6 Changes to Existing Files

**`app/routers/courses.py`** (lines 465-751):
- Refactor `POST /courses/validate` to delegate to `ValidationPipeline.validate_payload()` for the synchronous path.
- Keep the existing inline helpers (`_validate_mcq_page`, `_validate_content_text_page`, `_validate_welcome_page`) but convert them to call the new `BusinessRuleValidator` methods for consistency.
- Add a `mode` query parameter (`full` / `delta`) to the route.
- Normalize the response to the new `ValidationReport` schema (backward compatibility via `Accept` header negotiation — if `Accept: application/vnd.legacy+json` is absent, return new format; if present, return the old flat structure).

**`app/main.py`**:
- Register the new `validation` router:
  ```python
  from app.routers import validation
  api_router.include_router(validation.router)
  ```

**`app/routers/export.py`**:
- In `export_persisted_course()` (line 719), insert a validation gate before building the SCORM ZIP. Call `ValidationPipeline.validate_course(courseId)` and if `report.valid == False` with blocking errors, return HTTP 422 with the validation report.

### 2.7 Env Vars

| Variable | Default | Purpose |
|---|---|---|
| `VALIDATION_MAX_SYNC_PAGES` | `200` | Max pages before validation falls back to async job |
| `VALIDATION_MAX_SYNC_COMPONENTS` | `500` | Max components before validation falls back to async job |
| `VALIDATION_ASYNC_JOB_TTL_SECONDS` | `3600` | Async validation job expiry |
| `VALIDATION_REPORT_MAX_FINDINGS` | `500` | Max findings returned in one response (truncate excess) |

---

## 3. Non-Functional Requirements

- **NFR-01 (Performance)**: Full-course validation for a course with 50 pages and 150 components must complete within 2 seconds (P95).
- **NFR-02 (Scalability)**: The async validation path must handle concurrent requests for 50 courses without DB contention.
- **NFR-03 (Completeness)**: Every deployed component type in the renderer manifest (84 types across 14 categories) must have at least a structural check in the validation pipeline.
- **NFR-04 (Stability)**: The existing `POST /api/v1/courses/validate` endpoint must remain backward-compatible after refactoring — all existing callers must receive identical response structure when using the legacy accept header.
- **NFR-05 (Observability)**: Every validation run emits a structured log line with `courseId`, `durationMs`, `errorCount`, `warningCount`, `schemaVersion`, and `validatorVersion`.
- **NFR-06 (Lock-freedom)**: Report generation reads only; it never holds or waits on write locks. Writes during validation are not blocked.
- **NFR-07 (Memory)**: Async validation for courses up to 1000 pages must keep peak RSS under 512 MB per job.

---

## 4. Current State Analysis

### Existing Validation Infrastructure

**`POST /api/v1/courses/validate`** (in `app/routers/courses.py` lines 465-751):
- Accepts an ad-hoc `courseData` dict with `customizations` and optional `page_order`.
- Returns `ValidationResult { valid, errors[], warnings[], timestamp }`.
- Errors are `{ id, field, category (schema|business|template|navigation), message, level (error|warning|info), context }`.
- Supports inline validators: `_validate_mcq_page`, `_validate_content_text_page`, `_validate_welcome_page`.
- Validates required fields (`courseId`, `title`, `pages`), page content, template type vs. built-in types, and component presence.
- Runs Pydantic `Course(**course_data)` as a structural check.
- Does NOT currently: validate against the renderer manifest, run accessibility checks, support delta validation, link findings to `pageId`/`componentId`, or persist results.

**`ExportValidator`** (in `app/services/export_validator.py`):
- Validates course data for SCORM export readiness.
- Checks: component type support via `RendererManifest`, required fields per renderer entry, assets existence, style integrity, interaction configuration, and accessibility config presence.
- Returns `ExportValidationResult { isValid, errors[], warnings[], supportedComponentCount, unsupportedComponentCount }`.
- Currently invoked only during export, not during course validation.

**`RendererManifest`** (in `app/services/renderer_manifest.py`):
- Comprehensive registry of all 84 component types across 14 categories.
- Each entry declares `requiredFields`, `optionalFields`, `isExportable`, `fallbackComponent`, and `capabilities` (interaction, scoring, branching, responsive, etc.).
- Singleton pattern, refreshed only on restart.

**`ComponentType`** (in `app/models/component_type.py`):
- DB-backed registry with JSON Schema per type, scoring config, audio support, completion capabilities.
- Seeded at startup.

**`CourseRecord`/`PageRecord`/`ComponentRecord`** (in `app/models/persisted_course.py` and `app/models/page_component.py`):
- Full normalized persistence: courses have pages, pages have components.
- `PageRepository.list_by_course()` with `selectinload(PageRecord.components)` fetches the full page hierarchy.

**`CourseValidator`** (in `app/utils/validation.py`):
- Legacy class with `validate_course()` and `_validate_template_type()`.
- Checks built-in types first, then `TemplateDefinitionRepository`, then `ComponentTypeRepository`.
- Used by `validate_course_json` FastAPI dependency in the export path.

### Gaps
1. No linking of validation findings to specific DB page/component IDs.
2. No accessibility validation.
3. No export-readiness gate in the proposal apply flow.
4. No async validation for large courses.
5. No persisted validation history.
6. The existing `POST /courses/validate` endpoint validates ad-hoc payloads only; there is no endpoint to validate a persisted course by `courseId`.

---

## 5. Expansion Points

- **EP-01: Incremental validation cache** — Cache validation results per page/component hash; only re-validate changed items. Reduces P95 latency for large courses from 2s to sub-200ms.
- **EP-02: Validation rules engine** — Replace hard-coded business rule validators with a declarative rules engine (e.g., JSON-based rules stored in DB). Admins can add/remove custom validation rules per tenant.
- **EP-03: AI-driven remediation** — When validation fails, the LLM auto-generates a fix proposal. The validation report includes a `suggestedFix` field with a candidate patch. The user reviews and approves in one click.
- **EP-04: Custom template validation** — Extend `ComponentType.schema` to include validation rules so dynamic template types auto-register their validation logic alongside their data schema.
- **EP-05: Pre-export validation batch** — Run validation across all courses in a catalog before a bulk export or migration.
- **EP-06: Webhook on validation failure** — Emit a webhook event when a course transitions from valid to invalid state (e.g., after a bad edit). Integrations can notify authors via Slack/email.

---

## 6. Validation & Test Scenarios

### Unit Tests

| ID | Scenario | Expected Result |
|---|---|---|
| UT-01 | `BusinessRuleValidator.validate_mcq` with valid MCQ (4 options, 1 correct) | Zero findings |
| UT-02 | `BusinessRuleValidator.validate_mcq` with 0 options | Error finding, level=error, category=business |
| UT-03 | `BusinessRuleValidator.validate_mcq` with 0 correct answers | Error finding, level=error, category=business |
| UT-04 | `BusinessRuleValidator.validate_mcq` with 2 correct answers | Error finding, level=error, category=business |
| UT-05 | `BusinessRuleValidator.validate_final_assessment` with passingScore=110 | Error finding, level=error, category=business |
| UT-06 | `BusinessRuleValidator.validate_final_assessment` with 0 questions | Error finding, level=error, category=business |
| UT-07 | `BusinessRuleValidator.validate_content_text` with empty body | Warning finding, level=warning, category=business |
| UT-08 | `BusinessRuleValidator.validate_welcome` with no title | Error finding, level=error, category=business |
| UT-09 | `BusinessRuleValidator.validate_video` with missing videoAssetId | Error finding, level=error |
| UT-10 | `AccessibilityValidator.check_image_alt_text` with image missing altText | Warning finding, level=warning, category=accessibility |
| UT-11 | `AccessibilityValidator.check_image_alt_text` with image having altText | Zero findings |
| UT-12 | `ValidationPipeline._make_finding_id` deterministic for identical inputs | SHA-256 prefix matches |
| UT-13 | `ValidationPipeline._make_finding_id` different for different inputs | SHA-256 prefix differs |
| UT-14 | `ValidationPipeline.validate_course` with empty course (0 pages) | Error finding: "Course must have at least one page" |

### Integration Tests

| ID | Scenario | Expected Result |
|---|---|---|
| IT-01 | `POST /api/v1/courses/{courseId}/validate` with valid persisted course | 200, valid=true, zero findings |
| IT-02 | `POST /api/v1/courses/{courseId}/validate` with invalid course (MCQ missing correct answer) | 200, valid=false, at least 1 error finding |
| IT-03 | `POST /api/v1/courses/{courseId}/validate` for non-existent course | 404 |
| IT-04 | `POST /api/v1/courses/validate` with mode=delta and partial data | Validates only present fields |
| IT-05 | `POST /api/v1/courses/validate` with empty body | 422 or valid=false with schema errors |
| IT-06 | `POST /api/v1/ai/proposals/{proposalId}/validate` with valid proposal | 200, valid=true |
| IT-07 | `POST /api/v1/ai/proposals/{proposalId}/validate` with stale proposal | 200, valid=false, conflict error |
| IT-08 | `GET /api/v1/validation/jobs/{jobId}` for completed job | 200, status=completed, result present |
| IT-09 | `GET /api/v1/validation/jobs/{jobId}` for non-existent job | 404 |
| IT-10 | `POST /api/v1/courses/{courseId}/validate` for course with 250 pages | 202, jobId returned, async processing |
| IT-11 | `POST /api/v1/export/scorm/{courseId}` with invalid course | 422, validation report in detail |
| IT-12 | `POST /api/v1/export/scorm/{courseId}` with valid course | 200, ZIP downloaded |

### E2E / UI Tests

| ID | Scenario | Expected Result |
|---|---|---|
| E2E-01 | User clicks "Validate" from course toolbar | Validation panel appears with categorized findings |
| E2E-02 | User clicks an error finding linking to a page | Editor navigates to the affected page component |
| E2E-03 | User submits a proposal with blocking validation errors | Apply button is disabled, error tooltip shown |
| E2E-04 | User submits a proposal with only warnings | Apply button is enabled, warning banner visible |
| E2E-05 | User edits a page and saves | Validation re-runs; report refreshes within 500ms |
| E2E-06 | Large course validation (async path) | Spinner shown, poll completes, report rendered |

### Regression Tests

| ID | Scenario | Expected Result |
|---|---|---|
| RT-01 | `POST /api/v1/courses/validate` with legacy Accept header | Returns old format (`{valid, errors[], warnings[], timestamp}`) |
| RT-02 | `POST /api/v1/courses/validate` without legacy header (existing callers) | Returns new format (`{valid, findings[], errorCount, ...}`) |
| RT-03 | Existing `POST /api/v1/export` still works after validation router addition | 200, ZIP download |
| RT-04 | Existing course CRUD endpoints unaffected | All CRUD tests pass unchanged |

### Security Tests

| ID | Scenario | Expected Result |
|---|---|---|
| ST-01 | Validation request for course in different org/tenant | 403 Forbidden |
| ST-02 | Validation job poll with tampered jobId | 404 Not Found |
| ST-03 | Validator handles deeply nested malicious payload safely | Graceful error, no crash, no data leak |
| ST-04 | Validation report does not expose internal DB IDs | Only `pageId`/`componentId` UUIDs exposed |

---

## 7. Definition of Done

1. All new API endpoints are implemented and return correct responses per the API contracts above.
2. The validation pipeline covers at least these component types with template-specific business rules: `mcq`, `final-assessment`, `content-text`, `content-video`, `welcome`, `tabs`, `accordion`, `content-media`.
3. All 84 component types from the renderer manifest pass structural checks (componentType present, registered in manifest, required fields present).
4. Accessibility validation checks for alt text on image/carousel components, heading hierarchy, and ARIA labels on interactive components.
5. The existing `POST /api/v1/courses/validate` endpoint is backward-compatible (old callers receive identical responses via Accept header negotiation).
6. Async validation path works for courses exceeding configurable page/component thresholds, with a pollable job endpoint.
7. Export endpoints gate on validation: invalid courses receive 422 with validation report.
8. All acceptance criteria in the [Acceptance Criteria](#8-acceptance-criteria) section pass.
9. Unit tests: min 25 tests covering all validators, pipeline orchestration, and edge cases.
10. Integration tests: min 12 tests covering all new endpoints, sync/async paths, and error scenarios.
11. E2E tests: min 6 tests covering the full validation UI workflow.
12. Swagger/OpenAPI docs include the new endpoints and schemas.
13. A structured log line is emitted for every validation run.
14. The `validation_jobs` table is created in a migration (Alembic or auto-create via metadata).

---

## 8. Acceptance Criteria

- **AC-01**: `POST /api/v1/courses/{courseId}/validate` for a valid course returns HTTP 200 with `valid=true`, empty `findings` array, accurate `errorCount`/`warningCount`/`infoCount`, and non-null `courseHash`.
- **AC-02**: A course with an MCQ component missing a correct answer returns HTTP 200 with `valid=false` and at least one finding with `level=error`, `category=business`, `field` pointing to the options array, and `pageId`/`componentId` populated.
- **AC-03**: A course with an image component missing `altText` returns a finding with `level=warning`, `category=accessibility`, and a remediation hint in `context.remediation`.
- **AC-04**: A course exceeding the sync threshold receives HTTP 202 with a `jobId` and `pollUrl`; polling `GET /api/v1/validation/jobs/{jobId}` eventually returns `status=completed` with the full report.
- **AC-05**: The proposal apply flow rejects apply when `valid=false` with blocking errors; the frontend apply button is disabled and a tooltip shows the error count.
- **AC-06**: Warnings do not block proposal apply — the apply button remains enabled with a visible warning banner.
- **AC-07**: Navigating from a validation finding link opens the correct page/component in the editor.
- **AC-08**: Validation re-runs after manual page save and the report refreshes within 500ms.
- **AC-09**: `POST /api/v1/courses/validate` with a legacy client (`Accept: application/vnd.legacy+json`) returns the original `{valid, errors[], warnings[], timestamp}` structure.
- **AC-10**: `POST /api/v1/export/scorm/{courseId}` returns HTTP 422 with a validation report when the course has blocking errors.
- **AC-11**: All existing unit/integration tests for courses, export, and page-component CRUD pass without modification.
- **AC-12**: The validation report includes `schemaVersion` and `durationMs` for observability.

---

## 9. Task Breakdown

### Sprint 1: Pipeline Foundation (3 days)

| Task ID | Task | Assignee | Effort |
|---|---|---|---|
| T-001 | Create `app/services/validation/` package with `__init__.py` and `pipeline.py` implementing `ValidationPipeline` class. Wire through the 6-phase orchestration. | BE | 1 day |
| T-002 | Implement `_phase1_schema`: validate against Pydantic `Course` model, produce structured findings for each Pydantic `ValidationError`. | BE | 0.5 day |
| T-003 | Implement `_phase2_pages`: page-level structural checks (required `pageId`, `title`, valid `order_index`, components array). | BE | 0.5 day |
| T-004 | Implement `_phase3_components`: componentType presence check, RendererManifest lookup, required fields vs. manifest entry, component_type registry lookup. | BE | 1 day |
| T-005 | Implement `_phase4_business` -> `BusinessRuleValidator` in `app/services/validation/business.py` covering `mcq`, `final-assessment`, `content-text`, `content-video`, `welcome`, `tabs`, `accordion`. | BE | 1 day |
| T-006 | Implement `_phase5_export` -> delegate to existing `ExportValidator.validate()`, convert `ExportValidationError`s to `ValidationFinding` objects. | BE | 0.5 day |
| T-007 | Implement `_phase6_accessibility` -> `AccessibilityValidator` in `app/services/validation/accessibility.py` with alt-text check, heading hierarchy check, ARIA label check. | BE | 0.5 day |

### Sprint 2: API Endpoints & Persistence (2 days)

| Task ID | Task | Assignee | Effort |
|---|---|---|---|
| T-008 | Create `app/models/validation.py` with `ValidationJob` SQLAlchemy model (see DDL in Section 2.3). | BE | 0.5 day |
| T-009 | Create `app/repositories/validation_repo.py` with `create_job`, `update_job_result`, `get_job`, `get_latest_report`. | BE | 0.5 day |
| T-010 | Create `app/routers/validation.py` with `POST /api/v1/courses/{courseId}/validate` (sync/async dual path) and `GET /api/v1/validation/jobs/{jobId}`. | BE | 1 day |
| T-011 | Refactor existing `POST /api/v1/courses/validate` in `courses.py` to delegate to `ValidationPipeline.validate_payload()` while maintaining backward compatibility via Accept header negotiation. | BE | 1 day |
| T-012 | Implement `POST /api/v1/ai/proposals/{proposalId}/validate` endpoint. | BE | 0.5 day |

### Sprint 3: Integration & Gating (1 day)

| Task ID | Task | Assignee | Effort |
|---|---|---|---|
| T-013 | Register validation router in `app/main.py`. | BE | 0.1 day |
| T-014 | Add validation gate to `export_persisted_course()` in `app/routers/export.py`: run pipeline before ZIP generation, return 422 on blocking errors. | BE | 0.5 day |
| T-015 | Wire proposal validation into the apply pipeline (US-AI-010) so that `apply_*` endpoints reject with 422 when validation fails. | BE | 0.5 day |

### Sprint 4: Report Refresh & Re-validation (0.5 day)

| Task ID | Task | Assignee | Effort |
|---|---|---|---|
| T-016 | Implement course hash computation (`SHA-256` of canonical JSON-sorted course state) for staleness comparison. | BE | 0.25 day |
| T-017 | Add auto re-validation trigger in the edit save path: after `PageRepository.update()`, schedule a lightweight validation via background task. | BE | 0.25 day |

### Sprint 5: Testing (2 days)

| Task ID | Task | Assignee | Effort |
|---|---|---|---|
| T-018 | Write 25+ unit tests for BusinessRuleValidator, AccessibilityValidator, ValidationPipeline phases, finding ID generation, and edge cases. | QA/BE | 1 day |
| T-019 | Write 12+ integration tests for all new endpoints, sync/async paths, backward compatibility, and export gating. | QA/BE | 1 day |
| T-020 | Write 6+ E2E tests covering the validation UI workflow (course validate, proposal validate, navigate to error, async polling, export gate). | QA | 1 day |
| T-021 | Run full regression suite (courses CRUD, export, page-component, import) and confirm zero regressions. | QA | 0.5 day |

### Sprint 6: Documentation & Observability (0.5 day)

| Task ID | Task | Assignee | Effort |
|---|---|---|---|
| T-022 | Add structured logging for every validation run: `courseId`, `durationMs`, `errorCount`, `warningCount`, `infoCount`, `schemaVersion`. | BE | 0.25 day |
| T-023 | Update OpenAPI schema with new endpoints, `ValidationReport` and `ValidationFinding` models, and 202/422 response examples. | BE | 0.25 day |

### Total Effort: ~10.5 engineering days

---

**File Locations Reference:**
- New files go under: `C:\Users\ADMIN\e-learning-backend\app\services\validation\`, `C:\Users\ADMIN\e-learning-backend\app\routers\validation.py`, `C:\Users\ADMIN\e-learning-backend\app\models\validation.py`, `C:\Users\ADMIN\e-learning-backend\app\repositories\validation_repo.py`
- Existing files to modify: `C:\Users\ADMIN\e-learning-backend\app\routers\courses.py` (refactor validate endpoint), `C:\Users\ADMIN\e-learning-backend\app\routers\export.py` (add validation gate), `C:\Users\ADMIN\e-learning-backend\app\main.py` (register new router)
- Reference docs: `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\01_SystemArchitecture\Course_Validation_Flow.mmd`
- Existing validators to reuse: `app\services\export_validator.py` (ExportValidator), `app\utils\validation.py` (CourseValidator), `app\services\renderer_manifest.py` (RendererManifest with 84 component types)

---
The file is complete and verified. Here is a summary of what was delivered:

**File created:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-019_GENERATE_FULL_COURSE_FROM_FILE.md` (2,785 lines)

**Document covers all 8 mandatory sections:**

| Section | Content |
|---|---|
| **1. Functional Specification** | User story, overview, actor table, 5-phase flow (Initiate -> Generate -> Propose -> Review -> Apply -> Post-Creation), and 10 error conditions with exact HTTP status codes and error payloads |
| **2. Technical Specification** | Complete DDL for 2 new tables (`course_generation_jobs`, `generation_page_logs`), full SQLAlchemy ORM models with `to_dict()`, 8 Pydantic DTOs, exact API contracts for all 4 endpoints (request/response bodies, error shapes), 3 service signatures (`CourseGenerator`, `PromptBuilder`, `LLMClient`), repository with 10 methods, API router with 4 routes, audit/outbox event schemas, and 11 env vars |
| **3. Non-Functional Requirements** | Performance targets (per-page LLM <15s p95, full course <3min p95), security (file hash integrity, prompt injection resistance, LLM output validation, cross-tenant isolation), data integrity (all-or-nothing transactional apply, idempotency), availability (retry with backoff, job TTL, concurrent job limit), observability (6 metric counters, structured phase-transition logging) |
| **4. Current State** | Detailed inventory of 12 existing subsystems (ImportService, heuristic parser, schema inference, course CRUD, page/component CRUD, template repo, Pydantic models, component registry, validation pipeline, export readiness, feature flags) with exact file paths, plus a gap analysis of 17 missing components |
| **5. Expansion Points** | 7 future expansions: multi-format sources, course merge, multi-pass refinement, quality scoring, media asset sourcing, durable workflow integration, template harvesting |
| **6. Validation & Test Scenarios** | 46 unit test cases across 8 test classes, 12 integration test cases across 4 test classes, 5 E2E scenarios, 4 safety invariant tests, 3 concurrency tests |
| **7. Definition of Done** | 5 checklists: Code Complete (7 items), Tests Pass (6 items), Documentation (3 items), Security (5 items), Operational Readiness (6 items) |
| **8. Tasks** | 14 tasks with effort estimates, acceptance criteria, and dependency mapping totaling ~56.5 hours |

**Key API contracts defined:**
- `POST /api/v1/ai/generate-course` (202) -- start generation from approved page plan
- `GET /api/v1/ai/generate-course/{generation_job_id}` -- poll generation progress
- `GET /api/v1/ai/generate-course/{generation_job_id}/preview` -- fetch course preview with per-page validation
- `POST /api/v1/ai/generate-course/{generation_job_id}/confirm` -- confirm and apply course

**Key new files specified:**
- `app/models/course_generation.py` -- 2 ORM models
- `app/repositories/course_generation_repo.py` -- generation job repository
- `app/services/ai/course_generator.py` -- generation pipeline orchestrator
- `app/services/ai/prompt_builder.py` -- LLM prompt construction + response parsing
- `app/services/ai/llm_client.py` -- LLM provider HTTP client with retry
- `app/routers/ai_course_generation.py` -- 4-endpoint API router
- `app/routers/ai_course_generation_dtos.py` -- 8 Pydantic DTOs
- `alembic/versions/20260614_0002_add_course_generation_tables.py` -- migration

---
The epic has been written in full at:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-020_ADMIN_AUDIT_COMPLIANCE_RECOVERY_EPIC.md`** (2,174 lines, 8 sections)

Here is a summary of what the document contains:

**Section 1 -- Functional Specification:** 5 functional areas with 15 functional requirements covering audit log queries (FR-AUDIT-01 through 06), compliance dashboards (FR-COMP-01 through 05), recovery operations (FR-RECOV-01 through 05), and a table of 6 edge cases with expected behavior.

**Section 2 -- Technical Specification:** Full PostgreSQL DDL for `ai_audit_logs` (17 columns, 14 indexes including GIN on JSONB), `ai_safety_events` (11 columns, 6 indexes), and `ai_usage_records` (partitioned by month). Complete ORM models (`AIAuditLog`, `AISafetyEvent`) with `to_dict()` methods, check constraints, and composite indexes. Pydantic DTOs for all 12 admin endpoints. Exact API contracts with query parameters, request/response JSON examples, error responses (422, 404, 409, 500) for all 12 endpoints. Service class signature with 13 methods. Repository class with cursor-based pagination (base64-encoded `(id, created_at)`). Router implementation with all endpoints and admin auth dependency injection. Alembic migration (full upgrade/downgrade). Integration points for `main.py`, `alembic/env.py`, and `models/__init__.py`. Environment variables with defaults.

**Section 3 -- Non-Functional Requirements:** Performance targets (p95 < 500ms for queries, < 2s for rollback, < 3s for compliance aggregation), security requirements (admin-only access, PII redaction, audit immutability), data retention policies (365d audit, 730d safety, 90d usage, 48h export files), availability target (99.9%), and observability metrics.

**Section 4 -- Current State Assessment:** Maps each required component to its reference pattern in the existing codebase (e.g., `analytics.py` for read-only reporting, `interaction_event_repo.py` for repository patterns, `error_envelope.py` for error shape). Lists what exists vs. what needs building.

**Section 5 -- Expansion Points:** 3 future phases: Phase 2 (audit archiving, GDPR DSAR, compliance rules), Phase 3 (scheduled rollback, point-in-time restore, impact analysis), Phase 4 (federated audit, SIEM integration, Kafka schemas).

**Section 6 -- Validation Strategy:** 29 unit tests across repo and service layers, 15 API integration tests, 4 security tests, 3 performance tests -- each with scenario, HTTP method, and expected outcome.

**Section 7 -- Definition of Done:** 14 acceptance criteria, 9 quality gates (test coverage, feature flag, OpenAPI, lint, types, migration, performance, security), and a signoff checklist for Product Owner, Security Lead, QA Lead, Operations, and Tech Lead.

**Section 8 -- Task Breakdown:** 16 tasks across 6 groups (Foundation, Audit Read API, Recovery & Rollback, Configuration & Integration, Testing, Documentation) totaling 25 story points, with dependencies mapped to US-AI-004, US-AI-010, US-AI-009, US-AI-002, and US-AI-025.

---
The complete enriched US-AI-021 story has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-021_OBSERVABILITY_RATE_LIMITS_ROLLOUT_GATES.md`**

Here is a summary of what each of the 8 sections contains:

**1. Functional Specification** (4,200+ words)
- Three primary actors: Operator, Author, AI Orchestrator
- Six detailed flows: Trace ID propagation, Rate limit enforcement, Rollout gate evaluation, Metrics emission
- 10 error conditions with exact HTTP status codes, error codes, and behaviors

**2. Technical Specification** (8,500+ words)
- **Trace ID format and propagation**: UUID v4, `X-Trace-ID` header, `contextvars` for request-scoped access, `get_current_trace_id()` helper
- **Rate limit middleware**: Full `RateLimitMiddleware` class with `InProcessRateLimitStore` supporting 5 limit categories (user requests, tenant requests, endpoint burst, user daily tokens, tenant daily tokens) with sliding windows, `Retry-After` headers, and `X-RateLimit-*` response headers
- **Rollout gate middleware**: Full `RolloutGateMiddleware` with 5 gates evaluated in order (global kill switch, environment allowlist, tenant allowlist, role allowlist, percentage rollout via deterministic hash)
- **Telemetry events DB DDL**: `ai_telemetry_events` table with full column definitions, indexes, and SQLAlchemy ORM model
- **Prometheus metrics**: 12 counters (`ai_requests_total`, `ai_tool_calls_total`, `ai_llm_calls_total`, `ai_proposals_created`, `ai_proposals_applied`, `ai_rate_limits_exceeded`, `ai_rollout_gate_blocked`, `ai_token_usage_total`, `ai_validation_errors_total`, `ai_safety_events_total`), 5 histograms (latency, duration, rounds), and 3 gauges (active sessions, pending proposals, remaining quota)
- **6 API endpoints**: `GET /rate-limit-status`, `GET /usage-summary`, `GET /rollout-status`, `GET /telemetry`, `GET /metrics`, with full request/response JSON contracts
- **Pydantic DTOs**: `RateLimitStatusResponse`, `UsageSummaryResponse`, `RolloutGateStatusResponse`, `TelemetryQueryParams`
- **TelemetryService**: `record_event()` (non-blocking, fire-and-forget) and `query_events()` with 7 filter parameters
- **Alembic migration**: Creates `ai_telemetry_events` table and adds `trace_id` columns to 4 existing AI tables
- **16 environment variables**: All documented with defaults in `.env.example`
- **Grafana dashboard spec**: 12 panels with Prometheus metric references

**3. Non-Functional Requirements**
- Performance targets (middleware overhead < 5ms p95, store lookup < 2ms p99)
- Rate limit accuracy (sliding window within 1 second, fail-open behavior)
- Security requirements (no information leak in 429/404, admin-protected metrics, tenant-scoped telemetry)
- Availability patterns (fail-open for rate limiter, fail-closed for rollout gate, non-blocking telemetry)
- Observability targets (trace ID coverage on all AI routes, bounded metric cardinality, alert thresholds)

**4. Current State** — Detailed inventory of 10 existing artifacts (feature flags, health endpoints, logging, error envelope, analytics, env config, middleware, metrics, telemetry table, dependencies) and 14 gaps

**5. Expansion Points** — 8 future enhancements: Redis rate-limit store, adaptive rate limiting, per-model limits, token-based rate limiting, self-service admin UI, OpenTelemetry integration, anomaly detection alerts, A/B test integration

**6. Validation and Test Scenarios**
- 50+ unit test cases across 4 test files (telemetry middleware, rate limiter, rollout gate, telemetry service)
- 16 integration test cases for the observability API
- 6 E2E scenarios covering full trace correlation, rate limit exhaustion, rollout gating, gradual percentage rollout, metrics access, and fail-open behavior
- 4 safety invariant tests
- 3 concurrency tests

**7. Definition of Done** — 21 checklist items across code complete (9 new files), tests pass, documentation, security, and operational readiness

**8. Tasks** — 16 tasks with effort estimates totaling ~50 hours, from ORM model creation through code review and merge, each with explicit acceptance criteria and dependency mapping

---
The file has been written successfully at 1,416 lines.

## Summary

**File:** `C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-022_E2E_REGRESSION_RELEASE_READINESS.md`

The epic covers all 8 required sections:

1. **Functional Specification** (Sections 1.1-1.7) -- Full user story, all 4 actors, complete API map table covering every route across all 14 router files (courses, templates, pages/components, export, imports, health, component registry, themes, scoring/completion, branching, analytics, social, media, audio) with happy and negative status codes. Eight multi-step integration flows (F1-F7) mapping cross-endpoint business flows. Twenty-five specific negative test scenarios (NEG-001 through NEG-025) with status codes and error-shape assertions.

2. **Technical Specification** (Sections 2.1-2.8) -- Complete test architecture with directory structure (33 existing files, plus new `flows/` and `release/` directories), database fixture pattern exact implementation code, test naming conventions, response shape assertion helper functions, updated `pytest.ini`, CI/CD yaml additions, `.coveragerc` with per-package thresholds, and service-specific test contracts for `SCORMExportService`, `_resolve_theme_bundle`, `_map_template_record`, and the validate endpoint.

3. **NFRs** (Sections 3.1-3.6) -- Performance targets (full suite < 5 min, unit tests < 60s), reliability targets (flaky rate < 1%), maintainability requirements (shared assertion helpers, no hardcoded URLs), reporting outputs (JUnit, coverage HTML/XML, durations), environment config vars, and isolation requirements.

4. **Current State** (Sections 4.1-4.3) -- Audit of all 33 existing test files with line counts and coverage assessments (6,233 total lines), gap analysis table (8 gaps with domain, impact, and priority), infrastructure summary.

5. **Expansion Points** (Sections 5.1-5.8) -- Parallel execution, PostgreSQL CI matrix, property-based testing, snapshot testing, OpenAPI contract testing, load testing, mutation testing, test data factories.

6. **Validation** (Sections 6.1-6.4) -- 9-phase test plan with sign-off roles, pre-merge checklist, release readiness checklist, and 5 test execution modes.

7. **Definition of Done** (Sections 7.1-7.4) -- 16 must-have items, 6 should-have items, 6 could-have items, scope boundaries.

8. **Tasks** (10 tasks, Appendix A+B) -- 10 concrete tasks with effort estimates (19 days total), file manifest (15 new files, 8 modified files), and a complete canonical test file example for `test_themes_api.py`.

---

---

# Orchestration & Platform (US-AI-023 — US-AI-032)

The enriched user story has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-023_AI_CHAT_ENDPOINT_LLM_INTERACTION_LOOP.md`**

This is a 2553-line, complete 8-section epic covering:

**Section 1 — Functional Specification**: The AI chat endpoint and LLM interaction loop (server-side tool-calling loop pattern), with 4-phase flow (Send Message, Load Context, LLM Loop, Persist/Return), SSE event stream contract, and 20 enumerated error conditions with codes.

**Section 2 — Technical Specification**: Four new database tables (`ai_session_messages`, `ai_tool_call_logs`, `ai_telemetry_events`, `ai_rate_limits`) with full DDL, SQLAlchemy ORM models, 8 Pydantic DTOs, exact API contracts for 3 endpoints (`POST /api/v1/ai/chat` with SSE streaming, `GET .../messages`, `GET .../tokens`), four service class signatures (`ChatOrchestrator`, `LLMClient`, `ToolExecutor`, `ContextBuilder`), repository interfaces, 10 tool handler mappings for the tool executor, tool registry integration table, and 24 environment variables.

**Section 3 — Non-Functional Requirements**: Performance targets (p95 latencies for turn processing, tool execution, LLM first-token), security controls (session gating, tool scope enforcement, PII redaction), data integrity guarantees, availability mechanisms (model fallback, graceful degradation), and 10 observability metric definitions.

**Section 4 — Current State**: Inventory of 5 existing assets (session management, feature flags, CRUD, validation, error envelopes) and 15 identified gaps.

**Section 5 — Expansion Points**: 7 post-MVP enhancements (semantic memory, streaming tool generation, parallel execution, HITL tool approval, token budgets, prompt A/B testing, multi-provider routing).

**Section 6 — Test Scenarios**: 45 unit test signatures across 4 test classes, 12 integration test signatures, 5 E2E scenarios, 4 safety invariant tests, and 3 concurrency tests.

**Section 7 — Definition of Done**: 5 subsections covering code complete checklist (14 items), test pass criteria (6 items), documentation (3 items), security (7 items), and operational readiness (8 items).

**Section 8 — Tasks**: 15 numbered tasks with specific acceptance criteria, effort estimates (totaling ~66.5 hours), and dependency chains.

---
The enriched story has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-024_FRONTEND_AI_INTEGRATION_LAYER.md`** (2,163 lines)

The story covers all 8 sections with the following specifics:

**Section 1 -- Functional Specification:** Five detailed flows covering AI session lifecycle (sessionStorage, rehydration, expiry countdown), proposal review and apply, destructive confirmation modal (type "DELETE" guard), file ingestion upload and review, and feature flag gating. Error handling matrix covering 10 error conditions.

**Section 2 -- Technical Specification:** Complete frontend module architecture at `src/ai/` with 8 subdirectories (api, components, hooks, stores, types, utils). Full TypeScript interfaces for all domains (session, proposal, chat, ingestion). `AIClient` class with session auth header injection, XHR-based upload progress, and `AIApiError` normalization. All 6 API contracts with request/response JSON examples. Four hooks (`useAISession`, `useChat`, `useProposal`, `useFileIngestion`) with full signatures and implementation notes. Component behavior specs for `ConfirmationModal` (focus trap, no backdrop dismiss, loading/error states), `ProposalCard` (8 visual states), `ProposalDiff` (field-level highlighting), and `ExtractionPreview` (drag-and-drop reorder, inline editing). Session storage contract. Feature flag integration with the existing `FeatureFlagService`. Error envelope mapping from backend codes to 15 user-facing messages.

**Section 3 -- Non-Functional Requirements:** Performance targets (panel render <200ms, diff compute <50ms), security (sessionStorage only, Bearer auth, DOMPurify for AI HTML, client-side file validation, CSRF via token), data integrity (no optimistic mutations, reload re-fetches state), availability (graceful degradation, runtime flag polling), observability (dev logging, performance marks, Sentry integration).

**Section 4 -- Current State:** Inventory of existing backend AI endpoints (planned), frontend structure (`src/services/*`, `src/export-runtime/*`), feature flag system, error envelopes, and architecture documentation. Detailed gap analysis listing all 14+ missing deliverables. Dependency table mapping to US-AI-002 through US-AI-023.

**Section 5 -- Expansion Points:** Streaming chat (SSE), und/redo toasts, keyboard shortcuts (6 bindings), multi-tab session sync via BroadcastChannel, dark mode via CSS custom properties, mobile responsive panel, IndexedDB history persistence.

**Section 6 -- Validation and Test Scenarios:** 22 unit tests (hooks, API client, utilities), 35+ component tests (all states for ConfirmationModal, ProposalCard, ProposalDiff, ChatWindow, ExtractionPreview), 8 integration tests (full flows with MSW-mocked APIs), 6 E2E scenarios (Cypress/Playwright narratives), 10 accessibility tests.

**Section 7 -- Definition of Done:** 28 code files checklist, 4 test suite checkpoints (40+ unit, 30+ component, 10+ integration, 10+ a11y), 8 manual authoring preservation checks, 9 security checks, 6 operational readiness checks, 3 documentation checks.

**Section 8 -- Tasks:** 16 tasks totaling ~51 hours effort, each with specific files, acceptance criteria, and dependency mapping. Tasks range from types definition (1h) through component implementation (6h each for proposal and ingestion components) to integration tests (4h).

---
The enriched epic has been written to:

**`C:\Users\ADMIN\e-learning-backend\docs\AI_Implemenation\00_User_StoriesUseCases\US-AI-025_PROMPT_SAFETY_CONTENT_GUARDRAILS.md`**

Here is a summary of what the complete 8-section document contains:

**Section 1: Functional Specification** -- Three guard layers (Input Guard for injection/jailbreak detection, PII Scanner with reject/redact/mask modes, Output Guard for toxicity/blocked terms), four detailed flows, and an error conditions table mapping 7 scenarios to HTTP status codes and error codes.

**Section 2: Technical Specification** -- Full PostgreSQL DDL for `ai_safety_events` (with 8 indexes, check constraints, FK to `ai_audit_logs`) and `ai_blocked_terms`. Complete ORM model `AISafetyEvent` with `to_dict()`. Pydantic DTOs: `GuardrailConfigOut`, `GuardResult`, `SafetyEventOut`, `BlockedTermCreate`, `GuardedChatRequest/Response`. Five API contracts with request/response JSON: guardrail config GET, config reload POST, blocked terms CRUD, safety events list with filtering, safety events stats. Four service implementations with full method signatures: `InputGuard` (10 injection patterns, 10 PII patterns with Luhn validation), `OutputGuard` (5 toxicity patterns, runtime blocklist), `SafetyEventService` (non-blocking persist + query), `GuardIntegration` (orchestrator wrapper). Chat orchestrator integration pseudocode. Alembic migration creating both tables with all constraints/indexes. 14 environment variables documented. Main application registration (model import, blocked terms init, router include).

**Section 3: Non-Functional Requirements** -- Performance targets (input guard <50ms p95, output guard <30ms p95), accuracy targets (injection recall >90%, PII recall >98%, toxicity false positives <1%), security invariants (no raw PII in logs, fail-open on guard failure, admin protection), availability constraints, and 5 Prometheus metrics definitions.

**Section 4: Current State** -- Assessment of existing codebase: no guardrail infrastructure exists, no `app/services/ai/` directory, no AI routers beyond US-AI-020 admin pattern, no PII libraries, no toxicity classifier, existing `error_envelope.py` and `feature_flags.py` available for reuse.

**Section 5: Expansion Points** -- Six post-MVP upgrades: ML-based toxicity detection (Perspective API/HuggingFace), context-aware injection detection, Microsoft Presidio integration, DB-backed blocked terms with LISTEN/NOTIFY, PII allowlisting, output factuality checking.

**Section 6: Validation and Test Scenarios** -- 25 unit tests across three test files (injection detection, PII scanning with all modes, toxicity detection, blocked terms, safety event persistence), 12 integration tests for the admin API, 6 E2E scenarios, 4 safety invariant tests, 4 performance benchmarks.

**Section 7: Definition of Done** -- 22-item checklist across Code Complete, Tests Pass, Documentation, Security, and Operational Readiness.

**Section 8: Tasks** -- 14 tasks with file paths, acceptance criteria, effort estimates, and dependency ordering totaling ~45 hours: ORM model (1.5h), DTOs (1h), InputGuard (8h), OutputGuard (5h), SafetyEventService (3h), GuardIntegration (2h), Admin router (4h), Orchestrator wiring (3h), Alembic migration (1.5h), Env config (0.5h), Unit tests (8h), Integration tests (4h), Documentation (2h), Review/merge (2h).

---