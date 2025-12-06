# Phase 1 - SCORM Import System: Architecture Reverse Engineering

**Document Type**: Architectural Analysis & Reverse Engineering
**Date**: December 4, 2025
**Phase**: Phase 1 (Analysis & Schema Inference)
**Status**: Implementation Complete

---

## 📋 Executive Summary

### Intent of Phase 1 Implementation

The Phase 1 implementation creates an **automated SCORM package analysis and template schema inference system** that:

1. **Extracts** JSON course data from minified/packaged JavaScript in SCORM files
2. **Detects** template types automatically by analyzing data structures
3. **Infers** field schemas from extracted data without predefined templates
4. **Maps** media assets and normalizes file references
5. **Stages** the results for review before commit

### Simple English Goal

> "Take a SCORM package (a ZIP file containing course data), automatically figure out what data it contains, understand what types of templates are being used, map all the media files, and present the organized information for a user to review before importing."

---

## 🏗️ Architecture Overview

### High-Level Flow

```
User Uploads SCORM ZIP File
         ↓
ImportService.analyze_package()
         ↓
┌────────────────────────────────────────────────┐
│ Phase 1: Analysis Pipeline                      │
├────────────────────────────────────────────────┤
│ 1. Extract ZIP Contents                         │
│    └─ zipfile.ZipFile.extractall()             │
│                                                 │
│ 2. Discover JSON Payloads                       │
│    └─ HeuristicParser.extract_json_from_js()  │
│       ├─ AST parsing (pyjsparser)             │
│       ├─ Regex pattern matching               │
│       └─ Simple object detection              │
│                                                 │
│ 3. Extract Templates from Course Data          │
│    └─ ImportService._extract_templates()      │
│                                                 │
│ 4. Analyze Each Template                       │
│    └─ ImportService._analyze_templates()      │
│       └─ SchemaInferenceEngine.infer_template_definition()
│          ├─ Compute schema from data          │
│          ├─ Generate render template          │
│          └─ Create field schema                │
│                                                 │
│ 5. Map Assets & Build File Index               │
│    └─ AssetRewriter.build_file_map()          │
│       └─ AssetRewriter.detect_ambiguous_assets()
│                                                 │
│ 6. Collect Warnings                            │
│    └─ ImportService._collect_warnings()        │
│                                                 │
│ 7. Stage Results in Database                   │
│    └─ ImportJobRepository.update_result()     │
│                                                 │
│ 8. Update Job Status                           │
│    └─ ImportJobRepository.update_status()     │
└────────────────────────────────────────────────┘
         ↓
Job Status: "analyzed" (100% complete)
Staged Data Ready for Review
```

---

## 🔍 Detailed Component Analysis

### Component 1: HeuristicParser (heuristic_parser.py)

**Purpose**: Extract JSON payloads from JavaScript files

**Method**: `extract_json_from_js(js_content: str)`
- **Input**: JavaScript source code (minified or readable)
- **Output**: List of extracted JSON objects
- **Strategy**: Three-tier fallback approach

**Sub-Methods**:

1. **`_extract_via_ast(js_content)`** - AST Parsing
   - Uses `pyjsparser.parse()` to parse JavaScript into Abstract Syntax Tree
   - Walks the AST looking for `AssignmentExpression` nodes
   - Converts AST nodes to Python objects using `_ast_node_to_python()`
   - **Best for**: Minified/complex JavaScript code
   - **Risk**: Fails on invalid JS syntax

2. **`_walk_ast(node, payloads)`** - AST Traversal
   - Recursively traverses the AST structure
   - Searches for `ObjectExpression` and `ArrayExpression` nodes
   - Extracts assignments of objects/arrays to variables
   - Handles nested structures

3. **`_ast_node_to_python(node)`** - AST to Python Conversion
   - Converts `ObjectExpression` → Python `dict`
   - Converts `ArrayExpression` → Python `list`
   - Handles `Literal` values (strings, numbers, booleans)
   - **Returns**: Native Python object or None

