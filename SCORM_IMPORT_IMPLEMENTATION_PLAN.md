# SCORM Import Implementation Plan
## Phase 2: Detailed Sprint Planning & Task Breakdown

**Document Version**: 1.0  
**Status**: READY FOR EXECUTION  
**Based On**: BRD v1.9 + Technical Architecture v2.0  
**Estimated Duration**: 8-10 weeks (4-5 sprints)

---

## Executive Summary

This document translates the Business Requirements (BRD v1.9) and Technical Architecture (v2.0) into **actionable development tasks** organized by sprint. Each task includes:

- **Acceptance criteria** (testable conditions)
- **Technical approach** (code patterns to use)
- **Dependencies** (blockers and prerequisites)
- **Estimated effort** (T-shirt sizing: S, M, L, XL)
- **Testing strategy** (unit, integration, e2e)

---

## Sprint Planning Overview

| Sprint | Theme | Duration | Key Deliverables |
|--------|-------|----------|------------------|
| **Sprint 0** | Foundation & Setup | 1 week | Database migrations, repo structure |
| **Sprint 1** | Core Parsing Services | 2 weeks | HeuristicParser, SchemaInference, AssetRewriter |
| **Sprint 2** | Import Orchestration | 2 weeks | ImportService, Repository layer |
| **Sprint 3** | API & Background Jobs | 2 weeks | REST endpoints, async processing |
| **Sprint 4** | Integration & Hardening | 2 weeks | Security, performance, testing |
| **Sprint 5** | Documentation & Launch | 1 week | Docs, deployment, monitoring |

---

## Sprint 0: Foundation (Week 1)

### Goal
Set up database schema, repository structure, and development environment.

### Tasks

#### Task 0.1: Database Migrations
**Story**: As a developer, I need database tables for import jobs and template definitions.

**Acceptance Criteria**:
- [ ] `import_jobs` table created with all columns
- [ ] `template_definitions` table created with all columns
- [ ] `global_templates` table created with all columns
- [ ] All indexes created
- [ ] Migration reversible (down migration works)
- [ ] Seed data script for core template types

**Technical Approach**:
```bash
# Create migration
alembic revision --autogenerate -m "Add import jobs and template definitions"

# Migration file structure
alembic/versions/20251219_0001_add_import_tables.py
```

**SQL Schema** (from Technical Architecture):
```sql
-- See Section 3.1 of SCORM_IMPORT_TECHNICAL_ARCHITECTURE.md
CREATE TABLE import_jobs (...);
CREATE TABLE template_definitions (...);
CREATE TABLE global_templates (...);
```

**Testing**:
```python
# tests/test_migrations.py
def test_import_jobs_table_exists():
    """Verify import_jobs table created."""
    ...

def test_template_definitions_indexes():
    """Verify all indexes exist."""
    ...
```

**Effort**: M  
**Dependencies**: None  
**Owner**: Backend Team

---

#### Task 0.2: ORM Models
**Story**: As a developer, I need SQLAlchemy models for new tables.

**Acceptance Criteria**:
- [ ] `ImportJob` model in `app/models/persisted_course.py`
- [ ] `TemplateDefinition` model (already exists, verify structure)
- [ ] `GlobalTemplate` model
- [ ] All models have `to_dict()` methods
- [ ] Type hints for all fields

**Technical Approach**:
```python
# app/models/persisted_course.py
class ImportJob(Base):
    __tablename__ = "import_jobs"
    # See Section 3.2 of Technical Architecture
```

**Testing**:
```python
# tests/unit/test_models.py
def test_import_job_to_dict():
    """Verify ImportJob serialization."""
    job = ImportJob(job_id="test", status="pending")
    assert job.to_dict()["jobId"] == "test"
```

**Effort**: S  
**Dependencies**: Task 0.1  
**Owner**: Backend Team

---

#### Task 0.3: Repository Base Class
**Story**: As a developer, I need a base repository pattern.

**Acceptance Criteria**:
- [ ] `BaseRepository` abstract class created
- [ ] Common CRUD methods defined
- [ ] Async session management
- [ ] Error handling patterns

**Technical Approach**:
```python
# app/repositories/base.py
from abc import ABC
from sqlalchemy.ext.asyncio import AsyncSession

class BaseRepository(ABC):
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def commit(self):
        await self.session.commit()
    
    async def rollback(self):
        await self.session.rollback()
```

