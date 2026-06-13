# E2E Test Case Templates (Production Grade)

**Date:** 2026-06-13  
**Status:** Production Specification  
**Test Framework:** Playwright + Cypress  
**Coverage:** Chunks 0–2 functionality + edge cases  

---

## Overview

This document provides **templates and examples** for end-to-end test cases. QA teams use these templates to:
1. Execute manual tests
2. Automate tests via Cypress/Playwright
3. Validate each chunk before sign-off
4. Regression-test after deployments

**Test Naming Convention:** `TC-CH{chunk}-{test-type}-{variant}`
- Example: `TC-CH0-FEATURE_FLAG-DISABLED` = Test that feature flag, when disabled, hides AI button

---

## Test Case Template

```
Test ID: TC-CH{chunk}-{category}-{number}
Title: {Human-readable title}
Severity: {Critical|High|Medium|Low}
Duration: {5 min | 15 min | 30 min}
Prerequisites: {Environment setup, user account, data required}

Setup:
  - {Step 1}
  - {Step 2}
  ...

Steps:
  1. {Action}
  2. {Action}
  3. {Verification}
  ...

Expected Result:
  - {What should happen}
  - {UI state after completion}

Edge Cases / Variations:
  - {Alternative scenario 1}
  - {Alternative scenario 2}

Automation Script: {Cypress/Playwright code or link}

Post-Test Cleanup:
  - {Remove test data}
  - {Reset state}
```

---

## Chunk 0 Test Cases

### TC-CH0-FEATURE_FLAG-DISABLED

**Title:** Feature flag disabled hides AI button  
**Severity:** Critical  
**Duration:** 5 minutes

**Prerequisites:**
- Feature flag `AI_AUTHORING_ENABLED` set to `false` in `.env`
- Backend deployed and running
- Logged in as `teacher@example.com`

**Setup:**
```bash
export AI_AUTHORING_ENABLED=false
docker restart api  # or: restart backend service
```

**Steps:**
1. Navigate to `/dashboard`
2. Locate "Create Course" section
3. Observe buttons/menu items displayed
4. Check network requests (DevTools → Network tab)

**Expected Result:**
- ✅ "Create Course" button visible
- ✅ "✨ Build with AI" button NOT visible (hidden)
- ✅ UI layout unchanged from before
- ✅ No console errors
- ✅ Feature check GET request succeeded

**Edge Cases:**
- User navigates directly to `/ai/create` → should redirect to `/dashboard`
- User with browser cache → should still not show AI button

**Automation Script:**
```typescript
// cypress/e2e/chunk0-feature-flag-disabled.cy.ts
describe("Chunk 0: Feature Flag Disabled", () => {
  beforeEach(() => {
    cy.visit("/dashboard");
    cy.loginAs("teacher@example.com");
  });

  it("TC-CH0-FEATURE_FLAG-DISABLED: AI button hidden", () => {
    cy.get("button:contains('Create Course')").should("be.visible");
    cy.get("button:contains('✨ Build with AI')").should("not.exist");
    
    // Verify no errors
    cy.task("log", "Checking console for errors...");
    cy.window().then((win) => {
      const logs = (win as any).__loggedErrors || [];
      expect(logs).to.be.empty;
    });
  });
});
```

**Post-Test Cleanup:**
```bash
# None required; feature flag reverts on restart
```

---

### TC-CH0-FEATURE_FLAG-ENABLED

**Title:** Feature flag enabled shows AI button  
**Severity:** Critical  
**Duration:** 5 minutes

**Prerequisites:**
- Feature flag `AI_AUTHORING_ENABLED` set to `true` in `.env`
- Backend restarted after flag change
- Logged in as `teacher@example.com`

**Setup:**
```bash
export AI_AUTHORING_ENABLED=true
docker restart api
```

**Steps:**
1. Navigate to `/dashboard`
2. Observe "Create Course" menu
3. Count buttons/menu items