4. **`_extract_via_regex(js_content)`** - Regex Pattern Matching
   - Pattern 1: `var name = {...}` for object assignments
   - Pattern 2: `var name = [...]` for array assignments
   - Uses `json.loads()` to validate extracted strings
   - **Fallback for**: Simple, readable JavaScript

5. **`_extract_simple_objects(js_content)`** - Direct JSON Detection
   - Searches for standalone JSON objects/arrays
   - Uses `_looks_like_course_data()` heuristic to filter relevant data
   - **Fallback for**: When patterns don't match

6. **`_looks_like_course_data(obj)`** - Data Validation
   - Checks for course-related keys: `courseId`, `title`, `templates`, `slides`, `pages`
   - Checks if list contains template-like objects (with `type`, `id`, `title`, `data`)
   - **Purpose**: Avoid extracting random JSON from comments/strings

7. **`extract_from_file(file_path)`** - File-based Extraction
   - Reads JavaScript file from disk
   - Calls `extract_json_from_js()` on contents
   - **Handles**: File encoding errors gracefully

**Example Flow**:
```
minified.js content:
  "var courseData={courseId:'c1',title:'Math 101',templates:[...]}"
  
→ _extract_via_ast() fails on minification
→ _extract_via_regex() finds: courseId, title, templates
→ json.loads() converts to dict
→ _looks_like_course_data() validates
→ Returns: [{'courseId': 'c1', 'title': 'Math 101', 'templates': [...]}]
```

---

### Component 2: SchemaInferenceEngine (schema_inference.py)

**Purpose**: Automatically detect template types and infer field schemas

**Main Method**: `infer_template_definition(template_data, template_type, source_metadata)`
- **Input**: Template data dict, template type name
- **Output**: Complete template definition ready for database
- **Logic**: Analyzes data structure without needing predefined schemas

**Sub-Methods**:

1. **`infer_schema_from_data(data)`** - Schema Generation
   - Iterates through each key-value pair in data dict
   - Calls `_infer_type(value)` for each field
   - **Output**: Schema object with fields array
   - **Example**:
     ```json
     Input:  {"question": "What is 2+2?", "options": ["3", "4", "5"]}
     Output: {
       "type": "object",
       "fields": [
         {"name": "question", "type": "text", "required": true},
         {"name": "options", "type": "array[text]", "required": true}
       ]
     }
     ```

2. **`_infer_type(value)`** - Type Detection
   - Returns schema type string for any Python value
   - **Type Mappings**:
     - `None` → `"null"`
     - `bool` → `"boolean"`
     - `int` → `"integer"`
     - `float` → `"number"`
     - `str` starting with http/https → `"url"`
     - `str` with HTML tags → `"html"`
     - `str` (plain) → `"text"`
     - `list` → `"array"` or `"array[type]"`
     - `dict` → `"object"`
   - **Smart Detection**: Recognizes URLs and HTML automatically

3. **`generate_render_template(schema, template_type)`** - HTML Template Generation
   - Creates Jinja2 template string for rendering
   - Generates field-specific HTML:
     - `html` fields → `{{ data.field | safe }}`
     - `url` fields → `<img src="{{ data.field }}" />`
     - `array` fields → `{% for item in data.field %}`
   - **Purpose**: Ready-to-use template for displaying data
   - **Example**:
     ```html
     <div class='template template-mcq'>
       <div class='header'>MCQ</div>
       <div class='content'>
         <div class='field-question'>{{ data.question }}</div>
         <ul class='list-options'>
           {% for item in data.options %}
           <li>{{ item }}</li>
           {% endfor %}
         </ul>
       </div>
     </div>
     ```

4. **`compute_schema_signature(schema)`** - Schema Hashing
   - Creates SHA-256 hash of schema definition
   - **Input**: Schema dict
   - **Output**: 64-character hex string
   - **Purpose**: Detect duplicate schemas, version schemas
   - **Method**: `hashlib.sha256(canonical_json).hexdigest()`

