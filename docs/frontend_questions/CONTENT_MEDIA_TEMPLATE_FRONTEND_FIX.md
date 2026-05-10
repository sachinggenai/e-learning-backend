# Frontend Fix: `content-media` (Text + Image) Template — SCORM Export
**Date:** 2026-05-10  
**Reported by:** Backend Team  
**Affects:** SCORM Export only (live preview is unaffected)  
**Severity:** Critical — image never appears in exported SCORM package

---

## 1. Root Cause

The `content-media` template renders correctly in the **live preview** because the
frontend reads images from its own in-memory/component state.

During **SCORM export**, the image disappears because the frontend serializes
`"mediaUrl": ""` (empty string) into the export payload. The backend has no other
way to locate the image and the SCORM package ships with no image.

---

## 2. The Export Payload Contract

The backend export endpoint `POST /api/v1/export` accepts a `Course` JSON object.
For every template of type `content-media`, the `data` object **MUST** include a
non-empty `mediaUrl` field pointing to a server-accessible absolute URL.

### Full required shape for `content-media` data

```jsonc
{
  "courseId": "course_<timestamp>",
  "title": "My Course",
  "description": "",
  "language": "en",
  "author": "Course Author",
  "version": "1.0.0",
  "templates": [
    {
      "id": "<uuid>",             // required, alphanumeric + hyphens only
      "type": "content-media",   // exact string
      "order": 0,                // zero-based integer
      "title": "Text with Media",
      "pageId": "<uuid>",        // source page ID for theme scoping
      "data": {

        // ── TEXT BODY (REQUIRED) ──────────────────────────────────────
        // Rich HTML string for the text panel.
        // Use "body" as the primary field.
        // Do NOT also put the body HTML in "content".
        "body": "<p>Your rich text HTML here...</p>",

        // ── MEDIA URL (REQUIRED when showing an image or video) ───────
        // Absolute URL to the media file on the server.
        // Must start with https:// or http://
        // Obtain this from POST /api/v1/media/upload (see Section 3).
        "mediaUrl": "https://your-api-domain.com/api/v1/media/files/global/image/<uuid>.jpg",

        // ── MEDIA TYPE (REQUIRED) ────────────────────────────────────
        // Exactly one of: "image" | "video"
        "mediaType": "image",

        // ── LAYOUT POSITION (REQUIRED) ───────────────────────────────
        // Exactly one of: "left" | "right" | "top" | "bottom"
        // Controls where the media sits relative to the text.
        "mediaPosition": "right",

        // ── LEGACY FIELDS (keep as null, do not repurpose) ───────────
        "content": null,
        "subtitle": null,
        "videoUrl": null,
        "questions": null,
        "tabs": null,
        "panels": null
      }
    }
  ],
  "assets": [],
  "settings": {
    "theme": "default",
    "autoplay": false
  }
}
```

---

## 3. Image Upload Flow — Step by Step

### Step 1: Upload image when user selects it in the editor

```http
POST /api/v1/media/upload
Content-Type: multipart/form-data

file=<binary file>
course_id=<optional integer course ID>
```

### Step 2: Store the URL from the response

```jsonc
// Response from POST /api/v1/media/upload
{
  "success": true,
  "media": {
    "id": "a1b2c3d4-e5f6-...",
    "original_filename": "photo.jpg",
    "stored_filename": "a1b2c3d4-e5f6-....jpg",
    "path": "global/image/a1b2c3d4-e5f6-....jpg",
    "url": "/api/v1/media/files/global/image/a1b2c3d4-e5f6-....jpg",  // ← store this
    "mime_type": "image/jpeg",
    "category": "image",
    "size": 204800,
    "course_id": null,
    "uploaded_at": "2026-05-10T10:00:00"
  }
}
```

### Step 3: Build the absolute mediaUrl for the export payload

```js
// The backend returns a relative URL — make it absolute before export:
const BASE_URL = process.env.REACT_APP_API_BASE; // e.g. "https://api.domain.com"
const mediaUrl = BASE_URL + response.data.media.url;
// Result: "https://api.domain.com/api/v1/media/files/global/image/<uuid>.jpg"
```

---

## 4. State Management Rules

When the user interacts with the `content-media` template editor:

| User Action | Frontend Must Do |
|---|---|
| Selects an image file | `POST /api/v1/media/upload` → store absolute `mediaUrl` in component/store state |
| Changes image | Upload new file → replace stored `mediaUrl` |
| Removes image | Set `mediaUrl: ""` and `mediaType: "none"` in state |
| Clicks Export | Read `mediaUrl` from state → include in export payload |