**Expected Result:**
- ✅ "Create Course" button visible
- ✅ "✨ Build with AI" button visible and clickable
- ✅ Both buttons functional (not disabled)

**Edge Cases:**
- AI button disabled while loading → should enable after load
- Feature flag changed after page load → should refresh automatically

**Automation Script:**
```typescript
// cypress/e2e/chunk0-feature-flag-enabled.cy.ts
describe("Chunk 0: Feature Flag Enabled", () => {
  beforeEach(() => {
    cy.visit("/dashboard");
    cy.loginAs("teacher@example.com");
  });

  it("TC-CH0-FEATURE_FLAG-ENABLED: AI button visible", () => {
    cy.get("button:contains('✨ Build with AI')").should("be.visible");
    cy.get("button:contains('✨ Build with AI')").should("not.be.disabled");
  });

  it("TC-CH0-FEATURE_FLAG-ENABLED: AI button clickable", () => {
    cy.get("button:contains('✨ Build with AI')").click();
    // Should navigate to AI chat panel or modal
    cy.url().should("include", "/ai/create");
  });
});
```

---

### TC-CH0-MANUAL_CREATE-REGRESSION

**Title:** Manual course creation unchanged (regression)  
**Severity:** Critical  
**Duration:** 15 minutes

**Prerequisites:**
- Feature flag `AI_AUTHORING_ENABLED` can be true or false
- Logged in as `teacher@example.com`
- Empty course list

**Setup:**
```bash
# Delete any test courses from previous runs
curl -X DELETE http://localhost:8000/api/v1/courses/test-course-xyz \
  -H "Authorization: Bearer $(get_auth_token)"
```

**Steps:**
1. Navigate to `/dashboard`
2. Click "Create Course"
3. Fill in form: Title = "Regression Test Course", Description = "Testing..."
4. Add page: Title = "Page 1", Template = "text-content"
5. Fill template: Title = "Intro", Content = "Learn this topic"
6. Save page
7. Save course
8. Navigate to course
9. Edit page (change title to "Intro (Edited)")
10. Save
11. Preview course
12. Export as SCORM

**Expected Result:**
- ✅ Course created successfully
- ✅ Page added with correct template
- ✅ Page edited and saved
- ✅ Preview renders correctly
- ✅ SCORM export succeeds and is valid

**Edge Cases:**
- Create course with special characters in title → should sanitize
- Add max pages (e.g., 100) → should handle gracefully
- Create duplicate course names → should allow or warn user

**Automation Script:**
```typescript
// cypress/e2e/chunk0-manual-regression.cy.ts
describe("Chunk 0: Manual Course Creation (Regression)", () => {
  const courseTitle = `Regression Test ${Date.now()}`;

  it("TC-CH0-MANUAL_CREATE-REGRESSION: Full flow", () => {
    cy.visit("/dashboard");
    cy.loginAs("teacher@example.com");

    // Create course
    cy.contains("button", "Create Course").click();
    cy.get("input[name='courseTitle']").type(courseTitle);
    cy.get("textarea[name='courseDescription']").type("Testing manual flow");
    cy.contains("button", "Continue").click();

    // Add page
    cy.contains("button", "Add Page").click();
    cy.get("input[name='pageTitle']").type("Page 1");
    cy.contains("button", "text-content").click();

    // Fill template
    cy.get("input[name='title']").type("Intro");
    cy.get("textarea[name='content']").type("Learn this topic");
    cy.contains("button", "Save").click();

    // Save course
    cy.contains("button", "Save Course").click();

    // Verify created
    cy.contains(courseTitle).should("be.visible");
    
    // Navigate to course
    cy.contains(courseTitle).click();
    cy.url().should("include", "/courses/");

    // Edit page
    cy.contains("Page 1").click();
    cy.get("input[name='title']").clear().type("Intro (Edited)");
    cy.contains("button", "Save").click();
    
    // Verify updated
    cy.contains("Intro (Edited)").should("be.visible");

    // Preview
    cy.contains("button", "Preview").click();
    cy.contains("Intro (Edited)").should("be.visible");
    cy.contains("Learn this topic").should("be.visible");

    // Export SCORM
    cy.contains("button", "Export").click();
    cy.contains("button", "SCORM 2004").click();
    cy.task("checkFileWasDownloaded", `${courseTitle}.zip`);
  });
});
```

