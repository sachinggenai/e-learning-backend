"""
Import Service for SCORM package ingestion and analysis.

Orchestrates the entire import workflow: extraction, parsing,
inference, and staging.
"""

import uuid
import tempfile
import zipfile
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.heuristic_parser import HeuristicParser
from app.services.schema_inference import SchemaInferenceEngine
from app.services.asset_rewriter import AssetRewriter
from app.services.import_strategies.registry import StrategyRegistry
from app.services.import_strategies.json_strategy import JsonPayloadStrategy
from app.services.import_strategies.scorm12_strategy import Scorm12Strategy
from app.repositories.import_job_repository import ImportJobRepository
from app.repositories.template_type_repo import (
    TemplateTypeRepository,
    TemplateTypeConflictError,
)

logger = logging.getLogger(__name__)


class ImportServiceError(Exception):
    """Base exception for import service errors."""
    pass


class NoPayloadFoundError(ImportServiceError):
    """Raised when no JSON payload is found in the SCORM package."""
    pass


class ImportService:
    """Service for importing and analyzing SCORM packages."""

    def __init__(
        self,
        db_session: AsyncSession,
        max_file_size: int = 200 * 1024 * 1024,
        template_type_repo: Optional[TemplateTypeRepository] = None,
        strategy_registry: Optional[StrategyRegistry] = None,
    ):
        """
        Initialize import service.

        Args:
            db_session: SQLAlchemy async session
            max_file_size: Maximum upload size in bytes (default 200MB)
        """
        self.session = db_session
        self.max_file_size = max_file_size
        self.job_repo = ImportJobRepository(db_session)
        self.template_type_repo = template_type_repo or TemplateTypeRepository(
            db_session
        )
        self.parser = HeuristicParser()
        self.schema_engine = SchemaInferenceEngine()
        self.asset_rewriter = AssetRewriter()
        if strategy_registry is not None:
            self.strategy_registry = strategy_registry
        else:
            strategies = []
            if os.getenv("IMPORT_ENABLE_SCORM12", "true").lower() == "true":
                strategies.append(Scorm12Strategy())
            if os.getenv("IMPORT_ENABLE_JSON", "true").lower() == "true":
                strategies.append(JsonPayloadStrategy())
            if not strategies:
                raise ImportServiceError("No import strategies enabled")
            self.strategy_registry = StrategyRegistry(strategies)

    async def analyze_package(
        self,
        zip_data: bytes,
        course_id: Optional[str] = None
    ) -> str:
        """
        Analyze an uploaded SCORM package.

        This is the first step of the import workflow. It:
        1. Creates an import job
        2. Extracts the ZIP
        3. Finds JSON payloads
        4. Infers schemas
        5. Stages the data in the job

        Args:
            zip_data: Raw ZIP file bytes
            course_id: Optional target course ID

        Returns:
            Job ID for polling status

        Raises:
            ImportServiceError: If analysis fails
        """
        # Validate size
        if len(zip_data) > self.max_file_size:
            raise ImportServiceError(
                f"File too large: {len(zip_data)} > {self.max_file_size}"
            )

        # Create job
        job_id = str(uuid.uuid4())
        await self.job_repo.create(
            job_id=job_id,
            status="analyzing",
            course_id=course_id,
            source_file_path=f"temp://{job_id}",
            metadata={"created_at": datetime.utcnow().isoformat()},
        )

        try:
            # Extract ZIP
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = Path(tmpdir) / "package.zip"
                zip_path.write_bytes(zip_data)

                # Extract and read contents
                zip_contents = self._extract_zip(zip_path)
                entries = list(zip_contents.keys())

                # Strategy-driven analysis
                strategy_result = await self.strategy_registry.analyze(
                    zip_data, entries
                )
                logger.info(
                    "Import strategy selected: %s (files=%d)",
                    strategy_result.strategy,
                    len(entries),
                )
                course_data = strategy_result.course_data

                # Extract templates (tolerate missing key)
                templates = self._extract_templates(course_data)

                # Infer schemas for each template
                analyzed_templates = await self._analyze_templates(templates)

                # Build file map for asset rewriting
                file_map = self.asset_rewriter.build_file_map(zip_contents)
                ambiguous = self.asset_rewriter.detect_ambiguous_assets(
                    file_map
                )

                # Stage the data
                staged_data = {
                    "courseId": course_data.get("courseId", str(uuid.uuid4())),
                    "title": course_data.get("title", "Imported Course"),
                    "description": course_data.get("description", ""),
                    "templates": analyzed_templates,
                    "assets": {
                        "total": len(file_map),
                        "ambiguous": len(ambiguous),
                        "ambiguous_files": list(ambiguous.keys())
                    },
                        "warnings": list(strategy_result.warnings)
                        + await self._collect_warnings(analyzed_templates),
                }

                # Update job with staged data
                await self.job_repo.update_result(job_id, staged_data)
                await self.job_repo.update_status(
                    job_id, "analyzed", progress=1.0
                )

                logger.info(
                    "Analyzed package %s: %s templates",
                    job_id,
                    len(analyzed_templates),
                )
                return job_id

        except Exception as e:
            logger.error(f"Analysis failed for job {job_id}: {e}")
            await self.job_repo.update_status(
                job_id,
                "failed",
                error_message=str(e)
            )
            raise

    async def get_preview(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the preview of an import job.

        Returns the staged data with extracted templates and any warnings.

        Args:
            job_id: Import job ID

        Returns:
            Dictionary with preview data, or None if job not found
        """
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            return None

        return {
            "jobId": job.job_id,
            "status": job.status,
            "progress": job.progress,
            "courseData": job.result_data,
            "createdAt": (
                job.created_at.isoformat() if job.created_at else None
            ),
            "updatedAt": job.updated_at.isoformat() if job.updated_at else None
        }

    async def commit_import(self, job_id: str) -> Dict[str, Any]:
        """
        Commit an analyzed import job to the database.

        This finalizes the import and creates the course record.

        Args:
            job_id: Import job ID

        Returns:
            Dictionary with import results

        Raises:
            ImportServiceError: If job not found or commit fails
        """
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise ImportServiceError(f"Job not found: {job_id}")

        if job.status != "analyzed":
            raise ImportServiceError(
                f"Cannot commit job in status: {job.status}"
            )

        try:
            await self.job_repo.update_status(
                job_id, "committing", progress=0.9
            )

            # Harvest unique templates into the global library
            # (idempotent, capped)
            templates = (job.result_data or {}).get("templates", [])
            harvest_result = await self._harvest_templates(
                templates=templates,
                source_job_id=job_id,
                max_items=100,
            )
            logger.info(
                "Harvested templates from job %s: %s",
                job_id,
                harvest_result,
            )

            # In Phase 1, we just mark it as committed
            # Phase 2 will actually create the course record
            await self.job_repo.update_status(
                job_id, "committed", progress=1.0
            )

            return {
                "jobId": job_id,
                "status": "committed",
                "courseData": job.result_data,
                "harvest": harvest_result,
            }

        except Exception as e:
            logger.error(f"Commit failed for job {job_id}: {e}")
            await self.job_repo.update_status(
                job_id,
                "failed",
                error_message=f"Commit failed: {str(e)}"
            )
            raise

    def _extract_zip(self, zip_path: Path) -> Dict[str, bytes]:
        """Extract ZIP file contents."""
        contents = {}
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Security: check for Zip Slip vulnerability
                for name in zf.namelist():
                    if name.startswith("/") or ".." in name:
                        raise ImportServiceError(
                            f"Suspicious path in ZIP: {name}"
                        )

                for name in zf.namelist():
                    if not name.endswith("/"):
                        contents[name] = zf.read(name)
        except zipfile.BadZipFile:
            raise ImportServiceError("Invalid ZIP file")

        if not contents:
            raise ImportServiceError("ZIP file is empty")

        return contents

    async def _discover_payloads(
        self, zip_contents: Dict[str, bytes]
    ) -> List[Dict[str, Any]]:
        """Discover JSON payloads in extracted ZIP contents."""
        all_payloads = []

        # Look for JavaScript files first
        for file_path, content in zip_contents.items():
            if file_path.endswith((".js", ".json")):
                try:
                    text = content.decode("utf-8", errors="ignore")
                    payloads = self.parser.extract_json_from_js(text)
                    all_payloads.extend(payloads)
                    if payloads:
                        logger.debug(
                            "Found %s payloads in %s",
                            len(payloads),
                            file_path,
                        )
                except Exception as e:
                    logger.debug(f"Failed to parse {file_path}: {e}")
                    continue

        # If not found, try HTML files
        if not all_payloads:
            for file_path, content in zip_contents.items():
                if file_path.endswith(".html"):
                    try:
                        text = content.decode("utf-8", errors="ignore")
                        payloads = self.parser.extract_json_from_js(text)
                        all_payloads.extend(payloads)
                        if payloads:
                            logger.debug(
                                "Found %s payloads in %s",
                                len(payloads),
                                file_path,
                            )
                    except Exception as e:
                        logger.debug(f"Failed to parse {file_path}: {e}")
                        continue

        return all_payloads

    def _extract_templates(
        self, course_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract templates from course data."""
        # Try multiple keys that might contain templates
        for key in ("templates", "slides", "pages", "modules", "content"):
            if key in course_data and isinstance(course_data[key], list):
                return course_data[key]

        # If no templates key, assume the data itself is a list of templates
        if isinstance(course_data, list):
            return course_data

        return []

    async def _analyze_templates(
        self,
        templates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Analyze and infer schemas for templates."""
        analyzed = []

        for idx, template in enumerate(templates):
            if not isinstance(template, dict):
                analyzed.append({
                    "order": idx,
                    "error": "Template is not a dictionary",
                    "raw": str(template)
                })
                continue

            try:
                template_type = template.get("type", f"inferred_{idx}")
                template_data = template.get("data", {})

                # Infer schema
                schema = self.schema_engine.infer_schema_from_data(
                    template_data if isinstance(template_data, dict) else {}
                )

                analyzed.append({
                    "id": template.get("id", f"template_{idx}"),
                    "type": template_type,
                    "title": template.get("title", f"Template {idx}"),
                    "order": idx,
                    "schema": schema,
                    "schema_signature": self.schema_engine.
                    compute_schema_signature(schema),
                    "data": template_data
                })
            except Exception as e:
                logger.warning(f"Failed to analyze template {idx}: {e}")
                analyzed.append({
                    "order": idx,
                    "error": str(e),
                    "raw": template
                })

        return analyzed

    async def _collect_warnings(
        self, templates: List[Dict[str, Any]]
    ) -> List[str]:
        """Collect warnings from template analysis."""
        warnings = []
        error_count = sum(1 for t in templates if "error" in t)

        if error_count > 0:
            warnings.append(f"{error_count} template(s) failed to analyze")

        return warnings

    @staticmethod
    def _safe_text(value: Any, max_len: int) -> str:
        """Convert to plain string and trim; avoid embedding HTML in names."""
        text = ("" if value is None else str(value)).strip()
        return text[:max_len] if len(text) > max_len else text

    async def _harvest_templates(
        self,
        templates: List[Dict[str, Any]],
        source_job_id: str,
        max_items: int = 100,
    ) -> Dict[str, int]:
        """Promote analyzed templates into global template_types with de-dupe.

        Uses schema_signature as the deterministic fingerprint to avoid
        duplicates.
        Capped to `max_items` per job to prevent library pollution.
        """

        counters = {
            "harvested": 0,
            "duplicates": 0,
            "skipped_errors": 0,
            "skipped_missing_signature": 0,
            "capped": 0,
        }

        if not templates:
            return counters

        for tmpl in templates:
            if not isinstance(tmpl, dict):
                counters["skipped_errors"] += 1
                continue

            if "error" in tmpl:
                counters["skipped_errors"] += 1
                continue

            signature = tmpl.get("schema_signature")
            if not signature:
                counters["skipped_missing_signature"] += 1
                continue

            if counters["harvested"] >= max_items:
                counters["capped"] += 1
                continue

            template_id = f"imported_{signature}"
            name = self._safe_text(
                tmpl.get("title") or tmpl.get("type") or template_id, 200
            )
            description = self._safe_text(
                f"Imported from job {source_job_id}", 500
            )
            fields = tmpl.get("schema") or {}

            try:
                await self.template_type_repo.create(
                    template_id=template_id,
                    name=name,
                    description=description,
                    category="Imported",
                    thumbnail=None,
                    estimated_duration=None,
                    rating=0.0,
                    usage_count=0,
                    can_be_page=True,
                    fields=fields,
                    is_active=True,
                )
                counters["harvested"] += 1
            except TemplateTypeConflictError:
                counters["duplicates"] += 1
            except Exception as exc:  # pragma: no cover - log and continue
                logger.warning(
                    "Failed to harvest template %s from job %s: %s",
                    template_id,
                    source_job_id,
                    exc,
                )
                counters["skipped_errors"] += 1

        return counters