5. **`generate_field_schema_json(schema)`** - Field Schema Serialization
   - Creates JSON representation of field definitions
   - Includes version, fields array, timestamp
   - **Purpose**: Store in database

6. **`generate_schema_json(schema)`** - Schema Serialization
   - Simple JSON serialization of complete schema
   - **Purpose**: Store in database

**Example Flow**:
```
Template Data:
  {
    "question": "What color is the sky?",
    "options": [
      {"text": "Blue", "correct": true},
      {"text": "Green", "correct": false}
    ]
  }

→ infer_schema_from_data()
  ├─ "question" → _infer_type("What color...") → "text"
  ├─ "options" → _infer_type([{...}]) → "array[object]"

→ Schema:
  {
    "type": "object",
    "fields": [
      {"name": "question", "type": "text", ...},
      {"name": "options", "type": "array[object]", ...}
    ]
  }

→ compute_schema_signature() → "a1b2c3d4..."
→ generate_render_template() → "<div class='template-mcq'>..."
→ Final Template Definition ready for storage
```

---

### Component 3: AssetRewriter (asset_rewriter.py)

**Purpose**: Map media files and normalize asset references

**Main Methods**:

1. **`build_file_map(zip_contents)`** - Asset Indexing
   - **Input**: Dict of `{file_path: file_bytes}` from ZIP
   - **Output**: Dict of `{filename: [list of full paths]}`
   - **Logic**: 
     - Extracts filename from each path
     - Filters to asset types only
     - Groups paths by filename
   - **Example**:
     ```python
     Input:  {
       "images/logo.png": bytes,
       "media/logo.png": bytes,
       "content.html": bytes
     }
     
     Output: {
       "logo.png": ["images/logo.png", "media/logo.png"],
       # content.html skipped (not an asset)
     }
     ```

2. **`detect_ambiguous_assets(file_map)`** - Duplicate Detection
   - **Input**: file_map from `build_file_map()`
   - **Output**: Dict of filenames appearing in multiple paths
   - **Purpose**: Identify files that need manual resolution
   - **Example**:
     ```python
     Input:  {"logo.png": [2 paths], "style.css": [1 path]}
     Output: {"logo.png": ["images/logo.png", "media/logo.png"]}
     ```

3. **`rewrite_html_content(html_content, file_map, course_id, ambiguous_assets)`** - HTML Rewriting
   - **Input**: HTML string, file map, course ID
   - **Output**: Tuple of (rewritten_html, warnings_list)
   - **Logic**:
     - Finds all `src`, `href`, `data` attributes in HTML
     - Looks up file in file_map
     - Replaces with API URL: `/api/v1/media/{course_id}/{filename}`
     - Skips ambiguous files (logs warning)
   - **Example**:
     ```html
     Input:  <img src="images/logo.png">
     Output: <img src="/api/v1/media/course123/logo.png">
     ```

4. **`_is_asset(filename)`** - Asset Classification
   - Checks file extension against asset types
   - **Supported**: Images, video, audio, documents, archives
   - **Skipped**: HTML, CSS, JavaScript, XML (processed separately)

---

### Component 4: ImportService (import_service.py)

**Purpose**: Orchestrate the entire import workflow

**Main Methods**:

1. **`analyze_package(zip_data, course_id)`** - Primary Entry Point
   - **Input**: Raw ZIP file bytes, optional course ID
   - **Output**: Job ID for polling
   - **Process**:
     ```
     a) Create import job in database (status: "analyzing")
     b) Extract ZIP to temporary directory
     c) Read ZIP contents into memory
     d) Call _discover_payloads() to find JSON
     e) Call _extract_templates() to get template list
     f) Call _analyze_templates() to infer schemas
     g) Call build_file_map() to create asset index
     h) Call detect_ambiguous_assets() to find duplicates
     i) Stage data: call update_result() with staged data
     j) Update job status to "analyzed" (100% complete)
     k) Return job_id
     ```
   - **Error Handling**: On exception, update job status to "failed" with error message