**Effort**: S  
**Dependencies**: Task 0.2  
**Owner**: Backend Team

---

#### Task 0.4: Environment Configuration
**Story**: As a DevOps engineer, I need environment variables for import features.

**Acceptance Criteria**:
- [ ] Add `MAX_UPLOAD_SIZE` to `.env.example`
- [ ] Add `TEMP_FILE_RETENTION_HOURS`
- [ ] Add `IMPORT_WORKER_THREADS`
- [ ] Add `STORAGE_TYPE` (local/s3)
- [ ] Update configuration loading in `app/main.py`

**Technical Approach**:
```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    max_upload_size: int = 200 * 1024 * 1024
    temp_file_retention_hours: int = 24
    storage_type: str = "local"
```

**Effort**: S  
**Dependencies**: None  
**Owner**: DevOps Team

---

## Sprint 1: Core Parsing Services (Weeks 2-3)

### Goal
Implement the core services that extract and process SCORM package data.

---

#### Task 1.1: HeuristicParser - AST Parsing
**Story**: As a system, I need to extract JSON from minified JavaScript files.

**Acceptance Criteria**:
- [ ] `HeuristicParser` class created
- [ ] AST parsing using `pyjsparser`
- [ ] Regex fallback for simple cases
- [ ] Security scanning for dangerous patterns
- [ ] Handles minified and formatted code
- [ ] Returns `None` on failure (no exceptions)

**Technical Approach**:
```python
# app/services/heuristic_parser.py
import pyjsparser
import re
import json
from typing import Optional, Dict, Any

class HeuristicParser:
    DANGEROUS_PATTERNS = [
        r'\beval\s*\(',
        r'\bFunction\s*\(',
        r'\bsetTimeout\s*\(',
    ]
    
    def extract_json_from_js(self, js_code: str) -> Optional[Dict[str, Any]]:
        """Extract JSON using multiple strategies."""
        # Security check
        if self._has_dangerous_code(js_code):
            raise SecurityError("Dangerous code patterns detected")
        
        # Try AST
        if result := self._extract_via_ast(js_code):
            return result
        
        # Try regex
        if result := self._extract_via_regex(js_code):
            return result
        
        return None
```

**Testing**:
```python
# tests/unit/test_heuristic_parser.py
def test_extract_minified_es6():
    parser = HeuristicParser()
    js = "const data={title:'Test',templates:[{id:'1'}]};"
    result = parser.extract_json_from_js(js)
    assert result["title"] == "Test"

def test_reject_eval():
    parser = HeuristicParser()
    js = "eval('bad code'); var data = {};"
    with pytest.raises(SecurityError):
        parser.extract_json_from_js(js)
```

**Effort**: L  
**Dependencies**: None  
**Owner**: Senior Backend Developer

---

#### Task 1.2: SchemaInferenceEngine
**Story**: As a system, I need to automatically infer template schemas.

**Acceptance Criteria**:
- [ ] `SchemaInferenceEngine` class created
- [ ] `infer_schema_from_data()` method
- [ ] `compute_schema_signature()` (SHA-256 hash)
- [ ] `generate_render_template()` (Jinja2)
- [ ] Field type detection (text, URL, HTML, boolean, array)
- [ ] Deduplication via signature matching

**Technical Approach**:
```python
# app/services/schema_inference.py
import hashlib
import json
from typing import Dict, Any

class SchemaInferenceEngine:
    @staticmethod
    def infer_schema_from_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Infer JSON Schema from template data."""
        fields = []
        for key, value in data.items():
            field_type = SchemaInferenceEngine._infer_type(value)
            fields.append({
                "name": key,
                "type": field_type,
                "required": True,
                "nullable": value is None
            })
        return {"type": "object", "fields": fields}
    
    @staticmethod
    def compute_schema_signature(schema: Dict[str, Any]) -> str:
        """Compute SHA-256 hash of schema."""
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
```

**Testing**:
```python
# tests/unit/test_schema_inference.py
def test_infer_schema():
    engine = SchemaInferenceEngine()
    data = {"title": "Test", "options": ["A", "B"], "isActive": True}
    schema = engine.infer_schema_from_data(data)
    assert len(schema["fields"]) == 3
    assert schema["fields"][0]["type"] == "text"

def test_signature_deterministic():
    engine = SchemaInferenceEngine()
    schema1 = {"fields": ["a", "b"]}
    schema2 = {"fields": ["b", "a"]}  # Different order
    sig1 = engine.compute_schema_signature(schema1)
    sig2 = engine.compute_schema_signature(schema2)
    assert sig1 != sig2  # Order matters in our implementation
```