**Post-Test Cleanup:**
```bash
curl -X DELETE http://localhost:8000/api/v1/courses/[course-id] \
  -H "Authorization: Bearer $(get_auth_token)"
```

---

### TC-CH0-ENV_CONFIG-LOADS

**Title:** Environment config loads correctly  
**Severity:** High  
**Duration:** 5 minutes

**Prerequisites:**
- Backend server running
- `.env` file with all required variables

**Steps:**
1. Make request to `/api/v1/health` (or any endpoint)
2. Check logs for startup messages
3. Query `/api/v1/config/status` (if endpoint exists)

**Expected Result:**
- ✅ Server starts without errors
- ✅ Logs show model names, timeouts loaded
- ✅ Config is valid (no parsing errors)

**Automation Script:**
```python
# tests/test_chunk0_config.py
def test_config_loads():
    from app.config import settings
    assert settings.AI_PRIMARY_MODEL is not None
    assert settings.AI_FALLBACK_MODEL is not None
    assert settings.AI_RATE_LIMIT_CALLS_PER_HOUR > 0
    assert 0 < settings.AI_REQUEST_TIMEOUT_SECONDS < 300

def test_config_defaults():
    assert settings.AI_AUTHORING_ENABLED == False  # Default off
    assert settings.AI_MAX_RETRIES >= 0
```

---

## Chunk 1 Test Cases

### TC-CH1-TEMPLATE_REGISTRY-LOADED

**Title:** Template registry loads all 5 templates  
**Severity:** Critical  
**Duration:** 10 minutes

**Prerequisites:**
- Chunk 0 deployed and working
- Backend running

**Setup:**
```bash
# None required
```

**Steps:**
1. Query `/api/v1/ai/templates/allowed`
2. Parse response JSON
3. Count templates returned
4. Verify each template has required fields

**Expected Result:**
- ✅ Response status 200
- ✅ 5 templates returned: `text-content`, `tabs`, `accordion`, `click-reveal`, `final-assessment`
- ✅ Each template has: `displayName`, `description`, `schema`, `minItems`, `maxItems`
- ✅ Schema is valid JSON Schema

**Edge Cases:**
- Call with invalid Accept header → should still return JSON
- Call with auth error → should return 401

**Automation Script:**
```typescript
// cypress/e2e/chunk1-template-registry.cy.ts
describe("Chunk 1: Template Registry", () => {
  it("TC-CH1-TEMPLATE_REGISTRY-LOADED: All templates present", () => {
    cy.request("/api/v1/ai/templates/allowed").then((response) => {
      expect(response.status).to.eq(200);
      const templates = response.body.allowed;
      expect(templates).to.have.length(5);
      expect(templates).to.include.members([
        "text-content",
        "tabs",
        "accordion",
        "click-reveal",
        "final-assessment",
      ]);
    });
  });

  it("TC-CH1-TEMPLATE_REGISTRY-LOADED: Schemas valid", () => {
    cy.request("/api/v1/ai/templates/registry").then((response) => {
      const templates = response.body.templates;
      Object.values(templates).forEach((template: any) => {
        expect(template).to.have.all.keys(
          "displayName",
          "description",
          "category",
          "requiredFields",
          "optionalFields",
          "schema",
          "minItems",
          "maxItems",
          "complexity",
          "bestFor"
        );
        expect(template.schema).to.have.property("type", "object");
      });
    });
  });
});
```

---

### TC-CH1-VALIDATOR-ACCEPTS-VALID

**Title:** Validator accepts valid template data  
**Severity:** High  
**Duration:** 15 minutes

**Prerequisites:**
- Chunk 1 deployed
- Backend running

