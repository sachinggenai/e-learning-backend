# AI Authoring Tool Schemas (Claude Tool-Calling Format)

**Date:** 2026-06-13  
**Generated From:** OpenAPI 3.1.0 Spec (`backend/openapi-v3.1-complete.yaml`)  
**Status:** Production Grade  
**Framework:** Claude API Native Tool Calling  

---

## Overview

This document defines the complete set of tools available to the Claude AI course authoring agent. All tools follow Anthropic's [native tool-calling format](https://docs.anthropic.com/claude/reference/messages-api#tools).

**Tool Categories:**
- **Session Management:** Create and manage AI authoring sessions
- **Course Operations:** List, fetch, create, update, delete courses
- **Page Operations:** List, fetch, create, update, delete pages
- **Validation:** Schema validation, business rules, export readiness
- **Retrieval:** RAG-based similar course search
- **File Ingestion:** Analyze PDF/DOCX documents

**Total Tool Count:** 12 core tools

---

## Tool Definitions

### 1. Tool: `create_session`

**Purpose:** Create a new AI authoring session scoped to a single course.

**Implementation Note:** Called once per user interaction. Session manages permission scope and state.

```json
{
  "name": "create_session",
  "description": "Create a new AI course authoring session. Session is scoped to a single course and user. Use this before any other tool calls.",
  "input_schema": {
    "type": "object",
    "properties": {
      "user_id": {
        "type": "string",
        "description": "UUID of the current user"
      },
      "course_id": {
        "type": "string",
        "description": "UUID of the course to author (immutable for this session)"
      },
      "organization_id": {
        "type": "string",
        "description": "UUID of the organization (for multi-tenant scoping)"
      }
    },
    "required": ["user_id", "course_id", "organization_id"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string",
        "description": "Unique session identifier for subsequent tool calls"
      },
      "course_id": {
        "type": "string"
      },
      "user_id": {
        "type": "string"
      },
      "organization_id": {
        "type": "string"
      },
      "created_at": {
        "type": "string",
        "format": "date-time"
      },
      "expires_at": {
        "type": "string",
        "format": "date-time",
        "description": "Session expiry (default 24h)"
      },
      "current_course_state": {
        "type": "object",
        "description": "Current course data (pages, templates, metadata)"
      }
    },
    "required": ["session_id", "course_id", "user_id", "created_at", "expires_at"]
  },
  "idempotent": false,
  "permission_scope": "user_id + organization_id must match authenticated context"
}
```

---

### 2. Tool: `list_pages`

**Purpose:** Fetch all pages in the current course. ALWAYS call this before proposing edits.

```json
{
  "name": "list_pages",
  "description": "List all pages in the current course with metadata. ALWAYS call this before proposing edits to ensure you have the latest state from the database (not from prior conversation turns).",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string",
        "description": "Session ID from create_session"
      }
    },
    "required": ["session_id"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "pages": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "page_id": {
              "type": "string",
              "description": "UUID of the page"
            },
            "title": {
              "type": "string"
            },
            "template_type": {
              "type": "string",
              "enum": [
                "text-content",
                "tabs",
                "accordion",
                "click-reveal",
                "final-assessment"
              ]
            },
            "order": {
              "type": "integer",
              "description": "Zero-based page order"
            },
            "created_at": {
              "type": "string",
              "format": "date-time"
            },
            "updated_at": {
              "type": "string",
              "format": "date-time"
            }
          },
          "required": ["page_id", "title", "template_type", "order"]
        }
      },
      "total_pages": {
        "type": "integer"
      }
    },
    "required": ["pages", "total_pages"]
  },
  "idempotent": true,
  "permission_scope": "session.course_id must match requested course"
}
```

---

### 3. Tool: `fetch_page`

**Purpose:** Fetch a single page with full component data and template details.

