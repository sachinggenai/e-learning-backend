# US-PEND-023: SCORM Export Validation for AI-Generated Content — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟡 HIGH |
| **Batch** | 6 — Feature Development |
| **Depends On** | None |
| **Estimated Effort** | 1-2 days |
| **Target Files** | `app/services/export_validator.py` (existing), new: `tests/run_ai_scorm_export_tests.py` |

---

## User Story

**As a** course author exporting an AI-generated course to SCORM,
**I want** validation of manifest completeness, resource packaging, and HTML escaping,
**So that** AI-generated courses pass LMS import on the first try.

---

## Current State (Code Verified 2026-06-21)

- ✅ **Comprehensive SCORM module exists:** `app/services/scorm_export.py` (4,260+ lines), `app/services/scorm/builders/` (manifest, player, wrapper, course_data, styles), `app/services/asset_packager.py`, `app/services/export_validator.py`
- ✅ **`export_validator.py` exists** — can be extended for AI-specific checks
- ✅ SCORM export targets **SCORM 1.2** specification
- ❌ No AI-content-specific validation exists (HTML escaping, generated content structure)
- ❌ No dedicated test suite: `test -f tests/run_ai_scorm_export_tests.py` → NOT FOUND
- ❌ Story spec `US-BKND-AI-038` is NOT written (INDEX.md: ❌ TODO)

---

## 🔧 Open-Source Tooling

| Tool | Version | Purpose | Why Selected |
|------|---------|---------|-------------|
| **lxml** | 5.x | XML/XSD validation | Already in requirements.txt; validates imsmanifest.xml against SCORM 1.2 XSD |
| **beautifulsoup4** | 4.x | HTML parsing/validation | Already in requirements.txt; checks AI-generated HTML for issues |
| **xmlschema** | 3.x | XSD schema validation | Pure Python; validates XML against SCORM XSD schemas; better error messages than lxml alone |

### Add to `requirements.txt`:
```
xmlschema>=3.0.0
```

---

## Enriched Implementation

### Step 1: Extend `app/services/export_validator.py`

Add AI-specific validation methods:

```python
# In app/services/export_validator.py

class AI_SCORMValidator:
    """Validates AI-generated content for SCORM 1.2 compliance."""

    # SCORM 1.2 XSD (bundled or fetched)
    SCORM_XSD_URL = "https://raw.githubusercontent.com/adlnet/SCORM-1.2/main/schemas/adlcp_rootv1p2.xsd"

    def __init__(self):
        import xmlschema
        self._schema = None  # Lazy-loaded XSD schema

    async def validate_manifest(self, manifest_xml: str) -> dict:
        """Validate imsmanifest.xml against SCORM 1.2 XSD schema."""
        import xmlschema
        if self._schema is None:
            self._schema = xmlschema.XMLSchema(self.SCORM_XSD_URL)

        errors = []
        try:
            self._schema.validate(manifest_xml)
        except xmlschema.XMLSchemaValidationError as e:
            errors.append({
                "code": "XSD_VALIDATION_FAILED",
                "message": str(e),
                "severity": "error",
            })

        return {"valid": len(errors) == 0, "errors": errors}

    async def validate_resources(self, manifest: dict, zip_contents: list) -> dict:
        """Verify all <resource> entries have corresponding files."""
        errors = []
        resources = manifest.get("resources", [])
        zip_filenames = {f["path"] for f in zip_contents}

        for resource in resources:
            for file_ref in resource.get("files", []):
                if file_ref not in zip_filenames:
                    errors.append({
                        "code": "MISSING_RESOURCE",
                        "message": f"Resource '{file_ref}' referenced in manifest but not found in package",
                        "severity": "error",
                        "resource_id": resource.get("identifier"),
                        "missing_file": file_ref,
                    })

        return {"valid": len(errors) == 0, "errors": errors}

    async def validate_ai_content(self, pages: list) -> dict:
        """Validate AI-generated page content for SCORM compatibility."""
        import re
        from bs4 import BeautifulSoup

        errors = []
        warnings = []

        for i, page in enumerate(pages):
            content = page.get("content", {})
            html = content.get("html", "")

            # Check 1: Unescaped special XML chars
            unescaped_xml = re.findall(r'&(?!amp;|lt;|gt;|quot;|apos;)', html)
            if unescaped_xml:
                errors.append({
                    "code": "UNESCAPED_XML",
                    "message": f"Page {i} ('{page.get('title')}') has unescaped XML characters",
                    "severity": "error",
                    "page_index": i,
                    "count": len(unescaped_xml),
                })

            # Check 2: Parse with BeautifulSoup for structural issues
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all():
                if tag.name not in ALLOWED_HTML_TAGS:
                    warnings.append({
                        "code": "UNKNOWN_HTML_TAG",
                        "message": f"Page {i}: tag '<{tag.name}>' may not work in SCORM player",
                        "severity": "warning",
                        "page_index": i,
                        "tag": tag.name,
                    })

            # Check 3: Empty content
            if not html.strip():
                warnings.append({
                    "code": "EMPTY_PAGE",
                    "message": f"Page {i} ('{page.get('title')}') has no content",
                    "severity": "warning",
                    "page_index": i,
                })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    async def validate_full(self, manifest_xml: str, manifest_dict: dict,
                            zip_contents: list, pages: list) -> dict:
        """Run full SCORM validation suite for AI-generated content."""
        results = {
            "manifest_xsd": await self.validate_manifest(manifest_xml),
            "resource_integrity": await self.validate_resources(manifest_dict, zip_contents),
            "ai_content": await self.validate_ai_content(pages),
        }
        overall_valid = all(r["valid"] for r in results.values())
        return {
            "valid": overall_valid,
            "checks": results,
            "total_errors": sum(len(r.get("errors", [])) for r in results.values()),
            "total_warnings": sum(len(r.get("warnings", [])) for r in results.values()),
        }


# SCORM 1.2 allowed HTML tags (conservative set for LMS compatibility)
ALLOWED_HTML_TAGS = {
    "a", "b", "br", "cite", "code", "dd", "dfn", "div", "dl", "dt",
    "em", "h1", "h2", "h3", "h4", "h5", "h6", "i", "img", "li",
    "ol", "p", "pre", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}
```

### Step 2: Integrate into workflow SCORM export step

In `app/services/workflow/steps/scorm_export.py`, add validation call in `create_zip_step`:

```python
from app.services.export_validator import AI_SCORMValidator

# After building manifest and ZIP:
validator = AI_SCORMValidator()
validation = await validator.validate_ai_content(
    pages=checkpoint.get("pages", [])
)
if validation["errors"]:
    logger.warning(
        "SCORM validation found %d errors, %d warnings",
        len(validation["errors"]), len(validation["warnings"]),
    )
    checkpoint["scorm_validation"] = validation
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Manifest validates against SCORM 1.2 XSD | Run `AI_SCORMValidator().validate_manifest()` with valid manifest |
| AC-2 | Missing resources flagged as errors | Test: manifest references file not in ZIP → error |
| AC-3 | Unescaped XML chars in AI content flagged | Test: page with `&copy;` → error |
| AC-4 | Empty pages flagged as warnings | Test: page with empty HTML → warning |
| AC-5 | Test suite covers valid/invalid/edge cases | `python tests/run_ai_scorm_export_tests.py` |

---

## Validation

```bash
# Install xmlschema
pip install xmlschema>=3.0.0

# Verify import
PYTHONPATH=. python -c "from app.services.export_validator import AI_SCORMValidator; print('OK')"

# Run tests
python tests/run_ai_scorm_export_tests.py
```
