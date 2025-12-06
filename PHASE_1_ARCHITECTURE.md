# Phase 1 - Visual Architecture & Component Interaction

## 🏗️ System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          REST API LAYER                              │
│  POST /api/v1/imports/analyze     GET /api/v1/imports/jobs/{id}    │
│                   ↓                              ↓                   │
│           analyze_import()               get_import_status()       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATION LAYER                             │
│                                                                       │
│                     ImportService                                    │
│                   analyze_package()                                  │
│                                                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  1. Extract ZIP                                             │  │
│   │     _extract_zip() → Dict[path, bytes]                     │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  2. Discover Payloads                                       │  │
│   │     _discover_payloads() → List[JSON objects]              │  │
│   │     ↓ calls ↓                                               │  │
│   │     HeuristicParser.extract_json_from_js()                │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  3. Extract Templates                                       │  │
│   │     _extract_templates() → List[template objects]          │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  4. Analyze Templates                                       │  │
│   │     _analyze_templates() → List[analyzed templates]        │  │
│   │     ↓ calls for each ↓                                      │  │
│   │     SchemaInferenceEngine.infer_template_definition()      │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  5. Map Assets                                              │  │
│   │     ↓ calls ↓                                               │  │
│   │     AssetRewriter.build_file_map()                          │  │
│   │     AssetRewriter.detect_ambiguous_assets()                │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  6. Collect Warnings                                        │  │
│   │     _collect_warnings() → List[warning strings]            │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  7. Stage Results                                           │  │
│   │     ImportJobRepository.update_result(data)                │  │
│   │     ImportJobRepository.update_status("analyzed")          │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                 │
│                                                                       │
│  ┌──────────────────┐  ┌────────────────────┐  ┌────────────────┐  │
│  │ HeuristicParser  │  │ SchemaInferenceEng │  │ AssetRewriter  │  │
│  ├──────────────────┤  ├────────────────────┤  ├────────────────┤  │
│  │ extract_json()   │  │ infer_schema()     │  │ build_file_map │  │
│  │ _extract_via_*() │  │ _infer_type()      │  │ detect_ambig() │  │
│  │ _looks_like_*()  │  │ generate_render()  │  │ rewrite_html() │  │
│  │ extract_from_*() │  │ compute_signature()│  │ _is_asset()    │  │
│  └──────────────────┘  └────────────────────┘  └────────────────┘  │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                   REPOSITORY LAYER                                   │
│                                                                       │
│               ImportJobRepository                                    │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ create()         - Create new import job                     │ │
│  │ get_by_id()      - Retrieve job by ID                        │ │
│  │ update_status()  - Update job status & progress             │ │
│  │ update_result()  - Store staged data                        │ │
│  │ update_course_id() - Link to course                         │ │
│  │ list_by_status() - Query jobs by status                     │ │
│  │ list_all()       - Get all jobs                             │ │
│  │ delete()         - Delete job                               │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      DATABASE LAYER                                  │
│                                                                       │
│                    import_jobs Table                                 │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ id INT (primary key)                                          │ │
│  │ job_id VARCHAR(36) UNIQUE                                    │ │
│  │ status VARCHAR(50)    [analyzing, analyzed, committed, ...]  │ │
│  │ progress FLOAT         [0.0 to 1.0]                          │ │
│  │ course_id VARCHAR(255) [optional target course]              │ │
│  │ source_file_path VARCHAR(500)                                │ │
│  │ result_data JSON       [staged course data]                  │ │
│  │ error_message TEXT                                           │ │
│  │ created_at DATETIME                                          │ │
│  │ updated_at DATETIME                                          │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Component Interaction Flow

### Component 1: HeuristicParser Interaction

```
Import Analysis Request
    ↓
ImportService._discover_payloads()
    ↓
for each .js file in ZIP:
    ↓
HeuristicParser.extract_json_from_js(js_content)
    ↓
    ├─ Try: _extract_via_ast(js_content)
    │  if pyjsparser available:
    │    ├─ pyjsparser.parse() → AST
    │    ├─ _walk_ast(ast)
    │    ├─ _ast_node_to_python() → Objects
    │    └─ Return payloads
    │
    ├─ Try: _extract_via_regex(js_content)
    │  if no AST results:
    │    ├─ re.finditer() → var assignments
    │    ├─ json.loads() → Parse
    │    └─ Return payloads
    │
    └─ Try: _extract_simple_objects(js_content)
       if no regex results:
         ├─ re.finditer() → {..} patterns
         ├─ _looks_like_course_data() → Filter
         └─ Return payloads
    ↓
Return: List[Dict] or raise ParseError
```