**Effort**: M  
**Dependencies**: None  
**Owner**: Backend Developer

---

#### Task 1.3: AssetRewriter - Path Normalization
**Story**: As a system, I need to rewrite asset URLs in HTML and CSS.

**Acceptance Criteria**:
- [ ] `AssetRewriter` class created
- [ ] `build_file_map()` to index assets
- [ ] `detect_ambiguous_assets()` for duplicates
- [ ] `rewrite_html_content()` using BeautifulSoup
- [ ] `rewrite_css_content()` using regex
- [ ] Handles relative paths (`../../img.png`)
- [ ] Returns warnings for ambiguous assets

**Technical Approach**:
```python
# app/services/asset_rewriter.py
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Tuple
from pathlib import Path

class AssetRewriter:
    def build_file_map(self, zip_contents: Dict[str, bytes]) -> Dict[str, List[str]]:
        """Build map of filename -> [paths]."""
        file_map = {}
        for path in zip_contents.keys():
            filename = Path(path).name
            if filename not in file_map:
                file_map[filename] = []
            file_map[filename].append(path)
        return file_map
    
    def detect_ambiguous_assets(self, file_map: Dict[str, List[str]]) -> List[str]:
        """Find duplicate filenames."""
        return [name for name, paths in file_map.items() if len(paths) > 1]
    
    def rewrite_html_content(self, html: str, asset_map: Dict[str, str]) -> str:
        """Rewrite src/href attributes."""
        soup = BeautifulSoup(html, 'lxml')
        for tag in soup.find_all(['img', 'video', 'audio'], src=True):
            if new_url := asset_map.get(tag['src']):
                tag['src'] = new_url
        return str(soup)
```

**Testing**:
```python
# tests/unit/test_asset_rewriter.py
def test_build_file_map():
    rewriter = AssetRewriter()
    contents = {
        "module1/img.png": b"data1",
        "module2/img.png": b"data2",
        "logo.jpg": b"data3"
    }
    file_map = rewriter.build_file_map(contents)
    assert len(file_map["img.png"]) == 2
    assert len(file_map["logo.jpg"]) == 1

def test_rewrite_html():
    rewriter = AssetRewriter()
    html = '<img src="old.jpg">'
    asset_map = {"old.jpg": "/api/v1/media/course/new.jpg"}
    result = rewriter.rewrite_html_content(html, asset_map)
    assert "/api/v1/media/course/new.jpg" in result
```

**Effort**: M  
**Dependencies**: None  
**Owner**: Backend Developer

---

#### Task 1.4: StorageService Abstraction
**Story**: As a system, I need to abstract file storage.

**Acceptance Criteria**:
- [ ] `StorageService` ABC created
- [ ] `LocalStorageService` implementation
- [ ] Factory function `get_storage_service()`
- [ ] Environment-based injection
- [ ] S3 storage stub (not implemented)

**Technical Approach**:
```python
# app/services/storage.py
from abc import ABC, abstractmethod

class StorageService(ABC):
    @abstractmethod
    async def save_file(self, file_path: str, content: bytes) -> str:
        """Save file and return URL."""
        pass
    
    @abstractmethod
    async def get_file(self, file_path: str) -> bytes:
        """Retrieve file."""
        pass

class LocalStorageService(StorageService):
    # See Section 2.3 of Technical Architecture
```

**Effort**: M  
**Dependencies**: None  
**Owner**: Backend Developer

---

## Sprint 2: Import Orchestration (Weeks 4-5)

### Goal
Implement the ImportService that orchestrates the entire import workflow.

---

#### Task 2.1: ImportJobRepository
**Story**: As a system, I need database operations for import jobs.

**Acceptance Criteria**:
- [ ] `ImportJobRepository` class created
- [ ] `create()` method
- [ ] `get_by_id()` method
- [ ] `update_status()` method
- [ ] `update_result()` method
- [ ] `list_by_status()` method
- [ ] All methods are async
- [ ] Proper error handling