```json
{
  "name": "fetch_page",
  "description": "Fetch a single page with full template-specific data. Call this before updating a page to ensure you have current state.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "page_id": {
        "type": "string",
        "description": "UUID of the page to fetch"
      }
    },
    "required": ["session_id", "page_id"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "page_id": {
        "type": "string"
      },
      "title": {
        "type": "string"
      },
      "template_type": {
        "type": "string",
        "enum": [
          "text-content",
          "tabs",
          "accordion",
          "click-reveal",
          "final-assessment"
        ]
      },
      "order": {
        "type": "integer"
      },
      "data": {
        "type": "object",
        "description": "Template-specific data structure (varies by template_type)"
      },
      "created_at": {
        "type": "string",
        "format": "date-time"
      },
      "updated_at": {
        "type": "string",
        "format": "date-time"
      }
    },
    "required": ["page_id", "title", "template_type", "order", "data"]
  },
  "idempotent": true,
  "permission_scope": "page must belong to session.course_id"
}
```

---

### 4. Tool: `propose_create_page`

**Purpose:** Propose a new page (returns preview; no mutation). User must approve before apply.

```json
{
  "name": "propose_create_page",
  "description": "Propose creating a new page. Returns a proposal ID and validation results. Does NOT create the page yet. After user reviews and approves in UI, call apply_page_proposal to actually create.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "title": {
        "type": "string",
        "maxLength": 200,
        "description": "Page title"
      },
      "template_type": {
        "type": "string",
        "enum": [
          "text-content",
          "tabs",
          "accordion",
          "click-reveal",
          "final-assessment"
        ],
        "description": "Only these 5 templates allowed"
      },
      "data": {
        "type": "object",
        "description": "Template-specific data. Must conform to template schema (validated server-side)."
      },
      "insert_at_index": {
        "type": "integer",
        "description": "Optional: 0-based position. Omit to append at end."
      }
    },
    "required": ["session_id", "title", "template_type", "data"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "proposal_id": {
        "type": "string",
        "description": "UUID of this proposal (used with apply_page_proposal)"
      },
      "preview_page": {
        "type": "object",
        "properties": {
          "page_id": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "template_type": {
            "type": "string"
          },
          "data": {
            "type": "object"
          }
        }
      },
      "validation_status": {
        "type": "string",
        "enum": ["valid", "warning", "error"],
        "description": "'valid' = safe to apply; 'warning' = works but may have issues; 'error' = cannot apply"
      },
      "validation_messages": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "severity": {
              "type": "string",
              "enum": ["error", "warning", "info"]
            },
            "field": {
              "type": "string",
              "description": "Field name (e.g., 'data.title', 'data.questions')"
            },
            "message": {
              "type": "string",
              "description": "Human-readable error/warning"
            }
          }
        },
        "description": "Validation issues (if any)"
      }
    },
    "required": ["proposal_id", "preview_page", "validation_status"]
  },
  "idempotent": false,
  "permission_scope": "session.course_id"
}
```

---

### 5. Tool: `apply_page_proposal`

**Purpose:** Apply a proposed page creation (requires explicit user confirmation via UI).

```json
{
  "name": "apply_page_proposal",
  "description": "Apply a proposed page creation. ONLY call after user has reviewed and approved the proposal in the UI. Requires user_confirmed=true to prevent accidental mutations.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "proposal_id": {
        "type": "string",
        "description": "UUID returned from propose_create_page"
      },
      "user_confirmed": {
        "type": "boolean",
        "description": "Must be true. Set only after user approves in UI."
      }
    },
    "required": ["session_id", "proposal_id", "user_confirmed"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "page_id": {
        "type": "string",
        "description": "UUID of created page"
      },
      "status": {
        "type": "string",
        "enum": ["created", "rejected", "error"],
        "description": "'created' = success; 'rejected' = proposal expired; 'error' = other failure"
      },
      "message": {
        "type": "string"
      }
    },
    "required": ["page_id", "status"]
  },
  "idempotent": true,
  "permission_scope": "session.course_id; server validates proposal belongs to session"
}
```

---

### 6. Tool: `propose_update_page`

**Purpose:** Propose changes to an existing page (returns diff; no mutation).

