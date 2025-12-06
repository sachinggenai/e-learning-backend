# Phase 1 - Quick Reference Summary

## 🎯 What is Phase 1?

**Automatic SCORM Package Analysis & Template Schema Inference**

A system that takes a SCORM course package (ZIP file) and:
1. Extracts the course data from JavaScript
2. Automatically detects template types
3. Figures out field schemas without predefined templates
4. Maps all media files
5. Stages everything for review

---

## 🏗️ The 5 Core Components

### 1️⃣ HeuristicParser
**Extracts JSON from JavaScript files**
- **3-tier strategy**: AST parsing → Regex → Simple JSON detection
- **Functions**:
  - `extract_json_from_js()` - Main entry point
  - `_extract_via_ast()` - Parse minified code
  - `_extract_via_regex()` - Pattern matching fallback
  - `_extract_simple_objects()` - Direct JSON detection
  - `_looks_like_course_data()` - Validate extracted data

### 2️⃣ SchemaInferenceEngine
**Automatically detects field types and schemas**
- **No predefined templates needed**
- **Functions**:
  - `infer_schema_from_data()` - Generate schema from data
  - `_infer_type()` - Detect field type (text, URL, image, etc)
  - `generate_render_template()` - Create HTML/Jinja2 template
  - `compute_schema_signature()` - Create unique schema hash
  - `infer_template_definition()` - Complete template definition

### 3️⃣ AssetRewriter
**Maps media files and normalizes references**
- **Finds all images, videos, documents**
- **Functions**:
  - `build_file_map()` - Index all files
  - `detect_ambiguous_assets()` - Find duplicates
  - `rewrite_html_content()` - Update URLs
  - `_is_asset()` - Check if file is media

### 4️⃣ ImportService
**Orchestrates the entire workflow**
- **Main operations**:
  - `analyze_package()` - Complete analysis
  - `_discover_payloads()` - Find JSON data
  - `_extract_templates()` - Get template list
  - `_analyze_templates()` - Infer each schema
  - `_collect_warnings()` - Identify issues
  - `get_preview()` - Review staged data
  - `commit_import()` - Finalize (marks as committed)

### 5️⃣ REST API Endpoints
**HTTP interface for import operations**
- `POST /api/v1/imports/analyze` - Upload & analyze
- `GET /api/v1/imports/jobs/{job_id}` - Get status
- `GET /api/v1/imports/jobs/{job_id}/preview` - Get preview
- `POST /api/v1/imports/jobs/{job_id}/commit` - Finalize

---

## 📊 The Data Flow

```
SCORM ZIP Upload
     ↓
extract_json_from_js()
     ↓
_extract_templates()
     ↓
infer_template_definition() × for each template
     ↓
build_file_map() + detect_ambiguous_assets()
     ↓
Stage in Database
     ↓
Return Job ID to User
     ↓
User Polls: GET /api/v1/imports/jobs/{job_id}
     ↓
User Reviews Staged Data
     ↓
User Commits: POST /api/v1/imports/jobs/{job_id}/commit
     ↓
Import Complete (ready for Phase 2)
```

---

## 🔍 Example: What Gets Analyzed

### Input SCORM Package
```
mycoursev2.zip
├── imsmanifest.xml
├── course.js (contains: var courseData = {...})
├── content/
│   ├── slide1.html
│   └── slide2.html
└── images/
    ├── logo.png
    └── icon.svg
```

### Step 1: Extract JSON
```
course.js contains:
var courseData = {
  courseId: 'MATH101',
  title: 'Math Basics',
  templates: [
    {type: 'welcome', data: {text: '...'}},
    {type: 'mcq', data: {question: '...', options: [...]}}
  ]
}
```

### Step 2: Analyze Templates
```
Template 1 (welcome):
  Data: {text: "Welcome!"}
  Inferred Schema:
    - Field: "text" → Type: "text"

Template 2 (mcq):
  Data: {question: "...", options: [...]}
  Inferred Schema:
    - Field: "question" → Type: "text"
    - Field: "options" → Type: "array"
```

### Step 3: Map Assets
```
Found: logo.png, icon.svg (2 assets total)
Ambiguous: None
```

### Step 4: Stage Results
```
Database stores:
- Job ID: "uuid-123"
- Status: "analyzed"
- Course: courseId=MATH101, title=Math Basics
- Templates: 2 (with schemas inferred)
- Assets: 2 files mapped
```