**Technical Approach**:
```python
# app/repositories/import_job_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.persisted_course import ImportJob

class ImportJobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self, 
        job_id: str, 
        status: str, 
        source_file_path: str
    ) -> ImportJob:
        """Create new import job."""
        job = ImportJob(
            job_id=job_id,
            status=status,
            source_file_path=source_file_path
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job
    
    async def get_by_id(self, job_id: str) -> ImportJob:
        """Get job by ID."""
        query = select(ImportJob).where(ImportJob.job_id == job_id)
        result = await self.session.execute(query)
        job = result.scalar_one_or_none()
        if not job:
            raise JobNotFoundError(f"Job {job_id} not found")
        return job
```

**Testing**:
```python
# tests/integration/test_import_job_repository.py
@pytest.mark.asyncio
async def test_create_job(db_session):
    repo = ImportJobRepository(db_session)
    job = await repo.create("test-job-1", "pending", "/tmp/test.zip")
    assert job.job_id == "test-job-1"
    assert job.status == "pending"

@pytest.mark.asyncio
async def test_get_nonexistent_job(db_session):
    repo = ImportJobRepository(db_session)
    with pytest.raises(JobNotFoundError):
        await repo.get_by_id("nonexistent")
```

**Effort**: M  
**Dependencies**: Task 0.2, Task 0.3  
**Owner**: Backend Developer

---

#### Task 2.2: ImportService - Package Analysis
**Story**: As a system, I need to analyze uploaded SCORM packages.

**Acceptance Criteria**:
- [ ] `ImportService` class created
- [ ] `analyze_package()` method
- [ ] ZIP extraction with security
- [ ] Call HeuristicParser
- [ ] Call SchemaInferenceEngine
- [ ] Call AssetRewriter
- [ ] Stage data in `import_jobs.result_data`
- [ ] Collect warnings
- [ ] Update job status to "analyzed"

**Technical Approach**:
```python
# app/services/import_service.py
import uuid
import tempfile
import zipfile
from pathlib import Path

class ImportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = ImportJobRepository(session)
        self.parser = HeuristicParser()
        self.schema_engine = SchemaInferenceEngine()
        self.asset_rewriter = AssetRewriter()
    
    async def analyze_package(
        self, 
        zip_data: bytes, 
        course_id: Optional[str] = None
    ) -> str:
        """Analyze SCORM package."""
        # Create job
        job_id = str(uuid.uuid4())
        await self.job_repo.create(job_id, "analyzing", f"temp://{job_id}")
        
        try:
            # Extract ZIP
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = Path(tmpdir) / "package.zip"
                zip_path.write_bytes(zip_data)
                
                # Extract safely
                zip_contents = self._extract_zip_safely(zip_path, Path(tmpdir))
                
                # Find JSON payload
                course_data = self._discover_payload(zip_contents)
                if not course_data:
                    raise NoPayloadFoundError("No JSON payload found")
                
                # Process templates
                templates = course_data.get("templates", [])
                processed_templates = []
                warnings = []
                
                for idx, template in enumerate(templates):
                    try:
                        # Infer schema
                        schema = self.schema_engine.infer_schema_from_data(template.get("data", {}))
                        signature = self.schema_engine.compute_schema_signature(schema)
                        
                        # Check for existing definition
                        # ... (deduplication logic)
                        
                        processed_templates.append({
                            **template,
                            "schema_signature": signature
                        })
                    except Exception as e:
                        warnings.append({
                            "index": idx,
                            "message": str(e),
                            "type": "template_processing_error"
                        })
                
                # Stage results
                await self.job_repo.update_result(
                    job_id,
                    {
                        "courseId": course_id,
                        "templates": processed_templates,
                        "warnings": warnings
                    }
                )
                await self.job_repo.update_status(job_id, "analyzed", 1.0)
                
                return job_id
        
        except Exception as e:
            await self.job_repo.update_status(job_id, "failed", 0.0)
            await self.job_repo.update_error(job_id, str(e))
            raise
```

**Testing**:
```python
# tests/integration/test_import_service.py
@pytest.mark.asyncio
async def test_analyze_valid_package(db_session, sample_scorm_zip):
    service = ImportService(db_session)
    job_id = await service.analyze_package(sample_scorm_zip)
    
    # Verify job created
    repo = ImportJobRepository(db_session)
    job = await repo.get_by_id(job_id)
    assert job.status == "analyzed"
    assert job.result_data is not None
    assert len(job.result_data["templates"]) > 0
```