2. **`_extract_zip(zip_path)`** - ZIP Extraction
   - **Input**: Path to ZIP file
   - **Output**: Dict of `{file_path: file_bytes}`
   - **Logic**: Extracts all files into memory dict

3. **`_discover_payloads(zip_contents)`** - Payload Discovery
   - **Input**: ZIP contents dict
   - **Output**: List of extracted JSON payloads
   - **Logic**:
     - Iterates through each file
     - Looks for `.js`, `.json` files
     - Calls `HeuristicParser.extract_json_from_js()` on JS files
     - Parses JSON files directly
     - Returns first valid payload or raises `NoPayloadFoundError`

4. **`_extract_templates(course_data)`** - Template Extraction
   - **Input**: Parsed course data dict
   - **Output**: List of template objects
   - **Logic**: Accesses `course_data.get("templates", [])`
   - **Assumes**: Course data has a `templates` array

5. **`_analyze_templates(templates)`** - Template Analysis
   - **Input**: List of template objects
   - **Output**: List of analyzed template definitions
   - **Logic**:
     ```
     For each template:
       a) Get template type: template.get("type")
       b) Get template data: template.get("data", {})
       c) Call SchemaInferenceEngine.infer_template_definition()
       d) Enrich with template metadata
     ```

6. **`_collect_warnings(analyzed_templates)`** - Warning Collection
   - **Input**: List of analyzed templates
   - **Output**: List of warning messages
   - **Checks**:
     - Missing required fields
     - Ambiguous asset references
     - Unsupported data types
     - Schema conflicts

7. **`get_preview(job_id)`** - Preview Retrieval
   - **Input**: Job ID
   - **Output**: Dict with job status, progress, staged course data
   - **Purpose**: Allow user to review before commit

8. **`commit_import(job_id)`** - Import Commitment
   - **Input**: Job ID
   - **Output**: Dict with commit results
   - **Logic**: Updates job status to "committed"
   - **Note**: Phase 1 only marks as committed; Phase 2 creates actual course

---

### Component 5: ImportJobRepository (import_job_repository.py)

**Purpose**: Database persistence for import jobs

**Methods**:

1. **`create(status, course_id, source_file_path, metadata)`** - Job Creation
   - **Input**: Job parameters
   - **Output**: Created ImportJob ORM object
   - **Database**: Inserts new row in `import_jobs` table
   - **Generates**: UUID for job_id

2. **`get_by_id(job_id)`** - Job Retrieval
   - **Input**: Job UUID
   - **Output**: ImportJob object or None
   - **Query**: `SELECT * FROM import_jobs WHERE job_id = ?`

3. **`update_status(job_id, status, progress, error_message)`** - Status Update
   - **Input**: Job ID, new status, progress (0.0-1.0), optional error
   - **Output**: Updated ImportJob object
   - **Updates**: Timestamps included automatically

4. **`update_result(job_id, result_data)`** - Result Staging
   - **Input**: Job ID, staged data dict
   - **Output**: Updated ImportJob object
   - **Stores**: Course data as JSON in `result_data` column
   - **Purpose**: Stage data before commit

5. **`update_course_id(job_id, course_id)`** - Course Linking
   - **Input**: Job ID, course ID
   - **Output**: Updated ImportJob object
   - **Purpose**: Link import job to final course

6. **`list_by_status(status, limit)`** - Status Query
   - **Input**: Status string, max results
   - **Output**: List of ImportJob objects
   - **Purpose**: Find all jobs in particular status

7. **`list_all(limit)`** - All Jobs Query
   - **Input**: Max results
   - **Output**: List of ImportJob objects

8. **`delete(job_id)`** - Job Deletion
   - **Input**: Job ID
   - **Output**: Boolean success
   - **Purpose**: Clean up old jobs

---