```json
{
  "name": "propose_update_page",
  "description": "Propose updating an existing page. Returns a diff for user review. Does NOT mutate the page yet. Call apply_update_proposal after user approves.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "page_id": {
        "type": "string",
        "description": "UUID of page to update"
      },
      "patch": {
        "type": "object",
        "description": "Partial update. Only include fields you want to change (e.g., { 'title': 'New Title' })",
        "properties": {
          "title": {
            "type": "string"
          },
          "data": {
            "type": "object",
            "description": "Template-specific data (partial or full replacement)"
          }
        }
      }
    },
    "required": ["session_id", "page_id", "patch"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "proposal_id": {
        "type": "string"
      },
      "diff": {
        "type": "object",
        "properties": {
          "before": {
            "type": "object",
            "description": "Original page data"
          },
          "after": {
            "type": "object",
            "description": "Updated page data"
          },
          "changed_fields": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "List of changed fields"
          }
        }
      },
      "validation_status": {
        "type": "string",
        "enum": ["valid", "warning", "error"]
      },
      "validation_messages": {
        "type": "array"
      }
    },
    "required": ["proposal_id", "diff", "validation_status"]
  },
  "idempotent": false,
  "permission_scope": "page must belong to session.course_id"
}
```

---

### 7. Tool: `apply_update_proposal`

**Purpose:** Apply proposed page update (requires user confirmation).

```json
{
  "name": "apply_update_proposal",
  "description": "Apply a proposed page update. ONLY call after user has reviewed and approved the diff in the UI.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "proposal_id": {
        "type": "string"
      },
      "user_confirmed": {
        "type": "boolean"
      }
    },
    "required": ["session_id", "proposal_id", "user_confirmed"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "page_id": {
        "type": "string"
      },
      "status": {
        "type": "string",
        "enum": ["updated", "rejected", "error"]
      },
      "message": {
        "type": "string"
      }
    },
    "required": ["page_id", "status"]
  },
  "idempotent": true,
  "permission_scope": "session.course_id"
}
```

---

### 8. Tool: `propose_delete_page`

**Purpose:** Propose page deletion (requires separate confirmation for destructive ops).

```json
{
  "name": "propose_delete_page",
  "description": "Propose deleting a page. Because deletion is destructive, this requires explicit confirmation via a separate tool call.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "page_id": {
        "type": "string"
      }
    },
    "required": ["session_id", "page_id"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "proposal_id": {
        "type": "string"
      },
      "page_preview": {
        "type": "object",
        "properties": {
          "page_id": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "template_type": {
            "type": "string"
          }
        }
      },
      "confirmation_required": {
        "type": "boolean",
        "description": "Always true (destructive operation)"
      }
    },
    "required": ["proposal_id", "page_preview", "confirmation_required"]
  },
  "idempotent": false,
  "permission_scope": "session.course_id"
}
```

---

### 9. Tool: `confirm_delete_page`

**Purpose:** Confirm destructive delete after user approval in UI modal.

```json
{
  "name": "confirm_delete_page",
  "description": "Confirm page deletion. ONLY call after user has approved in UI confirmation modal.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "proposal_id": {
        "type": "string"
      },
      "user_approved_delete": {
        "type": "boolean",
        "description": "Must be true"
      }
    },
    "required": ["session_id", "proposal_id", "user_approved_delete"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "status": {
        "type": "string",
        "enum": ["deleted", "cancelled", "error"]
      },
      "message": {
        "type": "string"
      }
    },
    "required": ["status"]
  },
  "idempotent": false,
  "permission_scope": "session.course_id"
}
```

---

### 10. Tool: `validate_course`

**Purpose:** Validate entire course against business rules, SCORM, WCAG.