**Effort**: XL  
**Dependencies**: Task 1.1, Task 1.2, Task 1.3, Task 2.1  
**Owner**: Senior Backend Developer

---

#### Task 2.3: ImportService - Commit Import
**Story**: As a system, I need to finalize imports and create courses.

**Acceptance Criteria**:
- [ ] `commit_import()` method
- [ ] Validate job status is "analyzed"
- [ ] Create `CourseRecord` from staged data
- [ ] Create `TemplateRecord` entries
- [ ] Move assets to permanent storage
- [ ] Optional: Harvest templates to global library
- [ ] Update job status to "committed"
- [ ] Transaction management (rollback on error)

**Technical Approach**:
```python
# app/services/import_service.py (continued)

async def commit_import(
    self, 
    job_id: str, 
    harvest_templates: bool = False
) -> str:
    """Commit analyzed import to database."""
    # Get job
    job = await self.job_repo.get_by_id(job_id)
    if job.status != "analyzed":
        raise InvalidStateError(f"Job must be analyzed, not {job.status}")
    
    try:
        # Extract staged data
        course_data = job.result_data
        course_id = course_data["courseId"]
        
        # Create course
        course_repo = CourseRepository(self.session)
        course = await course_repo.create(
            course_id=course_id,
            title=course_data["title"],
            json_data=course_data
        )
        
        # Create templates
        for idx, template in enumerate(course_data["templates"]):
            await course_repo.create_template(
                course_id=course.id,
                template_uid=template["id"],
                template_type=template["type"],
                title=template.get("title", f"Template {idx}"),
                order_index=idx,
                json_data=template
            )
        
        # Optional: Harvest templates
        if harvest_templates:
            await self._harvest_templates(course_data["templates"])
        
        # Update job
        await self.job_repo.update_status(job_id, "committed", 1.0)
        await self.job_repo.update_course_id(job_id, course_id)
        
        return course_id
    
    except Exception as e:
        await self.session.rollback()
        await self.job_repo.update_status(job_id, "failed", 0.5)
        await self.job_repo.update_error(job_id, str(e))
        raise
```

**Testing**:
```python
# tests/integration/test_import_service.py
@pytest.mark.asyncio
async def test_commit_import(db_session, analyzed_job_id):
    service = ImportService(db_session)
    course_id = await service.commit_import(analyzed_job_id)
    
    # Verify course created
    course_repo = CourseRepository(db_session)
    course = await course_repo.get_by_course_id(course_id)
    assert course is not None
    
    # Verify templates created
    templates = await course_repo.get_templates(course.id)
    assert len(templates) > 0
```

**Effort**: L  
**Dependencies**: Task 2.2  
**Owner**: Senior Backend Developer

---

## Sprint 3: API & Background Jobs (Weeks 6-7)

### Goal
Implement REST endpoints and async background processing.

---

#### Task 3.1: POST /api/v1/imports/analyze Endpoint
**Story**: As a client, I can upload a ZIP file for analysis.

**Acceptance Criteria**:
- [ ] Endpoint created in `app/routers/imports.py`
- [ ] Accepts multipart/form-data with ZIP file
- [ ] Validates file size (max 200MB)
- [ ] Validates file type (.zip)
- [ ] Returns 202 Accepted with job_id
- [ ] Triggers background task
- [ ] Proper error responses (400, 413, 500)

**Technical Approach**:
```python
# app/routers/imports.py
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/imports", tags=["imports"])

class ImportAnalysisResponse(BaseModel):
    job_id: str
    status: str
    progress: float

@router.post("/analyze", response_model=ImportAnalysisResponse, status_code=202)
async def analyze_import(
    file: UploadFile = File(...),
    course_id: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session)
):
    """Upload and analyze SCORM package."""
    # Validate file type
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "File must be a ZIP archive")
    
    # Validate size (checked in middleware)
    content = await file.read()
    
    # Create service
    service = ImportService(session)
    
    # Start analysis in background
    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        service.analyze_package_background,
        job_id=job_id,
        zip_data=content,
        course_id=course_id
    )
    
    return {
        "job_id": job_id,
        "status": "analyzing",
        "progress": 0.0
    }
```

