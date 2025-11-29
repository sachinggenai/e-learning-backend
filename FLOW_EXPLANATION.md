# eLearning Backend Flow: From Input to Output

## Short Overview of the Project
- **What it does**: This is a backend API for an eLearning platform that lets users create courses with different content types (like quizzes, videos, text) and export them as SCORM packages for use in Learning Management Systems (LMS) like Moodle.
- **Main features**: Course creation, validation, template management, SCORM export, media upload.
- **Tech stack**: FastAPI (web framework), SQLAlchemy (database), Pydantic (data validation), Async operations for performance.
- **Purpose**: Helps educators and developers build and share interactive courses easily, without hardcoding content types.
- **Key benefit**: Dynamic templates mean you can add new content types (e.g., a new quiz style) by just updating the database, not the code.

## Big Picture Flow from Input to Output
1. **User/Client sends request**: Via HTTP (e.g., POST to create a course or export SCORM).
2. **FastAPI Router receives**: Matches the URL, validates input data.
3. **Validation happens**: Uses Pydantic models and custom logic to check data.
4. **Service layer processes**: Handles business logic, like generating SCORM files.
5. **Repository layer accesses DB**: Saves or retrieves data from SQLite/PostgreSQL.
6. **Response sent back**: JSON for data, ZIP file for exports.

Layers: API (Routers) → Business Logic (Services) → Data Access (Repositories) → Database.

## Detailed Flow for Create Course Endpoint

### Step 1: Client Sends Request
- User sends POST `/api/v1/courses` with JSON: `{"courseId": "math101", "title": "Math Basics", "data": {...}}`

### Step 2: Router Function Called
- Function: `create_course()` in `app/routers/courses.py`
- What it does: Takes `CourseCreate` payload, gets `CourseRepository` via dependency injection.

### Step 3: Service/Validation (None here, but validation could be added)
- No service called directly; validation is in the Pydantic model.

### Step 4: Repository Function Called
- Function: `repo.create()` in `CourseRepository`
- What it does: Checks if `course_id` already exists in DB; if not, creates `CourseRecord`, adds to session.

### Step 5: DB Actions
- Query: `SELECT` to check existing course.
- Insert: `INSERT` into `courses` table with `course_id`, `title`, `json_data`.
- Commit: Saves changes.

### Step 6: Response Sent
- Returns JSON: `{"courseId": "math101", "title": "Math Basics", ...}` with 201 status.

## Detailed Flow for SCORM Export Endpoint

### Step 1: Client Sends Request
- User sends POST `/api/v1/export` with JSON: `{"course": {...course data...}}`

### Step 2: Router Function Called
- Function: `export_course()` in `app/routers/export.py`
- What it does: Validates course with `validate_course_json()`, calls `scorm_service.generate_scorm_package()`.

### Step 3: Validation Service Called
- Function: `validate_course_json()` in `app/utils/validation.py`
- What it does: Parses JSON to `Course` Pydantic model, checks business rules (e.g., template order).

### Step 4: SCORM Service Function Called
- Function: `generate_scorm_package()` in `SCORMExportService`
- What it does: Validates course, estimates size, creates temp files (manifest, HTML, JS), zips them.

### Step 5: Repository/DB Actions (If needed for persisted courses)
- For persisted courses: `CourseRepository.get_by_course_id()` to fetch data.
- DB Query: `SELECT` from `courses` table.

### Step 6: Final SCORM ZIP Created
- Generates `imsmanifest.xml`, `course_data.js`, `index.html`, etc.
- Zips into buffer.

### Step 7: Response Sent
- Returns ZIP file as download with headers like `Content-Disposition: attachment`.

## How Data Moves Through the System
- **Input**: JSON from client → Pydantic validation → Dict/object.
- **Processing**: Services transform data (e.g., sanitize HTML, generate XML).
- **Storage**: Objects saved as JSON in DB via SQLAlchemy.
- **Output**: DB data → Services generate files → ZIP or JSON response.

## Simple Text Diagram of the Flow
```
[Client/User]
    ↓ (HTTP Request)
[FastAPI Router] (e.g., export_course)
    ↓ (Calls)
[Validation/Utils] (validate_course_json)
    ↓ (Validates)
[Service] (SCORMExportService.generate_scorm_package)
    ↓ (Fetches if needed)
[Repository] (CourseRepository.get_by_course_id)
    ↓ (Queries)
[Database] (SQLite/PostgreSQL)
    ↓ (Returns data)
[Service] (Generates files, zips)
    ↓ (Returns)
[Router] (StreamingResponse)
    ↓ (Sends)
[Client/User] (ZIP Download)
```

## All Main APIs Supported
- **Courses**: POST `/courses` (create), GET `/courses` (list), GET `/courses/{id}` (get), PATCH `/courses/{id}` (update).
- **Export**: POST `/export` (SCORM from JSON), POST `/export/scorm/{course_id}` (from DB).
- **Templates**: GET/POST for template management.
- **Media**: POST `/upload` (upload files).
- **Health**: GET `/health` (status).

All follow similar flow: Router → Validation → Service/Repo → DB → Response.