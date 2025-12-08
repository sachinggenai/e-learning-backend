# SCORM Import Technical Architecture Specification
## Version 2.0 - Production-Ready Implementation Guide

**Status**: ✅ ARCHITECT-APPROVED  
**Compliance**: SCORM 1.2, SOLID Principles, Clean Architecture  
**Date**: December 2025  
**Author**: Technical Architecture Team

---

## Executive Summary

This document provides the **atomic-level technical specifications** for implementing the SCORM Import functionality described in BRD v1.9. It bridges the gap between business requirements and production code by specifying:

1. **Exact library versions** and configuration
2. **Database indexes** and query optimization strategies
3. **Security hardening** measures with code examples
4. **Performance benchmarks** and monitoring strategies
5. **Error handling** patterns with retry logic
6. **Testing strategies** with coverage targets

This document is mandatory reading before starting implementation.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Technology Stack Decisions](#technology-stack-decisions)
3. [Database Design & Optimization](#database-design--optimization)
4. [Security Architecture](#security-architecture)
5. [Performance & Scalability](#performance--scalability)
6. [Error Handling & Resilience](#error-handling--resilience)
7. [API Design Specifications](#api-design-specifications)
8. [Testing Strategy](#testing-strategy)
9. [Deployment & Operations](#deployment--operations)
10. [Code Quality Standards](#code-quality-standards)

---

## 1. Architecture Overview

### 1.1 Design Principles

This implementation follows **Clean Architecture** with strict layer separation:

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (Routers)                   │
│  - REST endpoints                                        │
│  - Input validation (Pydantic)                           │
│  - Response serialization                                │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                  Service Layer (Business Logic)          │
│  - ImportService: Orchestration                          │
│  - HeuristicParser: JS/JSON extraction                   │
│  - SchemaInferenceEngine: Type detection                 │
│  - AssetRewriter: Path normalization                     │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                Repository Layer (Data Access)            │
│  - ImportJobRepository                                   │
│  - TemplateDefinitionRepository                          │
│  - CourseRepository                                      │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                  Database (PostgreSQL/SQLite)            │
└─────────────────────────────────────────────────────────┘
```

**Key Architectural Decisions:**

1. **Async-First**: All I/O operations use `async/await`
2. **Repository Pattern**: No direct SQLAlchemy in services
3. **Dependency Injection**: FastAPI's native DI for all dependencies
4. **Immutable Data Structures**: Pydantic models for data transfer
5. **Fail-Fast Validation**: Early validation at API boundary

### 1.2 Data Flow Architecture

```mermaid
sequenceDiagram
    participant Client
    participant API as Import Router
    participant Service as Import Service
    participant Parser as Heuristic Parser
    participant Inference as Schema Engine
    participant Repo as ImportJob Repo
    participant DB as PostgreSQL

    Client->>API: POST /api/v1/imports/analyze (ZIP)
    API->>API: Validate file size & type
    API->>Service: analyze_package(zip_bytes)
    Service->>Service: Create temp directory
    Service->>Repo: create_job(job_id, status=PENDING)
    Repo->>DB: INSERT import_jobs
    DB-->>Repo: job_id
    Repo-->>Service: ImportJob
    Service-->>API: job_id
    API-->>Client: 202 Accepted {job_id}
    
    Note over Service: Background Task Starts
    Service->>Service: Extract ZIP safely
    Service->>Parser: extract_json_from_js(file)
    Parser->>Parser: Try AST parsing
    Parser-->>Service: course_data
    Service->>Inference: infer_schema_from_data(template)
    Inference->>Inference: Compute signature
    Inference->>DB: SELECT template_definitions WHERE signature=?
    DB-->>Inference: existing_def OR None
    alt Schema exists
        Inference-->>Service: existing_type
    else New schema
        Inference->>DB: INSERT template_definitions (status=DRAFT)
        Inference-->>Service: new_type
    end
    Service->>Repo: update_result(job_id, staged_data)
    Repo->>DB: UPDATE import_jobs SET result_data=?, status=ANALYZED
    
    Client->>API: GET /api/v1/imports/jobs/{job_id}
    API->>Repo: get_by_id(job_id)
    Repo->>DB: SELECT * FROM import_jobs WHERE job_id=?
    DB-->>Repo: ImportJob(status=ANALYZED, result_data=...)
    Repo-->>API: ImportJob
    API-->>Client: 200 OK {status, templates, warnings}
    
    Client->>API: POST /api/v1/imports/jobs/{job_id}/commit
    API->>Service: commit_import(job_id)
    Service->>Repo: get_by_id(job_id)
    Service->>Service: Validate staged_data
    Service->>Repo: create_course(course_data)
    Service->>Repo: update_status(job_id, COMMITTED)
    Service-->>API: course_id
    API-->>Client: 200 OK {course_id}
```

---

## 2. Technology Stack Decisions

### 2.1 JavaScript Parsing

**Requirement**: Parse minified ES6+ JavaScript without executing code.

**Decision**: Use `pyjsparser` v2.7.1+

**Rationale**:
- ✅ Supports ES6 (arrow functions, `let`, `const`, template literals)
- ✅ Pure Python (no Node.js dependency)
- ✅ Well-maintained (active development)
- ✅ Safe (AST parsing, no `eval()`)
- ❌ Alternatives rejected:
  - `slimit`: Unmaintained, ES5 only
  - `esprima-python`: Slower, less ES6 coverage

**Installation**:
```bash
pip install pyjsparser==2.7.1
```

**Usage Pattern**:
```python
import pyjsparser
from typing import Any, Optional

class HeuristicParser:
    @staticmethod
    def _extract_via_ast(js_code: str) -> Optional[dict]:
        """Extract JSON from JS using AST parsing."""
        try:
            ast = pyjsparser.parse(js_code)
            # Walk AST looking for variable assignments
            for node in HeuristicParser._walk_ast(ast):
                if node.get("type") == "VariableDeclaration":
                    for decl in node.get("declarations", []):
                        init = decl.get("init")
                        if init and init.get("type") in ["ObjectExpression", "ArrayExpression"]:
                            # Convert AST node to Python dict
                            return HeuristicParser._ast_to_dict(init)
            return None
        except Exception as e:
            logger.warning(f"AST parsing failed: {e}")
            return None
```

### 2.2 HTML/CSS Parsing

**Requirement**: Rewrite asset URLs in HTML strings and CSS.

**Decision**: Use `beautifulsoup4` v4.12+ with `lxml` parser

**Rationale**:
- ✅ Industry standard for HTML parsing
- ✅ Lenient parsing (handles malformed HTML)
- ✅ CSS selector support
- ✅ Thread-safe

**Installation**:
```bash
pip install beautifulsoup4==4.12.2 lxml==4.9.3
```

**Usage Pattern**:
```python
from bs4 import BeautifulSoup
import re

class AssetRewriter:
    @staticmethod
    def rewrite_html_content(html: str, asset_map: dict) -> str:
        """Rewrite src/href attributes to API URLs."""
        soup = BeautifulSoup(html, 'lxml')
        
        # Rewrite <img src="...">
        for tag in soup.find_all(['img', 'video', 'audio', 'source']):
            if 'src' in tag.attrs:
                original = tag['src']
                if new_url := asset_map.get(original):
                    tag['src'] = new_url
        
        # Rewrite <link href="...">
        for tag in soup.find_all('link', href=True):
            original = tag['href']
            if new_url := asset_map.get(original):
                tag['href'] = new_url
        
        return str(soup)
    
    @staticmethod
    def rewrite_css_content(css: str, asset_map: dict) -> str:
        """Rewrite url(...) in CSS."""
        def replace_url(match):
            original = match.group(1).strip('\'"')
            return f"url('{asset_map.get(original, original)}')"
        
        return re.sub(r'url\(([^)]+)\)', replace_url, css)
```

### 2.3 Storage Abstraction

**Requirement**: Support local disk (dev) and cloud storage (prod).

**Decision**: Abstract Base Class with environment-based injection

**Implementation**:
```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO
import os

class StorageService(ABC):
    """Abstract storage interface."""
    
    @abstractmethod
    async def save_file(self, file_path: str, content: bytes) -> str:
        """Save file and return public URL."""
        pass
    
    @abstractmethod
    async def get_file(self, file_path: str) -> bytes:
        """Retrieve file content."""
        pass
    
    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Delete file."""
        pass

class LocalStorageService(StorageService):
    """Local filesystem storage for development."""
    
    def __init__(self, base_path: str = "./media"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    async def save_file(self, file_path: str, content: bytes) -> str:
        """Save to local disk."""
        full_path = self.base_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return f"/api/v1/media/{file_path}"
    
    async def get_file(self, file_path: str) -> bytes:
        """Read from local disk."""
        return (self.base_path / file_path).read_bytes()
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete from local disk."""
        try:
            (self.base_path / file_path).unlink()
            return True
        except FileNotFoundError:
            return False

# Factory function
def get_storage_service() -> StorageService:
    """Dependency injection factory."""
    storage_type = os.getenv("STORAGE_TYPE", "local")
    if storage_type == "local":
        return LocalStorageService(os.getenv("MEDIA_PATH", "./media"))
    elif storage_type == "s3":
        # Future: return S3StorageService(...)
        raise NotImplementedError("S3 storage not yet implemented")
    else:
        raise ValueError(f"Unknown storage type: {storage_type}")
```

---

## 3. Database Design & Optimization

### 3.1 Schema Definitions

**Import Jobs Table** (PostgreSQL JSONB for flexibility):
```sql
CREATE TABLE import_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) UNIQUE NOT NULL,  -- UUID v4
    status VARCHAR(32) NOT NULL,  -- PENDING, ANALYZING, ANALYZED, COMMITTING, COMMITTED, FAILED
    progress FLOAT NOT NULL DEFAULT 0.0,  -- 0.0 to 1.0
    course_id VARCHAR(64),  -- FK to courses (nullable until committed)
    source_file_path VARCHAR(500) NOT NULL,
    source_file_size BIGINT,  -- For validation
    error_message TEXT,
    result_data JSONB,  -- Staged course data
    metadata JSONB,  -- Upload metadata (filename, user agent, etc.)
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_import_jobs_job_id ON import_jobs(job_id);
CREATE INDEX idx_import_jobs_status ON import_jobs(status);
CREATE INDEX idx_import_jobs_created_at ON import_jobs(created_at DESC);
CREATE INDEX idx_import_jobs_course_id ON import_jobs(course_id) WHERE course_id IS NOT NULL;
```

**Template Definitions Table** (Dynamic schema storage):
```sql
CREATE TABLE template_definitions (
    id SERIAL PRIMARY KEY,
    template_type VARCHAR(100) UNIQUE NOT NULL,  -- 'mcq', 'inferred_abc123'
    display_name VARCHAR(200) NOT NULL,
    schema_signature VARCHAR(64) NOT NULL,  -- SHA-256 hash
    schema_json JSONB NOT NULL,  -- Field definitions
    render_template_html TEXT NOT NULL,  -- Jinja2 template
    is_active BOOLEAN NOT NULL DEFAULT FALSE,  -- DRAFT vs ACTIVE
    source_metadata JSONB,  -- {import_job_id, filename, timestamp}
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_template_def_type ON template_definitions(template_type);
CREATE INDEX idx_template_def_signature ON template_definitions(schema_signature);
CREATE INDEX idx_template_def_active ON template_definitions(is_active);
```

**Global Templates Table** (Harvested reusable content):
```sql
CREATE TABLE global_templates (
    id SERIAL PRIMARY KEY,
    global_template_id VARCHAR(64) UNIQUE NOT NULL,  -- UUID
    template_type VARCHAR(100) NOT NULL,  -- FK to template_definitions
    title VARCHAR(200) NOT NULL,
    description TEXT,
    json_data JSONB NOT NULL,  -- Template content
    version INTEGER NOT NULL DEFAULT 1,
    is_published BOOLEAN NOT NULL DEFAULT FALSE,
    tags TEXT[],  -- For search/filtering
    usage_count INTEGER NOT NULL DEFAULT 0,  -- Track popularity
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    FOREIGN KEY (template_type) REFERENCES template_definitions(template_type)
);

-- Indexes
CREATE INDEX idx_global_templates_type ON global_templates(template_type);
CREATE INDEX idx_global_templates_published ON global_templates(is_published);
CREATE INDEX idx_global_templates_tags ON global_templates USING GIN(tags);
```

### 3.2 SQLAlchemy ORM Models

**Critical Design Decision**: Use `Base = declarative_base()` from SQLAlchemy, NOT `app.database.Base`.

```python
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Float, BigInteger, Boolean
from datetime import datetime
from typing import Optional

Base = declarative_base()

class ImportJob(Base):
    """Import job tracking with JSONB staging."""
    __tablename__ = "import_jobs"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    course_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )
    
    def to_dict(self) -> dict:
        """Convert to API response format."""
        return {
            "jobId": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "courseId": self.course_id,
            "errorMessage": self.error_message,
            "resultData": self.result_data,
            "metadata": self.metadata,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
```

### 3.3 Query Optimization

**Problem**: Fetching large JSONB `result_data` is expensive.

**Solution**: Pagination and partial loading.

```python
class ImportJobRepository:
    async def get_preview(
        self, 
        job_id: str, 
        page: int = 1, 
        per_page: int = 10
    ) -> dict:
        """Get paginated preview of templates."""
        query = select(ImportJob).where(ImportJob.job_id == job_id)
        result = await self.session.execute(query)
        job = result.scalar_one_or_none()
        
        if not job or not job.result_data:
            raise JobNotFoundError(job_id)
        
        templates = job.result_data.get("templates", [])
        total = len(templates)
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            "jobId": job_id,
            "status": job.status,
            "templates": templates[start:end],
            "pagination": {
                "page": page,
                "perPage": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            }
        }
```

---

## 4. Security Architecture

### 4.1 ZIP Slip Prevention

**Vulnerability**: Malicious ZIP files with paths like `../../etc/passwd`.

**Mitigation**:
```python
import zipfile
from pathlib import Path

class SecureZipExtractor:
    @staticmethod
    def extract_safely(zip_path: Path, extract_to: Path) -> None:
        """Extract ZIP with path traversal protection."""
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.namelist():
                # Normalize path
                member_path = Path(member).resolve()
                target_path = (extract_to / member).resolve()
                
                # Ensure target is within extract directory
                if not str(target_path).startswith(str(extract_to.resolve())):
                    raise SecurityError(f"ZIP Slip attempt detected: {member}")
                
                # Extract
                zf.extract(member, extract_to)
```

### 4.2 No Code Execution

**Requirement**: Never execute JavaScript from uploads.

**Implementation**:
```python
class HeuristicParser:
    # BANNED PATTERNS
    DANGEROUS_PATTERNS = [
        r'\beval\s*\(',  # eval()
        r'\bFunction\s*\(',  # new Function()
        r'\bsetTimeout\s*\(',  # setTimeout()
        r'\bsetInterval\s*\(',  # setInterval()
    ]
    
    @staticmethod
    def scan_for_dangerous_code(js_code: str) -> list[str]:
        """Detect potentially malicious code."""
        violations = []
        for pattern in HeuristicParser.DANGEROUS_PATTERNS:
            if re.search(pattern, js_code, re.IGNORECASE):
                violations.append(f"Dangerous pattern detected: {pattern}")
        return violations
    
    async def extract_json_from_js(self, js_code: str) -> dict:
        """Extract JSON safely."""
        # Security check first
        if violations := self.scan_for_dangerous_code(js_code):
            raise SecurityError(f"Unsafe code detected: {violations}")
        
        # Parse with AST (no execution)
        return self._extract_via_ast(js_code)
```

### 4.3 File Size Limits

**Requirement**: Prevent resource exhaustion.

**Implementation**:
```python
# In app/main.py
from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class FileSizeLimitMiddleware(BaseHTTPMiddleware):
    MAX_SIZE = 200 * 1024 * 1024  # 200MB
    
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.MAX_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Max size: {self.MAX_SIZE} bytes"
                )
        return await call_next(request)

app.add_middleware(FileSizeLimitMiddleware)
```

### 4.4 Input Validation

**Use Pydantic V2 validators**:
```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class ImportAnalysisRequest(BaseModel):
    course_id: Optional[str] = Field(None, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    harvest_templates: bool = False
    
    @field_validator('course_id')
    @classmethod
    def validate_course_id(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.strip():
            raise ValueError("Course ID cannot be empty")
        return v
```

---

## 5. Performance & Scalability

### 5.1 Async Processing

**Pattern**: FastAPI Background Tasks for short jobs (<30s), Celery for longer.

```python
from fastapi import BackgroundTasks
import logging

logger = logging.getLogger(__name__)

@router.post("/analyze")
async def analyze_import(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Upload and trigger background analysis."""
    # Quick validation
    if file.size > 200 * 1024 * 1024:
        raise HTTPException(413, "File too large")
    
    # Create job
    service = ImportService(session)
    job_id = str(uuid.uuid4())
    await service.create_job(job_id, file.filename)
    
    # Schedule background task
    content = await file.read()
    background_tasks.add_task(
        service.analyze_package_background,
        job_id=job_id,
        zip_data=content
    )
    
    return {"job_id": job_id, "status": "analyzing"}
```

### 5.2 Database Connection Pooling

**Configuration**:
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,  # Base connections
    max_overflow=40,  # Additional connections under load
    pool_pre_ping=True,  # Health check connections
    pool_recycle=3600,  # Recycle after 1 hour
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
```

### 5.3 Caching Strategy

**Use Redis for template definitions**:
```python
from redis.asyncio import Redis
import json

class TemplateCacheService:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.ttl = 3600  # 1 hour
    
    async def get_definition(self, template_type: str) -> Optional[dict]:
        """Get cached definition."""
        key = f"template_def:{template_type}"
        if data := await self.redis.get(key):
            return json.loads(data)
        return None
    
    async def set_definition(self, template_type: str, definition: dict) -> None:
        """Cache definition."""
        key = f"template_def:{template_type}"
        await self.redis.setex(key, self.ttl, json.dumps(definition))
```

### 5.4 Monitoring & Metrics

**Use Prometheus metrics**:
```python
from prometheus_client import Counter, Histogram

import_requests = Counter(
    'import_requests_total', 
    'Total import requests',
    ['status']
)

import_duration = Histogram(
    'import_duration_seconds',
    'Time to analyze import',
    buckets=[1, 5, 10, 30, 60, 120]
)

# Usage in service
with import_duration.time():
    result = await self.analyze_package(zip_data)
    import_requests.labels(status='success').inc()
```

---

## 6. Error Handling & Resilience

### 6.1 Error Hierarchy

```python
class ImportServiceError(Exception):
    """Base exception for import service."""
    pass

class NoPayloadFoundError(ImportServiceError):
    """No JSON payload found in package."""
    code = "ERR_NO_PAYLOAD_FOUND"

class AmbiguousAssetError(ImportServiceError):
    """Duplicate asset filenames detected."""
    code = "ERR_AMBIGUOUS_ASSET"

class MalformedPackageError(ImportServiceError):
    """Package structure invalid."""
    code = "ERR_MALFORMED_PACKAGE"

class SecurityError(ImportServiceError):
    """Security violation detected."""
    code = "ERR_SECURITY_VIOLATION"
```

### 6.2 Graceful Degradation

**Best-effort import with error placeholders**:
```python
async def _process_templates(self, templates: list) -> tuple[list, list]:
    """Process templates with error handling."""
    results = []
    warnings = []
    
    for idx, template in enumerate(templates):
        try:
            # Validate and process
            processed = await self._process_single_template(template)
            results.append(processed)
        except Exception as e:
            logger.warning(f"Template {idx} failed: {e}")
            # Create error placeholder
            placeholder = {
                "id": f"error_{idx}",
                "type": "error_placeholder",
                "title": f"Import Error (Original Index: {idx})",
                "data": {
                    "error": str(e),
                    "original_data": template
                }
            }
            results.append(placeholder)
            warnings.append({
                "index": idx,
                "message": str(e),
                "type": "template_processing_error"
            })
    
    return results, warnings
```

### 6.3 Retry Logic

**For transient failures**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

class ImportJobRepository:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def update_status(
        self, 
        job_id: str, 
        status: str, 
        progress: float
    ) -> None:
        """Update job status with retry."""
        query = (
            update(ImportJob)
            .where(ImportJob.job_id == job_id)
            .values(status=status, progress=progress, updated_at=datetime.utcnow())
        )
        await self.session.execute(query)
        await self.session.commit()
```

---

## 7. API Design Specifications

### 7.1 REST Endpoint Design

**POST /api/v1/imports/analyze**

Request:
```http
POST /api/v1/imports/analyze HTTP/1.1
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW

------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="file"; filename="course.zip"
Content-Type: application/zip

[binary data]
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="course_id"

test-course-001
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="harvest_templates"

true
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

Response (202 Accepted):
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzing",
  "progress": 0.1,
  "message": "Analysis started"
}
```

**GET /api/v1/imports/jobs/{job_id}**

Response (200 OK - Completed):
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzed",
  "progress": 1.0,
  "courseData": {
    "courseId": "test-course-001",
    "title": "Imported Course",
    "templates": [
      {
        "id": "slide_1",
        "type": "welcome",
        "title": "Welcome",
        "data": {...}
      }
    ],
    "assets": {
      "images/logo.png": "/api/v1/media/test-course-001/abc123.png"
    }
  },
  "warnings": [
    {
      "type": "ambiguous_asset",
      "message": "Duplicate filename: bg.png",
      "details": {
        "filename": "bg.png",
        "paths": ["module1/bg.png", "module2/bg.png"]
      }
    }
  ],
  "createdAt": "2025-12-19T10:00:00Z",
  "updatedAt": "2025-12-19T10:00:05Z"
}
```

Response (200 OK - Failed):
```json
{
  "jobId": "550e8400-...",
  "status": "failed",
  "progress": 0.5,
  "errorMessage": "ERR_NO_PAYLOAD_FOUND: No JSON payload found in package",
  "createdAt": "2025-12-19T10:00:00Z",
  "updatedAt": "2025-12-19T10:00:03Z"
}
```

### 7.2 Error Responses

**Standard error format**:
```json
{
  "detail": {
    "code": "ERR_NO_PAYLOAD_FOUND",
    "message": "No JSON payload found in the uploaded package",
    "timestamp": "2025-12-19T10:00:00Z",
    "path": "/api/v1/imports/analyze",
    "suggestion": "Ensure the ZIP contains a file with JavaScript variable assignment (e.g., var courseData = {...})"
  }
}
```

---

## 8. Testing Strategy

### 8.1 Test Coverage Targets

- **Unit Tests**: 90% coverage for services and utilities
- **Integration Tests**: 80% coverage for API endpoints
- **E2E Tests**: Critical paths (upload → analyze → commit)

### 8.2 Test Structure

```python
# tests/unit/test_heuristic_parser.py
import pytest
from app.services.heuristic_parser import HeuristicParser

class TestHeuristicParser:
    @pytest.fixture
    def parser(self):
        return HeuristicParser()
    
    def test_extract_minified_js(self, parser):
        """Test parsing minified ES6 code."""
        js = "const data={title:'Test',templates:[{id:'1',type:'welcome'}]};"
        result = parser.extract_json_from_js(js)
        assert result["title"] == "Test"
        assert len(result["templates"]) == 1
    
    def test_reject_dangerous_code(self, parser):
        """Test security scanning."""
        js = "eval('malicious code'); var data = {};"
        with pytest.raises(SecurityError):
            parser.extract_json_from_js(js)
```

### 8.3 Mock Strategies

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
async def mock_import_service(mocker):
    """Mock ImportService for API tests."""
    service = AsyncMock()
    service.analyze_package.return_value = "test-job-id"
    service.get_job.return_value = {
        "job_id": "test-job-id",
        "status": "analyzed",
        "result_data": {...}
    }
    return service
```

---

## 9. Deployment & Operations

### 9.1 Environment Variables

```bash
# Core
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/elearning
STORAGE_TYPE=local  # or 's3'
MEDIA_PATH=./media

# Import-specific
MAX_UPLOAD_SIZE=209715200  # 200MB in bytes
TEMP_FILE_RETENTION_HOURS=24
IMPORT_WORKER_THREADS=4

# Caching
REDIS_URL=redis://localhost:6379/0
CACHE_TTL=3600

# Monitoring
ENABLE_METRICS=true
METRICS_PORT=9090
```

### 9.2 Health Checks

```python
@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "2.0",
        "components": {
            "database": await check_database(),
            "storage": await check_storage(),
            "redis": await check_redis()
        }
    }
```

### 9.3 Cleanup Tasks

**Startup task for temp file cleanup**:
```python
from fastapi import FastAPI
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

app = FastAPI()

@app.on_event("startup")
async def cleanup_temp_files():
    """Remove old temp files on startup."""
    temp_dir = Path("/tmp/uploads")
    cutoff = datetime.now() - timedelta(hours=24)
    
    for file_path in temp_dir.glob("*"):
        if datetime.fromtimestamp(file_path.stat().st_mtime) < cutoff:
            file_path.unlink()
            logger.info(f"Deleted old temp file: {file_path}")
```

---

## 10. Code Quality Standards

### 10.1 Type Hints

**All functions must have complete type annotations**:
```python
from typing import Optional, List, Dict, Any

async def analyze_package(
    self,
    zip_data: bytes,
    course_id: Optional[str] = None,
    harvest_templates: bool = False
) -> str:
    """Analyze SCORM package."""
    ...
```

### 10.2 Docstrings

**Use Google-style docstrings**:
```python
def compute_schema_signature(schema: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of schema.
    
    Args:
        schema: The schema dictionary to hash
        
    Returns:
        SHA-256 hex digest (64 characters)
        
    Raises:
        ValueError: If schema is empty or invalid
        
    Example:
        >>> compute_schema_signature({"fields": ["title", "content"]})
        "a3c65b..."
    """
    if not schema:
        raise ValueError("Schema cannot be empty")
    
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

### 10.3 Linting & Formatting

**Required tools**:
```bash
# Install
pip install black==23.12.1 flake8==7.0.0 mypy==1.8.0 isort==5.13.2

# Run
black app/ tests/
isort app/ tests/
flake8 app/ tests/ --max-line-length=100
mypy app/ --strict
```

### 10.4 Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
  
  - repo: https://github.com/PyCQA/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
        args: [--max-line-length=100]
  
  - repo: https://github.com/PyCQA/isort
    rev: 5.13.2
    hooks:
      - id: isort
```

---

## Appendix A: Implementation Checklist

### Phase 0: Prerequisites
- [ ] Review BRD v1.9
- [ ] Review this technical architecture document
- [ ] Set up development environment
- [ ] Install required dependencies
- [ ] Configure database (PostgreSQL recommended)

### Phase 1: Database Layer
- [ ] Create migration for `import_jobs` table
- [ ] Create migration for `template_definitions` table
- [ ] Create migration for `global_templates` table
- [ ] Add indexes for performance
- [ ] Test migrations with rollback

### Phase 2: Core Services
- [ ] Implement `HeuristicParser` with AST parsing
- [ ] Implement `SchemaInferenceEngine`
- [ ] Implement `AssetRewriter`
- [ ] Implement `StorageService` abstraction
- [ ] Implement `SecureZipExtractor`

### Phase 3: Repository Layer
- [ ] Implement `ImportJobRepository`
- [ ] Implement `TemplateDefinitionRepository`
- [ ] Implement `GlobalTemplateRepository`
- [ ] Add query optimization (pagination, caching)

### Phase 4: Service Layer
- [ ] Implement `ImportService.analyze_package`
- [ ] Implement `ImportService.commit_import`
- [ ] Implement template harvesting logic
- [ ] Add error handling and logging

### Phase 5: API Layer
- [ ] Implement `POST /imports/analyze`
- [ ] Implement `GET /imports/jobs/{id}`
- [ ] Implement `POST /imports/jobs/{id}/commit`
- [ ] Add input validation with Pydantic
- [ ] Add error response formatting

### Phase 6: Security
- [ ] Implement ZIP Slip protection
- [ ] Add dangerous code detection
- [ ] Add file size limits middleware
- [ ] Security audit

### Phase 7: Testing
- [ ] Unit tests for HeuristicParser
- [ ] Unit tests for SchemaInferenceEngine
- [ ] Integration tests for ImportService
- [ ] API endpoint tests
- [ ] E2E tests (upload → commit)
- [ ] Achieve 90% coverage target

### Phase 8: Performance
- [ ] Add connection pooling
- [ ] Implement caching strategy
- [ ] Add Prometheus metrics
- [ ] Load testing (100 concurrent imports)

### Phase 9: Operations
- [ ] Configure environment variables
- [ ] Set up health checks
- [ ] Implement temp file cleanup
- [ ] Add monitoring dashboards
- [ ] Write deployment guide

### Phase 10: Documentation
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Developer guide
- [ ] Deployment guide
- [ ] Troubleshooting guide

---

## Appendix B: Performance Benchmarks

**Target Metrics**:
- Upload & analyze (10MB ZIP): < 5 seconds
- Upload & analyze (100MB ZIP): < 30 seconds
- Commit import (100 templates): < 10 seconds
- API response time (status check): < 100ms
- Database query (get job): < 50ms
- Concurrent imports: 50+ simultaneous

---

## Appendix C: Migration from Current System

**Coexistence Strategy**:
1. Keep existing `TemplateType` enum for core types
2. Add `validate_hybrid_type()` function:
   ```python
   def validate_hybrid_type(template_type: str) -> bool:
       # Check enum first
       if template_type in TemplateType.__members__:
           return True
       # Check database for custom types
       return await template_def_repo.exists(template_type)
   ```
3. Gradually migrate core types to database
4. Deprecate enum in future version

---

## Conclusion

This technical architecture document provides the atomic-level specifications required for production-ready implementation of the SCORM Import functionality. All decisions are based on:

- ✅ **Industry best practices** (Clean Architecture, SOLID principles)
- ✅ **Security-first design** (no code execution, input validation)
- ✅ **Performance optimization** (async, caching, connection pooling)
- ✅ **Operational excellence** (monitoring, health checks, graceful degradation)

The development team is now equipped to begin implementation with confidence.

**Document Status**: ✅ APPROVED FOR IMPLEMENTATION  
**Next Review**: After Phase 2 completion

---

**Revision History**:
- v2.0 (Dec 2025): Initial production-ready specification