### CRITICAL RULES

1. **NEVER** use a `blob://` or `blob:http://` object URL in `mediaUrl`.  
   These are browser-local and will be dead once the SCORM player runs in another browser/LMS.

2. **NEVER** read the image from the DOM/canvas or from a local `<img>` src at export time.  
   Always use the persisted server URL from the upload response.

3. **ALWAYS** upload the image to the server first, then store the returned URL.  
   Export must read from that stored URL — not from any local state.

---

## 5. Field Resolution Priority (Backend Logic — for reference)

The backend transformer probes fields in this order when building the SCORM package.

**Text body resolution order:**
```
data.body → data.text → data.description → data.content (only if not a bare URL)
```

**Media URL resolution order:**
```
data.mediaUrl → data.imageUrl → data.videoUrl → data.src → data.url
→ data.content (only if value starts with http)
```

This means `imageUrl` is also accepted as an alternative to `mediaUrl` for images.

---

## 6. Validation Rules

| Field | Type | Constraint | What happens if violated |
|---|---|---|---|
| `type` | string | Must be `"content-media"` | 422 Unprocessable Entity |
| `mediaUrl` | string | If set, must start with `http://` or `https://` | Accepted silently — image won't render |
| `mediaType` | string | `"image"` or `"video"` | Defaults to `"image"` if missing |
| `mediaPosition` | string | `"left"`, `"right"`, `"top"`, `"bottom"` | Defaults to `"right"` if missing |
| `body` | string | Any valid HTML string | Accepted |
| `id` | string | Alphanumeric + hyphens/underscores only | 422 Unprocessable Entity |
| `order` | integer | Zero-based, contiguous, no duplicates | 400 Bad Request |

---

## 7. Minimal Working Payload (copy-paste test)

Send this to `POST /api/v1/export` to verify the fix is working end-to-end.
The downloaded SCORM ZIP should show text on the left and the image on the right.

```json
{
  "course": "{\"courseId\":\"course_test001\",\"title\":\"Test Text+Image\",\"description\":\"\",\"language\":\"en\",\"author\":\"Test Author\",\"version\":\"1.0.0\",\"templates\":[{\"id\":\"slide-001\",\"type\":\"content-media\",\"order\":0,\"title\":\"Text with Image\",\"data\":{\"body\":\"<p>This is the <strong>text side</strong> of the slide.</p>\",\"mediaUrl\":\"https://upload.wikimedia.org/wikipedia/commons/thumb/1/1e/Stonehenge.jpg/800px-Stonehenge.jpg\",\"mediaType\":\"image\",\"mediaPosition\":\"right\",\"content\":null,\"subtitle\":null,\"videoUrl\":null,\"questions\":null,\"tabs\":null,\"panels\":null}}],\"assets\":[],\"settings\":{\"theme\":\"default\",\"autoplay\":false}}"
}
```

Or as a pretty-printed `course` string value to build programmatically:

```json
{
  "courseId": "course_test001",
  "title": "Test Text+Image",
  "description": "",
  "language": "en",
  "author": "Test Author",
  "version": "1.0.0",
  "templates": [
    {
      "id": "slide-001",
      "type": "content-media",
      "order": 0,
      "title": "Text with Image",
      "data": {
        "body": "<p>This is the <strong>text side</strong> of the slide.</p>",
        "mediaUrl": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1e/Stonehenge.jpg/800px-Stonehenge.jpg",
        "mediaType": "image",
        "mediaPosition": "right",
        "content": null,
        "subtitle": null,
        "videoUrl": null,
        "questions": null,
        "tabs": null,
        "panels": null
      }
    }
  ],
  "assets": [],
  "settings": {
    "theme": "default",
    "autoplay": false
  }
}
```

---

## 8. What the SCORM Player Renders

### When `mediaPosition: "right"` + `mediaUrl` is populated ✅

```
┌──────────────────────────────────────────────────────────────────┐
│  Title (h2)                                                      │
├────────────────────────────────────┬─────────────────────────────┤
│  Text body (~55%)                  │  Image (~45%)               │
│  <div class="twm-text">            │  <div class="twm-media">    │
│  Rich HTML renders here            │  <img src="mediaUrl">       │
└────────────────────────────────────┴─────────────────────────────┘
```

### When `mediaUrl` is `""` or missing ❌ (the current bug)

```
┌──────────────────────────────────────────────────────────────────┐
│  Title (h2)                                                      │
├──────────────────────────────────────────────────────────────────┤
│  Text body (100% width — image column completely missing)        │
└──────────────────────────────────────────────────────────────────┘
```