**Setup:**
```bash
# None required
```

**Steps:**
1. Prepare valid `tabs` template data:
   ```json
   {
     "title": "Compare",
     "tabs": [
       {"title": "Option A", "content": "Details A"},
       {"title": "Option B", "content": "Details B"}
     ]
   }
   ```
2. POST to `/api/v1/ai/templates/validate?template_type=tabs` with data
3. Parse response

**Expected Result:**
- ✅ Status 200
- ✅ `isValid: true`
- ✅ `validationStatus: "valid"`
- ✅ `messages: []` (empty)

**Edge Cases:**
- Valid with optional fields → should still be valid
- Valid with extra unknown fields → should ignore or warn

**Automation Script:**
```typescript
// cypress/e2e/chunk1-validator-valid.cy.ts
describe("Chunk 1: Validator", () => {
  it("TC-CH1-VALIDATOR-ACCEPTS-VALID: Tabs template valid", () => {
    const validTabs = {
      title: "Compare",
      tabs: [
        { title: "Option A", content: "Details A" },
        { title: "Option B", content: "Details B" },
      ],
    };

    cy.request("POST", "/api/v1/ai/templates/validate", {
      template_type: "tabs",
      data: validTabs,
    }).then((response) => {
      expect(response.status).to.eq(200);
      expect(response.body.isValid).to.be.true;
      expect(response.body.validationStatus).to.eq("valid");
      expect(response.body.messages).to.be.empty;
    });
  });

  it("TC-CH1-VALIDATOR-ACCEPTS-VALID: Text-content template valid", () => {
    const validText = {
      title: "Introduction",
      content: "Welcome to the course...",
      key_points: ["Point 1", "Point 2"],
    };

    cy.request("POST", "/api/v1/ai/templates/validate", {
      template_type: "text-content",
      data: validText,
    }).then((response) => {
      expect(response.body.isValid).to.be.true;
    });
  });
});
```

---

### TC-CH1-VALIDATOR-REJECTS-INVALID

**Title:** Validator rejects invalid template data  
**Severity:** High  
**Duration:** 15 minutes

**Prerequisites:**
- Chunk 1 deployed

**Setup:**
```bash
# None required
```

**Steps:**

#### Variation A: Missing required field
```json
{
  "tabs": [
    {"title": "Option A", "content": "Details A"}
  ]
  // Missing "title"
}
```

#### Variation B: Insufficient items
```json
{
  "title": "Only One Tab",
  "tabs": [
    {"title": "Option A", "content": "Details A"}
    // Only 1 item; need min 2
  ]
}
```

#### Variation C: Wrong type
```json
{
  "title": "Bad",
  "tabs": "not-an-array"  // Should be array
}
```

**Expected Result (All Variations):**
- ✅ Status 200 (validation response, not HTTP error)
- ✅ `isValid: false`
- ✅ `validationStatus: "error"`
- ✅ `messages` array contains 1+ errors
- ✅ Each error has: `severity`, `field`, `message`

**Automation Script:**
```typescript
describe("Chunk 1: Validator Rejects Invalid", () => {
  it("TC-CH1-VALIDATOR-REJECTS-INVALID: Missing required field", () => {
    const invalidTabs = {
      tabs: [
        { title: "Option A", content: "Details A" },
        { title: "Option B", content: "Details B" },
      ],
      // Missing "title"
    };

    cy.request("POST", "/api/v1/ai/templates/validate", {
      template_type: "tabs",
      data: invalidTabs,
    }).then((response) => {
      expect(response.body.isValid).to.be.false;
      expect(response.body.messages).to.have.length.greaterThan(0);
      expect(response.body.messages[0]).to.have.keys("severity", "field", "message");
    });
  });

  it("TC-CH1-VALIDATOR-REJECTS-INVALID: Too few items", () => {
    const invalidTabs = {
      title: "Only One",
      tabs: [{ title: "A", content: "Content A" }], // Need 2
    };

    cy.request("POST", "/api/v1/ai/templates/validate", {
      template_type: "tabs",
      data: invalidTabs,
    }).then((response) => {
      expect(response.body.isValid).to.be.false;
      const messages = response.body.messages;
      const itemsError = messages.find((m: any) => m.field === "tabs");
      expect(itemsError).to.exist;
      expect(itemsError.message).to.include("2-6");
    });
  });
});
```

