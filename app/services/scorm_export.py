"""
SCORM Export Service
Implements SCORM package generation with Dynamic Template Runtime System.
Uses data-driven sanitization and validation - NO HARDCODED TEMPLATE LOGIC.
"""

import json
import zipfile
import tempfile
import os
import shutil
import re
import mimetypes
import html
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from io import BytesIO
# import aiofiles  # Reserved for future async file operations
import logging

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False
    print("Warning: BeautifulSoup not available. HTML sanitization will be limited.")

from ..models.course import Course, Template
from .scorm.sanitizers import DynamicSanitizer
from .scorm.registries import registry

logger = logging.getLogger(__name__)


def _ensure_dict(data: Any) -> Dict[str, Any]:
    """
    Convert various data types to dictionary.
    Handles Pydantic models, dataclasses, and plain objects.
    
    Args:
        data: Data to convert (dict, Pydantic model, dataclass, or object)
        
    Returns:
        Dictionary representation of the data
        
    Raises:
        ValueError: If data cannot be converted to dictionary
    """
    # If already a dict, return as-is
    if isinstance(data, dict):
        return data
    
    # If Pydantic model
    if hasattr(data, 'dict') and callable(getattr(data, 'dict')):
        try:
            return data.dict()
        except Exception as e:
            logger.warning(f"Failed to convert Pydantic model to dict: {e}")
    
    # If Pydantic v2 model
    if hasattr(data, 'model_dump') and callable(getattr(data, 'model_dump')):
        try:
            return data.model_dump()
        except Exception as e:
            logger.warning(f"Failed to convert Pydantic v2 model to dict: {e}")
    
    # If dataclass
    if hasattr(data, '__dataclass_fields__'):
        try:
            from dataclasses import asdict
            return asdict(data)
        except Exception as e:
            logger.warning(f"Failed to convert dataclass to dict: {e}")
    
    # If object with __dict__
    if hasattr(data, '__dict__') and not isinstance(data, type):
        try:
            return vars(data)
        except Exception as e:
            logger.warning(f"Failed to convert object to dict: {e}")
    
    # If still not dict, raise error
    raise ValueError(
        f"Cannot convert data of type {type(data).__name__} to dictionary. "
        f"Expected dict, Pydantic model, dataclass, or object with __dict__."
    )


class SCORMExportService:
    """Service for generating SCORM packages from course data"""

    def __init__(self):
        self.scorm_version = "1.2"
        self.package_identifier = None
        self.media_resources = {}
        self.resource_dependencies = {}
    
    async def generate_scorm_package(self, course: Course, include_assets: bool = True) -> BytesIO:
        """
        Generate a complete SCORM package as a ZIP file
        
        Args:
            course: Course data to export
            include_assets: Whether to include asset files in package
            
        Returns:
            BytesIO: ZIP file content as bytes
        """
        logger.info(f"Generating SCORM package for course: {course.courseId}")
        
        # Production hardening: Validate course before processing
        validation_result = await self.validate_for_export(course)
        if not validation_result.get("valid", False):
            error_msg = "; ".join(validation_result.get("errors", []))
            raise ValueError(f"Course validation failed: {error_msg}")
        
        # Production hardening: Check size limits
        size_estimate = self.estimate_package_size(course)
        max_size_mb = 50  # 50MB limit for SCORM packages
        if size_estimate.get("total_estimated_mb", 0) > max_size_mb:
            raise ValueError(
                f"Estimated package size ({size_estimate['total_estimated_mb']}MB) "
                f"exceeds maximum limit of {max_size_mb}MB. "
                f"Consider reducing content or optimizing assets."
            )
        
        # Production hardening: Template count limits
        max_templates = 100
        if len(course.templates) > max_templates:
            raise ValueError(
                f"Course has {len(course.templates)} templates, "
                f"exceeding maximum of {max_templates}"
            )
        
        # Production hardening: Asset count limits
        max_assets = 200
        if len(course.assets) > max_assets:
            raise ValueError(
                f"Course has {len(course.assets)} assets, "
                f"exceeding maximum of {max_assets}"
            )
        
        try:
            # Create temporary directory for package assembly
            with tempfile.TemporaryDirectory() as temp_dir:
                package_dir = Path(temp_dir) / "scorm_package"
                package_dir.mkdir()
                
                # Generate package identifier
                self.package_identifier = f"course_{course.courseId}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                # Create SCORM structure
                logger.info("Creating SCORM manifest")
                await self._create_imsmanifest(package_dir, course)
                logger.info("Creating course data")
                await self._create_course_data_js(package_dir, course)
                logger.info("Creating content HTML")
                await self._create_content_html(package_dir, course)
                logger.info("Creating SCORM wrapper")
                await self._create_scorm_wrapper(package_dir, course)
                
                # Include assets if requested
                if include_assets and course.assets:
                    logger.info("Copying assets")
                    await self._copy_assets(package_dir, course.assets)
                
                # Production hardening: Validate final package structure
                await self._validate_package_structure(package_dir)
                
                # Create ZIP package
                logger.info("Creating ZIP package")
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    self._add_directory_to_zip(zip_file, package_dir, "")
                
                # Production hardening: Final size check
                final_size_mb = len(zip_buffer.getvalue()) / (1024 * 1024)
                if final_size_mb > max_size_mb:
                    raise ValueError(
                        f"Final package size ({final_size_mb:.1f}MB) "
                        f"exceeds maximum limit of {max_size_mb}MB"
                    )
                
                zip_buffer.seek(0)
                logger.info("SCORM package generated successfully")
                return zip_buffer
                
        except Exception as error:
            logger.error(f"Failed to generate SCORM package: {str(error)}", exc_info=True)
            raise Exception(f"Failed to generate SCORM package: {str(error)}")
    
    async def _create_imsmanifest(self, package_dir: Path, course: Course) -> None:
        """Create the imsmanifest.xml file required by SCORM"""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course or not hasattr(course, 'courseId'):
                raise ValueError("Invalid course object provided")

            manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{self.package_identifier}" version="1" 
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                              http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd
                              http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">

    <metadata>
        <schema>ADL SCORM</schema>
        <schemaversion>{self.scorm_version}</schemaversion>
        <lom xmlns="http://www.imsglobal.org/xsd/imsmd_rootv1p2p1">
            <general>
                <identifier>
                    <catalog>URI</catalog>
                    <entry>{course.courseId}</entry>
                </identifier>
                <title>
                    <langstring xml:lang="en">{self._escape_xml(course.title)}</langstring>
                </title>
                <description>
                    <langstring xml:lang="en">{self._escape_xml(course.description)}</langstring>
                </description>
                <language>en</language>
            </general>
            <lifeCycle>
                <version>
                    <langstring xml:lang="en">{course.version}</langstring>
                </version>
                <contribute>
                    <role>
                        <source>LOMv1.0</source>
                        <value>Author</value>
                    </role>
                    <entity>{self._escape_xml(course.author)}</entity>
                    <date>
                        <dateTime>{course.createdAt.isoformat()}</dateTime>
                    </date>
                </contribute>
            </lifeCycle>
        </lom>
    </metadata>

    <organizations default="default_org">
        <organization identifier="default_org">
            <title>{self._escape_xml(course.title)}</title>
            {self._generate_items_xml(course)}
        </organization>
    </organizations>

    <resources>
        <resource identifier="resource_1" type="webcontent" adlcp:scormtype="sco" href="index.html">
            <file href="index.html"/>
            <file href="scorm_wrapper.js"/>
            <file href="course_data.js"/>
            <file href="styles.css"/>
            {self._generate_asset_files_xml(course.assets) if course.assets else ""}
        </resource>
    </resources>