**Testing**:
```python
# tests/api/test_imports_api.py
def test_analyze_endpoint(test_client, sample_zip):
    response = test_client.post(
        "/api/v1/imports/analyze",
        files={"file": ("test.zip", sample_zip, "application/zip")}
    )
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "analyzing"

def test_analyze_invalid_file_type(test_client):
    response = test_client.post(
        "/api/v1/imports/analyze",
        files={"file": ("test.txt", b"invalid", "text/plain")}
    )
    assert response.status_code == 400
```

**Effort**: M  
**Dependencies**: Task 2.2  
**Owner**: Backend Developer

---

#### Task 3.2: GET /api/v1/imports/jobs/{job_id} Endpoint
**Story**: As a client, I can check the status of an import job.

**Acceptance Criteria**:
- [ ] Endpoint created
- [ ] Returns job status and progress
- [ ] Returns full result_data when status is "analyzed"
- [ ] Returns error_message when status is "failed"
- [ ] Supports pagination for templates (query params)
- [ ] Returns 404 if job not found

**Technical Approach**:
```python
# app/routers/imports.py (continued)

class ImportStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: float
    course_data: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str

@router.get("/jobs/{job_id}", response_model=ImportStatusResponse)
async def get_import_status(
    job_id: str,
    page: int = 1,
    per_page: int = 10,
    session: AsyncSession = Depends(get_session)
):
    """Get import job status."""
    repo = ImportJobRepository(session)
    try:
        job = await repo.get_by_id(job_id)
    except JobNotFoundError:
        raise HTTPException(404, f"Job {job_id} not found")
    
    response_data = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat()
    }
    
    # Include result data if analyzed
    if job.status == "analyzed" and job.result_data:
        # Paginate templates
        templates = job.result_data.get("templates", [])
        start = (page - 1) * per_page
        end = start + per_page
        
        response_data["course_data"] = {
            **job.result_data,
            "templates": templates[start:end],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": len(templates)
            }
        }
    
    return response_data
```

**Testing**:
```python
# tests/api/test_imports_api.py
def test_get_job_status(test_client, analyzed_job_id):
    response = test_client.get(f"/api/v1/imports/jobs/{analyzed_job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "analyzed"
    assert "course_data" in data

def test_get_nonexistent_job(test_client):
    response = test_client.get("/api/v1/imports/jobs/nonexistent")
    assert response.status_code == 404
```

**Effort**: M  
**Dependencies**: Task 2.1, Task 3.1  
**Owner**: Backend Developer

---

#### Task 3.3: POST /api/v1/imports/jobs/{job_id}/commit Endpoint
**Story**: As a client, I can commit an analyzed import to create a course.

**Acceptance Criteria**:
- [ ] Endpoint created
- [ ] Accepts optional `harvest_templates` flag
- [ ] Calls `ImportService.commit_import()`
- [ ] Returns course_id on success
- [ ] Returns 400 if job not in "analyzed" state
- [ ] Returns 404 if job not found

**Technical Approach**:
```python
# app/routers/imports.py (continued)

class ImportCommitRequest(BaseModel):
    harvest_templates: bool = False

class ImportCommitResponse(BaseModel):
    job_id: str
    status: str
    course_id: str
    message: str

@router.post("/jobs/{job_id}/commit", response_model=ImportCommitResponse)
async def commit_import(
    job_id: str,
    request: ImportCommitRequest = ImportCommitRequest(),
    session: AsyncSession = Depends(get_session)
):
    """Commit analyzed import."""
    service = ImportService(session)
    
    try:
        course_id = await service.commit_import(
            job_id, 
            harvest_templates=request.harvest_templates
        )
        return {
            "job_id": job_id,
            "status": "committed",
            "course_id": course_id,
            "message": "Import committed successfully"
        }
    except JobNotFoundError:
        raise HTTPException(404, f"Job {job_id} not found")
    except InvalidStateError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Commit failed: {str(e)}")
```

**Testing**:
```python
# tests/api/test_imports_api.py
def test_commit_import(test_client, analyzed_job_id):
    response = test_client.post(
        f"/api/v1/imports/jobs/{analyzed_job_id}/commit",
        json={"harvest_templates": False}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "committed"
    assert "course_id" in data

def test_commit_pending_job(test_client, pending_job_id):
    response = test_client.post(f"/api/v1/imports/jobs/{pending_job_id}/commit")
    assert response.status_code == 400
```