---

### TC-CH1-ASSESSMENT-VALIDATOR

**Title:** Assessment template has special validation (min 3 questions, etc.)  
**Severity:** High  
**Duration:** 10 minutes

**Prerequisites:**
- Chunk 1 deployed

**Setup:**
```bash
# None required
```

**Steps:**

#### Variation A: Too few questions (only 2)
```json
{
  "title": "Quiz",
  "passing_score": 70,
  "questions": [
    {"question_text": "Q1?", "question_type": "true_false", "correct_answer": "True"},
    {"question_text": "Q2?", "question_type": "true_false", "correct_answer": "False"}
  ]
}
```

**Expected Result:**
- ✅ `isValid: false`
- ✅ Message mentions "at least 3 questions"

#### Variation B: Valid assessment (3 questions)
```json
{
  "title": "Quiz",
  "passing_score": 70,
  "questions": [
    {"question_text": "Q1?", "question_type": "true_false", "correct_answer": "True"},
    {"question_text": "Q2?", "question_type": "true_false", "correct_answer": "False"},
    {"question_text": "Q3?", "question_type": "true_false", "correct_answer": "True"}
  ]
}
```

**Expected Result:**
- ✅ `isValid: true`

**Automation Script:**
```typescript
describe("Chunk 1: Assessment Validator", () => {
  it("TC-CH1-ASSESSMENT-VALIDATOR: Rejects < 3 questions", () => {
    const tooFew = {
      title: "Quiz",
      passing_score: 70,
      questions: [
        { question_text: "Q1?", question_type: "true_false", correct_answer: "True" },
        { question_text: "Q2?", question_type: "true_false", correct_answer: "False" },
      ],
    };

    cy.request("POST", "/api/v1/ai/templates/validate", {
      template_type: "final-assessment",
      data: tooFew,
    }).then((response) => {
      expect(response.body.isValid).to.be.false;
      const msg = response.body.messages[0].message;
      expect(msg).to.include("3");
    });
  });

  it("TC-CH1-ASSESSMENT-VALIDATOR: Accepts 3+ questions", () => {
    const valid = {
      title: "Quiz",
      passing_score: 70,
      questions: [
        { question_text: "Q1?", question_type: "true_false", correct_answer: "True" },
        { question_text: "Q2?", question_type: "true_false", correct_answer: "False" },
        { question_text: "Q3?", question_type: "true_false", correct_answer: "True" },
      ],
    };

    cy.request("POST", "/api/v1/ai/templates/validate", {
      template_type: "final-assessment",
      data: valid,
    }).then((response) => {
      expect(response.body.isValid).to.be.true;
    });
  });
});
```

---

## Chunk 2 Test Cases

### TC-CH2-SESSION_CREATED

**Title:** Session created successfully  
**Severity:** Critical  
**Duration:** 10 minutes

**Prerequisites:**
- Chunks 0–1 deployed
- Backend running
- Logged in as `teacher@example.com`
- Course UUID `test-course-123` exists

**Setup:**
```bash
# Create test course
curl -X POST http://localhost:8000/api/v1/courses \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Course", "organization_id": "org-123"}'
# Response includes course_id: test-course-123
```

**Steps:**
1. POST to `/api/v1/ai/sessions` with:
   ```json
   {
     "user_id": "user-456",
     "course_id": "test-course-123",
     "organization_id": "org-123"
   }
   ```
2. Parse response

**Expected Result:**
- ✅ Status 200
- ✅ Response includes: `sessionId`, `courseId`, `userId`, `createdAt`, `expiresAt`
- ✅ `expiresAt` is ~24 hours from now