```json
{
  "name": "validate_course",
  "description": "Validate the entire course against schema, business rules, SCORM compliance, and WCAG accessibility requirements. Returns categorized validation results.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "validation_scope": {
        "type": "string",
        "enum": ["schema_only", "business_rules", "scorm_compliance", "accessibility", "full"],
        "description": "'full' = all checks; 'schema_only' = skip business rules"
      }
    },
    "required": ["session_id"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "is_valid": {
        "type": "boolean",
        "description": "true if no errors; may have warnings"
      },
      "errors": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "code": {
              "type": "string",
              "description": "Error code (e.g., 'MISSING_REQUIRED_FIELD')"
            },
            "page_id": {
              "type": "string",
              "description": "Optional: UUID of affected page"
            },
            "field": {
              "type": "string"
            },
            "message": {
              "type": "string"
            },
            "hint": {
              "type": "string",
              "description": "Optional: suggestion for fix"
            }
          }
        }
      },
      "warnings": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "code": {
              "type": "string"
            },
            "page_id": {
              "type": "string"
            },
            "message": {
              "type": "string"
            }
          }
        }
      }
    },
    "required": ["is_valid", "errors", "warnings"]
  },
  "idempotent": true,
  "permission_scope": "session.course_id"
}
```

---

### 11. Tool: `query_similar_courses`

**Purpose:** RAG-based retrieval of similar courses for pedagogical examples and tone references.

```json
{
  "name": "query_similar_courses",
  "description": "Query RAG store for similar courses, pedagogical examples, and style/tone references. Use this to inform content generation with real examples from successful courses.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Query (e.g., 'introductory calculus', 'compliance training tone', 'interactive learning')"
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
        "default": 3,
        "description": "Max results to return"
      },
      "filters": {
        "type": "object",
        "description": "Optional filters",
        "properties": {
          "difficulty_level": {
            "type": "string",
            "enum": ["beginner", "intermediate", "advanced"]
          },
          "topic": {
            "type": "string"
          }
        }
      }
    },
    "required": ["query"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "course_title": {
              "type": "string"
            },
            "course_id": {
              "type": "string"
            },
            "relevance_score": {
              "type": "number",
              "minimum": 0,
              "maximum": 1,
              "description": "1.0 = perfect match; 0.0 = poor match"
            },
            "learning_objective": {
              "type": "string"
            },
            "target_audience": {
              "type": "string"
            },
            "example_pages": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "page_title": {
                    "type": "string"
                  },
                  "template_type": {
                    "type": "string"
                  },
                  "excerpt": {
                    "type": "string",
                    "description": "Sample content (first 200 chars)"
                  }
                }
              },
              "description": "Up to 3 example pages"
            },
            "tone_notes": {
              "type": "string",
              "description": "How this course addresses tone (formal, conversational, etc.)"
            },
            "accessibility_score": {
              "type": "number",
              "description": "0-100: how accessible/compliant"
            }
          }
        }
      }
    },
    "required": ["results"]
  },
  "idempotent": true,
  "permission_scope": "organization-level (no course scope)"
}
```

---

### 12. Tool: `analyze_document_for_import`

**Purpose:** Analyze uploaded PDF/DOCX for document segmentation (file ingestion pipeline).