### Component 2: SchemaInferenceEngine Interaction

```
For each extracted template:
    ↓
template_data = {question: "...", options: [...]}
    ↓
SchemaInferenceEngine.infer_template_definition(data, type)
    ↓
    ├─ infer_schema_from_data(data)
    │  ├─ for each key, value in data.items():
    │  │  ├─ _infer_type(value)
    │  │  └─ type → "text"|"url"|"html"|"array"|etc
    │  └─ Return: {type: "object", fields: [...]}
    │
    ├─ compute_schema_signature(schema)
    │  ├─ json.dumps(schema, sort_keys=True)
    │  ├─ hashlib.sha256()
    │  └─ Return: "abc123def456..."
    │
    ├─ generate_render_template(schema, type)
    │  ├─ Build Jinja2 HTML template
    │  └─ Return: "<div class='template-type'>..."
    │
    ├─ generate_field_schema_json(schema)
    │  └─ Return: JSON string
    │
    ├─ generate_schema_json(schema)
    │  └─ Return: JSON string
    │
    └─ Return: {
         template_type: type,
         schema: {...},
         signature: "abc123...",
         render_template: "<div>...",
         field_schema_json: "...",
         schema_json: "...",
         is_active: False,
         created_at: "..."
       }
    ↓
Return: List[complete template definitions]
```

### Component 3: AssetRewriter Interaction

```
After templates analyzed:
    ↓
zip_contents = {path: bytes for all files}
    ↓
AssetRewriter.build_file_map(zip_contents)
    ├─ for each path in zip_contents:
    │  ├─ filename = Path(path).name
    │  ├─ _is_asset(filename) → check extension
    │  └─ if asset: file_map[filename] += path
    ├─ Return: {
         "logo.png": ["images/logo.png"],
         "video.mp4": ["media/video.mp4"],
         ...
       }
    ↓
AssetRewriter.detect_ambiguous_assets(file_map)
    ├─ for each filename, paths in file_map:
    │  ├─ if len(paths) > 1:
    │  │  └─ ambiguous[filename] = paths
    │  └─ Return: ambiguous dict
    ↓
Return: {
  total: number of unique files,
  ambiguous: number with duplicates,
  ambiguous_files: ["logo.png", ...]
}
```

### Component 4: Import Flow

```
ImportService.analyze_package(zip_data, course_id)
    ↓
    ├─ Validate size: len(zip_data) < max_file_size
    │
    ├─ Create job: ImportJobRepository.create()
    │  └─ status = "analyzing", progress = 0.0
    │
    ├─ Extract ZIP: _extract_zip(zip_path)
    │  └─ Returns: {path: bytes} dict
    │
    ├─ Discover payloads: _discover_payloads()
    │  └─ Calls: HeuristicParser.extract_json_from_js()
    │
    ├─ Extract templates: _extract_templates(course_data)
    │  └─ Returns: course_data["templates"]
    │
    ├─ Analyze templates: _analyze_templates(templates)
    │  └─ For each: SchemaInferenceEngine.infer_template_definition()
    │
    ├─ Map assets:
    │  ├─ AssetRewriter.build_file_map(zip_contents)
    │  └─ AssetRewriter.detect_ambiguous_assets()
    │
    ├─ Collect warnings: _collect_warnings(analyzed_templates)
    │  └─ Returns: ["warning1", "warning2", ...]
    │
    ├─ Stage results: ImportJobRepository.update_result()
    │  └─ Stores: {courseId, title, templates, assets, warnings}
    │
    ├─ Update status: ImportJobRepository.update_status()
    │  └─ status = "analyzed", progress = 1.0
    │
    └─ Return: job_id
        ↓
    User polls: GET /api/v1/imports/jobs/{job_id}
        ↓
    Return: {status: "analyzed", course_data: {...}}
        ↓
    User commits: POST /api/v1/imports/jobs/{job_id}/commit
        ↓
    Update status: "committed"
```

---

## 📊 Data Transformation Pipeline