**Automation Script:**
```typescript
describe("Chunk 2: Session Management", () => {
  it("TC-CH2-SESSION_CREATED: Creates session successfully", () => {
    cy.request("POST", "/api/v1/ai/sessions", {
      user_id: "user-456",
      course_id: "test-course-123",
      organization_id: "org-123",
    }).then((response) => {
      expect(response.status).to.eq(200);
      expect(response.body).to.have.all.keys(
        "sessionId",
        "courseId",
        "userId",
        "organizationId",
        "createdAt",
        "expiresAt"
      );
      
      const expiresAt = new Date(response.body.expiresAt);
      const now = new Date();
      const diffHours = (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60);
      expect(diffHours).to.be.closeTo(24, 1); // Within 1 hour of 24h
    });
  });
});
```

---

### TC-CH2-SESSION_SCOPE_ENFORCEMENT

**Title:** Cannot access other users' courses  
**Severity:** Critical  
**Duration:** 15 minutes

**Prerequisites:**
- Chunks 0–2 deployed
- Two test courses: `course-1` (owned by user-1), `course-2` (owned by user-2)
- Two sessions: `session-1` scoped to `course-1`, `session-2` scoped to `course-2`

**Setup:**
```bash
# Create courses
curl -X POST http://localhost:8000/api/v1/courses \
  -H "Content-Type: application/json" \
  -d '{"title": "Course 1", "organization_id": "org-123"}'
# → course-1

curl -X POST http://localhost:8000/api/v1/courses \
  -H "Content-Type: application/json" \
  -d '{"title": "Course 2", "organization_id": "org-123"}'
# → course-2

# Create sessions
curl -X POST http://localhost:8000/api/v1/ai/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-1", "course_id": "course-1", "organization_id": "org-123"}'
# → session-1

curl -X POST http://localhost:8000/api/v1/ai/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-2", "course_id": "course-2", "organization_id": "org-123"}'
# → session-2

# Create page in course-1
curl -X POST http://localhost:8000/api/v1/pages \
  -H "Authorization: Bearer $(get_token_for_user_1)" \
  -H "Content-Type: application/json" \
  -d '{"course_id": "course-1", "title": "Page in Course 1", ...}'
# → page-1
```

**Steps:**
1. Using session-1 (course-1), try to fetch page-1 → should succeed
2. Using session-2 (course-2), try to fetch page-1 → should fail with 403

**Expected Result:**

**Using session-1:**
- ✅ Status 200
- ✅ Returns page-1 data

**Using session-2:**
- ✅ Status 403 (Forbidden)
- ✅ Error message: "You do not have permission to access this page"

**Automation Script:**
```typescript
describe("Chunk 2: Session Scope Enforcement", () => {
  it("TC-CH2-SESSION_SCOPE_ENFORCEMENT: Cannot access other course pages", () => {
    // Try to fetch page from course-1 using session-2
    cy.request({
      method: "POST",
      url: "/api/v1/ai/tools/fetch_page",
      headers: {
        Authorization: "Session session-2",
      },
      body: { page_id: "page-1" },
      failOnStatusCode: false, // Allow 403 response
    }).then((response) => {
      expect(response.status).to.eq(403);
      expect(response.body.message).to.include("permission");
    });
  });
});
```

---

### TC-CH2-SESSION_EXPIRED

**Title:** Expired session is rejected  
**Severity:** High  
**Duration:** 10 minutes (or mock time)

**Prerequisites:**
- Chunk 2 deployed
- Session created

**Setup:**
```bash
# Create session (expires in 24h)
curl -X POST http://localhost:8000/api/v1/ai/sessions \
  -H "Content-Type: application/json" \
  -d '...'
# → session-id
```

**Steps:**
1. Wait 24+ hours (or mock time in tests)
2. Try to use session-id in tool call

**Expected Result:**
- ✅ Status 401 (Unauthorized)
- ✅ Error: "Session invalid or expired"