```json
{
  "name": "analyze_document_for_import",
  "description": "Analyze uploaded PDF/DOCX document for course creation. Returns extracted sections and proposed page breakdown.",
  "input_schema": {
    "type": "object",
    "properties": {
      "session_id": {
        "type": "string"
      },
      "file_url": {
        "type": "string",
        "format": "uri",
        "description": "URL of uploaded file (POST to /api/v1/media/upload first to get file_url)"
      },
      "file_name": {
        "type": "string",
        "description": "Original file name (for logging and reporting)"
      },
      "analysis_type": {
        "type": "string",
        "enum": ["extraction_only", "segmentation_only", "full"],
        "default": "full",
        "description": "'extraction_only' = structure; 'segmentation_only' = templates; 'full' = both"
      }
    },
    "required": ["session_id", "file_url", "file_name"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "job_id": {
        "type": "string",
        "description": "UUID for tracking import job"
      },
      "status": {
        "type": "string",
        "enum": ["success", "partial", "error"],
        "description": "'success' = ready for preview; 'partial' = some sections problematic; 'error' = cannot process"
      },
      "extraction": {
        "type": "object",
        "description": "Extracted document structure (if analysis_type includes extraction)",
        "properties": {
          "filename": {
            "type": "string"
          },
          "total_sections": {
            "type": "integer"
          },
          "sections": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "index": {
                  "type": "integer"
                },
                "heading": {
                  "type": "string"
                },
                "heading_level": {
                  "type": "integer",
                  "description": "1 = H1, 2 = H2, etc."
                },
                "text_content": {
                  "type": "string",
                  "description": "Text (truncated if very long)"
                },
                "tables": {
                  "type": "array",
                  "items": {
                    "type": "object"
                  }
                },
                "images": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                }
              }
            }
          }
        }
      },
      "proposed_pages": {
        "type": "array",
        "description": "Proposed page breakdown (if analysis_type includes segmentation)",
        "items": {
          "type": "object",
          "properties": {
            "page_title": {
              "type": "string"
            },
            "suggested_template": {
              "type": "string",
              "enum": [
                "text-content",
                "tabs",
                "accordion",
                "click-reveal",
                "final-assessment"
              ]
            },
            "source_indices": {
              "type": "array",
              "items": {
                "type": "integer"
              },
              "description": "Section indices that map to this page"
            },
            "rationale": {
              "type": "string"
            }
          }
        }
      },
      "validation_issues": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "severity": {
              "type": "string",
              "enum": ["error", "warning"]
            },
            "message": {
              "type": "string"
            },
            "section_index": {
              "type": "integer"
            }
          }
        },
        "description": "Issues found during analysis (e.g., 'scanned PDF detected')"
      }
    },
    "required": ["job_id", "status"]
  },
  "idempotent": false,
  "permission_scope": "session.course_id"
}
```

---

## Error Response Schema (All Tools)

All tools return errors in consistent shape:

```json
{
  "status": "error",
  "code": "VALIDATION_ERROR | PERMISSION_DENIED | NOT_FOUND | TIMEOUT | RATE_LIMIT | SERVER_ERROR",
  "message": "Human-readable error message",
  "details": {
    "field": "fieldName (optional)",
    "reason": "specific_failure_code (optional)"
  },
  "retryable": true | false,
  "retry_after_seconds": 60
}
```

**Example Validation Error:**
```json
{
  "status": "error",
  "code": "VALIDATION_ERROR",
  "message": "Page title exceeds max length (200 characters)",
  "details": {
    "field": "title",
    "reason": "max_length_exceeded",
    "max": 200,
    "actual": 235
  },
  "retryable": true
}
```

**Example Permission Error:**
```json
{
  "status": "error",
  "code": "PERMISSION_DENIED",
  "message": "Page does not belong to your course",
  "details": {
    "page_id": "abc123",
    "your_course_id": "xyz789",
    "page_course_id": "different456"
  },
  "retryable": false
}
```

---

## Template-Specific Data Schemas

### Text Content Template Data

```json
{
  "title": "string (required, max 200 chars)",
  "content": "string (required, markdown supported)",
  "key_points": ["string (optional, max 5 points)"]
}
```

**Example:**
```json
{
  "title": "Introduction to Machine Learning",
  "content": "Machine learning is a subset of artificial intelligence...",
  "key_points": [
    "ML enables systems to learn from data",
    "Three main types: supervised, unsupervised, reinforcement",
    "Used in recommendation systems, image recognition, etc."
  ]
}
```

### Tabs Template Data

```json
{
  "title": "string (required)",
  "tabs": [
    {
      "title": "string (required, max 50 chars)",
      "content": "string (required)",
      "icon": "string (optional, icon name)"
    }
  ]
}
```

**Validation Rules:**
- Minimum 2 tabs
- Maximum 6 tabs
- Each tab must have title + content

**Example:**
```json
{
  "title": "Compare Cloud Providers",
  "tabs": [
    {
      "title": "AWS",
      "content": "Amazon Web Services is...",
      "icon": "cloud"
    },
    {
      "title": "Azure",
      "content": "Microsoft Azure is...",
      "icon": "cloud"
    }
  ]
}
```

### Accordion Template Data