### Layout behaviour by `mediaPosition`

| mediaPosition | Layout |
|---|---|
| `right` | text left \| image right (default) |
| `left` | image left \| text right |
| `top` | image on top, text below (stacked) |
| `bottom` | text on top, image below (stacked) |

---

## 9. Video Support (same template type)

For video slides use the exact same template type `content-media`:

```json
{
  "type": "content-media",
  "data": {
    "body": "<p>Watch the intro video.</p>",
    "mediaUrl": "https://your-api/api/v1/media/files/global/video/<uuid>.mp4",
    "mediaType": "video",
    "mediaPosition": "right",
    "content": null,
    "subtitle": null,
    "videoUrl": null,
    "questions": null,
    "tabs": null,
    "panels": null
  }
}
```

The `videoUrl` legacy field is also resolved as a fallback but `mediaUrl` is preferred.

---

## 10. Backend Allowed Media Formats

Images: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.svg`  
Videos: `.mp4`, `.webm`, `.ogg`, `.mov`, `.avi`  
Max file size: **50 MB**

---

## 11. Summary Checklist for Frontend Team

- [ ] On image select: `POST /api/v1/media/upload` → store `response.media.url`
- [ ] Build absolute URL: `BASE_URL + response.media.url` → store as `mediaUrl`
- [ ] On export: read stored `mediaUrl` from state (not from DOM/blob)
- [ ] Populate `data.mediaUrl` in export payload with the absolute URL
- [ ] Populate `data.mediaType` = `"image"` or `"video"`
- [ ] Populate `data.mediaPosition` = `"left"` | `"right"` | `"top"` | `"bottom"`
- [ ] Populate `data.body` with rich HTML text (not `data.content`)
- [ ] Never send `blob://` URLs in `mediaUrl`
- [ ] Test with `POST /api/v1/export` using the minimal payload in Section 7

---

## 12. Backend Answers to Frontend Gap Analysis (B1 – B6)

> **Context:** The frontend team submitted a gap analysis with 6 architectural questions.  
> All answers below are backed by server-side code references.

---

### B1 — Which export endpoint should we call? `POST /export` (JSON payload) vs `POST /export/scorm/{courseId}` (DB read)?

**Use `POST /api/v1/export/scorm/{courseId}`.**

This is the correct path for a persisted course. It reads all course data, pages, and
components directly from the database, so `mediaUrl`, `body`, `mediaType`, and
`mediaPosition` are all read from what was saved via the component update API.

`POST /api/v1/export` (full JSON payload) is a **one-shot / testing endpoint** — callers
must construct the entire course JSON themselves. For the Export button workflow, use
the DB-read path.

**Code reference:** `app/routers/export.py`, function `export_persisted_course` — the
endpoint is declared as `@router.post("/export/scorm/{courseId}")`.

---

### B2 — Does the DB-read path correctly pass `mediaUrl` through to the SCORM generator?

**Yes, for courses stored via the Page/Component API (the standard frontend flow).**

When you use `PATCH /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}`
to save component data, the full `data` dict (including `mediaUrl`, `mediaType`,
`mediaPosition`, `body`) is stored as-is in `ComponentRecord.data` (a JSON column).

At export time, `_component_data_with_content()` in `export.py` (line ~366) preserves
**all keys** from `comp.data` and only synthesizes a `content` fallback from `body`.
The SCORM service then reads `mediaUrl` directly from that dict.

**What the frontend must guarantee:** save the full `data` dict including `mediaUrl`
when calling the component update endpoint. Example:

```json
PATCH /api/v1/courses/{courseId}/pages/{pageId}/components/{componentId}
{
  "data": {
    "body": "<p>Rich HTML text</p>",
    "mediaUrl": "/api/v1/media/files/global/image/<uuid>.jpg",
    "mediaType": "image",
    "mediaPosition": "right"
  }
}
```

**Backend fix applied (2026-05-10):** A second code path (`_map_template_record`, used
for courses imported via the older TemplateRecord API) was also patched — it previously
dropped all media fields for `content-media` / `text-with-media` templates. This is
fixed in the same commit. No frontend change required for that fix.

---

### B3 — What is the exact response shape of `POST /api/v1/media/upload`?

The response is **nested**. The URL lives at `response.data.media.url`, **not**
`response.data.url`.

