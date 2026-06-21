# US-PEND-021: Implement PDF/DOCX Async Text Extraction

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task |
| **Priority** | 🟡 HIGH |
| **Batch** | 6 — Feature Development |
| **Depends On** | None (workflow engine ready after Batch 1) |
| **Estimated Effort** | 3-4 days |
| **Target Files** | New: `app/services/ai/document_extractor.py`, modify: `app/services/ai/ingestion_service.py`, `requirements.txt` |

---

## User Story

**As a** course author uploading a PDF or DOCX file,  
**I want** the AI to extract text from my document and generate a course from it,  
**So that** I can turn my existing training materials into courses without manually copy-pasting.

---

## Current State

- `ingestion_service.py:21`: `ALLOWED_TYPES = {".pdf", ".docx", ".txt", ".md", ".zip"}`
- `ingestion_service.py:200-201`: MIME types defined for PDF and DOCX
- `_extract_text()` handles TXT/MD only — PDF/DOCX files accepted and stored but text is **never extracted**
- `test -f app/services/ai/document_extractor.py` → NOT FOUND

## Expected State

- `DocumentExtractor` class with `extract(file_path, mime_type) -> str`
- PDF extraction via `pdfplumber` or `PyPDF2`
- DOCX extraction via `python-docx`
- Integrated into `ingestion_service._extract_text()` flow
- Async extraction via workflow engine (US-BKND-AI-034) — submit extraction job, get text result

## Technical Details

```python
class DocumentExtractor:
    async def extract(self, file_path: str, mime_type: str) -> str:
        if mime_type == "application/pdf":
            return await self._extract_pdf(file_path)
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return await self._extract_docx(file_path)
```

### Dependencies to add to `requirements.txt`:
- `pdfplumber>=0.10` or `PyPDF2>=3.0`
- `python-docx>=1.0`

## Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Uploaded PDF file → text extracted → course generated |
| AC-2 | Uploaded DOCX file → text extracted → course generated |
| AC-3 | Extraction handles multi-page PDFs (up to 100 pages) |
| AC-4 | Extraction handles DOCX with images (extract text, skip images) |
| AC-5 | Corrupted files return clear error, not 500 |
| AC-6 | Extraction time logged in audit |

## Validation

```bash
python -c "from app.services.ai.document_extractor import DocumentExtractor; e = DocumentExtractor(); print(e.extract('sample.pdf', 'application/pdf'))"
python tests/run_ingestion_tests.py  # Extend with PDF/DOCX test cases
```