**Automation Script (Mock Time):**
```typescript
describe("Chunk 2: Session Expiry", () => {
  it("TC-CH2-SESSION_EXPIRED: Expired session rejected", () => {
    // Create session
    cy.request("POST", "/api/v1/ai/sessions", {
      user_id: "user-1",
      course_id: "course-1",
      organization_id: "org-1",
    }).then((createResponse) => {
      const sessionId = createResponse.body.sessionId;

      // Mock time to +25 hours
      cy.task("mockTime", "2025-01-01T13:00:00Z"); // Set to 25h later

      // Try to use session
      cy.request({
        method: "POST",
        url: "/api/v1/ai/tools/list_pages",
        headers: {
          Authorization: `Session ${sessionId}`,
        },
        failOnStatusCode: false,
      }).then((response) => {
        expect(response.status).to.eq(401);
      });
    });
  });
});
```

---

### TC-CH2-SESSION_MIDDLEWARE_ENFORCED

**Title:** All tool calls require Authorization header with session  
**Severity:** High  
**Duration:** 10 minutes

**Prerequisites:**
- Chunk 2 deployed

**Setup:**
```bash
# No special setup required
```

**Steps:**

#### Variation A: No Authorization header
```
POST /api/v1/ai/tools/list_pages
(no Authorization header)
```

#### Variation B: Invalid Authorization format
```
Authorization: Bearer xyz123  # Wrong format (should be "Session xyz123")
```

#### Variation C: Invalid session ID
```
Authorization: Session invalid-session-xyz
```

**Expected Result:**

**All Variations:**
- ✅ Status 401 (Unauthorized)
- ✅ Error message clearly states "Session invalid"

**Automation Script:**
```typescript
describe("Chunk 2: Session Middleware", () => {
  it("TC-CH2-SESSION_MIDDLEWARE_ENFORCED: No header rejected", () => {
    cy.request({
      method: "POST",
      url: "/api/v1/ai/tools/list_pages",
      failOnStatusCode: false,
    }).then((response) => {
      expect(response.status).to.eq(401);
    });
  });

  it("TC-CH2-SESSION_MIDDLEWARE_ENFORCED: Wrong format rejected", () => {
    cy.request({
      method: "POST",
      url: "/api/v1/ai/tools/list_pages",
      headers: {
        Authorization: "Bearer xyz123",
      },
      failOnStatusCode: false,
    }).then((response) => {
      expect(response.status).to.eq(401);
    });
  });

  it("TC-CH2-SESSION_MIDDLEWARE_ENFORCED: Invalid session rejected", () => {
    cy.request({
      method: "POST",
      url: "/api/v1/ai/tools/list_pages",
      headers: {
        Authorization: "Session invalid-session-xyz",
      },
      failOnStatusCode: false,
    }).then((response) => {
      expect(response.status).to.eq(401);
    });
  });
});
```

---

### TC-CH2-REFETCH_ENFORCEMENT

**Title:** `list_pages` always fetches fresh data from DB  
**Severity:** High  
**Duration:** 20 minutes

**Prerequisites:**
- Chunk 2 deployed
- Session created for course-1

**Setup:**
```bash
# Create course with 2 pages
curl -X POST http://localhost:8000/api/v1/courses ...
# → course-1

curl -X POST http://localhost:8000/api/v1/pages \
  -d '{"course_id": "course-1", "title": "Page 1", ...}'
# → page-1

curl -X POST http://localhost:8000/api/v1/pages \
  -d '{"course_id": "course-1", "title": "Page 2", ...}'
# → page-2

# Create session for course-1
curl -X POST http://localhost:8000/api/v1/ai/sessions \
  -d '{"user_id": "user-1", "course_id": "course-1", ...}'
# → session-1
```

**Steps:**
1. Call `list_pages` with session-1 → response has 2 pages
2. **Outside of AI session**, add page-3 directly via API
3. Call `list_pages` again with session-1 → response must have 3 pages (fresh from DB)