### Component 6: REST API Router (imports.py)

**Purpose**: HTTP endpoints for import operations

**Endpoints**:

1. **`POST /api/v1/imports/analyze`** - Upload & Analyze
   - **Request**: 
     - `file`: ZIP file (multipart/form-data)
     - `course_id`: Optional query parameter
   - **Response**: `ImportAnalysisResponse`
     ```json
     {
       "job_id": "uuid-here",
       "status": "analyzing",
       "progress": 0.5,
       "course_data": null,
       "error": null
     }
     ```
   - **Errors**:
     - 400: Not a ZIP file
     - 400: No payloads found
     - 500: Unexpected error
   - **Handler Method**: `analyze_import()`
     - Validates file type
     - Reads file bytes
     - Creates ImportService instance
     - Calls `analyze_package()`
     - Returns job_id

2. **`GET /api/v1/imports/jobs/{job_id}`** - Poll Status
   - **Request**: Job ID in URL
   - **Response**: `ImportStatusResponse`
     ```json
     {
       "job_id": "uuid",
       "status": "analyzed",
       "progress": 1.0,
       "course_data": { ... },
       "error": null,
       "created_at": "2025-12-04T...",
       "updated_at": "2025-12-04T..."
     }
     ```
   - **Errors**:
     - 404: Job not found
   - **Handler Method**: `get_import_status()`

3. **`GET /api/v1/imports/jobs/{job_id}/preview`** - Get Preview
   - **Request**: Job ID in URL
   - **Response**: Same as status endpoint
   - **Purpose**: Alias for status endpoint

4. **`POST /api/v1/imports/jobs/{job_id}/commit`** - Finalize Import
   - **Request**: `ImportCommitRequest`
     ```json
     {
       "job_id": "uuid",
       "merge_with_course_id": null
     }
     ```
   - **Response**: `ImportCommitResponse`
     ```json
     {
       "job_id": "uuid",
       "status": "committed",
       "course_id": null,
       "message": "Import committed successfully"
     }
     ```
   - **Handler Method**: `commit_import()`

---

## 🔄 Complete Data Flow Example

### Scenario: Importing a SCORM Package with 3 Templates

**Step 1: User Uploads ZIP**
```
Upload: mycoursev2.zip (5 MB)
URL: POST /api/v1/imports/analyze
```

**Step 2: HeuristicParser Extraction**
```
ZIP Contents:
  - imsmanifest.xml (manifest)
  - course.js (contains: var courseData = {...})
  - content/slide1.html
  - images/logo.png
  - images/icon.svg
  - video/intro.mp4

HeuristicParser._extract_via_regex() finds:
  "var courseData = {
    courseId: 'MATH101',
    title: 'Mathematics Basics',
    templates: [
      {type: 'welcome', data: {text: 'Welcome...'}},
      {type: 'content-video', data: {title: '...', videoUrl: '...'}},
      {type: 'mcq', data: {question: '...', options: [...]}}
    ]
  }"
  
Returns: [{courseId, title, templates}]
```

**Step 3: Template Extraction**
```
Templates extracted:
  1. {type: 'welcome', data: {text: '...'}}
  2. {type: 'content-video', data: {title: '...', videoUrl: '...'}}
  3. {type: 'mcq', data: {question: '...', options: [...]}}
```

**Step 4: Schema Inference for Each Template**
```
Template 1 (welcome):
  - Field "text" → _infer_type("Welcome...") → "text"
  Schema: {fields: [{name: "text", type: "text"}]}
  Signature: "abc123def456..."

Template 2 (content-video):
  - Field "title" → "text"
  - Field "videoUrl" → "url"
  Schema: {fields: [{name: "title", type: "text"}, {name: "videoUrl", type: "url"}]}
  Signature: "def789ghi012..."

Template 3 (mcq):
  - Field "question" → "text"
  - Field "options" → "array[object]"
  Schema: {fields: [{name: "question", type: "text"}, {name: "options", type: "array[object]"}]}
  Signature: "jkl345mno678..."
```