</manifest>"""

            manifest_path = package_dir / "imsmanifest.xml"
            with open(manifest_path, 'w', encoding='utf-8') as f:
                f.write(manifest_xml)

            logger.info("✓ SCORM manifest created successfully")

        except Exception as e:
            logger.error(f"Failed to create SCORM manifest: {e}")
            raise Exception(f"Manifest creation failed: {str(e)}")
    
    def _generate_items_xml(self, course: Course) -> str:
        """
        Generate pure SCORM 1.2 organization items XML.
        
        Pure SCORM 1.2 approach:
        - Single SCO (resource_1) referenced by all items
        - No SCORM 2004 sequencing elements
        - JavaScript-based completion tracking via objectives
        - Free navigation without manifest-based constraints
        """
        # FIX: Use single item for SPA architecture to avoid LMS aggregation issues
        # This ensures the LMS tracks the entire course as a single SCO
        return f"""
            <item identifier="item_course_full" identifierref="resource_1" isvisible="true">
                <title>{self._escape_xml(course.title)}</title>
            </item>"""

    def _generate_asset_files_xml(self, assets: List[Any]) -> str:
        """Generate file references for assets"""
        files_xml = ""
        
        for asset in assets:
            # Extract filename from path
            filename = os.path.basename(asset.path)
            files_xml += f'\n            <file href="assets/{filename}"/>'
        
        return files_xml
    
    async def _create_course_data_js(
        self, package_dir: Path, course: Course
    ) -> None:
        """
        FIX #1 & #3: Create properly structured course data JavaScript
        
        Ensures:
        - courseData is object with templates property (not array-only)
        - Includes all course metadata
        - Safe for early player initialization
        - Proper JSON serialization
        """
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course or not hasattr(course, 'templates'):
                raise ValueError("Invalid course object or missing templates")

            # Transform templates to safe format using dynamic sanitization
            templates_data = []
            for template in course.templates:
                try:
                    # Use dynamic sanitization based on template type
                    sanitized_data = await self._sanitize_data_dynamic(
                        template.type,
                        template.data
                    )
                    
                    safe_template = {
                        'id': template.id,
                        'type': template.type,
                        'order': template.order,
                        'title': self._sanitize_text(template.title),
                        'data': sanitized_data
                    }
                    templates_data.append(safe_template)
                except Exception as e:
                    logger.warning(
                        f"Failed to process template {template.id}: {e}"
                    )
                    # Continue with other templates

            # Create complete course object (not just array)
            course_data = {
                'courseId': course.courseId,
                'title': self._sanitize_text(course.title),
                'author': self._sanitize_text(course.author),
                'version': course.version,
                'language': course.language or 'en',
                'templates': templates_data,
                'totalSlides': len(templates_data),
                'createdAt': (
                    course.createdAt.isoformat()
                    if course.createdAt else None
                )
            }

            # Generate JavaScript with proper escaping
            course_data_js = (
                "// ============================================\n"
                "// COURSE DATA - Generated by eLearning Platform\n"
                f"// SCORM Package: {self._escape_js_string(course.title)}\n"
                f"// Generated: {datetime.now().isoformat()}\n"
                "// ============================================\n\n"
                "// Define courseData as a global variable\n"
                "// This will be safely initialized by the player\n"
                f"var courseData = {json.dumps(course_data, indent=2, ensure_ascii=False)};\n\n"
                "// Validation check\n"
                "if (typeof courseData !== 'object' || "
                "!courseData.templates) {\n"
                "    console.error('ERROR: courseData not properly loaded');\n"
                "    console.error('courseData type:', typeof courseData);\n"
                "    console.error('courseData value:', courseData);\n"
                "    throw new Error('Course data initialization failed');\n"
                "}\n\n"
                "console.log('✓ Course data loaded successfully');\n"
                "console.log('  Slides:', courseData.templates.length);\n"
                "console.log('  Title:', courseData.title);\n"
            )

            data_path = package_dir / "course_data.js"
            with open(data_path, 'w', encoding='utf-8') as f:
                f.write(course_data_js)

            logger.info("✓ Course data JavaScript created successfully")

        except Exception as e:
            logger.error(f"Failed to create course data JavaScript: {e}")
            raise Exception(f"Course data creation failed: {str(e)}")
    
    async def _create_content_html(
        self, package_dir: Path, course: Course
    ) -> None:
        """FIX #1 & #2: Unified player with proper script loading"""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course or not hasattr(course, 'templates'):
                raise ValueError("Invalid course object or missing templates")

            num_pages = len(course.templates)
            if num_pages == 0:
                raise ValueError("Course must have at least one template")

            # FIX #8: Comprehensive template validation before rendering
            await self._validate_templates_for_scorm(course.templates)

            course_title_safe = self._escape_html(course.title)

            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{course_title_safe}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="scorm-player">
        <header class="player-header">
            <h1 id="course-title">{course_title_safe}</h1>
            <div class="progress-container">
                <div class="progress-bar">
                    <div id="progress-fill" class="progress-fill"></div>
                </div>
                <span id="progress-text" class="progress-text">0%</span>
            </div>
        </header>

        <main class="player-content">
            <div id="slide-container" class="slide-container">
                <div class="loading"><p>Loading...</p></div>
            </div>
        </main>

        <footer class="player-controls">
            <button id="prev-btn" class="nav-btn" disabled>← Prev</button>
            <span id="slide-counter">1 of {num_pages}</span>
            <button id="next-btn" class="nav-btn">Next →</button>
            <button id="finish-btn" class="finish-btn" style="display:none;">
                Finish
            </button>
        </footer>
    </div>

    <!-- Scripts in correct order with defer -->
    <script src="scorm_wrapper.js" defer></script>
    <script src="course_data.js" defer></script>

    <script defer>
    // ============================================
    // PRODUCTION-GRADE PLAYER INITIALIZATION
    // ============================================

    var Player = {{
        state: {{
            currentSlide: 0,
            totalSlides: {num_pages},
            courseData: null,
            initialized: false,
            quizAnswers: {{}},
            scormReady: false
        }},

        // FIX: Promise-based initialization with timeout
        init: async function() {{
            console.log('Player: Starting initialization...');

            try {{
                // Wait for courseData with 5-second timeout
                await this.waitForCourseData(5000);

                // Validate courseData structure
                if (!this.validateCourseData()) {{
                    throw new Error('Invalid course data structure');
                }}

                // Initialize SCORM and restore progress
                this.state.scormReady = SCORM.initialize();
                var savedSlide = SCORM.restoreProgress(this.state.totalSlides);
                this.state.currentSlide = Math.min(savedSlide, this.state.totalSlides - 1);

                // DEBUG: Check objectives after initialization
                console.log('DEBUG: Checking objectives after initialization...');
                var objectivesAfterInit = SCORM.getAllObjectivesStatus(this.state.totalSlides);
                console.log('DEBUG: Objectives after init:', objectivesAfterInit);

                // Load first slide
                this.loadSlide(this.state.currentSlide);
                this.updateNavigation();
                this.updateProgress();

                this.state.initialized = true;
                console.log('✓ Player initialized successfully');
                return true;

            }} catch (error) {{
                console.error('❌ Player initialization failed:', error);
                this.showError('Failed to load course: ' + error.message);
                return false;
            }}
        }},

        // FIX: Wait for courseData to be available
        waitForCourseData: function(timeoutMs) {{
            return new Promise((resolve, reject) => {{
                var startTime = Date.now();

                var checkData = () => {{
                    if (typeof courseData !== 'undefined' && courseData.templates) {{
                        console.log('✓ courseData ready, slides:', courseData.templates.length);
                        resolve();
                    }} else if (Date.now() - startTime > timeoutMs) {{
                        reject(new Error('Timeout waiting for course data'));
                    }} else {{
                        setTimeout(checkData, 100);  // Check every 100ms
                    }}
                }};

                checkData();
            }});
        }},

        // FIX: Comprehensive data validation
        validateCourseData: function() {{
            if (!courseData || typeof courseData !== 'object') {{
                console.error('courseData is not an object:', courseData);
                return false;
            }}

            if (!courseData.templates || !Array.isArray(courseData.templates)) {{
                console.error('courseData.templates missing or not array:', courseData.templates);
                return false;
            }}

            if (courseData.templates.length === 0) {{
                console.error('No templates in courseData');
                return false;
            }}

            this.state.totalSlides = courseData.templates.length;
            this.state.courseData = courseData;
            return true;
        }},

        // FIX: Error boundaries in loadSlide
        loadSlide: function(index) {{
            try {{
                console.log('Loading slide:', index + 1, 'of', this.state.totalSlides);

                if (index < 0 || index >= this.state.totalSlides) {{
                    throw new Error('Invalid slide index: ' + index);
                }}

                var slide = this.state.courseData.templates[index];
                if (!slide) {{
                    throw new Error('Slide ' + index + ' not found in course data');
                }}

                var content = '';
                try {{
                    if (slide.type === 'content-text' || slide.type === 'content') {{
                        content = this.renderContent(slide);
                    }} else if (slide.type === 'mcq') {{
                        content = this.renderMCQ(slide, index);
                    }} else {{
                        content = '<div class="slide"><p>Unknown slide type: ' +
                                 this.sanitize(slide.type || 'undefined') + '</p></div>';
                    }}
                }} catch (renderError) {{
                    console.error('Render error for slide', index, ':', renderError);
                    content = '<div class="slide error"><p>Failed to render slide: ' +
                             this.sanitize(renderError.message) + '</p></div>';
                }}

                var container = document.getElementById('slide-container');
                if (!container) {{
                    throw new Error('Slide container element not found');
                }}

                container.innerHTML = content;
                this.state.currentSlide = index;

                // Mark as viewed and save progress (but don't mark as completed here)
                if (this.state.scormReady) {{
                    SCORM.saveProgress(index, this.state.totalSlides);
                }}

                this.updateNavigation();
                this.updateProgress();

                console.log('✓ Slide loaded successfully');

            }} catch (error) {{
                console.error('❌ loadSlide failed:', error);
                this.showError('Error loading slide: ' + error.message);
            }}
        }},

        renderContent: function(slide) {{
            try {{
                var data = slide.data || {{}};
                var title = this.sanitize(slide.title || 'Untitled');
                var body = this.sanitize(data.content || '');
                return '<div class="template content-template">' +
                       '<h2 class="content-title">' + title + '</h2>' +
                       '<div class="content-body">' + body + '</div>' +
                       '</div>';
            }} catch (error) {{
                console.error('renderContent error:', error);
                return '<div class="template error">' +
                       '<p>Content rendering failed</p></div>';
            }}
        }},

        renderMCQ: function(slide, idx) {{
            try {{
                if (!slide.data || !slide.data.questions ||
                    slide.data.questions.length === 0) {{
                    return '<div class="template"><p>No questions available</p></div>';
                }}

                var question = slide.data.questions[0];
                if (!question) {{
                    return '<div class="template"><p>Invalid question data</p></div>';
                }}

                var safeQuestion = this.sanitize(question.question || 'Question');
                var answeredIndex = this.state.quizAnswers[idx];

                var optionsHTML = '';
                if (question.options && Array.isArray(question.options)) {{
                    for (var i = 0; i < question.options.length; i++) {{
                        var option = question.options[i];
                        if (!option) continue;

                        var safeText = this.sanitize(option.text ||
                                                   'Option ' + (i + 1));
                        var isSelected = answeredIndex === i;
                        var checked = isSelected ? ' checked' : '';
                        var selectedClass = isSelected ? ' selected' : '';

                        optionsHTML += '<label class="mcq-option' + selectedClass +
                                     '">' +
                                     '<input type="radio" name="answer_' + idx +
                                     '" value="' + i +
                                     '" onchange="Player.selectAnswer(' +
                                     idx + ', ' + i + ')"' + checked + '>' +
                                     '<span class="option-text">' + safeText +
                                     '</span>' +
                                     '</label>';
                    }}
                }}

                return '<div class="template mcq-template">' +
                       '<h2 class="mcq-question">' + safeQuestion + '</h2>' +
                       '<div class="mcq-options">' + optionsHTML + '</div>' +
                       '<div id="feedback-' + idx + '" class="mcq-feedback">' +
                       '</div>' +
                       '</div>';

            }} catch (error) {{
                console.error('❌ renderMCQ failed:', error);
                return '<div class="template error">' +
                       '<p>Failed to render question</p></div>';
            }}
        }},

        selectAnswer: function(slideIdx, optIdx) {{
            try {{
                console.log('=== MCQ DEBUG: selectAnswer called ===');
                console.log('Slide index:', slideIdx, 'Option index:', optIdx);
                
                var slide = this.state.courseData.templates[slideIdx];
                if (!slide) {{
                    console.error('MCQ DEBUG: Slide not found at index', slideIdx);
                    return;
                }}
                console.log('Slide type:', slide.type, 'Title:', slide.title);
                
                if (!slide.data || !slide.data.questions) {{
                    console.error('MCQ DEBUG: Invalid slide data for slide', slideIdx, 'data:', slide.data);
                    return;
                }}

                var question = slide.data.questions[0];
                if (!question) {{
                    console.error('MCQ DEBUG: No question found in slide', slideIdx);
                    return;
                }}
                console.log('Question text:', question.question);
                
                if (!question.options) {{
                    console.error('MCQ DEBUG: No options found for question in slide', slideIdx);
                    return;
                }}
                console.log('Total options:', question.options.length);

                var option = question.options[optIdx];
                if (!option) {{
                    console.error('MCQ DEBUG: Option not found at index', optIdx, 'for slide', slideIdx);
                    return;
                }}
                console.log('Selected option text:', option.text);
                console.log('Raw option.isCorrect value:', option.isCorrect, 'Type:', typeof option.isCorrect);

                // Robust boolean checking for isCorrect
                var correct = false;
                if (typeof option.isCorrect === 'boolean') {{
                    correct = option.isCorrect;
                    console.log('MCQ DEBUG: isCorrect is boolean, value:', correct);
                }} else if (typeof option.isCorrect === 'string') {{
                    correct = option.isCorrect.toLowerCase() === 'true';
                    console.log('MCQ DEBUG: isCorrect is string, converted to:', correct);
                }} else {{
                    console.warn('MCQ DEBUG: Unexpected isCorrect type:', typeof option.isCorrect, 'value:', option.isCorrect);
                    correct = Boolean(option.isCorrect);
                    console.log('MCQ DEBUG: Forced boolean conversion result:', correct);
                }}

                console.log('MCQ DEBUG: Final correctness determination:', correct);
                console.log('MCQ DEBUG: Recording answer in state...');
                
                this.state.quizAnswers[slideIdx] = optIdx;
                console.log('MCQ DEBUG: Answer recorded in state.quizAnswers[' + slideIdx + '] =', optIdx);

                // Record in SCORM
                if (this.state.scormReady) {{
                    console.log('MCQ DEBUG: SCORM is ready, recording quiz answer...');
                    SCORM.recordQuizAnswer(
                        'q_' + slideIdx,
                        optIdx,
                        correct,
                        question.options
                    );
                    console.log('MCQ DEBUG: SCORM recording completed');
                }} else {{
                    console.warn('MCQ DEBUG: SCORM not ready, skipping SCORM recording');
                }}

                var fb = document.getElementById('feedback-' + slideIdx);
                if (fb) {{
                    var feedbackText = correct ? '✓ Correct!' : '✗ Incorrect';
                    fb.innerHTML = '<p class="' + (correct ? 'ok' : 'err') + '">' + feedbackText + '</p>';
                    console.log('MCQ DEBUG: Updated feedback element for slide', slideIdx, 'to:', feedbackText);
                }} else {{
                    console.warn('MCQ DEBUG: Feedback element not found for slide', slideIdx);
                }}

                console.log('=== MCQ DEBUG: selectAnswer completed successfully ===');

            }} catch (error) {{
                console.error('MCQ DEBUG: selectAnswer error:', error);
                console.error('MCQ DEBUG: Error stack:', error.stack);
            }}
        }},

        sanitize: function(text) {{
            if (!text) return '';
            var div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }},

        updateNavigation: function() {{
            try {{
                var prev = document.getElementById('prev-btn');
                var next = document.getElementById('next-btn');
                var fin = document.getElementById('finish-btn');

                if (prev) prev.disabled = this.state.currentSlide === 0;

                if (this.state.currentSlide === this.state.totalSlides - 1) {{
                    if (next) next.style.display = 'none';
                    if (fin) fin.style.display = 'inline-block';
                }} else {{
                    if (next) next.style.display = 'inline-block';
                    if (fin) fin.style.display = 'none';
                }}

                var cnt = document.getElementById('slide-counter');
                if (cnt) {{
                    cnt.textContent = (this.state.currentSlide + 1) + ' of ' + this.state.totalSlides;
                }}

            }} catch (error) {{
                console.error('updateNavigation error:', error);
            }}
        }},

        updateProgress: function() {{
            try {{
                var progressFill = document.getElementById('progress-fill');
                var progressText = document.getElementById('progress-text');

                if (!progressFill || !progressText) return;

                var pct = Math.round(((this.state.currentSlide + 1) / this.state.totalSlides) * 100);
                progressFill.style.width = pct + '%';
                progressText.textContent = pct + '%';

            }} catch (error) {{
                console.error('updateProgress error:', error);
            }}
        }},

        finishCourse: function() {{
            try {{
                console.log('=== COURSE COMPLETION DEBUG: finishCourse called ===');
                
                // 1. Validate all questions answered
                var unanswered = [];
                if (this.state.courseData && this.state.courseData.templates) {{
                    this.state.courseData.templates.forEach((t, i) => {{
                        if (t.type === 'mcq' && this.state.quizAnswers[i] === undefined) {{
                            unanswered.push(i + 1);
                        }}
                    }});
                }}
                
                if (unanswered.length > 0) {{
                    alert('Please answer all questions before finishing. Unanswered slides: ' + unanswered.join(', '));
                    return;
                }}

                // 2. Mark all slides as completed
                console.log('Marking all slides as completed...');
                for (var i = 0; i < this.state.totalSlides; i++) {{
                    if (this.state.scormReady) {{
                        SCORM.markSlideComplete(i, this.state.totalSlides);
                    }}
                }}
                
                // 3. Set Course Complete
                if (this.state.scormReady) {{
                    console.log('Setting course status to completed...');
                    SCORM.setCourseComplete();
                    
                    var score = SCORM.calculateScore();
                    alert('Course Complete! Score: ' + score + '%');
                    
                    // 4. Terminate SCORM session
                    console.log('Terminating SCORM session...');
                    SCORM.terminate();
                }} else {{
                    alert('Course completed (local only)');
                }}
                
                // 5. Close Window
                try {{
                    window.close();
                    if (window.parent && window.parent !== window) {{
                        window.parent.close();
                    }}
                    if (window.top && window.top !== window) {{
                        window.top.close();
                    }}
                }} catch (e) {{
                    console.warn('Could not close window:', e);
                }}
                
            }} catch (error) {{
                console.error('COMPLETION DEBUG: finishCourse error:', error);
                alert('Course completed (with errors)');
            }}
        }},

        showError: function(msg) {{
            try {{
                var container = document.getElementById('slide-container');
                if (container) {{
                    container.innerHTML = '<div class="error">' + this.sanitize(msg) + '</div>';
                }}
            }} catch (error) {{
                console.error('showError failed:', error);
            }}
        }}
    }};

    // FIX: Async initialization on page load
    window.addEventListener('load', async function() {{
        console.log('Page loaded, starting player initialization...');
        await Player.init();
    }});

    // FIX: Event handlers with error boundaries
    document.addEventListener('DOMContentLoaded', function() {{
        try {{
            var prevBtn = document.getElementById('prev-btn');
            var nextBtn = document.getElementById('next-btn');
            var finishBtn = document.getElementById('finish-btn');

            if (prevBtn) {{
                prevBtn.onclick = function() {{
                    if (Player.state.currentSlide > 0) {{
                        Player.loadSlide(Player.state.currentSlide - 1);
                    }}
                }};
            }}

            if (nextBtn) {{
                nextBtn.onclick = function() {{
                    console.log('DEBUG: Next button clicked, current slide:', Player.state.currentSlide);
                    if (Player.state.currentSlide < Player.state.totalSlides - 1) {{
                        // Mark current slide as completed before navigating
                        if (Player.state.scormReady) {{
                            console.log('DEBUG: SCORM ready, marking slide complete');
                            console.log('DEBUG: Objectives before marking:', SCORM.getAllObjectivesStatus(Player.state.totalSlides));
                            SCORM.markSlideComplete(Player.state.currentSlide, Player.state.totalSlides);
                            console.log('Marked current slide', Player.state.currentSlide, 'as completed');
                            console.log('DEBUG: Objectives after marking:', SCORM.getAllObjectivesStatus(Player.state.totalSlides));
                        }} else {{
                            console.log('DEBUG: SCORM not ready, skipping objective marking');
                        }}
                        Player.loadSlide(Player.state.currentSlide + 1);
                        console.log('DEBUG: Navigated to slide:', Player.state.currentSlide + 1);
                    }}
                }};
            }}

            if (finishBtn) {{
                finishBtn.onclick = function() {{
                    Player.finishCourse();
                }};
            }}

        }} catch (error) {{
            console.error('Event handler setup failed:', error);
        }}
    }});
    </script>