**Expected Result:**
- ✅ First call returns 2 pages
- ✅ After adding page-3 externally, second call returns 3 pages
- ✅ AI is forced to re-fetch (not using conversation history cache)

**Automation Script:**
```typescript
describe("Chunk 2: Re-Fetch Enforcement", () => {
  it("TC-CH2-REFETCH_ENFORCEMENT: list_pages returns fresh DB data", () => {
    const sessionId = "session-1"; // Pre-created

    // First call: should have 2 pages
    cy.request({
      method: "POST",
      url: "/api/v1/ai/tools/list_pages",
      headers: { Authorization: `Session ${sessionId}` },
    }).then((response1) => {
      expect(response1.body.pages).to.have.length(2);

      // Add page-3 directly (simulating external change)
      cy.task("addPageDirectly", {
        courseId: "course-1",
        title: "Page 3",
      });

      // Second call: should now have 3 pages
      cy.request({
        method: "POST",
        url: "/api/v1/ai/tools/list_pages",
        headers: { Authorization: `Session ${sessionId}` },
      }).then((response2) => {
        expect(response2.body.pages).to.have.length(3);
        const page3 = response2.body.pages.find((p: any) => p.title === "Page 3");
        expect(page3).to.exist;
      });
    });
  });
});
```

---

## Test Execution Plan

### Per-Chunk Sign-Off

**Before Chunk 0 Sign-Off:**
- [ ] TC-CH0-FEATURE_FLAG-DISABLED passes
- [ ] TC-CH0-FEATURE_FLAG-ENABLED passes
- [ ] TC-CH0-MANUAL_CREATE-REGRESSION passes
- [ ] TC-CH0-ENV_CONFIG-LOADS passes

**Before Chunk 1 Sign-Off:**
- [ ] All Chunk 0 tests still pass (regression)
- [ ] TC-CH1-TEMPLATE_REGISTRY-LOADED passes
- [ ] TC-CH1-VALIDATOR-ACCEPTS-VALID passes
- [ ] TC-CH1-VALIDATOR-REJECTS-INVALID passes
- [ ] TC-CH1-ASSESSMENT-VALIDATOR passes

**Before Chunk 2 Sign-Off:**
- [ ] All Chunk 0–1 tests still pass (regression)
- [ ] TC-CH2-SESSION_CREATED passes
- [ ] TC-CH2-SESSION_SCOPE_ENFORCEMENT passes
- [ ] TC-CH2-SESSION_EXPIRED passes
- [ ] TC-CH2-SESSION_MIDDLEWARE_ENFORCED passes
- [ ] TC-CH2-REFETCH_ENFORCEMENT passes

### Continuous Integration

**Pre-Deploy Checklist (per chunk):**
```bash
# Run Chunk 0 tests
npx cypress run --spec "cypress/e2e/chunk0-*.cy.ts"

# Run Chunk 1 tests
npx cypress run --spec "cypress/e2e/chunk1-*.cy.ts"

# Run Chunk 2 tests
npx cypress run --spec "cypress/e2e/chunk2-*.cy.ts"

# Run regression (all previous chunks)
npx cypress run --spec "cypress/e2e/chunk*.cy.ts"
```

---

## Test Reporting

**Test Result Template:**

```
Chunk: 0
Date: 2026-06-13
Environment: Development
Passed: 4/4
Failed: 0/4
Skipped: 0/4
Duration: 45 minutes

Details:
✅ TC-CH0-FEATURE_FLAG-DISABLED
✅ TC-CH0-FEATURE_FLAG-ENABLED
✅ TC-CH0-MANUAL_CREATE-REGRESSION
✅ TC-CH0-ENV_CONFIG-LOADS

Notes:
- All tests passed
- No regressions detected
- Ready for staging deployment

Sign-Off: ✅ QA Lead Approved
```

---

*Document Version: 1.0*  
*Status: Production Specification*  
*Last Updated: 2026-06-13*