**Effort**: M  
**Dependencies**: Task 2.3, Task 3.2  
**Owner**: Backend Developer

---

## Sprint 4: Integration & Hardening (Weeks 8-9)

### Goal
Security hardening, performance optimization, comprehensive testing.

---

#### Task 4.1: Security Audit
**Story**: As a security engineer, I need to ensure the system is secure.

**Acceptance Criteria**:
- [ ] ZIP Slip vulnerability tested and mitigated
- [ ] No eval() in codebase
- [ ] Input validation on all endpoints
- [ ] File size limits enforced
- [ ] SQL injection prevention verified
- [ ] XSS prevention in asset rewriting
- [ ] Security scan with `bandit`

**Technical Approach**:
```bash
# Run security scan
bandit -r app/ -ll

# Test ZIP Slip
# tests/security/test_zip_slip.py
def test_zip_slip_prevention():
    malicious_zip = create_zip_with_traversal("../../etc/passwd")
    service = ImportService(session)
    with pytest.raises(SecurityError):
        await service.analyze_package(malicious_zip)
```

**Effort**: L  
**Dependencies**: All Sprint 1-3 tasks  
**Owner**: Security Engineer / Senior Developer

---

#### Task 4.2: Performance Testing
**Story**: As a DevOps engineer, I need to ensure the system can handle load.

**Acceptance Criteria**:
- [ ] Load test with 50 concurrent uploads
- [ ] 100MB ZIP processes in < 30 seconds
- [ ] Database queries optimized (indexes verified)
- [ ] Memory usage stays below 2GB per worker
- [ ] No memory leaks detected

**Technical Approach**:
```python
# tests/performance/test_load.py
import asyncio
import time

async def test_concurrent_uploads():
    """Test 50 concurrent uploads."""
    tasks = [upload_and_analyze(sample_zip) for _ in range(50)]
    start = time.time()
    results = await asyncio.gather(*tasks)
    duration = time.time() - start
    
    assert all(r["status"] == "analyzing" for r in results)
    assert duration < 60  # Should complete within 1 minute
```

**Effort**: M  
**Dependencies**: All Sprint 1-3 tasks  
**Owner**: DevOps Engineer

---

#### Task 4.3: E2E Testing
**Story**: As a QA engineer, I need end-to-end test coverage.

**Acceptance Criteria**:
- [ ] E2E test: Upload → Analyze → Commit → Verify course
- [ ] E2E test: Upload invalid ZIP → Verify error
- [ ] E2E test: Upload with ambiguous assets → Verify warnings
- [ ] E2E test: Template harvesting flow
- [ ] All tests pass in CI/CD pipeline

**Technical Approach**:
```python
# tests/e2e/test_import_flow.py
@pytest.mark.e2e
async def test_full_import_flow(test_client, sample_scorm_zip):
    # 1. Upload
    response = test_client.post(
        "/api/v1/imports/analyze",
        files={"file": ("test.zip", sample_scorm_zip, "application/zip")}
    )
    job_id = response.json()["job_id"]
    
    # 2. Poll status
    while True:
        response = test_client.get(f"/api/v1/imports/jobs/{job_id}")
        status = response.json()["status"]
        if status in ("analyzed", "failed"):
            break
        await asyncio.sleep(0.5)
    
    assert status == "analyzed"
    
    # 3. Commit
    response = test_client.post(f"/api/v1/imports/jobs/{job_id}/commit")
    course_id = response.json()["course_id"]
    
    # 4. Verify course exists
    response = test_client.get(f"/api/v1/courses/{course_id}")
    assert response.status_code == 200
```

**Effort**: L  
**Dependencies**: All Sprint 1-3 tasks  
**Owner**: QA Engineer

---

#### Task 4.4: Monitoring & Logging
**Story**: As a DevOps engineer, I need observability.

**Acceptance Criteria**:
- [ ] Prometheus metrics endpoint
- [ ] Structured logging (JSON format)
- [ ] Request ID tracing
- [ ] Error rate monitoring
- [ ] Import duration metrics
- [ ] Dashboard in Grafana