### Step 5: User Reviews & Commits
```
GET /api/v1/imports/jobs/uuid-123
→ Shows all extracted data, templates, schemas
→ User reviews

POST /api/v1/imports/jobs/uuid-123/commit
→ Marks as "committed"
→ Ready for Phase 2 (actual course creation)
```

---

## 💡 Key Features

### ✅ Automatic Type Detection
- **Text fields** → detected automatically
- **URLs** → recognized from http:// pattern
- **Images** → found in src attributes
- **Arrays** → detected from data structure
- **Objects** → handled as nested data

### ✅ Zero Configuration
- No need to tell system what types exist
- No predefined template catalog
- Works with new template types automatically
- New formats supported without code changes

### ✅ Robust Parsing
- **Minified JavaScript** → AST parsing with pyjsparser
- **Readable JavaScript** → Regex pattern matching
- **JSON files** → Direct parsing
- **Graceful fallbacks** → Multiple strategies

### ✅ Safety
- **Temporary files** → Auto-cleaned
- **No actual database changes** → Only staging
- **Error tracking** → Job marked as failed, not stuck
- **User review** → Before anything is committed

### ✅ Scalability
- **Async/await** → Non-blocking I/O
- **Concurrent imports** → Independent jobs
- **Database-backed** → Can track hundreds of jobs
- **Incremental staging** → Large packages handled

---

## 🎯 What We Achieve

| Achievement | Description |
|-------------|-------------|
| **Automation** | No manual template mapping |
| **Flexibility** | Works with new template types |
| **Quality** | Schemas generated from actual data |
| **Audit Trail** | Every import tracked |
| **Safety** | User review before commit |
| **Scalability** | Multiple concurrent imports |
| **Extensibility** | Easy to add new strategies |

---

## 📋 Method Reference Table

### HeuristicParser Methods
| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `extract_json_from_js()` | JS code (str) | List[Dict] | Extract all JSON |
| `_extract_via_ast()` | JS code | List[Dict] | Parse minified JS |
| `_extract_via_regex()` | JS code | List[Dict] | Pattern-based extraction |
| `_extract_simple_objects()` | JS code | List[Dict] | Standalone JSON |

### SchemaInferenceEngine Methods
| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `infer_schema_from_data()` | Dict | Schema | Generate field schema |
| `_infer_type()` | Any value | str | Detect field type |
| `generate_render_template()` | Schema | str (HTML) | Create render template |
| `compute_schema_signature()` | Schema | str (SHA-256) | Unique schema ID |
| `infer_template_definition()` | Data, type | Dict | Complete template def |

### AssetRewriter Methods
| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `build_file_map()` | ZIP dict | Dict | Index all files |
| `detect_ambiguous_assets()` | File map | Dict | Find duplicates |
| `rewrite_html_content()` | HTML, files | (HTML, warns) | Update URLs |

### ImportService Methods
| Method | Input | Output | Purpose |
|--------|-------|--------|---------|
| `analyze_package()` | ZIP bytes | job_id (str) | Complete analysis |
| `_discover_payloads()` | ZIP dict | List[Dict] | Find JSON payloads |
| `_extract_templates()` | course_data | List[Dict] | Get templates |
| `_analyze_templates()` | templates | List[Dict] | Infer schemas |
| `get_preview()` | job_id | Dict | Show staged data |
| `commit_import()` | job_id | Dict | Mark committed |

### REST Endpoints
| Endpoint | Method | Purpose | Response |
|----------|--------|---------|----------|
| `/imports/analyze` | POST | Upload & analyze | `{job_id, status}` |
| `/imports/jobs/{id}` | GET | Poll status | `{status, course_data}` |
| `/imports/jobs/{id}/preview` | GET | Get preview | `{status, course_data}` |
| `/imports/jobs/{id}/commit` | POST | Finalize | `{status: committed}` |

---

## 🚀 Next Phase (Phase 2)

Once Phase 1 analysis is staged and committed:

1. Read staged data from job
2. Create course record
3. Create template records
4. Store media files
5. Activate course

**Separation of concerns** → User has time to review before Phase 2 creates actual records.

---

## ✨ Simple Summary

**Phase 1 is an analysis engine that:**
- Takes a SCORM ZIP file
- Automatically figures out the structure
- Detects template types without predefined schemas
- Maps all media files
- Stages the results for user review
- Waits for user confirmation to proceed

**It enables flexible, adaptive course importing** that works with new formats automatically.