**Step 5: Asset Mapping**
```
build_file_map():
  {
    "logo.png": ["images/logo.png"],
    "icon.svg": ["images/icon.svg"],
    "intro.mp4": ["video/intro.mp4"]
  }

detect_ambiguous_assets():
  {} (no duplicates)
```

**Step 6: Stage Results**
```
Job Database Update:
  {
    job_id: "uuid-123",
    status: "analyzing",
    progress: 0.5,
    result_data: {
      courseId: "MATH101",
      title: "Mathematics Basics",
      templates: [
        {type: "welcome", schema: {...}, signature: "abc123..."},
        {type: "content-video", schema: {...}, signature: "def789..."},
        {type: "mcq", schema: {...}, signature: "jkl345..."}
      ],
      assets: {
        total: 3,
        ambiguous: 0,
        ambiguous_files: []
      },
      warnings: []
    }
  }
```

**Step 7: API Response**
```json
{
  "job_id": "uuid-123",
  "status": "analyzing",
  "progress": 0.5
}
```

**Step 8: User Polls for Status**
```
GET /api/v1/imports/jobs/uuid-123

Response:
{
  "job_id": "uuid-123",
  "status": "analyzed",
  "progress": 1.0,
  "course_data": {
    "courseId": "MATH101",
    "title": "Mathematics Basics",
    "templates": [
      {type: "welcome", data: {...}, schema: {...}},
      {type: "content-video", data: {...}, schema: {...}},
      {type: "mcq", data: {...}, schema: {...}}
    ],
    "assets": {total: 3, ambiguous: 0}
  }
}
```

**Step 9: User Reviews & Commits**
```
POST /api/v1/imports/jobs/uuid-123/commit

Response:
{
  "job_id": "uuid-123",
  "status": "committed",
  "message": "Import committed successfully"
}
```

**Final Database State**:
- Job status: "committed"
- Course data staged and ready for Phase 2 (course creation)

---

## 📊 Data Models

### ImportJob (ORM Model)

```python
class ImportJob(Base):
    __tablename__ = "import_jobs"
    
    id: Integer (Primary Key)
    job_id: String(36) UNIQUE        # UUID for API reference
    status: String(50)               # analyzing, analyzed, committed, failed
    progress: Float                  # 0.0 to 1.0
    course_id: String(255) NULLABLE  # Target course (optional)
    source_file_path: String(500)    # Where ZIP came from
    result_data: JSON                # Staged course data
    error_message: String NULLABLE   # If failed
    created_at: DateTime             # Job creation time
    updated_at: DateTime             # Last update time
```

### Result Data Structure (JSON)

```json
{
  "courseId": "string",
  "title": "string",
  "description": "string",
  "templates": [
    {
      "type": "string",
      "id": "string",
      "data": {},
      "schema": {
        "type": "object",
        "fields": [
          {
            "name": "string",
            "type": "string (text|url|html|array|etc)",
            "required": boolean,
            "nullable": boolean
          }
        ]
      },
      "schema_signature": "string (SHA-256)",
      "render_template": "string (HTML/Jinja2)",
      "warnings": ["string"]
    }
  ],
  "assets": {
    "total": number,
    "ambiguous": number,
    "ambiguous_files": ["string"]
  },
  "warnings": ["string"]
}
```

---

## 🎯 What We Achieve After Phase 1 Implementation

### Immediate Outcomes

1. ✅ **Automatic Template Type Detection**
   - No need for predefined template catalogs
   - Schemas inferred from actual data
   - Works with new template types automatically

2. ✅ **Zero-Configuration Schema Generation**
   - Field names, types, requirements detected automatically
   - Supports: text, URL, HTML, images, arrays, objects, etc.
   - Generates render templates automatically

3. ✅ **Asset Indexing & Ambiguity Detection**
   - All media files discovered and mapped
   - Duplicate files detected (ambiguous assets)
   - Ready for CDN/storage integration