```
Input: SCORM ZIP File
  {
    "imsmanifest.xml": bytes,
    "course.js": bytes,
    "images/logo.png": bytes,
    ...
  }

↓ (extract_json_from_js)

Extracted JSON Objects
  {
    "courseId": "MATH101",
    "title": "Math Basics",
    "templates": [
      {"type": "welcome", "data": {...}},
      {"type": "mcq", "data": {...}}
    ]
  }

↓ (extract_templates)

Template List
  [
    {"type": "welcome", "data": {...}},
    {"type": "mcq", "data": {...}}
  ]

↓ (analyze_templates + infer_template_definition)

Analyzed Templates with Schemas
  [
    {
      "type": "welcome",
      "data": {...},
      "schema": {
        "type": "object",
        "fields": [
          {"name": "text", "type": "text"}
        ]
      },
      "schema_signature": "abc123...",
      "render_template": "<div>...</div>"
    },
    {
      "type": "mcq",
      "data": {...},
      "schema": {
        "type": "object",
        "fields": [
          {"name": "question", "type": "text"},
          {"name": "options", "type": "array[object]"}
        ]
      },
      "schema_signature": "def456...",
      "render_template": "<div>...</div>"
    }
  ]

↓ (build_file_map + detect_ambiguous_assets)

Asset Map
  {
    "total": 3,
    "ambiguous": 0,
    "ambiguous_files": [],
    "files": {
      "logo.png": ["images/logo.png"],
      "video.mp4": ["media/video.mp4"]
    }
  }

↓ (update_result)

Database Staged Data
  import_jobs.result_data = {
    "courseId": "MATH101",
    "title": "Math Basics",
    "templates": [analyzed templates],
    "assets": {asset map},
    "warnings": [...]
  }

↓ (commit_import)

Final Status
  {
    "job_id": "uuid-123",
    "status": "committed",
    "progress": 1.0
  }

↓ (Phase 2 will read this and create actual course)

Ready for Course Creation
```

---

## 🎯 Method Call Graph

```
User Request (Upload ZIP)
    ↓
REST Router: analyze_import()
    ↓
ImportService: analyze_package()
    ├── _extract_zip()
    ├── _discover_payloads()
    │  └─ HeuristicParser.extract_json_from_js()
    │     ├─ _extract_via_ast()
    │     ├─ _extract_via_regex()
    │     └─ _extract_simple_objects()
    ├── _extract_templates()
    ├── _analyze_templates()
    │  └─ SchemaInferenceEngine.infer_template_definition()
    │     ├─ infer_schema_from_data()
    │     │  └─ _infer_type()
    │     ├─ compute_schema_signature()
    │     ├─ generate_render_template()
    │     ├─ generate_field_schema_json()
    │     └─ generate_schema_json()
    ├── AssetRewriter.build_file_map()
    │  └─ _is_asset()
    ├── AssetRewriter.detect_ambiguous_assets()
    ├── _collect_warnings()
    └── ImportJobRepository operations:
        ├─ create()
        ├─ update_result()
        └─ update_status()
    ↓
Return job_id to User
```

---

## 🌐 REST API Call Sequence

```
1. Upload & Analyze
   POST /api/v1/imports/analyze
   ↓ File: SCORM.zip
   ← Response: {job_id: "uuid", status: "analyzing"}

2. Poll Status (user waits a moment)
   GET /api/v1/imports/jobs/uuid
   ← Response: {job_id: "uuid", status: "analyzed", course_data: {...}}

3. Review (optional)
   GET /api/v1/imports/jobs/uuid/preview
   ← Response: same as above

4. Commit
   POST /api/v1/imports/jobs/uuid/commit
   ← Response: {job_id: "uuid", status: "committed"}

5. Phase 2 (later)
   Reads: import_jobs.result_data for job "uuid"
   Creates: Course record with templates
```

---

## 📈 Scalability Pattern

```
Concurrent Imports:

User 1: Upload → Job 1
User 2: Upload → Job 2
User 3: Upload → Job 3

Each job is independent:
├─ Separate temporary directories
├─ Separate database rows
├─ Separate AsyncSession instance
└─ Can run in parallel (async)

Database handles:
├─ concurrent writes (ACID)
├─ separate transactions per job
└─ historical tracking (audit trail)

Result: 100+ concurrent imports without blocking
```

---

## ✅ Summary

**Phase 1 Architecture is:**

1. ✅ **Modular** - Each component has single responsibility
2. ✅ **Scalable** - Async throughout, handles concurrent imports
3. ✅ **Robust** - Multiple fallback strategies
4. ✅ **Extensible** - Easy to add new components
5. ✅ **Database-Backed** - Persistent job tracking
6. ✅ **REST-Driven** - Stateless, API-first
7. ✅ **Safe** - Staging before commit pattern

The design enables flexible, automated SCORM import that works with new template types automatically.