```json
{
  "success": true,
  "media": {
    "id": "a1b2c3d4-e5f6-...",
    "original_filename": "photo.jpg",
    "stored_filename": "a1b2c3d4-....jpg",
    "path": "global/image/a1b2c3d4-....jpg",
    "url": "/api/v1/media/files/global/image/a1b2c3d4-....jpg",
    "mime_type": "image/jpeg",
    "category": "image",
    "size": 204800,
    "course_id": null,
    "uploaded_at": "2026-05-10T10:00:00"
  }
}
```

**Correct access in JavaScript/TypeScript:**

```ts
const response = await api.post('/api/v1/media/upload', formData);
const relativeUrl: string = response.data.media.url;   // ✅
// NOT response.data.url                                  // ❌
```

Then build the absolute URL for the export payload:

```ts
const BASE = process.env.REACT_APP_API_BASE;  // e.g. "https://api.domain.com"
const mediaUrl = BASE + relativeUrl;
// → "https://api.domain.com/api/v1/media/files/global/image/<uuid>.jpg"
```

> **Note on env var name:** The correct environment variable in your project is
> `REACT_APP_API_BASE` (not `REACT_APP_API_BASE_URL` as written in earlier versions of
> this document). Sections 3 and 4 of this doc have been noted accordingly.

**Code reference:** `app/routers/media.py`, function `upload_media`, the `response_data`
dict (line ~295) shows the exact structure returned.

---

### B4 — Is `data.body` or `data.content` the canonical field for the text body?

**`data.body` is canonical.**

The backend SCORM generator resolves text in this priority order:
```
data.body → data.text → data.description → data.content (only if not a bare URL)
```

`data.content` is the **last resort fallback** and is used only for legacy templates.
The `_component_data_with_content()` function synthesizes `content = data.body || compType`
purely to satisfy Pydantic schema validation — the SCORM player never reads `content`
directly for `content-media` templates.

**Frontend must:**
- Save rich-text HTML to `data.body` when calling the component update endpoint.
- Never put the rich-text HTML in `data.content`.
- Transform export payload to use `data.body`, not `data.content`.

---

### B5 — Does the backend accept `"text-with-media"` as the template type?

**Yes.** Both `"text-with-media"` and `"content-media"` are accepted.

Two aliasing mechanisms handle this:

1. **SCORM generator** (`app/services/scorm_export.py`):
   `TEMPLATE_TYPE_ALIASES = {"text-with-media": "content-media", ...}`
   This normalises the type before dispatch.

2. **`_component_data_with_content()`** (`app/routers/export.py`, line ~378):
   ```python
   if comp_type in ("text-with-media", "content-media"):
       out["content"] = data.get("body") or comp_type
   ```
   Both types get the same treatment.

**Recommendation:** Store `"text-with-media"` in your DB if that is the frontend's
native type. The backend accepts it in all paths. You do NOT need a client-side
`text-with-media → content-media` mapping before the API call — the server handles it.

---

### B6 — Is `course_id` required for upload? Is 50 MB limit server-enforced?

**`course_id` is optional.** If omitted, the file is stored under `media/global/{category}/`.
If provided, it is stored under `media/{course_id}/{category}/`. Either path works for SCORM export.

```http
POST /api/v1/media/upload
Content-Type: multipart/form-data

file=<binary>
# course_id is optional — omit it or pass the numeric DB course ID
```

**50 MB is server-enforced** at two checkpoints:

1. **Pre-flight** — reads `Content-Length` header; rejects before reading body.
2. **Post-read** — validates `len(file_content) > MAX_FILE_SIZE` after full read.

```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB  (app/routers/media.py, line 44)
```

Error response when exceeded:
```json
{
  "detail": "File size (XX bytes) exceeds maximum allowed size (52428800 bytes)"
}
```

HTTP status: `400 Bad Request`.

---

### Summary Table — Frontend Actions by Gap Item

| Gap | Root Cause | Frontend Fix | Backend Status |
|-----|-----------|--------------|----------------|
| B1 | Wrong export endpoint | Use `POST /api/v1/export/scorm/{courseId}` | ✅ Endpoint exists |
| B2 | `mediaUrl` not saved | Save full `data` dict in `PATCH /components/{id}` | ✅ Fixed `_map_template_record` |
| B3 | Wrong response mapping | Use `response.data.media.url` not `response.data.url` | ✅ No backend change needed |
| B4 | Wrong text field | Write `data.body`, not `data.content` | ✅ No backend change needed |
| B5 | Type mismatch | `"text-with-media"` is accepted — no mapping needed | ✅ Backend aliases it |
| B6 | Unknown constraints | `course_id` optional; 50 MB server-enforced | ✅ No backend change needed |