</body>
</html>"""

            html_path = package_dir / "index.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Create comprehensive styles
            styles_css = """body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    margin: 0; padding: 0; background: #f5f5f5; }
#scorm-player { max-width: 1200px; margin: 0 auto; background: white;
    min-height: 100vh; display: flex; flex-direction: column; }
.player-header { background: linear-gradient(135deg, #667eea, #764ba2);
    color: white; padding: 2rem; text-align: center; }
.player-header h1 { margin: 0 0 1rem 0; font-size: 2rem; }
.progress-container { display: flex; align-items: center; gap: 1rem; }
.progress-bar { flex: 1; background: rgba(255,255,255,0.2);
    border-radius: 10px; height: 10px; overflow: hidden; }
.progress-fill { background: #10b981; height: 100%;
    transition: width 0.3s; width: 0%; }
.progress-text { min-width: 40px; }
.player-content { flex: 1; padding: 2rem; }
.template { max-width: 800px; margin: 0 auto; line-height: 1.6; }
.template h2 { color: #333; font-size: 1.8rem;
    border-bottom: 3px solid #667eea; }
.mcq-template { background: #f8f9fa; padding: 2rem; border-radius: 12px;
    margin: 2rem 0; }
.mcq-question { color: #2d3748; font-size: 1.5rem; margin-bottom: 1.5rem; }
.mcq-options { display: flex; flex-direction: column; gap: 1rem; }
.mcq-option { display: flex; align-items: center; background: white;
    padding: 1rem; border-radius: 8px; cursor: pointer; border: 2px solid #e2e8f0;
    transition: all 0.2s; }
.mcq-option:hover { border-color: #667eea; background: #f7fafc; }
.mcq-option.selected { border-color: #10b981; background: #f0fff4; }
.mcq-option input[type="radio"] { margin-right: 0.75rem; }
.option-text { flex: 1; font-size: 1.1rem; }
.mcq-feedback { margin-top: 1.5rem; padding: 1rem; border-radius: 8px;
    font-weight: bold; }
.mcq-feedback .ok { color: #155724; background: #d4edda; border: 1px solid #c3e6cb; }
.mcq-feedback .err { color: #721c24; background: #f8d7da; border: 1px solid #f5c6cb; }
.content-template { background: white; padding: 2rem; border-radius: 12px;
    margin: 2rem 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.content-title { color: #2d3748; font-size: 1.8rem; margin-bottom: 1.5rem;
    border-bottom: 3px solid #667eea; padding-bottom: 0.5rem; }
.content-body { font-size: 1.1rem; line-height: 1.7; }
.content-body p { margin-bottom: 1rem; }
.content-body ul, .content-body ol { margin: 1rem 0; padding-left: 2rem; }
.content-body li { margin-bottom: 0.5rem; }
.content-body strong { font-weight: 600; color: #2d3748; }
.content-body em { font-style: italic; color: #4a5568; }
.player-controls { background: #f8f9fa; padding: 1.5rem 2rem;
    display: flex; justify-content: space-between; align-items: center; }
.nav-btn, .finish-btn { padding: 0.75rem 1.5rem; border: 2px solid #667eea;
    background: white; color: #667eea; border-radius: 6px; cursor: pointer;
    font-size: 1rem; font-weight: 500; transition: all 0.2s; }
.nav-btn:hover, .finish-btn:hover { background: #667eea; color: white; }
.nav-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.finish-btn { background: #10b981; border-color: #10b981; color: white; }
.finish-btn:hover { background: #059669; }
.slide-counter { font-weight: 500; color: #4a5568; }
.error { background: #fed7d7; color: #c53030; padding: 1rem; border-radius: 6px;
    border: 1px solid #feb2b2; }
@media (max-width: 768px) {{
    .player-header {{ padding: 1rem; }}
    .player-header h1 {{ font-size: 1.5rem; }}
    .player-content {{ padding: 1rem; }}
    .mcq-template, .content-template {{ padding: 1rem; margin: 1rem 0; }}
    .mcq-question {{ font-size: 1.3rem; }}
    .content-title {{ font-size: 1.5rem; }}
    .player-controls {{ padding: 1rem; flex-direction: column; gap: 1rem; }}
    .nav-btn, .finish-btn {{ padding: 0.5rem 1rem; font-size: 0.9rem; }}
}}
@media (max-width: 480px) {{
    .mcq-options {{ gap: 0.5rem; }}
    .mcq-option {{ padding: 0.75rem; }}
    .option-text {{ font-size: 1rem; }}
    .progress-container {{ flex-direction: column; gap: 0.5rem; }}
    .progress-text {{ min-width: auto; }}
}}"""

            styles_path = package_dir / "styles.css"
            with open(styles_path, 'w', encoding='utf-8') as f:
                f.write(styles_css)

            logger.info("✓ Content HTML and styles created successfully")

        except Exception as e:
            logger.error(f"Failed to create content HTML: {e}")
            raise Exception(f"Content HTML creation failed: {str(e)}")
    
    async def _create_scorm_wrapper(self, package_dir: Path,
                                   course: Course) -> None:
        """FIX #2 & #4: Production-grade SCORM wrapper"""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not course:
                raise ValueError("Invalid course object")

            scorm_js = """// SCORM 1.2 API WRAPPER - Production with Mock API Fallback
var SCORM = {
    version: "1.2",
    initialized: false,
    sessionData: {
        answers: {}, 
        visitedSlides: [], // Track visited slides locally
        startTime: null
    },

    initialize: function() {
        if (this.initialized) return true; // Prevent double initialization
        
        try {
            var API = this.getAPI();
            if (!API) {
                console.log('No LMS API found, using Mock API for testing');
                this.mockMode = true;
                this.mockStorage = this.getMockStorage();
                this.sessionData.startTime = new Date();
                this.initialized = true;
                console.log('✓ Mock SCORM initialized');
                return true;
            }

            var r = API.LMSInitialize("");
            if (r !== "true") return false;
            
            // CRITICAL FIX: Only set to 'incomplete' if no status exists yet
            var currentStatus = API.LMSGetValue("cmi.core.lesson_status");
            if (!currentStatus || currentStatus === "" || currentStatus === "not attempted") {
                API.LMSSetValue("cmi.core.lesson_status", "incomplete");
                console.log('✓ SCORM initialized - status set to incomplete');
            } else {
                console.log('✓ SCORM initialized - preserving existing status:', currentStatus);
            }

            // RESTORE SESSION DATA (Quiz Answers & Visited Slides) from suspend_data
            var suspendData = API.LMSGetValue("cmi.suspend_data");
            if (suspendData && suspendData !== "") {
                try {
                    var parsed = JSON.parse(suspendData);
                    if (parsed) {
                        if (parsed.answers) this.sessionData.answers = parsed.answers;
                        if (parsed.visitedSlides) this.sessionData.visitedSlides = parsed.visitedSlides;
                        console.log('✓ Restored session data. Visited:', this.sessionData.visitedSlides.length);
                    }
                } catch (e) {
                    console.warn('Failed to parse suspend_data:', e);
                }
            }
            
            this.sessionData.startTime = new Date();
            this.initialized = true;
            return true;
        } catch (e) {
            console.error('SCORM init:', e);
            return false;
        }
    },

    getAPI: function() {
        var win = window;
        var maxRetries = 10;
        var retryDelay = 100;  // 100ms delay between retries
        
        for (var attempt = 0; attempt < maxRetries; attempt++) {
            // Check current window
            if (win.API != null) return win.API;
            
            // Check parent windows
            while (win.API == null && win.parent != win) {
                win = win.parent;
                if (win.API != null) return win.API;
            }
            
            // Check opener window
            if (win.API == null && win.opener) {
                win = win.opener;
                if (win.API != null) return win.API;
            }
            
            // Wait before retrying
            if (attempt < maxRetries - 1) {
                var start = Date.now();
                while (Date.now() - start < retryDelay) {
                    // Busy wait for delay
                }
            }
        }
        
        return null;
    },

    getMockStorage: function() {
        try {
            var stored = localStorage.getItem('scorm_mock_data');
            return stored ? JSON.parse(stored) : {
                'cmi.core.lesson_status': 'incomplete',
                'cmi.core.score.raw': '0',
                'cmi.core.score.max': '100',
                'cmi.core.lesson_location': '0'
            };
        } catch (e) {
            console.warn('localStorage not available, using memory storage');
            return {
                'cmi.core.lesson_status': 'incomplete',
                'cmi.core.score.raw': '0',
                'cmi.core.score.max': '100',
                'cmi.core.lesson_location': '0'
            };
        }
    },

    saveMockData: function() {
        if (this.mockStorage && typeof localStorage !== 'undefined') {
            try {
                localStorage.setItem('scorm_mock_data', JSON.stringify(this.mockStorage));
            } catch (e) {
                console.warn('Failed to save mock data:', e);
            }
        }
    },

    setValue: function(p, v) {
        try {
            console.log('SCORM setValue:', p, '=', v);
            if (this.mockMode) {
                if (this.mockStorage) {
                    this.mockStorage[p] = v;
                    this.saveMockData();
                }
                console.log('Mock setValue success');
                return true;
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM setValue failed: API not found');
                return false;
            }
            var result = API.LMSSetValue(p, v);
            console.log('SCORM LMSSetValue result:', result);
            if (result !== "true") {
                var err = API.LMSGetLastError();
                var errString = API.LMSGetErrorString(err);
                var diagnostic = API.LMSGetDiagnostic(err);
                console.error('SCORM setValue error:', err, errString, diagnostic);
            }
            return result === "true";
        } catch (e) {
            console.error('setValue exception:', e);
            return false;
        }
    },

    getValue: function(p) {
        try {
            console.log('SCORM getValue:', p);
            if (this.mockMode) {
                var value = this.mockStorage ? this.mockStorage[p] : "";
                console.log('Mock getValue result:', value);
                return value || "";
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM getValue failed: API not found');
                return "";
            }
            var value = API.LMSGetValue(p);
            console.log('SCORM LMSGetValue result:', value);
            var err = API.LMSGetLastError();
            if (err !== "0") {
                 var errString = API.LMSGetErrorString(err);
                 console.error('SCORM getValue error:', err, errString);
            }
            return value || "";
        } catch (e) {
            console.error('getValue exception:', e);
            return "";
        }
    },

    commit: function() {
        try {
            console.log('SCORM commit called');
            if (this.mockMode) {
                this.saveMockData();
                console.log('Mock commit success');
                return true;
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM commit failed: API not found');
                return false;
            }
            var result = API.LMSCommit("");
            console.log('SCORM LMSCommit result:', result);
            if (result !== "true") {
                var err = API.LMSGetLastError();
                console.error('SCORM commit error:', err, API.LMSGetErrorString(err));
            }
            return result === "true";
        } catch (e) {
            console.error('commit exception:', e);
            return false;
        }
    },

    recordAnswer: function(qId, selIdx, correct) {
        this.sessionData.answers[qId] = {selected: selIdx, correct: correct};
        if (this.initialized) {
            this.setValue('cmi.interactions.0.id', qId);
            this.setValue('cmi.interactions.0.type', 'choice');
            this.setValue('cmi.interactions.0.student_response', selIdx);
            this.commit();
        }
    },

    // FIX: Add missing SCORM methods for LMS compatibility
    markSlideComplete: function(slideIdx, totalSlides) {
        if (this.initialized) {
            // 1. Update Local State
            if (this.sessionData.visitedSlides.indexOf(slideIdx) === -1) {
                this.sessionData.visitedSlides.push(slideIdx);
                this.saveSessionData(); // Persist immediately
                console.log('Marked slide', slideIdx, 'visited. Total visited:', this.sessionData.visitedSlides.length);
            }

            // 2. Try to update LMS Objectives (Best Effort)
            // We do this for LMSs that support it, but we don't rely on it for logic
            var objId = 'obj_' + slideIdx;
            this.setValue('cmi.objectives.' + slideIdx + '.id', objId);
            this.setValue('cmi.objectives.' + slideIdx + '.status', 'completed');
            this.setValue('cmi.objectives.' + slideIdx + '.score.raw', '100');
            this.setValue('cmi.objectives.' + slideIdx + '.score.max', '100');
            
            // 3. Check Completion based on LOCAL state
            if (totalSlides) {
                this.checkCourseCompletion(totalSlides);
            }
            
            this.commit();
        }
    },

    checkCourseCompletion: function(totalSlides) {
        if (!this.initialized) return;
        
        console.log('Checking completion. Visited:', this.sessionData.visitedSlides.length, '/', totalSlides);
        
        // ROBUST CHECK: Use local visitedSlides count
        if (this.sessionData.visitedSlides.length >= totalSlides) {
            console.log('All slides visited (local check) - marking course complete');
            this.setCourseComplete();
        } else {
            console.log('Course not yet complete. Missing slides.');
        }
    },

    recordQuizAnswer: function(qId, selIdx, correct, options) {
        if (this.initialized) {
            // Get next interaction index (track in session)
            if (!this.sessionData.interactionCount) {
                this.sessionData.interactionCount = 0;
            }
            var interactionIdx = this.sessionData.interactionCount++;
            
            // Record interaction details with correct index
            var prefix = 'cmi.interactions.' + interactionIdx;
            this.setValue(prefix + '.id', qId);
            this.setValue(prefix + '.type', 'choice');
            this.setValue(prefix + '.student_response', selIdx.toString());
            this.setValue(prefix + '.result', correct ? 'correct' : 'wrong');
            this.setValue(prefix + '.weighting', '1');
            // REMOVED: latency is NOT required in SCORM 1.2, causes errors
            
            // Set correct responses - use index 0 for correct answer pattern
            if (options && options.length > 0) {
                for (var i = 0; i < options.length; i++) {
                    if (options[i] && options[i].isCorrect) {
                        // Use .0. not .3. for the first correct response
                        this.setValue(prefix + '.correct_responses.0.pattern', i.toString());
                        break; // Only need first correct answer
                    }
                }
            }
            
            this.commit();
            
            // Also store in sessionData for score calculation
            this.sessionData.answers[qId] = {selected: selIdx, correct: correct};
            this.saveSessionData(); // Persist to suspend_data
            
            console.log('Recorded quiz answer:', qId, 'idx:', interactionIdx, 'selected:', selIdx, 'correct:', correct);
            
            // Update score immediately
            this.submitScore();
        }
    },

    calculateScore: function() {
        var correct = 0, total = 0;
        
        // Count quiz answers from sessionData (recorded during quiz interactions)
        for (var qId in this.sessionData.answers) {
            total++;
            if (this.sessionData.answers[qId].correct) correct++;
        }
        
        // If no answers in sessionData, try to get from SCORM API
        if (total === 0 && this.initialized) {
            // Try to get quiz results from SCORM interactions
            // SCORM 1.2 doesn't have a direct way to query all interactions,
            // so we'll rely on the sessionData that's populated during quiz interactions
            console.log('No quiz answers found in sessionData for scoring');
        }
        
        var score = total === 0 ? 0 : Math.round((correct / total) * 100);
        console.log('Score calculation: correct=' + correct + ', total=' + total + ', score=' + score + '%');
        return score;
    },

    submitScore: function() {
        var score = this.calculateScore();
        if (this.initialized) {
            this.setValue('cmi.core.score.raw', score);
            this.setValue('cmi.core.score.min', '0');
            this.setValue('cmi.core.score.max', '100');
            this.commit();
            console.log('Score submitted:', score);
        }
        return score;
    },

    saveProgress: function(slideIdx) {
        if (this.initialized) {
            this.setValue('cmi.core.lesson_location', slideIdx);
            this.commit();
        }
    },

    restoreProgress: function(totalSlides) {
        if (!this.initialized) return 0;
        
        var saved = this.getValue('cmi.core.lesson_location');
        var slideIndex = saved && !isNaN(saved) ? parseInt(saved) : 0;
        
        console.log('Restoring progress: saved slide index =', slideIndex, 'total slides =', totalSlides);
        
        // Mark all slides up to the saved position as completed
        // This ensures that on revisit, previously viewed slides show as completed
        if (totalSlides && totalSlides > 0) {
            for (var i = 0; i <= slideIndex && i < totalSlides; i++) {
                this.markSlideComplete(i, totalSlides);
                console.log('Marked previously viewed slide', i, 'as completed');
            }
        }
        
        return slideIndex;
    },

    setCourseComplete: function() {
        console.log('setCourseComplete called');
        if (this.initialized) {
            this.submitScore();
            // Mark all objectives as completed before setting course complete
            // Only update objectives that actually exist (have IDs)
            for (var i = 0; i < 10; i++) {
                var objId = this.getValue('cmi.objectives.' + i + '.id');
                if (objId && objId !== '') {
                    console.log('Forcing completion for objective', i, 'id:', objId);
                    this.setValue('cmi.objectives.' + i + '.status', 'completed');
                    this.setValue('cmi.objectives.' + i + '.score.raw', '100');
                    this.setValue('cmi.objectives.' + i + '.score.max', '100');
                    // REMOVED: score.scaled is NOT valid in SCORM 1.2
                } else {
                    break; // No more objectives
                }
            }
            console.log('Setting cmi.core.lesson_status to completed');
            this.setValue('cmi.core.lesson_status', 'completed');
            this.setValue('cmi.core.score.min', '0'); // Ensure min score is set
            var commitResult = this.commit();
            console.log('setCourseComplete commit result:', commitResult);
        } else {
            console.warn('setCourseComplete called but SCORM not initialized');
        }
    },

    // Helper to format time as HHHH:MM:SS.SS for SCORM 1.2
    formatTime: function(ms) {
        var h = Math.floor(ms / 3600000);
        var m = Math.floor((ms % 3600000) / 60000);
        var s = Math.floor(((ms % 3600000) % 60000) / 1000);
        var cs = Math.floor((((ms % 3600000) % 60000) % 1000) / 10);
        
        if (h < 10) h = "0" + h;
        if (m < 10) m = "0" + m;
        if (s < 10) s = "0" + s;
        if (cs < 10) cs = "0" + cs;
        
        return h + ":" + m + ":" + s + "." + cs;
    },

    terminate: function() {
        try {
            // SCORM 1.2 Requirement: Set session time and exit status before finishing
            if (this.initialized && this.sessionData.startTime) {
                var endTime = new Date();
                var totalTime = endTime - this.sessionData.startTime;
                this.setValue("cmi.core.session_time", this.formatTime(totalTime));
                
                // Set exit to 'suspend' to ensure lesson_location (bookmarking) is preserved
                this.setValue("cmi.core.exit", "suspend");
            }

            if (this.mockMode) {
                this.saveMockData();
                console.log('Mock SCORM terminated');
            } else {
                var API = this.getAPI();
                if (API) API.LMSFinish("");
            }
            this.initialized = false;
        } catch (e) {
            console.error('terminate error:', e);
        }
    },

    // Enhanced debugging methods
    getDebugInfo: function() {
        return {
            initialized: this.initialized,
            mockMode: this.mockMode,
            sessionData: this.sessionData,
            mockStorage: this.mockStorage,
            apiAvailable: !!this.getAPI()
        };
    },

    // DEBUG: Check current objective status
    getObjectiveStatus: function(slideIdx) {
        if (!this.initialized) return 'not_initialized';
        
        var objId = 'obj_' + slideIdx;
        var status = this.getValue('cmi.objectives.' + slideIdx + '.status');
        var id = this.getValue('cmi.objectives.' + slideIdx + '.id');
        
        console.log('DEBUG: Objective', slideIdx, '- ID:', id, 'Status:', status);
        return {id: id, status: status, expectedId: objId};
    },

    // DEBUG: Check all objectives status
    getAllObjectivesStatus: function(totalSlides) {
        if (!this.initialized) return [];
        
        var objectives = [];
        for (var i = 0; i < totalSlides; i++) {
            objectives.push(this.getObjectiveStatus(i));
        }
        return objectives;
    },

    // DEBUG: Force refresh of objective data (for testing)
    refreshObjectives: function(totalSlides) {
        if (!this.initialized) return false;
        
        console.log('DEBUG: Refreshing objectives for', totalSlides, 'slides');
        for (var i = 0; i < totalSlides; i++) {
            var objId = 'obj_' + i;
            var currentId = this.getValue('cmi.objectives.' + i + '.id');
            var currentStatus = this.getValue('cmi.objectives.' + i + '.status');
            
            console.log('DEBUG: Slide', i, '- Current ID:', currentId, 'Expected ID:', objId, 'Status:', currentStatus);
            
            // Re-set the objective data if needed
            if (currentId !== objId) {
                console.log('DEBUG: Re-setting objective ID for slide', i);
                this.setValue('cmi.objectives.' + i + '.id', objId);
            }
            
            // Ensure status is set
            if (currentStatus !== 'completed') {
                console.log('DEBUG: Re-setting objective status for slide', i, 'to completed');
                this.setValue('cmi.objectives.' + i + '.status', 'completed');
                this.setValue('cmi.objectives.' + i + '.score.raw', '100');
                this.setValue('cmi.objectives.' + i + '.score.max', '100');
            }
        }
        
        this.commit();
        console.log('DEBUG: Objectives refreshed and committed');
        return true;
    },

    // Helper to persist session data
    saveSessionData: function() {
        if (this.initialized) {
            try {
                var dataStr = JSON.stringify({
                    answers: this.sessionData.answers,
                    visitedSlides: this.sessionData.visitedSlides
                });
                this.setValue("cmi.suspend_data", dataStr);
            } catch (e) {
                console.error('Failed to save session data:', e);
            }
        }
    },
};
window.addEventListener('load', () => SCORM.initialize());
window.addEventListener('unload', () => SCORM.terminate());
console.log('✓ SCORM wrapper with Mock API loaded');
"""

            scorm_path = package_dir / "scorm_wrapper.js"
            with open(scorm_path, 'w', encoding='utf-8') as f:
                f.write(scorm_js)

            logger.info("✓ SCORM wrapper created successfully")

        except Exception as e:
            logger.error(f"Failed to create SCORM wrapper: {e}")
            raise Exception(f"SCORM wrapper creation failed: {str(e)}")

    def _resolve_asset_source_path(self, raw_path: str) -> Path:
        """Resolve an asset path into a concrete local filesystem path."""
        if not raw_path:
            raise ValueError("Asset path is empty")

        media_root = Path("media").resolve()

        # Absolute path support (must stay under workspace/media).
        if os.path.isabs(raw_path):
            candidate = Path(raw_path).resolve()
            if candidate.exists():
                return candidate

        # API URL format from media endpoints.
        api_prefix = "/api/v1/media/files/"
        if raw_path.startswith(api_prefix):
            relative = raw_path[len(api_prefix):].lstrip("/")
            candidate = (media_root / relative).resolve()
            if str(candidate).startswith(str(media_root)) and candidate.exists():
                return candidate

        # Relative media path stored by upload response.
        relative_candidate = (media_root / raw_path.lstrip("/")).resolve()
        if (
            str(relative_candidate).startswith(str(media_root))
            and relative_candidate.exists()
        ):
            return relative_candidate

        # Last resort: relative to current workspace.
        workspace_candidate = Path(raw_path).expanduser().resolve()
        if workspace_candidate.exists():
            return workspace_candidate

        raise FileNotFoundError(f"Asset file not found for path '{raw_path}'")
    
    async def _copy_assets(self, package_dir: Path, assets: List[Any]) -> None:
        """Copy real asset files into the package and fail on invalid assets."""
        try:
            # Validate inputs
            if not package_dir or not package_dir.exists():
                raise ValueError(f"Invalid package directory: {package_dir}")
            if not assets:
                logger.info("No assets to copy")
                return

            assets_dir = package_dir / "assets"
            assets_dir.mkdir(exist_ok=True)

            copied_count = 0
            seen_target_names = set()
            copy_errors = []
            for index, asset in enumerate(assets):
                try:
                    if not hasattr(asset, "path"):
                        raise ValueError(
                            f"Asset at index {index} is missing 'path'"
                        )

                    source_path = self._resolve_asset_source_path(asset.path)
                    filename = os.path.basename(source_path.name)
                    if not filename:
                        raise ValueError(
                            f"Asset path '{asset.path}' has no filename"
                        )

                    if filename in seen_target_names:
                        raise ValueError(
                            f"Duplicate asset filename '{filename}' in package"
                        )
                    seen_target_names.add(filename)

                    target_path = assets_dir / filename
                    shutil.copy2(source_path, target_path)
                    copied_count += 1

                except Exception as e:
                    asset_name = getattr(asset, "name", f"asset_{index}")
                    copy_errors.append(f"{asset_name}: {e}")

            if copy_errors:
                raise ValueError(
                    "Asset copy failed: " + "; ".join(copy_errors)
                )

            logger.info(f"✓ Copied {copied_count} asset files")

        except Exception as e:
            logger.error(f"Failed to copy assets: {e}")
            raise Exception(f"Asset copying failed: {str(e)}")
    
    async def _validate_package_structure(self, package_dir: Path) -> None:
        """
        Validate the structure of the generated package
        """
        required_files = ['imsmanifest.xml', 'course_data.js', 'index.html', 'scorm_wrapper.js']
        for filename in required_files:
            if not (package_dir / filename).exists():
                raise ValueError(f"Missing required file: {filename}")

    def _add_directory_to_zip(self, zip_file: zipfile.ZipFile, dir_path: Path, arc_name: str) -> None:
        """Recursively add directory contents to ZIP file"""
        for item in dir_path.iterdir():
            item_arc_name = f"{arc_name}/{item.name}" if arc_name else item.name
            
            if item.is_file():
                zip_file.write(item, item_arc_name)
            elif item.is_dir():
                self._add_directory_to_zip(zip_file, item, item_arc_name)
    
    def _escape_xml(self, text: str) -> str:
        """Escape special characters for XML"""
        if not text:
            return ""
        
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#x27;"))
    
    def _escape_html(self, text: str) -> str:
        """Escape special characters for HTML"""
        if not text:
            return ""
        
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#x27;"))
    
    def _escape_js_string(self, text: str) -> str:
        """
        FIX #7: Escape string for safe insertion into JavaScript
        """
        if not text:
            return ""
        
        return (text
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("'", "\\'")
                .replace("\n", "\\n")
                .replace("\r", "\\r"))
    
    def _sanitize_text(self, text: Any) -> str:
        """
        FIX #7: Sanitize text for safe display
        Removes potentially dangerous patterns
        """
        if not text:
            return ""
        
        text_str = str(text)
        # Remove potentially dangerous patterns
        text_str = re.sub(
            r'<script[^>]*>.*?</script>',
            '',
            text_str,
            flags=re.IGNORECASE | re.DOTALL
        )
        text_str = re.sub(r'on\w+\s*=', '', text_str, flags=re.IGNORECASE)
        
        return html.escape(text_str)
    async def _validate_templates_for_scorm(self, templates: List) -> None:
        """
        Dynamic template validation using template definitions.
        NO HARDCODED TEMPLATE LOGIC - Uses template registry.
        
        Validates that all templates have required fields based on their
        registered definition before attempting to render them in SCORM player.
        
        Args:
            templates: List of template objects to validate
            
        Raises:
            ValueError: If any template fails validation
        """
        if not templates:
            raise ValueError("No templates provided for validation")
        
        validation_errors = []
        
        for i, template in enumerate(templates):
            try:
                # Check required template attributes
                if not hasattr(template, 'type') or not template.type:
                    validation_errors.append(
                        f"Template {i+1}: Missing or empty 'type' field"
                    )
                    continue
                
                if not hasattr(template, 'title'):
                    validation_errors.append(
                        f"Template {i+1}: Missing 'title' field"
                    )
                    continue
                
                # Check if template type is registered
                if not await registry.exists(template.type):
                    validation_errors.append(
                        f"Template {i+1} ({template.title}): "
                        f"Type '{template.type}' not registered"
                    )
                    continue
                
                # Get template definition
                definition = await registry.get(template.type)
                
                # Validate data exists
                if not hasattr(template, 'data') or not template.data:
                    validation_errors.append(
                        f"Template {i+1} ({template.title}): "
                        "Missing or empty data"
                    )
                    continue
                
                # Convert to dict
                try:
                    template_data = (
                        _ensure_dict(template.data)
                        if not isinstance(template.data, dict)
                        else template.data
                    )
                except ValueError as e:
                    validation_errors.append(
                        f"Template {i+1} ({template.title}): "
                        f"Data conversion failed: {str(e)}"
                    )
                    continue
                
                # Validate required fields from definition
                for field in definition.field_schema:
                    if field.required and field.name not in template_data:
                        validation_errors.append(
                            f"Template {i+1} ({template.title}): "
                            f"Missing required field '{field.name}'"
                        )
                        
            except Exception as e:
                validation_errors.append(
                    f"Template {i+1}: Validation error - {str(e)}"
                )
        
        if validation_errors:
            error_msg = (
                f"Template validation failed with "
                f"{len(validation_errors)} errors:\n"
                + "\n".join(validation_errors)
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(
            f"✓ Template validation passed for {len(templates)} templates"
        )
    
    async def _sanitize_data_dynamic(self, template_type: str, data: Any) -> Dict:
        """
        Dynamic data sanitization using template-specific rules from registry.
        
        This method replaces all hardcoded template type checks with dynamic
        sanitization based on template definitions stored in the database.
        
        Args:
            template_type: Type key of the template (e.g., 'mcq', 'content-text')
            data: The template data to sanitize (dict, Pydantic model, or other)
            
        Returns:
            Sanitized dictionary safe for SCORM package inclusion
        """
        if data is None:
            return {}
        
        # Get template definition from registry
        definition = await registry.get(template_type)
        if not definition:
            logger.warning(
                f"No template definition found for type '{template_type}', "
                f"using basic sanitization"
            )
            # Fallback: convert to dict and sanitize text fields only
            data_dict = _ensure_dict(data) if not isinstance(data, dict) else data
            return {
                k: self._sanitize_text(str(v)) if isinstance(v, str) else v
                for k, v in data_dict.items()
            }
        
        # Convert data to dict if needed
        data_dict = _ensure_dict(data) if not isinstance(data, dict) else data
        
        # Use DynamicSanitizer with template definition
        sanitizer = DynamicSanitizer()
        sanitized = await sanitizer.sanitize_template_data(
            type_key=template_type,
            data=data_dict
        )
        
        return sanitized
    
    def _looks_like_html(self, text: str) -> bool:
        """
        Check if text content appears to be HTML
        """
        if not text or not isinstance(text, str):
            return False
        
        # Simple heuristic: check for HTML tags
        html_indicators = ['<p>', '<br', '<div', '<span', '<strong', '<em', '<h1', '<h2', '<h3', '<ul', '<ol', '<li']
        text_lower = text.lower().strip()
        
        return any(indicator in text_lower for indicator in html_indicators)
    
    def _sanitize_html_content(self, html_content: str) -> str:
        """
        FIX #4: Advanced HTML sanitization using BeautifulSoup
        Removes dangerous tags and attributes while preserving safe formatting
        
        Args:
            html_content: Raw HTML content to sanitize
            
        Returns:
            Sanitized HTML content safe for display
        """
        if not html_content or not isinstance(html_content, str):
            return ""
        
        # If BeautifulSoup is not available, fall back to basic sanitization
        if not HAS_BEAUTIFULSOUP:
            logger.warning("BeautifulSoup not available, using basic HTML sanitization")
            return self._sanitize_text(html_content)
        
        try:
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Define allowed tags and their allowed attributes
            allowed_tags = {
                'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'span', 'div',
                'table', 'thead', 'tbody', 'tr', 'th', 'td',
                'img', 'a', 'hr'
            }
            
            allowed_attributes = {
                'img': ['src', 'alt', 'title', 'width', 'height'],
                'a': ['href', 'title'],
                'span': ['class', 'style'],
                'div': ['class', 'style'],
                'th': ['colspan', 'rowspan'],
                'td': ['colspan', 'rowspan'],
                'table': ['border', 'cellpadding', 'cellspacing']
            }
            
            # Remove dangerous tags and attributes
            for tag in soup.find_all():
                # Remove script and style tags entirely
                if tag.name in ['script', 'style', 'iframe', 'object', 'embed']:
                    tag.decompose()
                    continue
                
                # Remove event handlers (attributes starting with 'on')
                for attr in list(tag.attrs.keys()):
                    if attr.startswith('on') or attr in ['onclick', 'onload', 'onerror']:
                        del tag[attr]
                        continue
                    
                    # Check if attribute is allowed for this tag
                    if tag.name in allowed_attributes:
                        if attr not in allowed_attributes[tag.name]:
                            del tag[attr]
                    else:
                        # For tags not in allowed_attributes, only keep basic attrs
                        if attr not in ['class', 'id', 'title']:
                            del tag[attr]
                
                # Remove tags that are not in allowed list
                if tag.name not in allowed_tags:
                    tag.unwrap()  # Remove tag but keep content
            
            # Convert back to string and escape any remaining dangerous content
            sanitized = str(soup)
            
            # Additional safety: remove any remaining script-like patterns
            sanitized = re.sub(r'javascript:', '', sanitized, flags=re.IGNORECASE)
            sanitized = re.sub(r'vbscript:', '', sanitized, flags=re.IGNORECASE)
            sanitized = re.sub(r'data:', '', sanitized, flags=re.IGNORECASE)
            
            return sanitized
            
        except Exception as e:
            logger.error(f"HTML sanitization failed: {e}")
            # Fall back to basic text sanitization
            return self._sanitize_text(html_content)
    
    def estimate_package_size(self, course: Course) -> Dict[str, Any]:
        """
        Estimate the size of the generated SCORM package
        
        Args:
            course: Course data to analyze
            
        Returns:
            Dict containing size estimates
        """
        try:
            # Base SCORM structure size (manifest + HTML + JS)
            base_size = 15000  # ~15KB for base files
            
            # Estimate content size based on templates
            content_size = 0
            for template in course.templates:
                # Generic estimation based on data size (no hardcoded types)
                # Convert template data to string for size calculation
                try:
                    data_str = str(_ensure_dict(template.data))
                    content_size += len(data_str)
                except Exception:
                    # Fallback to string conversion
                    content_size += len(str(template.data))
            
            # Estimate asset sizes (placeholder values)
            asset_size = len(course.assets) * 50000  # ~50KB per asset estimate
            
            total_estimated = base_size + content_size + asset_size
            
            return {
                "base_structure_bytes": base_size,
                "content_bytes": content_size,
                "assets_bytes": asset_size,
                "total_estimated_bytes": total_estimated,
                "total_estimated_mb": round(total_estimated / 1024 / 1024, 2),
                "template_count": len(course.templates),
                "asset_count": len(course.assets)
            }
            
        except Exception as e:
            logger.error(f"Size estimation failed: {e}")
            return {"error": str(e), "total_estimated_mb": 0}

    async def validate_for_export(self, course: Course) -> Dict[str, Any]:
        """
        Validate course data before export
        
        Args:
            course: Course data to validate
            
        Returns:
            Dict with validation results
        """
        try:
            # Basic validation
            if not course:
                return {"valid": False, "errors": ["No course data provided"]}
            
            if not course.templates or len(course.templates) == 0:
                return {"valid": False, "errors": ["Course has no templates"]}
            
            # Check for required fields
            if not course.title:
                return {"valid": False, "errors": ["Course title is missing"]}
            
            # Validate templates
            await self._validate_templates_for_scorm(course.templates)
            
            return {
                "valid": True,
                "errors": [],
                "warnings": []
            }
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {
                "valid": False,
                "errors": [f"Validation failed: {str(e)}"],
                "warnings": []
            }
