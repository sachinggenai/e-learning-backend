# 🌐 API Endpoints - cURL Command Reference

Complete reference for all exposed API endpoints with ready-to-use cURL commands.

**Base URL**: `http://localhost:8000`

---

## 📑 Table of Contents

1. [Root & Documentation](#root--documentation)
2. [Health Check Endpoints](#health-check-endpoints)
3. [Course Management (CRUD)](#course-management-crud)
4. [Template Management](#template-management)
5. [Export/SCORM Endpoints](#exportscorm-endpoints)
6. [Media Upload](#media-upload)
7. [Enhanced Templates](#enhanced-templates)
8. [Course Pages & Validation](#course-pages--validation)

---

## 1. Root & Documentation

### Get API Information
```bash
curl -X GET http://localhost:8000/
```

**Response**:
```json
{
  "name": "eLearning Authoring App API",
  "version": "1.0.0",
  "status": "running",
  "environment": "development",
  "timestamp": "2025-11-27T12:00:00.000000",
  "docs": "/docs",
  "health": "/api/v1/health"
}
```

### Access Swagger Documentation
```bash
# Open in browser
open http://localhost:8000/docs

# Or via curl (HTML response)
curl -X GET http://localhost:8000/docs
```

### Access ReDoc Documentation
```bash
# Open in browser
open http://localhost:8000/redoc

# Or via curl
curl -X GET http://localhost:8000/redoc
```

### Get OpenAPI Specification
```bash
curl -X GET http://localhost:8000/openapi.json
```

---

## 2. Health Check Endpoints

### Basic Health Check
```bash
curl -X GET http://localhost:8000/api/v1/health
```

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development",
  "timestamp": "2025-11-27T12:00:00.000000",
  "uptime": 3600.5
}
```

### Detailed Health Check
```bash
curl -X GET http://localhost:8000/api/v1/health/detailed
```

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development",
  "timestamp": "2025-11-27T12:00:00.000000",
  "uptime": 3600.5,
  "components": {
    "validation": {
      "schema_loaded": true,
      "validation_working": true
    },
    "system": {
      "memory_available": true,
      "disk_space": true
    }
  },
  "details": {
    "cors_origins": ["http://localhost:3000"],
    "python_version": "3.11.0",
    "startup_time": "2025-11-27T11:00:00.000000"
  }
}
```

### Readiness Check (Kubernetes-style)
```bash
curl -X GET http://localhost:8000/api/v1/health/ready
```

**Response**:
```json
{
  "status": "ready",
  "timestamp": "2025-11-27T12:00:00.000000"
}
```

### Liveness Check (Kubernetes-style)
```bash
curl -X GET http://localhost:8000/api/v1/health/live
```

**Response**:
```json
{
  "status": "alive",
  "timestamp": "2025-11-27T12:00:00.000000",
  "pid": 12345
}
```

---

## 3. Course Management (CRUD)

### Create Course
```bash
curl -X POST http://localhost:8000/api/v1/courses \
  -H "Content-Type: application/json" \
  -d '{
    "courseId": "COURSE-001",
    "title": "Introduction to Python",
    "description": "Learn Python programming from scratch",
    "data": {
      "author": "John Doe",
      "duration": 120,
      "level": "beginner"
    }
  }'
```

**Response**:
```json
{
  "id": 1,
  "courseId": "COURSE-001",
  "title": "Introduction to Python",
  "status": "draft",
  "description": "Learn Python programming from scratch",
  "createdAt": "2025-11-27T12:00:00.000000",
  "updatedAt": "2025-11-27T12:00:00.000000",
  "data": {
    "author": "John Doe",
    "duration": 120,
    "level": "beginner"
  }
}
```

### List All Courses
```bash
curl -X GET http://localhost:8000/api/v1/courses
```

**Response**:
```json
[
  {
    "id": 1,
    "courseId": "COURSE-001",
    "title": "Introduction to Python",
    "status": "draft",
    "description": "Learn Python programming",
    "createdAt": "2025-11-27T12:00:00.000000",
    "updatedAt": "2025-11-27T12:00:00.000000",
    "data": {}
  }
]
```

### Get Course by ID
```bash
curl -X GET http://localhost:8000/api/v1/courses/COURSE-001
```

**Response**: Same as create response

### Update Course
```bash
curl -X PATCH http://localhost:8000/api/v1/courses/COURSE-001 \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Advanced Python Programming",
    "status": "published",
    "description": "Master advanced Python concepts"
  }'
```

### Delete Course
```bash
curl -X DELETE http://localhost:8000/api/v1/courses/COURSE-001
```

**Response**: `204 No Content`

---

## 4. Template Management

### List Templates for Course
```bash
curl -X GET http://localhost:8000/api/v1/courses/1/templates
```

**Response**:
```json
[
  {
    "id": 1,
    "templateId": "template-001",
    "type": "mcq",
    "title": "Introduction Quiz",
    "order": 0,
    "data": {
      "questions": []
    }
  }
]
```

### Create Template
```bash
curl -X POST http://localhost:8000/api/v1/courses/1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "templateId": "template-001",
    "type": "content-text",
    "title": "Welcome Page",
    "data": {
      "content": "<h1>Welcome to the course!</h1>"
    },
    "order": 0
  }'
```

### Get Template by ID
```bash
curl -X GET http://localhost:8000/api/v1/courses/1/templates/1
```

### Update Template
```bash
curl -X PATCH http://localhost:8000/api/v1/courses/1/templates/1 \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated Welcome Page",
    "data": {
      "content": "<h1>Welcome! Updated content</h1>"
    }
  }'
```

### Reorder Templates
```bash
curl -X POST http://localhost:8000/api/v1/courses/1/templates/reorder \
  -H "Content-Type: application/json" \
  -d '{
    "orderedIds": [3, 1, 2]
  }'
```

### Delete Template
```bash
curl -X DELETE http://localhost:8000/api/v1/courses/1/templates/1
```

**Response**: `204 No Content`

---

## 5. Export/SCORM Endpoints

### Export Course as SCORM Package (JSON Payload)
```bash
curl -X POST http://localhost:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -d '{
    "course": "{\"courseId\":\"test-course\",\"title\":\"Test Course\",\"author\":\"Test Author\",\"templates\":[{\"id\":\"t1\",\"type\":\"welcome\",\"title\":\"Welcome\",\"order\":0,\"data\":{\"content\":\"Welcome!\"}}],\"assets\":[]}"
  }' \
  --output course_export.zip
```

### Validate Course for Export
```bash
curl -X POST http://localhost:8000/api/v1/export/validate \
  -H "Content-Type: application/json" \
  -d '{
    "course": "{\"courseId\":\"test-course\",\"title\":\"Test Course\",\"author\":\"Test Author\",\"templates\":[{\"id\":\"t1\",\"type\":\"welcome\",\"title\":\"Welcome\",\"order\":0,\"data\":{\"content\":\"Welcome!\"}}],\"assets\":[]}"
  }'
```

**Response**:
```json
{
  "success": true,
  "message": "Course data is valid for export",
  "course_info": {
    "courseId": "test-course",
    "title": "Test Course",
    "author": "Test Author",
    "template_count": 1,
    "asset_count": 0
  },
  "validation": {
    "templates_valid": true,
    "structure_valid": true
  },
  "estimated_size": 1024000,
  "timestamp": "2025-11-27T12:00:00.000000"
}
```

### Get Supported Export Formats
```bash
curl -X GET http://localhost:8000/api/v1/export/formats
```

**Response**:
```json
{
  "success": true,
  "formats": [
    {
      "id": "scorm_1_2",
      "name": "SCORM 1.2",
      "description": "SCORM 1.2 compliant package",
      "file_extension": ".zip",
      "supported": true,
      "features": [
        "Basic manifest generation",
        "Simple HTML player",
        "Course structure preservation",
        "Asset bundling"
      ]
    }
  ],
  "timestamp": "2025-11-27T12:00:00.000000"
}
```

### Export Persisted Course as SCORM
```bash
curl -X POST http://localhost:8000/api/v1/export/scorm/1 \
  -H "Content-Type: application/json" \
  -d '{
    "format": "scorm1.2",
    "include_media": true
  }' \
  --output persisted_course_export.zip
```

### Get Export Status (Async)
```bash
curl -X GET http://localhost:8000/api/v1/export/status/export-123
```

**Response**:
```json
{
  "success": true,
  "export_id": "export-123",
  "status": "completed",
  "message": "Export operations are synchronous in Phase 1",
  "timestamp": "2025-11-27T12:00:00.000000"
}
```

---

## 6. Media Upload

### Upload Media File (Global)
```bash
curl -X POST http://localhost:8000/api/v1/media/upload \
  -F "file=@/path/to/image.jpg" \
  -F "category=image"
```

**Response**:
```json
{
  "success": true,
  "file_id": "uuid-string",
  "filename": "image.jpg",
  "media_type": "image",
  "size": 102400,
  "url": "/api/v1/media/global/image/uuid-string.jpg",
  "uploaded_at": "2025-11-27T12:00:00.000000"
}
```

### Upload Media for Specific Course
```bash
curl -X POST "http://localhost:8000/api/v1/media/upload?course_id=COURSE-001" \
  -F "file=@/path/to/video.mp4" \
  -F "category=video"
```

### Get Media File
```bash
curl -X GET http://localhost:8000/api/v1/media/global/image/uuid-string.jpg \
  --output downloaded_image.jpg
```

### List Course Media
```bash
curl -X GET "http://localhost:8000/api/v1/media/list?course_id=COURSE-001"
```

**Response**:
```json
{
  "success": true,
  "media": [
    {
      "file_id": "uuid-1",
      "filename": "image.jpg",
      "media_type": "image",
      "size": 102400,
      "url": "/api/v1/media/COURSE-001/image/uuid-1.jpg",
      "uploaded_at": "2025-11-27T12:00:00.000000"
    }
  ],
  "total_count": 1,
  "total_size": 102400
}
```

### Delete Media File
```bash
curl -X DELETE http://localhost:8000/api/v1/media/global/image/uuid-string.jpg
```

**Response**:
```json
{
  "success": true,
  "message": "Media file deleted successfully"
}
```

---

## 7. Enhanced Templates

### Get Template Categories
```bash
curl -X GET http://localhost:8000/api/v1/templates/enhanced/categories
```

**Response**:
```json
[
  {
    "id": "assessments",
    "name": "Assessments",
    "description": "Quizzes, tests, and evaluation templates",
    "color": "#FF6B6B",
    "icon": "quiz",
    "templateCount": 15,
    "subcategories": ["quiz", "test", "survey", "poll"]
  }
]
```

### Get Categories with Stats
```bash
curl -X GET "http://localhost:8000/api/v1/templates/enhanced/categories?include_stats=true"
```

### Search Templates
```bash
curl -X GET "http://localhost:8000/api/v1/templates/enhanced/search?query=quiz&category=assessments"
```

### Get Template by ID
```bash
curl -X GET http://localhost:8000/api/v1/templates/enhanced/quiz_basic_001
```

### Get Template Fields
```bash
curl -X GET http://localhost:8000/api/v1/templates/enhanced/quiz_basic_001/fields
```

### Preview Template
```bash
curl -X POST http://localhost:8000/api/v1/templates/enhanced/quiz_basic_001/preview \
  -H "Content-Type: application/json" \
  -d '{
    "field_values": {
      "question": "What is 2+2?",
      "options": ["3", "4", "5"]
    }
  }'
```

### Validate Template Data
```bash
curl -X POST http://localhost:8000/api/v1/templates/enhanced/quiz_basic_001/validate \
  -H "Content-Type: application/json" \
  -d '{
    "field_values": {
      "question": "What is Python?"
    }
  }'
```

---

## 8. Course Pages & Validation

### Get Available Templates for Pages
```bash
curl -X GET http://localhost:8000/api/v1/templates/available
```

**Response**:
```json
{
  "templates": [
    {
      "id": 1,
      "templateId": "template_intro_001",
      "type": "introduction",
      "title": "Course Introduction",
      "order": 0,
      "data": {
        "content": {},
        "description": "Welcome page with course overview"
      }
    }
  ],
  "categories": ["introduction", "lab", "assessment"],
  "total_count": 3
}
```

### Filter Templates by Category
```bash
curl -X GET "http://localhost:8000/api/v1/templates/available?category=assessment&sort_by=rating"
```

### Search Templates
```bash
curl -X GET "http://localhost:8000/api/v1/templates/available?search=quiz"
```

### Get Course Pages
```bash
curl -X GET http://localhost:8000/api/v1/courses/COURSE-001/pages
```

**Response**:
```json
[
  {
    "id": "page_COURSE-001_1",
    "course_id": "COURSE-001",
    "title": "Welcome Page",
    "type": "content-text",
    "content": {},
    "template_id": "template_intro_001",
    "page_order": 1,
    "is_published": true,
    "created_at": "2025-11-27T12:00:00.000000",
    "updated_at": "2025-11-27T12:00:00.000000"
  }
]
```

### Create Page from Template
```bash
curl -X POST http://localhost:8000/api/v1/courses/COURSE-001/pages/from-template \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "template_intro_001",
    "page_title": "Course Introduction",
    "customizations": {
      "courseTitle": "Introduction to Python",
      "welcomeMessage": "Welcome to the course!"
    },
    "page_order": 1
  }'
```

**Response**:
```json
{
  "page": {
    "id": "page_COURSE-001_1",
    "course_id": "COURSE-001",
    "title": "Course Introduction",
    "type": "content-text",
    "content": {
      "template_id": "template_intro_001",
      "template_name": "Course Introduction",
      "fields": {
        "courseTitle": "Introduction to Python",
        "welcomeMessage": "Welcome to the course!"
      },
      "generated_at": "2025-11-27T12:00:00.000000"
    },
    "template_id": "template_intro_001",
    "page_order": 1,
    "is_published": true,
    "created_at": "2025-11-27T12:00:00.000000",
    "updated_at": "2025-11-27T12:00:00.000000"
  },
  "message": "Page added successfully from template"
}
```

### Validate Course Data
```bash
curl -X POST http://localhost:8000/api/v1/courses/validate \
  -H "Content-Type: application/json" \
  -d '{
    "courseData": {
      "courseId": "COURSE-001",
      "title": "Test Course",
      "pages": [
        {
          "id": "page1",
          "title": "Welcome",
          "templateType": "welcome",
          "content": {
            "title": "Welcome to the course"
          }
        },
        {
          "id": "page2",
          "title": "Quiz",
          "templateType": "mcq",
          "content": {
            "question": "What is 2+2?",
            "options": ["3", "4", "5"],
            "correctAnswer": 1
          }
        }
      ]
    }
  }'
```

**Response**:
```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "timestamp": "2025-11-27T12:00:00.000000"
}
```

### Validation with Errors Example
```bash
curl -X POST http://localhost:8000/api/v1/courses/validate \
  -H "Content-Type: application/json" \
  -d '{
    "courseData": {
      "courseId": "COURSE-001",
      "pages": [
        {
          "id": "page1",
          "templateType": "mcq",
          "content": {
            "options": ["Option 1"]
          }
        }
      ]
    }
  }'
```

**Response**:
```json
{
  "valid": false,
  "errors": [
    {
      "id": "missing-title",
      "field": "title",
      "category": "schema",
      "message": "Required field 'title' is missing",
      "level": "error"
    },
    {
      "id": "page-0-missing-title",
      "field": "pages[0].title",
      "category": "schema",
      "message": "Page 1 missing required 'title' field",
      "level": "error"
    },
    {
      "id": "page-0-mcq-no-question",
      "field": "pages[0].content.question",
      "category": "business",
      "message": "MCQ page 1 must have a question",
      "level": "error"
    },
    {
      "id": "page-0-mcq-insufficient-options",
      "field": "pages[0].content.options",
      "category": "business",
      "message": "MCQ page 1 must have at least 2 options",
      "level": "error"
    }
  ],
  "warnings": [],
  "timestamp": "2025-11-27T12:00:00.000000"
}
```

---

## 🔧 Advanced Usage Examples

### Complete Course Creation Flow

```bash
# 1. Create course
COURSE_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/courses \
  -H "Content-Type: application/json" \
  -d '{
    "courseId": "PYTHON-101",
    "title": "Python Programming 101",
    "description": "Complete Python course"
  }')

# Extract course ID
COURSE_ID=$(echo $COURSE_RESPONSE | jq -r '.id')

# 2. Create welcome template
curl -X POST http://localhost:8000/api/v1/courses/$COURSE_ID/templates \
  -H "Content-Type: application/json" \
  -d '{
    "templateId": "welcome-001",
    "type": "welcome",
    "title": "Welcome to Python 101",
    "order": 0,
    "data": {
      "content": "<h1>Welcome!</h1><p>Let'\''s learn Python together.</p>"
    }
  }'

# 3. Create quiz template
curl -X POST http://localhost:8000/api/v1/courses/$COURSE_ID/templates \
  -H "Content-Type: application/json" \
  -d '{
    "templateId": "quiz-001",
    "type": "mcq",
    "title": "Python Basics Quiz",
    "order": 1,
    "data": {
      "questions": [
        {
          "id": "q1",
          "question": "What is Python?",
          "options": [
            {"id": "opt1", "text": "A programming language", "isCorrect": true},
            {"id": "opt2", "text": "A snake", "isCorrect": false}
          ]
        }
      ]
    }
  }'

# 4. Export as SCORM
curl -X POST http://localhost:8000/api/v1/export/scorm/$COURSE_ID \
  -H "Content-Type: application/json" \
  -d '{
    "format": "scorm1.2",
    "include_media": true
  }' \
  --output python101_scorm.zip
```

### Batch Operations with jq

```bash
# Get all course IDs
curl -s http://localhost:8000/api/v1/courses | jq -r '.[].courseId'

# Count templates per course
for id in $(curl -s http://localhost:8000/api/v1/courses | jq -r '.[].id'); do
  count=$(curl -s http://localhost:8000/api/v1/courses/$id/templates | jq 'length')
  echo "Course $id: $count templates"
done

# Export all courses
for id in $(curl -s http://localhost:8000/api/v1/courses | jq -r '.[].id'); do
  curl -X POST http://localhost:8000/api/v1/export/scorm/$id \
    -H "Content-Type: application/json" \
    -d '{"format": "scorm1.2"}' \
    --output "course_${id}_export.zip"
done
```

---

## 📝 Notes

### Authentication
Currently, the API does not require authentication. In production, you would add:

```bash
curl -X GET http://localhost:8000/api/v1/courses \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Error Responses
All endpoints return consistent error formats:

```json
{
  "success": false,
  "error": "Error message",
  "timestamp": "2025-11-27T12:00:00.000000",
  "path": "/api/v1/courses"
}
```

### Common HTTP Status Codes
- `200 OK` - Success
- `201 Created` - Resource created
- `204 No Content` - Success with no body
- `400 Bad Request` - Invalid input
- `404 Not Found` - Resource not found
- `422 Unprocessable Entity` - Validation error
- `500 Internal Server Error` - Server error

### CORS Headers
If calling from a browser/frontend, ensure CORS is configured:

```bash
# Check CORS headers
curl -X OPTIONS http://localhost:8000/api/v1/health \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -v
```

---

## 🚀 Testing Tips

### Save responses to files
```bash
curl -X GET http://localhost:8000/api/v1/courses \
  --output courses.json
```

### Pretty print JSON responses
```bash
curl -s http://localhost:8000/api/v1/health | jq '.'
```

### Include headers in output
```bash
curl -i http://localhost:8000/api/v1/health
```

### Show only HTTP status code
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health
```

### Measure response time
```bash
curl -s -o /dev/null -w "Time: %{time_total}s\n" http://localhost:8000/api/v1/health
```

---

**Generated**: November 27, 2025  
**API Version**: 1.0.0  
**Base URL**: http://localhost:8000