```json
{
  "title": "string (required)",
  "items": [
    {
      "heading": "string (required)",
      "content": "string (required)",
      "expanded": "boolean (optional, default false)"
    }
  ]
}
```

**Validation Rules:**
- Minimum 2 items
- Maximum 20 items
- All items must have heading + content

**Example:**
```json
{
  "title": "Frequently Asked Questions",
  "items": [
    {
      "heading": "What is the course duration?",
      "content": "The course typically takes 4-6 weeks...",
      "expanded": false
    },
    {
      "heading": "Do I need prerequisites?",
      "content": "You should have basic knowledge of...",
      "expanded": false
    }
  ]
}
```

### Click-to-Reveal Template Data

```json
{
  "title": "string (required)",
  "items": [
    {
      "label": "string (required, max 100 chars)",
      "reveal_content": "string (required, markdown)"
    }
  ]
}
```

**Validation Rules:**
- Minimum 2 items
- Maximum 10 items
- All items must have label + reveal_content

**Example:**
```json
{
  "title": "Key Concepts",
  "items": [
    {
      "label": "Click to reveal: What is API?",
      "reveal_content": "An API (Application Programming Interface) is a set of rules..."
    },
    {
      "label": "Click to reveal: REST vs SOAP",
      "reveal_content": "REST is simpler and more widely used. SOAP is more rigid..."
    }
  ]
}
```

### Final Assessment Template Data

```json
{
  "title": "string (required)",
  "passing_score": "number (required, 0-100)",
  "questions": [
    {
      "question_text": "string (required)",
      "question_type": "multiple_choice | true_false | fill_in | multi_select",
      "options": ["string (required for multiple_choice/multi_select)"],
      "correct_answer": "string or number (required)",
      "explanation": "string (optional but recommended)"
    }
  ]
}
```

**Validation Rules:**
- Minimum 3 questions
- Maximum 50 questions
- Each question must have valid question_type
- passing_score must be 0-100
- All questions must have at least one correct answer
- Multiple_choice/multi_select require 2-5 options

**Example:**
```json
{
  "title": "Module 1 Assessment",
  "passing_score": 70,
  "questions": [
    {
      "question_text": "Which of the following is a benefit of AI?",
      "question_type": "multiple_choice",
      "options": [
        "Increased automation",
        "Better decision making",
        "Cost reduction",
        "All of the above"
      ],
      "correct_answer": "All of the above",
      "explanation": "All three are significant benefits of AI implementation."
    },
    {
      "question_text": "True or False: Machine learning is a subset of AI",
      "question_type": "true_false",
      "correct_answer": "True",
      "explanation": "Machine learning is indeed a subset of AI that focuses on learning from data."
    }
  ]
}
```

---

## Tool Schemas Version Management

**Current Version:** 1.0.0  
**Generated:** 2026-06-13  
**OpenAPI Spec Version:** 3.1.0  

**Version Tracking:**
- Every change to OpenAPI spec → regenerate tool schemas
- Update version string in system prompt
- Deployed to Claude via tool definitions upload
- If LLM confusion: swap to previous version via API

---

## Implementation Notes

### Tool Calling Best Practices

1. **Always call `list_pages` before proposing edits**
   - Ensures you have latest DB state
   - Prevents stale data operations
   - REQUIRED by the system

2. **Use propose-then-apply pattern**
   - propose_* tools never mutate data
   - User reviews diff in UI
   - Only apply_* tools mutate
   - Prevents accidental changes

3. **Handle validation errors gracefully**
   - Validation error returned? Don't retry same call
   - Instead, fix the data based on error message
   - Max 2 automatic retries per proposal

4. **For destructive operations (delete)**
   - propose_delete_page first
   - Wait for UI confirmation
   - confirm_delete_page with user_approved_delete=true

5. **RAG queries are read-only**
   - Never use RAG results as API contracts
   - Use for pedagogical examples only
   - Combine with tool contracts for accuracy

---

*Document Version: 1.0.0*  
*Status: Production Grade*  
*Last Updated: 2026-06-13*