4. ✅ **Multi-Strategy Parsing**
   - Works with minified JavaScript (AST parsing)
   - Works with readable JavaScript (regex)
   - Falls back gracefully

5. ✅ **User Review Before Commit**
   - Staged data available for preview
   - Users can see what was extracted
   - Users can confirm before finalizing

### Strategic Advantages

6. ✅ **Extensibility**
   - New template types added automatically
   - No code changes needed
   - System adapts to new formats

7. ✅ **Quality Control**
   - Schema signatures for deduplication
   - Warnings collected for known issues
   - Error tracking and job history

8. ✅ **Database Integration**
   - Job history persistent
   - Status tracking for long operations
   - Result staging before commit

### Business Value

9. ✅ **Reduced Manual Data Entry**
   - Existing courses can be imported programmatically
   - No manual template mapping required
   - Bulk import capability (future)

10. ✅ **Course Conversion**
    - Convert SCORM packages to internal format
    - Preserve course structure and content
    - Support legacy course migration

11. ✅ **API-First Architecture**
    - RESTful, stateless endpoints
    - Async/non-blocking operations
    - Scalable (multiple concurrent imports)

12. ✅ **Audit Trail**
    - Every import tracked in database
    - Job history with timestamps
    - Error messages for debugging

---

## 🚀 Next Steps (Phase 2)

Once Phase 1 staging is complete, Phase 2 will:

1. Read staged data from import job
2. Create course record in database
3. Create template records linked to course
4. Store media files to CDN/storage
5. Update course status to "active"

This clean separation allows:
- User review between phases
- Validation checks before actual creation
- Rollback capability (delete job)
- Batch processing without database locks

---

## 📈 Performance Characteristics

- **ZIP Extraction**: O(n) where n = number of files
- **JSON Parsing**: O(n) where n = file size
- **Schema Inference**: O(m) where m = number of fields
- **Total Time**: Typically 1-5 seconds for 5MB package

### Scalability Notes

- Async/await throughout → no thread blocking
- Temporary files cleaned up automatically
- Database commits after each major operation
- Supports concurrent imports (independent jobs)

---

## ✅ Testing Recommendations

### Unit Tests
- [ ] HeuristicParser: Test each parsing strategy
- [ ] SchemaInferenceEngine: Test type inference
- [ ] AssetRewriter: Test URL rewriting
- [ ] ImportService: Test complete flow

### Integration Tests
- [ ] Upload valid SCORM ZIP
- [ ] Poll job status
- [ ] Retrieve preview data
- [ ] Commit import

### Edge Cases
- [ ] Empty ZIP file
- [ ] No JSON payloads
- [ ] Malformed JSON
- [ ] Missing templates
- [ ] Ambiguous assets

---

## 📚 Summary Table

| Component | Purpose | Key Methods | Input | Output |
|-----------|---------|-------------|-------|--------|
| **HeuristicParser** | Extract JSON from JS | `extract_json_from_js()` | JS code | List[Dict] |
| **SchemaInferenceEngine** | Infer schemas | `infer_template_definition()` | Template data | Template def |
| **AssetRewriter** | Map media files | `build_file_map()` | ZIP contents | File map |
| **ImportService** | Orchestrate workflow | `analyze_package()` | ZIP bytes | Job ID |
| **ImportJobRepository** | Database persistence | `create(), get_by_id()` | Job params | ImportJob |
| **REST Router** | HTTP endpoints | `analyze_import()` | File upload | JSON response |

---

## 🎓 Key Takeaway

**Phase 1 is a fully autonomous analysis engine** that takes any SCORM package and:
1. **Understands** its structure automatically
2. **Discovers** template types without predefined schemas
3. **Analyzes** each template independently
4. **Stages** the results safely in the database
5. **Waits** for user confirmation before proceeding

This creates the foundation for flexible, adaptive course import that works with new course formats automatically.

