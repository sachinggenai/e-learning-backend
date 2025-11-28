"""
Refactored SCORM Export Service (Architecture v2)
Uses modular builders and async I/O for SCORM package generation.
"""

import zipfile
import logging
from typing import Dict, Any
from io import BytesIO
import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.models.course import Course
from app.services.scorm.builders.manifest import ManifestBuilder
from app.services.scorm.builders.player import PlayerBuilder
from app.services.scorm.builders.wrapper import WrapperBuilder
from app.services.scorm.builders.course_data import CourseDataBuilder
from app.services.scorm.builders.styles import StylesBuilder
from app.services.scorm.utils.sanitization import (
    sanitize_text,
    sanitize_html,
    sanitize_mcq_options
)

logger = logging.getLogger(__name__)


def _ensure_dict(data: Any) -> Dict[str, Any]:
    """Convert Pydantic models to dictionaries safely."""
    if isinstance(data, dict):
        return data
    if hasattr(data, 'model_dump'):
        return data.model_dump()
    if hasattr(data, 'dict'):
        return data.dict()
    if hasattr(data, '__dict__'):
        return vars(data)
    raise ValueError(f"Cannot convert {type(data)} to dict")


class SCORMExportServiceV2:
    """Orchestrates SCORM package generation using modular builders."""

    def __init__(self):
        self.scorm_version = "1.2"
        self.max_package_size = 50 * 1024 * 1024  # 50MB
        self.max_templates = 100
        
        # Initialize builders
        self.manifest_builder = ManifestBuilder()
        self.player_builder = PlayerBuilder()
        self.wrapper_builder = WrapperBuilder()
        self.course_data_builder = CourseDataBuilder()
        self.styles_builder = StylesBuilder()

    async def generate_scorm_package(
        self,
        course: Course,
        include_assets: bool = True
    ) -> BytesIO:
        """Generate complete SCORM package as ZIP file.
        
        Args:
            course: Course data to export
            include_assets: Whether to include asset files
            
        Returns:
            BytesIO containing the ZIP package
        """
        logger.info(f"Generating SCORM package for course: {course.courseId}")
        
        # Pre-flight validation
        await self._validate_for_export(course)
        
        # Prepare context
        context = await self._prepare_context(course)
        
        # Build all components
        components = await self._build_components(context)
        
        # Package into ZIP (run in thread pool for blocking I/O)
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            zip_buffer = await loop.run_in_executor(
                executor,
                self._create_zip_package,
                components,
                include_assets,
                context
            )
        
        logger.info(
            f"SCORM package generated: {len(zip_buffer.getvalue())} bytes"
        )
        return zip_buffer

    async def _validate_for_export(self, course: Course):
        """Validate course data before export."""
        course_dict = _ensure_dict(course)
        
        # Check template count
        templates = course_dict.get('templates', [])
        if len(templates) > self.max_templates:
            raise ValueError(
                f"Too many templates: {len(templates)}. "
                f"Max allowed: {self.max_templates}"
            )
        
        # Validate templates have required fields
        for idx, template in enumerate(templates):
            if not isinstance(template, dict):
                template = _ensure_dict(template)
            
            if 'type' not in template:
                raise ValueError(
                    f"Template {idx} missing 'type' field"
                )
            if 'data' not in template:
                raise ValueError(
                    f"Template {idx} missing 'data' field"
                )

    async def _prepare_context(self, course: Course) -> Dict[str, Any]:
        """Prepare rendering context from course data."""
        course_dict = _ensure_dict(course)
        
        # Sanitize templates
        sanitized_templates = []
        for template in course_dict.get('templates', []):
            if not isinstance(template, dict):
                template = _ensure_dict(template)
            
            sanitized = await self._sanitize_template(template)
            sanitized_templates.append(sanitized)
        
        return {
            'course_id': course_dict.get('courseId'),
            'title': sanitize_text(course_dict.get('title', '')),
            'author': sanitize_text(course_dict.get('author', '')),
            'version': course_dict.get('version', '1.0.0'),
            'templates': sanitized_templates,
            'assets': course_dict.get('assets', []),
        }

    async def _sanitize_template(
        self, template: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Sanitize template data to prevent XSS."""
        sanitized = {
            'id': sanitize_text(template.get('id', '')),
            'type': template.get('type'),
            'title': sanitize_text(template.get('title', '')),
            'order': template.get('order', 0),
            'data': {}
        }
        
        data = template.get('data', {})
        if not isinstance(data, dict):
            data = _ensure_dict(data)
        
        # Sanitize based on template type
        template_type = template.get('type')
        
        if template_type == 'mcq':
            sanitized['data'] = {
                'content': sanitize_html(data.get('content', '')),
                'questions': [
                    {
                        'id': q.get('id'),
                        'question': sanitize_html(q.get('question', '')),
                        'options': sanitize_mcq_options(
                            q.get('options', [])
                        )
                    }
                    for q in data.get('questions', [])
                ]
            }
        else:
            # Default: sanitize all text fields
            sanitized['data'] = {
                'content': sanitize_html(data.get('content', '')),
                'subtitle': sanitize_text(data.get('subtitle', '')),
                'videoUrl': data.get('videoUrl'),
            }
        
        return sanitized

    async def _build_components(
        self, context: Dict[str, Any]
    ) -> Dict[str, str]:
        """Build all SCORM components in parallel."""
        # Build components concurrently
        manifest_task = self.manifest_builder.build(context)
        player_task = self.player_builder.build(context)
        wrapper_task = self.wrapper_builder.build(context)
        course_data_task = self.course_data_builder.build(context)
        styles_task = self.styles_builder.build(context)
        
        results = await asyncio.gather(
            manifest_task,
            player_task,
            wrapper_task,
            course_data_task,
            styles_task
        )
        
        return {
            'imsmanifest.xml': results[0],
            'index.html': results[1],
            'scorm_wrapper.js': results[2],
            'course_data.js': results[3],
            'styles.css': results[4],
        }

    def _create_zip_package(
        self,
        components: Dict[str, str],
        include_assets: bool,
        context: Dict[str, Any]
    ) -> BytesIO:
        """Create ZIP package from components (blocking I/O)."""
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(
            zip_buffer, 'w', zipfile.ZIP_DEFLATED
        ) as zf:
            # Add all components
            for filename, content in components.items():
                zf.writestr(filename, content)
            
            # Add assets if requested
            if include_assets:
                for asset in context.get('assets', []):
                    # TODO: Add asset file inclusion logic
                    pass
        
        zip_buffer.seek(0)
        return zip_buffer

    async def estimate_package_size(self, course: Course) -> int:
        """Estimate the size of the generated SCORM package."""
        context = await self._prepare_context(course)
        components = await self._build_components(context)
        
        total_size = sum(len(c.encode('utf-8')) for c in components.values())
        
        # Add estimated asset sizes
        for asset in context.get('assets', []):
            total_size += asset.get('size', 0)
        
        return total_size