**Technical Approach**:
```python
# app/main.py
from prometheus_client import make_asgi_app, Counter, Histogram

# Metrics
import_requests_total = Counter(
    'import_requests_total',
    'Total import requests',
    ['status']
)

import_duration_seconds = Histogram(
    'import_duration_seconds',
    'Import analysis duration',
    buckets=[1, 5, 10, 30, 60, 120]
)

# Mount metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

**Effort**: M  
**Dependencies**: None (can be parallel)  
**Owner**: DevOps Engineer

---

## Sprint 5: Documentation & Launch (Week 10)

### Goal
Finalize documentation, deployment guide, and production launch.

---

#### Task 5.1: API Documentation
**Story**: As a frontend developer, I need complete API documentation.

**Acceptance Criteria**:
- [ ] OpenAPI/Swagger docs complete
- [ ] Example requests/responses for all endpoints
- [ ] Error codes documented
- [ ] Authentication notes (none for Phase 2)
- [ ] Rate limiting notes

**Effort**: S  
**Owner**: Backend Developer

---

#### Task 5.2: Deployment Guide
**Story**: As a DevOps engineer, I need deployment instructions.

**Acceptance Criteria**:
- [ ] Render deployment steps
- [ ] Environment variable checklist
- [ ] Database migration steps
- [ ] Rollback procedure
- [ ] Health check verification

**Effort**: S  
**Owner**: DevOps Engineer

---

#### Task 5.3: User Guide
**Story**: As a product manager, I need user-facing documentation.

**Acceptance Criteria**:
- [ ] Import workflow explained
- [ ] Supported file formats
- [ ] Error troubleshooting guide
- [ ] Best practices for package structure

**Effort**: S  
**Owner**: Product Manager

---

#### Task 5.4: Production Deployment
**Story**: As a DevOps engineer, I deploy to production.

**Acceptance Criteria**:
- [ ] Run all migrations
- [ ] Deploy to staging first
- [ ] Run smoke tests
- [ ] Deploy to production
- [ ] Monitor for 24 hours
- [ ] Enable feature flag (if applicable)

**Effort**: M  
**Dependencies**: All previous tasks  
**Owner**: DevOps Engineer

---

## Risk Register

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| AST parsing fails on complex JS | High | Medium | Implement robust regex fallback |
| Large ZIP files exhaust memory | High | Low | Stream processing, temp files |
| Database performance under load | Medium | Medium | Proper indexing, connection pooling |
| Security vulnerability discovered | Critical | Low | Security audit before launch |
| Background tasks lost on restart | Medium | Medium | Document limitation, add persistence later |

---

## Success Metrics

**Launch Criteria**:
- [ ] All unit tests pass (90%+ coverage)
- [ ] All integration tests pass
- [ ] E2E tests pass
- [ ] Security audit complete
- [ ] Load test passes (50 concurrent)
- [ ] Documentation complete
- [ ] Stakeholder sign-off

**Post-Launch KPIs**:
- Import success rate > 95%
- Average import time < 15 seconds (100MB file)
- Error rate < 5%
- Zero security incidents
- User satisfaction score > 4.0/5.0

---

## Appendix: Testing Data

### Sample SCORM Packages

**Minimal Valid Package**:
```
minimal_course.zip
├── course_data.js
│   var courseData = {
│     courseId: "test-001",
│     title: "Test Course",
│     templates: [
│       {id: "1", type: "welcome", title: "Welcome", data: {content: "Hello"}}
│     ]
│   };
└── index.html
```

**Complex Package**:
```
complex_course.zip
├── data/
│   └── config.js (minified ES6)
├── media/
│   ├── images/
│   │   └── logo.png
│   └── videos/
│       └── intro.mp4
├── styles/
│   └── main.css (with url() references)
└── index.html (with <img> tags)
```

**Malicious Package** (for security testing):
```
malicious_course.zip
└── ../../../etc/passwd  (ZIP Slip attempt)
```

---

## Conclusion

This implementation plan provides a **sprint-by-sprint roadmap** with:
- ✅ Clear task definitions
- ✅ Acceptance criteria
- ✅ Code examples
- ✅ Testing strategies
- ✅ Dependencies mapped
- ✅ Effort estimates
- ✅ Risk mitigation

The development team can now execute with confidence, knowing exactly what to build and how to validate success.

**Next Steps**:
1. Review this plan with the team
2. Assign owners to each task
3. Set up project board (Jira/GitHub Projects)
4. Begin Sprint 0

---

**Document Version**: 1.0  
**Last Updated**: December 2025  
**Next Review**: After Sprint 2 completion
