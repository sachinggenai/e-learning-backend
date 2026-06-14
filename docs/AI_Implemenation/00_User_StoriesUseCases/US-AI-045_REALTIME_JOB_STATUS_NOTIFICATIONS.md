# US-AI-045: Real-Time Job Status and Notifications for Async AI Operations

**Status:** Draft
**Priority:** SHOULD
**Depends on:** US-AI-024 (Frontend AI Integration Layer), US-AI-034 (Durable Workflow Engine)
**Source flow:** File_Ingestion_Document_Import_Flow.mmd, Full_Course_From_Uploaded_File_Scenario_Flow.mmd, Platform Runtime and Operations Flow
**GAP-ID:** GAP-12 (from RESEARCH_AUDIT.md)
**Epic Owner:** Technical Product Owner

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 User Story

As an **Author**, I want to see real-time progress of long-running AI operations (course generation, batch content repair, SCORM export, preview generation) directly within the chat panel or editor UI, so that I know the system is working and can estimate when it will complete without manually refreshing or polling blindly.

As a **Platform Operator**, I want a unified, standards-based real-time notification channel for all async AI job status transitions, so that the frontend can subscribe to events once and receive push updates rather than hammering the API with polling requests, and so that connection interruptions are handled gracefully with automatic reconnection and gap-filling.

### 1.2 Overview

The e-learning backend currently relies on frontend-driven polling for all async status checks. US-AI-034 defines `GET /api/v1/workflows/{job_id}` with a recommended 2-second polling interval, and US-AI-024 implements `pollJob()` in the frontend ingestion module. This polling-only approach has several production deficiencies:

1. **Inefficient network usage:** Each frontend session polls every 2 seconds even when job status has not changed, consuming backend database query resources for all active users.
2. **Delayed status delivery:** Polling at 2-second intervals means status changes are not visible to the user until the next poll cycle (up to 2 seconds latency on average, 2 seconds in the worst case).
3. **No standard event schema:** Each frontend module implements its own polling logic (workflow polling, preview polling, import job polling) with duplicated infrastructure.
4. **No connection recovery:** If the user's network drops or the page reloads, there is no mechanism to replay missed events or re-establish a subscription.
5. **No progress granularity:** Job progress is reported only when the frontend polls; the backend has no mechanism to push granular progress updates (e.g., "page 9 of 20 generated") as they happen.

This user story introduces a **dual-channel notification system**:

**Channel 1 -- Server-Sent Events (SSE) for real-time push:** The backend exposes an SSE endpoint `GET /api/v1/events/subscribe` that streams job status events to authenticated clients. SSE is chosen over WebSockets because: (a) SSE is unidirectional server-to-client, matching our use case (server pushes events, client reads them); (b) SSE has automatic reconnection built into the browser `EventSource` API; (c) SSE works through HTTP/1.1 proxies and load balancers without special configuration; (d) SSE is simpler to implement and debug on the FastAPI side using `StreamingResponse`.

**Channel 2 -- Optimized polling as fallback:** For environments where SSE is blocked (corporate proxies, certain CDN configurations), the frontend falls back to an optimized polling strategy with adaptive interval, exponential backoff on idle, and batch status fetching.

The frontend `src/ai/` module (defined in US-AI-024) gains a new `useJobNotifications` hook that: (a) attempts an SSE connection on mount; (b) falls back to adaptive polling on error; (c) provides a unified event stream of job status updates to all consuming components (workflow panel, preview cards, ingestion flow); (d) handles reconnection with missed-event replay.

### 1.3 Eight Functional Requirements

**FR1: Server-Sent Events Subscription Endpoint**
The backend shall provide a single SSE endpoint `GET /api/v1/events/subscribe` that accepts an `Authorization: Bearer <session_token>` header and streams `event:` lines for all job status transitions that the authenticated session is authorized to observe. The endpoint must support filtering by `?job_ids=` (comma-separated list of job UUIDs to subscribe to specific jobs) and `?types=` (comma-separated list of event types: `workflow_job`, `preview_job`, `import_job`, `proposal_preview`). Each SSE event must follow the standard `text/event-stream` format with `event:`, `data:`, `id:`, and `retry:` fields. The server must send a heartbeat comment (`: heartbeat`) every 15 seconds to keep the connection alive and detect client disconnection. The server must enforce a maximum subscription duration of 30 minutes per connection, after which the connection is gracefully closed with a `terminated` event and a `retry` directive instructing the client to reconnect.

**FR2: Standardized Job Event Schema**
Every SSE event payload must conform to a unified JSON schema with the following structure:
```json
{
  "event_id": "uuid",
  "event_type": "status_change" | "progress_update" | "heartbeat" | "error" | "completed" | "cancelled" | "terminated",
  "job_id": "uuid",
  "job_type": "workflow_job" | "preview_job" | "import_job" | "proposal_preview",
  "previous_status": "string | null",
  "current_status": "string",
  "progress": 0.0..1.0,
  "current_state": "string | null",
  "message": "string | null",
  "metadata": {},
  "timestamp": "ISO-8601"
}
```
All consuming frontend components must process events from this schema. Backend services that generate job events must write to a unified `job_events_outbox` table from which the SSE publisher reads. The same event structure must be returned by the polling fallback endpoint `GET /api/v1/events/poll?since=<event_id>` for gap-filling.

**FR3: Unified Frontend Notification Hook (useJobNotifications)**
The frontend `src/ai/` module must provide a React hook `useJobNotifications(jobIds: string[], options?: {sseUrl?: string, pollingFallback?: boolean, pollIntervalMs?: number})` that:
- Returns `{ events: JobEvent[], statuses: Map<string, JobStatus>, isConnected: boolean, connectionMode: 'sse' | 'polling' | 'offline', error: string | null, reconnect: () => void, clearEvents: () => void }`.
- On mount, attempts to open an `EventSource` connection to `GET /api/v1/events/subscribe?job_ids=<comma-separated>`.
- On `EventSource` open, sets `connectionMode = 'sse'` and `isConnected = true`.
- On `EventSource` error (including 401, 403, network drop), falls back to adaptive polling mode within 500 milliseconds. Stores the last received `event_id` in `sessionStorage` to support gap-filling on reconnect.
- On `EventSource` message, parses the SSE `data:` JSON, updates the internal event log and job status map, and triggers re-render of consuming components.
- In polling fallback mode, calls `GET /api/v1/events/poll?since=<last_event_id>` every `pollIntervalMs` (default 2000, adapts up to 10000 on idle, down to 1000 on activity). Uses `AbortController` to cancel in-flight polls on unmount.
- Exposes a `reconnect()` function that closes the current `EventSource` and opens a new one with the `Last-Event-ID` header set.
- Handles the SSE `terminated` event by automatically reconnecting after `retry` milliseconds.
- Cleans up `EventSource` and `AbortController` on component unmount.

**FR4: Adaptive Backend Event Publisher**
The backend must implement an `EventPublisher` service (`app/services/events/publisher.py`) that:
- Provides `publish(job_id, job_type, event_type, previous_status, current_status, progress, current_state, message, metadata)` method that writes to the `job_events_outbox` table.
- Is called by: `WorkflowOrchestrator` after every state transition (US-AI-034); `PreviewWorker` after every preview status change (US-AI-041); `ImportJobService` after import job state changes; and any future job-type service.
- Supports synchronous publish (write to outbox and notify SSE broadcaster immediately via an `asyncio.Event` or `asyncio.Queue`) and deferred publish (write to outbox only, for batch reconciliation).
- Must not block the caller: the publish method must return within 50 milliseconds even if the SSE broadcaster is slow. The outbox write and the SSE fan-out must happen asynchronously via a background `EventBroadcaster` worker.

**FR5: Event Outbox and Gap-Filling**
The backend must maintain a `job_events_outbox` table (see section 2.2 for DDL) that stores all published events with a monotonically increasing `event_id`. The table serves two purposes:
- **SSE fan-out source:** The `EventBroadcaster` background worker reads new rows from `job_events_outbox` in order and fans them out to all active SSE connections that match the event's `job_id` or `job_type`.
- **Gap-filling source:** The fallback polling endpoint `GET /api/v1/events/poll?since=<event_id>&job_ids=<comma-separated>` returns all events with `event_id > since` that match the requested `job_ids`. This allows reconnecting clients to replay missed events.
- The outbox must be periodically cleaned: events older than 7 days are deleted by a background janitor task. The janitor must delete in batches of 5000 rows with a 1-second sleep between batches to avoid replication lag.
- The outbox must have an index on `(event_id, created_at)` for efficient since-based queries, and an index on `(job_id, event_id)` for job-filtered queries.

**FR6: Frontend Visual Progress Indicators**
The frontend must render job progress in three visual tiers based on context:

- **Tier 1 -- Minimal (AI Chat Panel):** When a workflow job is running in the background (e.g., course generation from file ingestion), the chat panel must show a compact progress bar at the bottom of the message list: "Generating course pages... [=====       ] 45%". The bar must update in real-time via SSE events. When the job completes, the bar is replaced with a success message and the "Review Course" button appears. On failure, the bar turns red with the error message and a "Retry" button.

- **Tier 2 -- Detailed (Workflow Detail Panel):** A side panel accessible from the course editor toolbar ("Job Status" button) shows a table of all active and recent jobs for the current course: job type, current state, progress bar, elapsed time, estimated remaining time, and action buttons (Cancel, Retry, View Details). Clicking "View Details" opens a step-by-step timeline of the job's state transitions with per-step duration and status.

- **Tier 3 -- Notification Toast (Global):** When any job completes, fails, or requires attention, the frontend must show a global notification toast (using the existing toast system) regardless of which panel the user is currently viewing. The toast must be dismissable but persist for a minimum of 10 seconds or until the user interacts with it. Clicking the toast navigates to the relevant context (e.g., clicking a "Course generation complete" toast navigates to the course review screen).

**FR7: SSE Connection Lifecycle Management**
The frontend must implement the following SSE lifecycle:

1. **Connection Initiation:** Frontend calls `GET /api/v1/events/subscribe?job_ids=<comma-separated>` with `Authorization: Bearer <session_token>`. The `EventSource` constructor is used with `{withCredentials: false}` to avoid sending cookies. The token is passed via a query parameter fallback `?token=<jwt>` for `EventSource` compatibility (the `EventSource` API does not support custom headers).

2. **Heartbeat Monitoring:** The frontend tracks time since the last received event (including heartbeat comments). If no event is received for 30 seconds, the frontend considers the connection stale, closes the `EventSource`, logs a warning, and enters polling fallback mode.

3. **Reconnection:** The frontend listens for the SSE `terminated` event which includes a `retry` field (milliseconds). On receiving this event, the frontend waits `retry` milliseconds then calls `GET /api/v1/events/poll?since=<last_event_id>&job_ids=<comma-separated>` to replay any missed events, then opens a new `EventSource`.

4. **Graceful Degradation:** If SSE connection fails 3 consecutive times with non-401/403 errors, the frontend locks into polling-only mode for the remainder of the session (or until the user manually clicks "Reconnect"). If SSE fails with 401/403, the frontend stops all reconnection attempts and shows a "Session expired" message.

5. **Page Navigation and Tab Visibility:** When the user navigates away from the course editor (SPA route change), the frontend does not close the `EventSource` -- the subscription remains active for toast notifications. When the browser tab becomes hidden (`document.visibilityState === 'hidden'`), the frontend switches from SSE to polling mode with a 30-second interval to reduce network activity. On tab becoming visible again, it replays missed events via the poll endpoint and reconnects SSE.

**FR8: Admin Dashboard Event Monitoring**
The admin dashboard (US-AI-020) must provide a real-time event monitor view that:
- Connects to the same SSE endpoint with `?types=workflow_job,import_job` (admin scope, no job_ids filter -- receives all job events).
- Shows a scrolling live feed of job events with columns: timestamp, job_id (truncated, clickable), job type, event type, previous status -> current status, progress bar.
- Supports filtering by job type, status, and time range.
- Shows active connection status indicator (green/yellow/red).
- Supports exporting the last 1000 events as CSV.

### 1.4 User Flow

#### Happy Path: Course Generation with SSE

1. User uploads a course outline PDF through the file ingestion panel (US-AI-024 Flow 4).
2. User reviews the page breakdown and clicks "Confirm and Create".
3. Frontend calls `POST /api/v1/workflows` with `course_generation` workflow type (US-AI-034).
4. Backend returns HTTP 202 with `{ job_id, polling_url }`.
5. Frontend `useJobNotifications` hook is initialized with `[job_id]`.
6. Hook opens `EventSource` to `GET /api/v1/events/subscribe?job_ids=<job_id>`.
7. Backend `EventBroadcaster` sends SSE `progress_update` events as each page is generated:
   - `event: progress_update` `data: {"event_type":"progress_update","progress":0.05,"current_state":"generate_pages","message":"Generating page 1 of 20: Introduction"}`
   - `event: progress_update` `data: {"progress":0.10,"message":"Generating page 2 of 20: Getting Started"}`
   - ... (continues for each page)
8. The chat panel progress bar updates smoothly without polling.
9. Estimated remaining time is computed client-side from the rate of progress updates.
10. Backend sends `event: completed` `data: {"event_type":"completed","progress":1.0,"result":{"batch_proposal_id":"...","total_pages":20}}`.
11. Frontend replaces the progress bar with a green "Course generation complete" banner and a "Review Course" button.
12. A global toast appears: "Course generation complete. Click to review."
13. SSE connection is gracefully closed by the frontend (unsubscribes from this job_id).

#### Error Path: SSE Connection Failure with Fallback

1. User initiates course generation as above.
2. Frontend `EventSource` connection fails (corporate proxy blocks streaming responses).
3. `EventSource` fires `onerror`. The hook detects no `event.data` was received and waits 500ms.
4. After 500ms, the hook transitions to `connectionMode = 'polling'` and sets `isConnected = false`.
5. Hook calls `GET /api/v1/events/poll?since=0&job_ids=<job_id>` to get all events since the start.
6. Backend returns all published events for this job_id. Frontend replays them in order to build current state.
7. Hook continues polling at 2-second intervals. Polling interval adapts: if no status change in 3 consecutive polls, interval increases to 5 seconds. If a status change is detected, interval drops to 1 second for the next 5 polls.
8. When the job completes, the backend publishes the `completed` event to the outbox. The next poll retrieves it.
9. Frontend renders the completion state identically to the SSE path -- the consuming components are agnostic to the transport mechanism.

#### Error Path: Backend Job Failure

1. Backend `generate_pages` step fails with an LLM API error after 3 retries.
2. Backend transitions workflow to `failed` with `error: {"code":"LLM_RATE_LIMITED","message":"Anthropic API rate limit exceeded. Retry in 60 seconds."}`.
3. `EventPublisher.publish(job_id, 'workflow_job', 'error', 'running', 'failed', 0.3, 'generate_pages', 'LLM API rate limit exceeded')` is called.
4. SSE broadcasts the error event to the frontend.
5. Frontend renders the progress bar in red with the error message and a "Retry" button.
6. A persistent error toast is shown: "Course generation failed: LLM API rate limit exceeded. You can retry in 60 seconds."
7. User clicks "Retry". Frontend calls `POST /api/v1/workflows/{job_id}/retry`.
8. Backend resets the workflow to `pending`. The cycle resumes from step 6 of the happy path.

#### Error Path: Page Reload During Job

1. User initiates course generation. Job is at 45% progress.
2. User accidentally refreshes the browser page.
3. On mount, `useJobNotifications` hook checks `sessionStorage` for `last_event_id` and `active_job_ids`.
4. Hook finds `active_job_ids = ['<job_id>']` and `last_event_id = '42'`.
5. Hook calls `GET /api/v1/events/poll?since=42&job_ids=<job_id>` to replay events since the last known event.
6. Backend returns all events from event_id 43 to current (including the current `running` status and progress).
7. Frontend reconstructs the current job state from the replayed events.
8. Hook then opens a new SSE connection (or continues polling) from the current state.
9. The progress bar re-renders at the correct 45% position.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 GET /api/v1/events/subscribe -- SSE Subscription Endpoint

```
GET /api/v1/events/subscribe?job_ids=uuid1,uuid2&types=workflow_job,preview_job
Authorization: Bearer <session_token>
Accept: text/event-stream
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_ids` | string (comma-separated UUIDs) | No | Subscribe to specific job UUIDs. If omitted, subscribes to all jobs authorized for the session. |
| `types` | string (comma-separated) | No | Filter by job type: `workflow_job`, `preview_job`, `import_job`, `proposal_preview`. If omitted, all types are included. |
| `token` | string | No | JWT token for `EventSource` compatibility (since `EventSource` does not support custom headers). If present, validated instead of `Authorization` header. |

**Response (200 OK):**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

: heartbeat

event: status_change
id: 101
data: {"event_id":"f1a2b3c4-...","event_type":"status_change","job_id":"a1b2c3d4-...","job_type":"workflow_job","previous_status":"pending","current_status":"running","progress":0.0,"current_state":"validate_input","message":null,"metadata":{},"timestamp":"2026-06-14T10:30:01Z"}

event: progress_update
id: 102
data: {"event_id":"f1a2b3c5-...","event_type":"progress_update","job_id":"a1b2c3d4-...","job_type":"workflow_job","previous_status":"running","current_status":"running","progress":0.05,"current_state":"generate_pages","message":"Generating page 1 of 20: Introduction","metadata":{"pages_total":20,"pages_generated":1},"timestamp":"2026-06-14T10:30:15Z"}

event: completed
id: 150
data: {"event_id":"f1a2b3c6-...","event_type":"completed","job_id":"a1b2c3d4-...","job_type":"workflow_job","previous_status":"running","current_status":"complete","progress":1.0,"current_state":"complete","message":"Course generation completed. Created 20 pages.","metadata":{"total_pages":20,"batch_proposal_id":"bp-123","duration_seconds":187},"timestamp":"2026-06-14T10:33:08Z"}

event: terminated
id: 151
retry: 3000
data: {"event_id":"f1a2b3c7-...","event_type":"terminated","job_id":null,"job_type":null,"previous_status":null,"current_status":"terminated","progress":null,"current_state":null,"message":"Subscription duration limit reached. Reconnect to continue receiving updates.","metadata":{"reconnect_delay_ms":3000},"timestamp":"2026-06-14T11:00:08Z"}
```

**Error Responses:**
- 401: `{"code": "AUTHENTICATION_REQUIRED", "message": "Missing or invalid session token"}` (response body is JSON, not SSE)
- 403: `{"code": "FORBIDDEN", "message": "Session does not have access to the requested job_ids"}`
- 422: `{"code": "VALIDATION_ERROR", "field": "job_ids", "message": "Invalid UUID format in job_ids parameter"}`
- 429: `{"code": "RATE_LIMITED", "message": "Too many SSE connections from this session. Max 3 concurrent connections per session."}` (response body is JSON, not SSE)

**Rate Limiting:**
- Maximum 3 concurrent SSE connections per session token.
- Maximum 30-minute connection duration. After 30 minutes, server sends `terminated` event with `retry: 3000`.
- Maximum 100 SSE connections per user across all sessions.
- These limits are configurable via environment variables (see section 2.5).

#### 2.1.2 GET /api/v1/events/poll -- Polling Fallback Endpoint

```
GET /api/v1/events/poll?since=42&job_ids=a1b2c3d4-...,f2a3b4c5-...&limit=100
Authorization: Bearer <session_token>
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `since` | integer (event_id) | Yes | Return only events with `event_id > since`. Pass `0` to get all events. |
| `job_ids` | string (comma-separated UUIDs) | No | Filter by job UUIDs. If omitted, returns events for all jobs the session can access. |
| `limit` | integer (1-500) | No | Maximum number of events to return. Default 100, max 500. |
| `types` | string (comma-separated) | No | Filter by job type(s). |

**Response (200 OK):**
```json
{
  "events": [
    {
      "event_id": 43,
      "event_type": "progress_update",
      "job_id": "a1b2c3d4-...",
      "job_type": "workflow_job",
      "previous_status": "running",
      "current_status": "running",
      "progress": 0.10,
      "current_state": "generate_pages",
      "message": "Generating page 2 of 20: Getting Started",
      "metadata": {
        "pages_total": 20,
        "pages_generated": 2
      },
      "timestamp": "2026-06-14T10:30:28Z"
    }
  ],
  "has_more": false,
  "latest_event_id": 150,
  "total_returned": 1
}
```

**Error Responses:**
- 400: `{"code": "INVALID_SINCE", "message": "since parameter must be a non-negative integer"}`
- 401: `{"code": "AUTHENTICATION_REQUIRED", "message": "Missing or invalid session token"}`
- 422: `{"code": "VALIDATION_ERROR", "field": "job_ids", "message": "Invalid UUID format"}`

#### 2.1.3 DELETE /api/v1/events/subscribe -- Close SSE Connection from Client

```
DELETE /api/v1/events/subscribe?job_ids=uuid1,uuid2
Authorization: Bearer <session_token>
```

Optional: allows the frontend to explicitly signal that it is no longer interested in events for specific job_ids, so the server can clean up its fan-out subscription list without waiting for connection closure.

**Response (200 OK):**
```json
{
  "unsubscribed_job_ids": ["a1b2c3d4-...", "f2a3b4c5-..."],
  "remaining_subscriptions": 2
}
```

#### 2.1.4 JobEvent Pydantic Model

```python
# app/models/events.py

from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from uuid import UUID


class JobEvent(BaseModel):
    """Unified job event schema for both SSE and polling."""
    event_id: int = Field(..., description="Monotonically increasing event ID from the outbox")
    event_type: str = Field(..., description="Event type: status_change, progress_update, heartbeat, error, completed, cancelled, terminated")
    job_id: UUID = Field(..., description="The job UUID this event relates to")
    job_type: str = Field(..., description="Job type discriminator: workflow_job, preview_job, import_job, proposal_preview")
    previous_status: Optional[str] = Field(None, description="Previous job status before this event")
    current_status: str = Field(..., description="Current job status after this event")
    progress: Optional[float] = Field(None, ge=0.0, le=1.0, description="Job progress 0.0 to 1.0")
    current_state: Optional[str] = Field(None, description="Current state within the job's state machine")
    message: Optional[str] = Field(None, description="Human-readable description of the current event")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata payload")
    timestamp: datetime = Field(..., description="ISO-8601 timestamp of when the event was published")


class JobEventPollResponse(BaseModel):
    events: list[JobEvent]
    has_more: bool
    latest_event_id: int
    total_returned: int


class SSEEventPayload(BaseModel):
    """SSE wire format -- same data, serialized as JSON in the data: field."""
    event_id: str  # UUID v7 for global uniqueness
    event_type: str
    job_id: str
    job_type: str
    previous_status: Optional[str]
    current_status: str
    progress: Optional[float]
    current_state: Optional[str]
    message: Optional[str]
    metadata: dict[str, Any]
    timestamp: str  # ISO-8601 string
```

#### 2.1.5 TypeScript Types (Frontend)

```typescript
// src/ai/types/events.ts

export type JobEventType =
  | 'status_change'
  | 'progress_update'
  | 'heartbeat'
  | 'error'
  | 'completed'
  | 'cancelled'
  | 'terminated';

export type JobType = 'workflow_job' | 'preview_job' | 'import_job' | 'proposal_preview';

export interface JobEvent {
  eventId: number;
  eventType: JobEventType;
  jobId: string;
  jobType: JobType;
  previousStatus: string | null;
  currentStatus: string;
  progress: number | null;
  currentState: string | null;
  message: string | null;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export interface JobStatus {
  jobId: string;
  jobType: JobType;
  currentStatus: string;
  currentState: string | null;
  progress: number;
  message: string | null;
  metadata: Record<string, unknown>;
  lastUpdated: string;
}

export type ConnectionMode = 'sse' | 'polling' | 'offline';

export interface UseJobNotificationsOptions {
  sseBaseUrl?: string;        // Default: '/api/v1/events/subscribe'
  pollBaseUrl?: string;       // Default: '/api/v1/events/poll'
  pollingFallback?: boolean;  // Default: true
  initialPollIntervalMs?: number; // Default: 2000
  maxPollIntervalMs?: number;     // Default: 10000
  minPollIntervalMs?: number;     // Default: 1000
  idlePollCountThreshold?: number; // Default: 3
}

export interface UseJobNotificationsReturn {
  events: JobEvent[];
  statuses: Map<string, JobStatus>;
  isConnected: boolean;
  connectionMode: ConnectionMode;
  error: string | null;
  reconnect: () => void;
  clearEvents: () => void;
  unsubscribe: (jobIds: string[]) => void;
}
```

### 2.2 Database Schema

#### 2.2.1 `job_events_outbox` Table

```sql
CREATE TABLE job_events_outbox (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    
    -- Global event identifier (UUID v7 for distributed ordering)
    event_uuid      UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    
    -- Event classification
    event_type      VARCHAR(32)   NOT NULL
                    CHECK (event_type IN (
                        'status_change', 'progress_update', 'heartbeat',
                        'error', 'completed', 'cancelled', 'terminated'
                    )),
    
    -- Job reference
    job_id          UUID          NOT NULL,
    job_type        VARCHAR(32)   NOT NULL
                    CHECK (job_type IN (
                        'workflow_job', 'preview_job', 'import_job', 'proposal_preview'
                    )),
    
    -- Status transition
    previous_status VARCHAR(64),
    current_status  VARCHAR(64)   NOT NULL,
    
    -- Progress and state
    progress        REAL          CHECK (progress IS NULL OR (progress >= 0.0 AND progress <= 1.0)),
    current_state   VARCHAR(128),
    
    -- Human-readable payload
    message         TEXT,
    metadata        JSONB         NOT NULL DEFAULT '{}'::jsonb,
    
    -- Timing
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Index for since-based gap-filling queries (polling fallback)
CREATE INDEX idx_job_events_outbox_id ON job_events_outbox (id);

-- Index for job-filtered queries (SSE fan-out filter)
CREATE INDEX idx_job_events_outbox_job_event ON job_events_outbox (job_id, id);

-- Index for type-filtered queries (admin dashboard)
CREATE INDEX idx_job_events_outbox_type_event ON job_events_outbox (job_type, id);

-- Index for janitor cleanup
CREATE INDEX idx_job_events_outbox_created ON job_events_outbox (created_at);

-- Partition hint: for production with high volume, partition by month on created_at
-- CREATE TABLE job_events_outbox_y2026m06 PARTITION OF job_events_outbox
--     FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

#### 2.2.2 `sse_subscriptions` Table (for Server-Side Subscription Tracking)

```sql
CREATE TABLE sse_subscriptions (
    id                  BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    
    -- Client identification
    subscription_id     UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    session_id          UUID          NOT NULL REFERENCES ai_sessions(id) ON DELETE CASCADE,
    user_id             VARCHAR(64)   NOT NULL,
    
    -- Subscription filter criteria
    subscribed_job_ids  UUID[]        NOT NULL DEFAULT '{}',
    subscribed_types    VARCHAR(32)[] NOT NULL DEFAULT '{}',
    
    -- Connection metadata
    connected_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_heartbeat_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_event_id_sent  BIGINT        NOT NULL DEFAULT 0,
    
    -- Expiry
    expires_at          TIMESTAMPTZ   NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes'),
    
    -- Status
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_sse_subs_session ON sse_subscriptions (session_id) WHERE is_active = TRUE;
CREATE INDEX idx_sse_subs_expires ON sse_subscriptions (expires_at) WHERE is_active = TRUE;
```

#### 2.2.3 Alembic Migration

```python
"""Create event notification tables

Revision ID: 20260614_0003
Revises: 20260614_0002  # follows workflow engine migration
Create Date: 2026-06-14 12:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

revision: str = "20260614_0003"
down_revision: Union[str, None] = "20260614_0002"  # to be filled
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- job_events_outbox --
    op.create_table(
        "job_events_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_uuid", UUID(), nullable=False, unique=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("job_id", UUID(), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(64), nullable=True),
        sa.Column("current_status", sa.String(64), nullable=False),
        sa.Column("progress", sa.REAL(), nullable=True),
        sa.Column("current_state", sa.String(128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_job_events_outbox_id", "job_events_outbox", ["id"])
    op.create_index("idx_job_events_outbox_job_event", "job_events_outbox", ["job_id", "id"])
    op.create_index("idx_job_events_outbox_type_event", "job_events_outbox", ["job_type", "id"])
    op.create_index("idx_job_events_outbox_created", "job_events_outbox", ["created_at"])

    # -- sse_subscriptions --
    op.create_table(
        "sse_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("subscription_id", UUID(), nullable=False, unique=True),
        sa.Column("session_id", UUID(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("subscribed_job_ids", ARRAY(UUID()), nullable=False, server_default="{}"),
        sa.Column("subscribed_types", ARRAY(sa.String(32)), nullable=False, server_default="{}"),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_event_id_sent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
    )
    op.create_index("idx_sse_subs_session", "sse_subscriptions", ["session_id"])
    op.create_index("idx_sse_subs_expires", "sse_subscriptions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("sse_subscriptions")
    op.drop_table("job_events_outbox")
```

### 2.3 Service/Module Design

#### 2.3.1 Backend Module Structure

```
app/services/events/
├── __init__.py
├── publisher.py              # EventPublisher: writes to outbox, signals broadcaster
├── broadcaster.py            # EventBroadcaster: background task that fans out events to SSE connections
├── sse_manager.py            # SSESubscriptionManager: manages active SSE connections per session
├── outbox_janitor.py         # OutboxJanitor: background task that cleans old events
├── router.py                 # FastAPI router for /api/v1/events/* endpoints
├── models.py                 # Pydantic models (JobEvent, SSEEventPayload, etc.)
└── dependencies.py           # FastAPI dependencies (get_sse_manager, get_event_publisher)
```

#### 2.3.2 EventPublisher Service

```python
# app/services/events/publisher.py

class EventPublisher:
    """
    Publishes job events to the outbox and notifies the SSE broadcaster.
    
    Usage:
        publisher = EventPublisher(db_session, broadcaster_queue)
        await publisher.publish(
            job_id=job_id,
            job_type='workflow_job',
            event_type='progress_update',
            previous_status='running',
            current_status='running',
            progress=0.45,
            current_state='generate_pages',
            message='Generating page 9 of 20: Variables',
            metadata={'pages_total': 20, 'pages_generated': 9}
        )
    """
    
    async def publish(
        self,
        job_id: UUID,
        job_type: str,
        event_type: str,
        previous_status: Optional[str],
        current_status: str,
        progress: Optional[float] = None,
        current_state: Optional[str] = None,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        """Write event to outbox and signal broadcaster. Returns the event ID."""
        # 1. Validate event_type and job_type against allowed enums.
        # 2. INSERT INTO job_events_outbox ...
        # 3. RETURNING id into local variable.
        # 4. Put (event_id, job_id, job_type) onto the broadcaster asyncio.Queue.
        # 5. Return event_id.
        # Must complete within 50ms. The broadcaster processes asynchronously.
```

#### 2.3.3 EventBroadcaster Background Worker

```python
# app/services/events/broadcaster.py

class EventBroadcaster:
    """
    Background task that reads events from the publisher queue and fans them out
    to all active SSE subscriptions whose filter criteria match.
    
    Spawned in main.py lifespan:
        broadcaster = EventBroadcaster()
        task = asyncio.create_task(broadcaster.run())
    
    The run() loop:
        1. await self.queue.get()  -- blocks until a new event is published.
        2. Query sse_subscriptions WHERE is_active = TRUE
           AND (subscribed_job_ids @> ARRAY[event.job_id] OR subscribed_job_ids = '{}')
           AND (subscribed_types @> ARRAY[event.job_type] OR subscribed_types = '{}').
        3. For each matching subscription, write the SSE-formatted event to the
           subscription's asyncio.Queue (one per SSE connection).
        4. Update last_event_id_sent on the subscription row.
        5. If a subscription's queue is full (backpressure), drop the oldest event
           from that queue and log a warning.
    
    Concurrency:
        - Maximum 1000 concurrent SSE connections (configurable).
        - Each connection has its own asyncio.Queue with maxsize=100.
        - The broadcaster loop is single-threaded and must process each event
          in O(N) where N is the number of active subscriptions. For N > 500,
          the broadcaster should batch: collect events for 50ms or 50 events,
          then fan-out in a single batch per subscription.
    """
```

#### 2.3.4 SSESubscription Manager

```python
# app/services/events/sse_manager.py

class SSESubscriptionManager:
    """
    Manages individual SSE connections.
    
    create_subscription(session_id, user_id, job_ids, types) -> subscription_id
        - Inserts a row into sse_subscriptions.
        - Creates an asyncio.Queue for this subscription.
        - Registers the queue in the broadcaster's subscription registry.
    
    get_event_stream(subscription_id) -> AsyncGenerator[str, None]
        - FastAPI endpoint uses this to stream SSE events.
        - Yields SSE-formatted strings from the subscription queue.
        - Sends heartbeat comments every 15 seconds via a separate task.
        - On generator exit (client disconnect), marks subscription inactive.
    
    close_subscription(subscription_id)
        - Marks sse_subscriptions.is_active = FALSE.
        - Removes queue from broadcaster's registry.
    
    get_active_count() -> int
        - Returns count of active subscriptions.
    
    cleanup_expired_subscriptions()
        - Background task that runs every 60 seconds.
        - SELECT FROM sse_subscriptions WHERE expires_at < NOW() AND is_active = TRUE.
        - For each expired subscription, puts a 'terminated' event in its queue
          and marks it inactive.
    """
```

#### 2.3.5 SSEResponse FastAPI Endpoint

```python
# app/services/events/router.py

router = APIRouter(prefix="/api/v1/events", tags=["Events"])

@router.get("/subscribe")
async def subscribe_sse(
    request: Request,
    job_ids: Optional[str] = Query(None, description="Comma-separated job UUIDs"),
    types: Optional[str] = Query(None, description="Comma-separated job types"),
    token: Optional[str] = Query(None, description="JWT for EventSource compatibility"),
    session: AISession = Depends(get_session_from_token_or_header),
    sse_manager: SSESubscriptionManager = Depends(get_sse_manager),
    event_publisher: EventPublisher = Depends(get_event_publisher),
):
    """SSE endpoint for real-time job status updates."""
    
    # 1. Validate parameters.
    # 2. Enforce rate limits (max 3 concurrent per session).
    # 3. Check authorization for requested job_ids.
    # 4. Create subscription.
    # 5. Return StreamingResponse with media_type="text/event-stream".
    
    return StreamingResponse(
        sse_manager.get_event_stream(subscription_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/poll")
async def poll_events(
    since: int = Query(..., description="Return events with ID > since"),
    job_ids: Optional[str] = Query(None, description="Comma-separated job UUIDs"),
    limit: int = Query(100, ge=1, le=500, description="Max events to return"),
    types: Optional[str] = Query(None, description="Comma-separated job types"),
    session: AISession = Depends(get_session_from_token_or_header),
    db: AsyncSession = Depends(get_session),
) -> JobEventPollResponse:
    """Polling fallback: returns events since a given event_id."""
    # 1. Build query from job_events_outbox WHERE id > since.
    # 2. Apply job_ids and types filters if provided.
    # 3. Check authorization for filtered job_ids.
    # 4. Return ordered list of events with pagination metadata.
    ...


@router.delete("/subscribe")
async def unsubscribe_events(
    job_ids: str = Query(..., description="Comma-separated job UUIDs to unsubscribe from"),
    session: AISession = Depends(get_session_from_token_or_header),
    sse_manager: SSESubscriptionManager = Depends(get_sse_manager),
):
    """Remove job_ids from the active subscription filter."""
    ...
```

#### 2.3.6 Frontend Hook Implementation

```typescript
// src/ai/hooks/useJobNotifications.ts

export function useJobNotifications(
  jobIds: string[],
  options?: UseJobNotificationsOptions
): UseJobNotificationsReturn {
  // ... implementation using React hooks (useState, useEffect, useCallback, useRef)
  
  // Internal state machine:
  // 1. MOUNT -> attemptSSE()
  // 2. SSE_OPEN -> receiveEvents() -> updateState()
  // 3. SSE_ERROR -> attemptPollFallback() (if pollingFallback enabled)
  // 4. POLLING -> setInterval() -> fetchEvents() -> updateState()
  // 5. RECONNECT -> closeSSE() -> attemptSSE() (with Last-Event-ID header simulation via ?since=)
  // 6. UNMOUNT -> closeSSE() / clearInterval() / abortPendingRequests()
  // 7. TAB_HIDDEN -> switchToPolling(30s interval)
  // 8. TAB_VISIBLE -> replayMissedEvents() -> attemptSSE()
}
```

### 2.4 Integration Points

| Integration | Direction | Description |
|---|---|---|
| US-AI-034 (WorkflowOrchestrator) | Calls EventPublisher | After every state transition in the workflow engine, calls `publish()` with state machine event data. |
| US-AI-041 (PreviewWorker) | Calls EventPublisher | After every preview status change (pending -> rendering -> ready/failed), calls `publish()`. |
| ImportJobService (existing) | Calls EventPublisher | After import job state transitions (pending -> processing -> completed/failed), calls `publish()`. Migration path: existing ImportJob status updates should be extended to call `EventPublisher.publish()`. |
| US-AI-024 (Frontend AI Integration Layer) | Consumes SSE/Poll events | `useJobNotifications` hook integrated into `AIPanel.tsx`, file ingestion flow, and preview cards. |
| US-AI-020 (Admin Dashboard) | Consumes SSE events | Admin event monitor subscribes to all job types without job_id filter. |
| main.py lifespan | Spawns/tears down | Spawns `EventBroadcaster`, `OutboxJanitor`, and `SubscriptionCleaner` background tasks on startup. Gracefully cancels them on shutdown. |

### 2.5 Configuration Variables

```python
# app/core/config.py additions

# -- Event Notification Configuration --
EVENTS_SSE_ENABLED: bool = True
"""Master toggle for SSE support. When False, only polling fallback is available."""

EVENTS_MAX_CONCURRENT_SSE_PER_SESSION: int = 3
"""Maximum concurrent SSE connections per session token."""

EVENTS_MAX_CONCURRENT_SSE_PER_USER: int = 100
"""Maximum concurrent SSE connections per user across all sessions."""

EVENTS_SSE_HEARTBEAT_INTERVAL_SECONDS: int = 15
"""Interval between SSE heartbeat comments."""

EVENTS_SSE_MAX_DURATION_SECONDS: int = 1800
"""Maximum SSE connection duration (1800s = 30 minutes)."""

EVENTS_POLL_MAX_LIMIT: int = 500
"""Maximum number of events returned by the poll endpoint."""

EVENTS_OUTBOX_CLEANUP_DAYS: int = 7
"""Events older than this many days are deleted by the janitor."""

EVENTS_OUTBOX_CLEANUP_BATCH_SIZE: int = 5000
"""Number of rows deleted per batch during cleanup."""

EVENTS_OUTBOX_CLEANUP_INTERVAL_SECONDS: int = 3600
"""How often the janitor runs (3600s = 1 hour)."""

EVENTS_BROADCASTER_TICK_MS: int = 50
"""Maximum time the broadcaster waits to batch events before fan-out (50ms)."""
```

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance Targets

| Requirement | Target | Measurement |
|---|---|---|
| Event publish latency (p50) | < 10 ms | From caller invoking `publish()` to outbox INSERT return. |
| Event publish latency (p99) | < 50 ms | Under load of 1000 events/second. |
| SSE fan-out latency (p50) | < 100 ms | From outbox write to event appearing on all matched SSE connections for N=100 connections. |
| SSE fan-out latency (p99) | < 500 ms | From outbox write to event appearing on all matched SSE connections for N=1000 connections. |
| Poll endpoint response time (p95) | < 200 ms | For queries filtering by since=latest and job_ids. |
| Max concurrent SSE connections | 1000 | Across all sessions on a single backend instance. |
| Max events per second | 2000 | Sustained publish rate before backpressure/throttling kicks in. |
| Outbox janitor impact | < 5% CPU | During cleanup batches. Must not block writers (DELETE uses non-conflicting lock mode). |
| Frontend SSE reconnect time | < 2 seconds | From disconnect to re-established connection. |
| Frontend SSE-to-polling fallover | < 1 second | From SSE error detection to first poll request. |

### 3.2 Security Requirements

1. **Authentication:** All `/api/v1/events/*` endpoints require a valid session token (same scheme as other `/api/v1/ai/*` endpoints). The token must be provided either as `Authorization: Bearer <token>` or as a `?token=` query parameter (for `EventSource` compatibility). The query parameter approach must only be accepted on the SSE endpoint, not on poll or DELETE endpoints.

2. **Authorization:** The server must verify that the session has access to every job_id in the subscription filter. For admin sessions (US-AI-020), job_ids filtering is optional and all jobs are visible. For regular sessions, only jobs scoped to the session's course_id are accessible.

3. **Rate Limiting:** Hard limits on concurrent SSE connections per session (3) and per user (100). Violations return HTTP 429 with a JSON body explaining which limit was exceeded and when the client may retry.

4. **Data Isolation:** Event metadata must never include sensitive user data (passwords, API keys, PII). The `EventPublisher` must accept a `sanitize_metadata` parameter or sanitize metadata automatically based on a denylist of keys.

5. **SSE Injection Prevention:** All event fields must be JSON-encoded before transmission. The SSE `data:` field must be followed by a valid JSON string. No user-supplied content is ever placed directly into an SSE field without JSON encoding.

6. **Connection Hijacking Prevention:** The `subscription_id` (UUID v4) is cryptographically random and serves as the de facto connection token. If an attacker obtains a valid `subscription_id` and `session_id`, they could hijack an SSE stream. Mitigation: the SSE stream generator validates that the calling session matches the subscription's session_id before yielding any events. This is enforced server-side, not client-side.

### 3.3 Reliability Requirements

1. **No Event Loss:** If the backend process crashes between `EventPublisher.publish()` committing the outbox INSERT and the `EventBroadcaster` fanning out, the event is not lost. On restart, the broadcaster reads the `sse_subscriptions` table and replays events from `last_event_id_sent` forward for each active subscription. Duplicate events are possible (at-most-once delivery), but event loss is not.

2. **At-Most-Once Delivery Guarantee:** The SSE system provides at-most-once delivery. The frontend uses the polling gap-filling endpoint to retrieve missed events on reconnect. The frontend is responsible for deduplication using `event_id`.

3. **Graceful Degradation:** If the `job_events_outbox` INSERT fails (e.g., database connection lost), the `EventPublisher.publish()` method must raise an exception to the caller. The caller (WorkflowOrchestrator, PreviewWorker, etc.) must handle this by logging the error and continuing -- the job state machine transition is not rolled back if event publishing fails. The event can be retried on the next state transition.

4. **Backpressure:** If an SSE client is slow to consume events (its `asyncio.Queue` reaches `maxsize=100`), the broadcaster drops the oldest undelivered event for that client and logs a warning. The dropped event count is exposed as a metric. The client can recover missed events via the poll gap-filling endpoint on reconnect.

5. **Connection Draining:** On application shutdown (SIGTERM/SIGINT), the lifespan handler must:
   - Stop accepting new SSE subscriptions (return 503).
   - Set a 10-second grace period for existing connections to drain.
   - Send a `terminated` event with `retry: 10000` to all active subscriptions.
   - Mark all active subscriptions as inactive.
   - Cancel background tasks (broadcaster, janitor, subscription cleaner).

### 3.4 Scalability Requirements

1. **Horizontal Scaling:** The SSE notification system is designed for single-instance use in MVP. For horizontal scaling (multiple backend instances), the system must be extended with a shared event bus (Redis Pub/Sub, NATS, or PostgreSQL `LISTEN/NOTIFY`). This is explicitly out of scope for this story but the architecture must support it: the `EventBroadcaster` should be replaceable with a distributed pub/sub adapter without changing the `EventPublisher` API.

2. **Database Load:** At 2000 events/second with 1000 concurrent SSE connections, the `job_events_outbox` INSERT rate is 2000 rows/second (approximately 400 KB/s at 200 bytes/row). The `sse_subscriptions` query on fan-out (once per event) must be efficient: the index on `(job_id, id)` ensures sub-millisecond lookup for the most common filter path (by job_id). For the catch-all case (admin dashboard), the index on `(event_id)` is used with a sequential scan -- acceptable for N < 1000 subscriptions.

3. **Memory Footprint:** Each SSE connection maintains an `asyncio.Queue` with `maxsize=100`. At 200 bytes per event, each connection uses approximately 20 KB of queue memory. At 1000 connections, this is 20 MB. The `sse_subscriptions` table in memory (SQLAlchemy ORM instances) adds another ~1 MB. Total memory footprint for the event system at scale is approximately 50 MB.

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists

1. **US-AI-024 `pollJob()`:** The frontend `src/ai/hooks/useFileIngestion.ts` contains a `pollJob` function that polls `GET /api/v1/imports/jobs/{job_id}` every 2 seconds. This is tightly coupled to the file ingestion flow and uses a dedicated endpoint with a non-standard response format.

2. **US-AI-034 Polling in Frontend:** The durable workflow engine specification recommends the frontend poll `GET /api/v1/workflows/{job_id}` every 2 seconds. No unified hook or connection management exists.

3. **US-AI-041 Preview Polling:** The preview generation service expects the frontend to poll `GET /api/v1/ai/proposals/{proposal_id}/preview` every 2 seconds. Another disconnected polling implementation.

4. **Existing `ImportJob` Model:** The `ImportJob` ORM model in `app/models/persisted_course.py` has `status`, `progress`, and `error_message` fields but no event publishing mechanism.

5. **`WorkflowJob` Model:** The WorkflowJob in `app/models/workflow.py` (from US-AI-034) has heartbeats but no event outbox integration.

6. **Frontend `sessionStorage` Usage:** The frontend already uses `sessionStorage` for AI session data (token, expiry), providing a pattern for storing `last_event_id` and `active_job_ids`.

7. **`main.py` Lifespan:** The application already uses the `lifespan` context manager for startup/shutdown lifecycle, into which the `EventBroadcaster`, `OutboxJanitor`, and `SubscriptionCleaner` tasks can be integrated.

### 4.2 What Must Be Built

1. **`app/services/events/` module (entirely new):**
   - `publisher.py` -- `EventPublisher` class with `publish()` method.
   - `broadcaster.py` -- `EventBroadcaster` background worker.
   - `sse_manager.py` -- `SSESubscriptionManager` with connection lifecycle.
   - `outbox_janitor.py` -- `OutboxJanitor` background cleanup task.
   - `router.py` -- FastAPI router for `/api/v1/events/subscribe`, `/api/v1/events/poll`, `/api/v1/events/subscribe` (DELETE).
   - `models.py` -- `JobEvent`, `JobEventPollResponse`, `SSEEventPayload` Pydantic models.
   - `dependencies.py` -- FastAPI dependency injection for event services.

2. **Database tables:**
   - `job_events_outbox` (new)
   - `sse_subscriptions` (new)

3. **Frontend `src/ai/hooks/useJobNotifications.ts` (entirely new):**
   - React hook with SSE + adaptive polling fallback.
   - Connection lifecycle management.
   - Tab visibility handling.
   - Reconnection with gap-filling.

4. **Frontend `src/ai/types/events.ts` (new):**
   - TypeScript types for `JobEvent`, `JobStatus`, `ConnectionMode`, etc.

5. **Frontend visual components (new/modified):**
   - `CompactProgressBar` component for chat panel inline progress.
   - `JobStatusPanel` component for detailed workflow detail side panel.
   - Integration with existing toast notification system.

### 4.3 What Must Be Modified

1. **`app/main.py`:** Add lifespan hooks to spawn/cancel `EventBroadcaster`, `OutboxJanitor`, `SubscriptionCleaner` background tasks. Register `events.router`.

2. **`app/services/workflow/orchestrator.py` (from US-AI-034):** After each state machine transition, call `EventPublisher.publish()` with the state transition data. This is approximately 10-15 lines added to the orchestrator's step execution loop.

3. **`app/services/ai/preview_service.py` (from US-AI-041):** In the PreviewWorker, after each preview status change, call `EventPublisher.publish()`.

4. **`app/services/import_service.py` (existing):** Extend the import job status update paths to call `EventPublisher.publish()`. This is a non-breaking additive change.

5. **`app/core/config.py`:** Add the 12 configuration variables defined in section 2.5.

6. **`src/ai/hooks/useFileIngestion.ts` (from US-AI-024):** Replace the inline polling logic with `useJobNotifications` hook integration. The `pollJob` function is deprecated in favor of the unified hook.

7. **`src/ai/components/AIPanel.tsx` (from US-AI-024):** Integrate `useJobNotifications` for the compact progress bar in the chat panel.

8. **`src/ai/components/ExtractionPreview.tsx` (from US-AI-024):** Replace inline polling with `useJobNotifications` for course generation status.

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion Points

1. **Redis/NATS Pub/Sub Backplane for Horizontal Scaling (TECH-1):** The current `EventBroadcaster` uses an in-process `asyncio.Queue` to receive events from `EventPublisher`. For horizontal scaling (multiple backend instances), the publisher must publish to a shared Redis Pub/Sub channel or NATS subject, and each instance's broadcaster must subscribe to that channel. The `EventPublisher` and `EventBroadcaster` interfaces should be abstracted behind an `EventBus` protocol so the in-process implementation can be replaced without changing service code.

2. **WebSocket Upgrade Path for Bidirectional Needs (TECH-2):** If future requirements demand bidirectional communication (e.g., frontend sending "cancel" without an HTTP request), the SSE infrastructure can be wrapped in a WebSocket upgrade: the initial connection uses SSE, and the server sends an `upgrade` event directing the client to switch to a WebSocket connection at a specific URL. The `EventBroadcaster` queue architecture supports this transparently since both SSE and WebSocket use the same per-connection queue.

3. **Partitioned Outbox for Write Throughput (TECH-3):** At very high scale (10,000+ events/second), the `job_events_outbox` table can be partitioned by month using PostgreSQL declarative partitioning. Each partition inherits the table schema and indexes. The `OutboxJanitor` drops entire partitions instead of running DELETE statements, reducing bloat and vacuum overhead. The `EventPublisher` must be partition-aware (use `pg_partman` or manual partition creation).

4. **Event Schema Registry with Avro/Protobuf (TECH-4):)** As the number of event types grows (future job types, custom events), a schema registry prevents drift between producers and consumers. The `metadata` JSONB field can be replaced with a schema-versioned payload that is validated against a registry. This is a future optimization -- for MVP, JSONB with documentation is sufficient.

### 5.2 Functional Expansion Points

1. **Push Notifications for External Channels (FUNC-1):** Extend the `EventPublisher` to support channel adapters for email, Slack, or webhook delivery. When a job completes or fails, an admin-configurable notification channel sends a message. The outbox already provides the event stream; a new `NotificationDispatcher` worker would read from the outbox and route events to adapters based on user preferences stored in a new `notification_preferences` table.

2. **Per-User Event Preferences and Filtering (FUNC-2):** Allow users to configure which event types trigger toast notifications, which trigger sound alerts, and which are silently recorded. For example: "Notify me only on completion and failure of course generation jobs; ignore preview generation events." Preferences stored in a `user_event_preferences` table, checked by the frontend before showing toasts.

3. **Job Timeline Visualization (FUNC-3):)** The step-by-step timeline (section 1.3 FR6 Tier 2) can be enhanced to show a Gantt-like visualization of job steps with durations, retries, and concurrent step execution. This requires the `WorkflowOrchestrator` to publish additional `step_started` and `step_ended` event types (beyond the current status_change/progress_update pair), and the frontend to implement a timeline chart component.

4. **Automated Alerting Rules for Operators (FUNC-4):** Allow platform operators to define alerting rules: "If a course_generation job fails more than 3 times in 1 hour, send a PagerDuty alert." This hooks into the `job_events_outbox` via a rules engine that evaluates events against user-defined thresholds. The outbox's `created_at` index makes time-window queries efficient.

---

## 6. VALIDATION AND TESTING

### 6.1 Unit Tests (5+)

**UT-01: EventPublisher publishes and returns event ID**
```python
async def test_event_publisher_publishes_event():
    """Verify that EventPublisher.publish() writes to the outbox and returns a
    positive integer event_id."""
    # Arrange: create mock DB session, EventBroadcaster queue
    publisher = EventPublisher(mock_db, mock_queue)
    
    # Act
    event_id = await publisher.publish(
        job_id=uuid4(),
        job_type='workflow_job',
        event_type='status_change',
        previous_status='pending',
        current_status='running',
        progress=0.0,
    )
    
    # Assert
    assert isinstance(event_id, int)
    assert event_id > 0
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    mock_queue.put.assert_awaited_once()
```

**UT-02: EventPublisher validates event_type and job_type enums**
```python
async def test_event_publisher_rejects_invalid_event_type():
    """Verify that publish() raises ValueError for invalid event_type."""
    publisher = EventPublisher(mock_db, mock_queue)
    
    with pytest.raises(ValueError, match="Invalid event_type"):
        await publisher.publish(
            job_id=uuid4(),
            job_type='workflow_job',
            event_type='invalid_event_type',
            previous_status=None,
            current_status='running',
        )
```

**UT-03: SSESubscriptionManager enforces rate limits**
```python
async def test_sse_manager_enforces_session_limit():
    """Verify that a 4th SSE connection from the same session is rejected."""
    manager = SSESubscriptionManager(db_session, max_per_session=3)
    
    # Create 3 subscriptions (should succeed)
    for _ in range(3):
        await manager.create_subscription(session_id=uuid4(), ...)
    
    # 4th subscription should raise RateLimitExceeded
    with pytest.raises(RateLimitExceeded, match="Max 3 concurrent"):
        await manager.create_subscription(session_id=uuid4(), ...)
```

**UT-04: Poll endpoint returns events since given event_id**
```python
async def test_poll_returns_events_since():
    """Verify that GET /api/v1/events/poll?since=X returns only events with id > X."""
    # Arrange: insert 5 events into outbox
    events = []
    for i in range(5):
        e = await insert_outbox_event(job_id=test_job_id)
        events.append(e)
    
    # Act: poll with since=events[2].id
    response = await client.get(f"/api/v1/events/poll?since={events[2].id}&job_ids={test_job_id}")
    data = response.json()
    
    # Assert
    assert len(data['events']) == 2  # events[3] and events[4]
    assert data['latest_event_id'] == events[4].id
    assert data['has_more'] is False
```

**UT-05: Frontend hook transitions from SSE to polling on connection error**
```typescript
// Using Jest + @testing-library/react-hooks
test('useJobNotifications falls back to polling on SSE error', async () => {
  // Arrange: mock EventSource to fire 'error' immediately
  const mockEventSource = mockSSE({ immediateError: true });
  const mockFetch = mockPollEndpoint({ events: [] });
  
  // Act
  const { result, waitForNextUpdate } = renderHook(() =>
    useJobNotifications(['job-1'], { pollingFallback: true })
  );
  
  // Assert
  await waitForNextUpdate();
  expect(result.current.connectionMode).toBe('polling');
  expect(result.current.isConnected).toBe(false);
  expect(mockFetch).toHaveBeenCalledWith(
    expect.stringContaining('/api/v1/events/poll?since=0')
  );
});
```

**UT-06: Frontend hook deduplicates events by event_id**
```typescript
test('useJobNotifications deduplicates events by eventId', async () => {
  // Arrange: simulate receiving the same event twice (SSE reconnection scenario)
  const duplicateEvent: JobEvent = {
    eventId: 42,
    eventType: 'progress_update',
    jobId: 'job-1',
    // ... other fields
  };
  
  // Act
  const { result } = renderHook(() => useJobNotifications(['job-1']));
  act(() => result.current['_testInjectEvent'](duplicateEvent));
  act(() => result.current['_testInjectEvent'](duplicateEvent)); // duplicate
  
  // Assert
  expect(result.current.events).toHaveLength(1);
  expect(result.current.events[0].eventId).toBe(42);
});
```

### 6.2 Integration Tests (3+)

**IT-01: SSE to Polling Fallover (End-to-End)**
```python
async def test_sse_disconnect_triggers_polling_fallback():
    """Test that when SSE connection drops, the frontend falls back to polling
    and the poll endpoint returns events published during the SSE outage."""
    
    # 1. Client A opens SSE connection to /api/v1/events/subscribe?job_ids=job-1.
    # 2. Backend publishes 3 progress_update events for job-1.
    # 3. Client A receives events 1-3 via SSE.
    # 4. Client A's SSE connection is forcibly closed (simulate network drop).
    # 5. Backend publishes events 4-6 while client A is disconnected.
    # 6. Client A detects SSE error, falls back to polling.
    # 7. Client A calls GET /api/v1/events/poll?since=3&job_ids=job-1.
    # 8. Assert response contains events 4, 5, 6.
    # 9. Assert frontend processes events 4-6 and updates progress from 30% to 60%.
```

**IT-02: Concurrent SSE Connections Respect Rate Limits**
```python
async def test_sse_rate_limits_enforced():
    """Test that opening a 4th SSE connection from the same session returns 429."""
    
    # 1. Open 3 SSE connections with the same session token.
    # 2. Open a 4th SSE connection with the same session token.
    # 3. Assert 4th connection returns HTTP 429 with JSON body.
    # 4. Assert error message mentions "Max 3 concurrent connections per session".
    # 5. Close one of the first 3 connections.
    # 6. Open a new SSE connection -- assert it succeeds (HTTP 200 with text/event-stream).
```

**IT-03: Full Flow -- Workflow Job Completes with SSE Notifications**
```python
async def test_workflow_completion_with_sse():
    """Test that a complete workflow job lifecycle publishes correct SSE events."""
    
    # 1. Create a course_generation workflow via POST /api/v1/workflows.
    # 2. Open SSE subscription for the returned job_id.
    # 3. WorkflowOrchestrator processes the job (simulate with mocked step functions).
    # 4. Collect all SSE events received during the job lifecycle.
    # 5. Assert event sequence: status_change(running) -> progress_update(0.1) -> ... -> progress_update(1.0) -> completed.
    # 6. Assert final event has current_status='complete', progress=1.0.
    # 7. Assert workflow_jobs row has status='complete' in database.
```

### 6.3 End-to-End Tests (2+)

**E2E-01: Author Initiates Course Generation and Sees Progress in Real-Time**

Precondition: Author is logged in, has a course with an approved page plan (status `plan_approved`), and is on the course editor page.

1. Author clicks "Confirm and Create" in the extraction preview panel.
2. Frontend calls `POST /api/v1/workflows` with `course_generation` workflow type.
3. Frontend `useJobNotifications` opens SSE connection for the returned `job_id`.
4. Backend `WorkflowOrchestrator` starts processing.
5. Within 3 seconds, the frontend chat panel shows a compact progress bar with 0% progress.
6. As pages are generated, the progress bar updates in real-time (within 2 seconds of each backend page generation) without page refresh.
7. Job status panel (click "Job Status" button in toolbar) shows current step "Generating page X of Y", elapsed time, and estimated remaining time.
8. When generation completes, the progress bar turns green and shows "Course generation complete -- 20 pages created".
9. A global toast notification appears: "Course generation complete. Click to review."
10. Author clicks the toast and is navigated to the course review screen.
11. SSE connection is closed cleanly.

Expected: No polling requests visible in browser DevTools Network tab (only SSE connection). Progress updates appear within 2 seconds of backend state changes.

**E2E-02: Network Interruption During Job -- Frontend Recovers via Polling Fallback**

Precondition: Author has an active course generation job running at approximately 50% progress with an active SSE connection.

1. Developer Tools network throttling is enabled (Offline mode).
2. SSE connection drops. Within 1 second, the UI shows "Connection lost -- updating..." but does not hide the progress bar.
3. After 5 seconds, network throttling is disabled.
4. Within 2 seconds, the frontend detects connectivity restored, calls `GET /api/v1/events/poll?since=<last_event_id>`, and replays missed events.
5. Progress bar jumps from 50% to the current progress (e.g., 75%) without gaps or incorrect intermediate states.
6. The frontend attempts to reopen the SSE connection.
7. If SSE succeeds, `connectionMode` returns to `'sse'`. If SSE fails, `connectionMode` stays at `'polling'` but job state is accurately reflected.
8. Job completes normally. Toast notification appears.

Expected: No duplicate events. No progress regression. User does not need to manually refresh.

### 6.4 Manual QA Steps

1. **SSE Connection Establishment:** Open browser DevTools to the Network tab. Filter by "text/event-stream". Initiate a course generation job. Verify a single SSE connection is established to `/api/v1/events/subscribe?job_ids=<uuid>&token=<jwt>`. Verify the `Content-Type` is `text/event-stream` and `X-Accel-Buffering: no` header is present.

2. **Heartbeat Verification:** Observe the SSE stream in DevTools. Verify that a `: heartbeat` comment (no `event:` or `data:` prefix) is received approximately every 15 seconds. Verify that the connection remains open for at least 5 heartbeats.

3. **Event Content Inspection:** Capture SSE events during a course generation job. Verify each `data:` line is valid JSON. Verify the JSON contains all required fields: `event_id`, `event_type`, `job_id`, `job_type`, `previous_status`, `current_status`, `progress`, `current_state`, `message`, `metadata`, `timestamp`. Verify `progress` values are monotonically non-decreasing.

4. **Tab Visibility Behavior:** Open the course generation page. Initiate a job. Switch to another browser tab. Verify through DevTools that SSE events stop being received (browser throttles inactive tabs). After 60 seconds, switch back to the original tab. Verify the frontend calls the poll endpoint to catch up on missed events within 2 seconds.

5. **Browser Compatibility:** Test SSE connection in Chrome, Firefox, Safari, and Edge. Verify automatic reconnection works in all browsers. Verify the `EventSource` polyfill is not needed for supported browsers (Chrome 6+, Firefox 6+, Safari 5+, Edge 79+). Note: IE11 is not supported.

6. **Backpressure Behavior (Stress Test):** Use a script to publish 500 events in rapid succession for a single job_id. Open an SSE connection on a slow network (DevTools throttling to "Slow 3G"). Verify that the frontend receives events (potentially with backpressure drops) and can recover via polling. Verify no crash or memory leak.

7. **30-Minute Connection Limit:** Initiate a long-running job (or mock one). Leave the SSE connection open. After 30 minutes, verify the server sends a `terminated` event with `retry: 3000`. Verify the frontend automatically reconnects within 3-5 seconds.

8. **Rate Limit Enforcement:** Open 4 browser tabs to the same course editor page. Each tab initiates a separate SSE connection. Verify the 4th connection receives HTTP 429. Close one tab, verify a new connection can be established.

---

## 7. DEFINITION OF DONE

- [ ] The `job_events_outbox` and `sse_subscriptions` tables exist in the database with correct indexes and constraints, verified by running the Alembic migration against a clean PostgreSQL instance.
- [ ] The `EventPublisher.publish()` method writes events to the `job_events_outbox` table and notifies the `EventBroadcaster` via the asyncio queue, verified by unit test UT-01.
- [ ] The `EventBroadcaster` background task fans out events to all matching active SSE subscriptions within 100ms (p50) under normal load, verified by integration test IT-03.
- [ ] The `GET /api/v1/events/subscribe` SSE endpoint streams correctly formatted `text/event-stream` responses with `event:`, `data:`, `id:`, and `retry:` fields, verified by manual QA step 1 and automated SSE parsing test.
- [ ] The SSE endpoint enforces rate limits: max 3 concurrent connections per session and max 100 per user, returning HTTP 429 with JSON body on violation, verified by unit test UT-03 and manual QA step 8.
- [ ] The SSE endpoint enforces the 30-minute connection duration limit, sending a `terminated` event before closing, verified by manual QA step 7.
- [ ] The `GET /api/v1/events/poll` endpoint returns paginated events with correct `since` filtering, verified by unit test UT-04 and integration test IT-01.
- [ ] The frontend `useJobNotifications` hook successfully establishes an SSE connection on mount, verified by unit test UT-05 and E2E test E2E-01.
- [ ] The frontend hook falls back to adaptive polling within 1 second of SSE connection failure, verified by unit test UT-05 and E2E test E2E-02.
- [ ] The frontend hook handles tab visibility changes: switches to 30-second polling when hidden, replays missed events via poll when visible again, verified by manual QA step 4.
- [ ] The frontend renders three visual tiers of progress: compact bar in chat panel, detailed panel in "Job Status" drawer, and global toast on completion/failure, verified by E2E test E2E-01.
- [ ] The `WorkflowOrchestrator` (US-AI-034) calls `EventPublisher.publish()` after every state machine transition, verified by integration test IT-03.
- [ ] The `OutboxJanitor` background task deletes events older than 7 days in batches of 5000 with 1-second pauses, verified by reviewing janitor logs and measuring `job_events_outbox` table size.
- [ ] The `SubscriptionCleaner` background task marks expired subscriptions as inactive every 60 seconds, verified by reviewing cleaner logs.
- [ ] All configuration variables (section 2.5) are added to `app/core/config.py` with documented defaults and environment variable overrides.
- [ ] The application lifespan handler in `main.py` correctly spawns and cancels all background tasks (`EventBroadcaster`, `OutboxJanitor`, `SubscriptionCleaner`), verified by application startup/shutdown logs.
- [ ] At least 6 unit tests (UT-01 through UT-06), 3 integration tests (IT-01 through IT-03), and 2 E2E tests (E2E-01, E2E-02) pass in CI.
- [ ] Manual QA steps 1-8 have been executed and signed off by QA.
- [ ] The `useFileIngestion.ts` hook in US-AI-024 has been refactored to use `useJobNotifications` instead of inline polling, verified by code review.
- [ ] All existing frontend tests continue to pass without modification (no regressions from replacing polling with hook integration).

---

## 8. TASKS AND SUB-TASKS

| Task ID | Task Description | Owner | Estimated Hours | Dependencies | Deliverable |
|---------|-----------------|-------|-----------------|--------------|-------------|
| T-001 | **Create database schema and migration** | Backend Engineer | 4 | US-AI-034 DB schema merged | Alembic migration `20260614_0003` creating `job_events_outbox` and `sse_subscriptions` tables. Verified against clean PG instance. |
| T-001.1 | Write `job_events_outbox` DDL with all columns, constraints, CHECK enums, and indexes | Backend Engineer | 1 | None | DDL SQL in migration |
| T-001.2 | Write `sse_subscriptions` DDL with all columns, indexes, and FK to `ai_sessions` | Backend Engineer | 1 | T-001.1 | DDL SQL in migration |
| T-001.3 | Write Alembic migration script with upgrade/downgrade paths | Backend Engineer | 1 | T-001.2 | Migration `.py` file |
| T-001.4 | Write downgrade that drops both tables and indexes | Backend Engineer | 0.5 | T-001.3 | Downgrade function |
| T-001.5 | Add ORM models for both tables in `app/models/events.py` | Backend Engineer | 0.5 | T-001.3 | Python SQLAlchemy models |
| T-002 | **Implement EventPublisher service** | Backend Engineer | 6 | T-001 | `app/services/events/publisher.py` with `publish()` method, enum validation, outbox INSERT, and broadcaster signal. |
| T-002.1 | Define `JobEvent`, `SSEEventPayload`, `JobEventPollResponse` Pydantic models in `app/services/events/models.py` | Backend Engineer | 1 | None | Pydantic models |
| T-002.2 | Implement `EventPublisher.publish()` with DB write and queue signal | Backend Engineer | 3 | T-002.1 | Publisher implementation |
| T-002.3 | Implement event_type and job_type validation with enum constrains | Backend Engineer | 1 | T-002.2 | Enum validation |
| T-002.4 | Write unit tests UT-01, UT-02 for EventPublisher | Backend Engineer | 1 | T-002.2 | Test file `tests/test_event_publisher.py` |
| T-003 | **Implement EventBroadcaster background worker** | Backend Engineer | 8 | T-002 | `app/services/events/broadcaster.py` with fan-out loop, per-connection queues, backpressure handling. |
| T-003.1 | Implement `EventBroadcaster` class with `asyncio.Queue` input and subscription registry | Backend Engineer | 3 | T-002 | Broadcaster class |
| T-003.2 | Implement fan-out logic: query matching subscriptions, write events to per-connection queues | Backend Engineer | 3 | T-003.1 | Fan-out logic |
| T-003.3 | Implement backpressure: drop oldest event when queue exceeds `maxsize=100`, log warning, track dropped count metric | Backend Engineer | 1 | T-003.2 | Backpressure logic |
| T-003.4 | Implement event batching: collect events for 50ms or 50 events before fan-out | Backend Engineer | 1 | T-003.1 | Batching logic |
| T-004 | **Implement SSESubscriptionManager and SSE endpoint** | Backend Engineer | 10 | T-003 | `app/services/events/sse_manager.py` and `router.py` with full SSE lifecycle, heartbeat, rate limiting, auth. |
| T-004.1 | Implement `SSESubscriptionManager` with create, get_event_stream, close, cleanup | Backend Engineer | 3 | T-003 | Manager class |
| T-004.2 | Implement `get_event_stream` async generator yielding SSE-formatted strings with 15s heartbeats | Backend Engineer | 2 | T-004.1 | SSE stream generator |
| T-004.3 | Implement rate limiting: track concurrent connections per session/user, reject with 429 | Backend Engineer | 2 | T-004.1 | Rate limiter |
| T-004.4 | Implement `GET /api/v1/events/subscribe` endpoint with token fallback auth | Backend Engineer | 2 | T-004.1, T-004.2 | Router endpoint |
| T-004.5 | Implement `GET /api/v1/events/poll` endpoint | Backend Engineer | 1 | T-004.1 | Poll endpoint |
| T-004.6 | Implement `DELETE /api/v1/events/subscribe` endpoint | Backend Engineer | 0.5 | T-004.1 | Unsubscribe endpoint |
| T-004.7 | Implement `SubscriptionCleaner` background task (60s interval, marks expired subscriptions inactive) | Backend Engineer | 0.5 | T-004.1 | Cleaner task |
| T-004.8 | Write integration tests IT-01, IT-02, IT-03 | Backend Engineer | 3 | T-004.4, T-004.5 | Test files |
| T-005 | **Implement OutboxJanitor background task** | Backend Engineer | 3 | T-001 | `app/services/events/outbox_janitor.py` with batched DELETE, configurable retention, and logging. |
| T-005.1 | Implement `OutboxJanitor` with configurable retention (default 7 days), batch size (5000), and interval (1 hour) | Backend Engineer | 2 | T-001 | Janitor class |
| T-005.2 | Add janitor startup log with configuration summary and per-cleanup log with deleted count and duration | Backend Engineer | 0.5 | T-005.1 | Logging |
| T-005.3 | Write unit test for janitor cleanup logic with mock DB | Backend Engineer | 0.5 | T-005.1 | Test file |
| T-006 | **Integrate EventPublisher into WorkflowOrchestrator** | Backend Engineer | 4 | T-002, US-AI-034 | Modified `app/services/workflow/orchestrator.py` that calls `EventPublisher.publish()` on every state transition. |
| T-006.1 | Add `EventPublisher` as a dependency to `WorkflowOrchestrator.__init__` | Backend Engineer | 0.5 | T-002 | Dependency injection |
| T-006.2 | Call `publish()` after each state machine transition in the orchestrator loop | Backend Engineer | 2 | T-006.1 | Publish calls |
| T-006.3 | Call `publish()` with progress updates (including page-level granularity from the step function) | Backend Engineer | 1 | T-006.2 | Progress events |
| T-006.4 | Update integration test IT-03 to verify event sequence matches workflow state transitions | Backend Engineer | 0.5 | T-006.2 | Updated test |
| T-007 | **Integrate EventPublisher into PreviewWorker (US-AI-041)** | Backend Engineer | 2 | T-002, US-AI-041 | Modified `app/services/ai/preview_service.py` that calls `EventPublisher.publish()` on preview status changes. |
| T-007.1 | Call `publish()` after preview status changes (pending -> rendering -> ready/failed) | Backend Engineer | 1.5 | T-002 | Publish calls |
| T-007.2 | Write unit test verifying preview event sequence | Backend Engineer | 0.5 | T-007.1 | Test file |
| T-008 | **Integrate EventPublisher into ImportJobService** | Backend Engineer | 2 | T-002 | Modified `app/services/import_service.py` that calls `EventPublisher.publish()` on import job status changes. |
| T-008.1 | Call `publish()` after import job status changes (pending -> processing -> completed/failed) | Backend Engineer | 1.5 | T-002 | Publish calls |
| T-008.2 | Write unit test verifying import job event sequence | Backend Engineer | 0.5 | T-008.1 | Test file |
| T-009 | **Register event router and background tasks in main.py** | Backend Engineer | 2 | T-004, T-005 | Updated `app/main.py` with lifespan hooks and router registration. |
| T-009.1 | Add `events.router` to `api_router` | Backend Engineer | 0.5 | T-004 | Router registration |
| T-009.2 | Spawn `EventBroadcaster`, `OutboxJanitor`, `SubscriptionCleaner` in startup phase | Backend Engineer | 1 | T-005, T-004 | Lifespan hooks |
| T-009.3 | Gracefully cancel all background tasks on shutdown with 10-second drain period | Backend Engineer | 0.5 | T-009.2 | Shutdown logic |
| T-010 | **Add configuration variables to app/core/config.py** | Backend Engineer | 1 | None | 12 new configuration variables with env var overrides and docstrings. |
| T-011 | **Implement frontend useJobNotifications hook** | Frontend Engineer | 12 | US-AI-024 | `src/ai/hooks/useJobNotifications.ts` with SSE, adaptive polling, tab visibility, reconnection, gap-filling. Complete with TypeScript types. |
| T-011.1 | Define TypeScript types (`JobEvent`, `JobStatus`, `ConnectionMode`, etc.) in `src/ai/types/events.ts` | Frontend Engineer | 1 | None | Types file |
| T-011.2 | Implement `useJobNotifications` hook: SSE connection with EventSource, event parsing, state updates | Frontend Engineer | 4 | T-011.1 | Hook implementation |
| T-011.3 | Implement adaptive polling fallback with configurable interval, idle detection, and activity boost | Frontend Engineer | 2 | T-011.2 | Fallback logic |
| T-011.4 | Implement tab visibility handling: switch to idle polling when hidden, replay on visible | Frontend Engineer | 1.5 | T-011.2 | Visibility handling |
| T-011.5 | Implement sessionStorage persistence for `last_event_id` and `active_job_ids`, with replay on mount | Frontend Engineer | 1.5 | T-011.2 | Persistence |
| T-011.6 | Implement `reconnect()` and `unsubscribe()` methods | Frontend Engineer | 1 | T-011.2 | Reconnect logic |
| T-011.7 | Implement deduplication by event_id (handle at-most-once delivery) | Frontend Engineer | 1 | T-011.2 | Deduplication |
| T-012 | **Implement frontend visual progress components** | Frontend Engineer | 8 | T-011 | `CompactProgressBar`, `JobStatusPanel`, toast integration. |
| T-012.1 | Implement `CompactProgressBar` component for chat panel: animated bar, percentage, message text, status colors | Frontend Engineer | 2 | T-011 | Progress bar component |
| T-012.2 | Implement `JobStatusPanel` component: table of active/recent jobs, progress bars, timeline view, cancel/retry actions | Frontend Engineer | 4 | T-011 | Job status panel |
| T-012.3 | Integrate global toast notifications for job completion/failure using existing toast system | Frontend Engineer | 1 | T-012.2 | Toast integration |
| T-012.4 | Implement estimated remaining time computation (client-side from progress update rate) | Frontend Engineer | 1 | T-012.1 | ETA display |
| T-013 | **Integrate useJobNotifications into existing frontend flows** | Frontend Engineer | 6 | T-011, T-012 | Refactored `AIPanel.tsx`, `ExtractionPreview.tsx`, `useFileIngestion.ts` |
| T-013.1 | Replace inline polling in `useFileIngestion.ts` with `useJobNotifications` | Frontend Engineer | 2 | T-011 | Refactored hook |
| T-013.2 | Add `CompactProgressBar` to `AIPanel.tsx` for course generation progress | Frontend Engineer | 1.5 | T-012 | Panel integration |
| T-013.3 | Add "Job Status" button to course editor toolbar opening `JobStatusPanel` | Frontend Engineer | 1.5 | T-012 | Toolbar integration |
| T-013.4 | Add toast subscription in `App.tsx` or root layout for global job notifications | Frontend Engineer | 1 | T-012 | Toast subscription |
| T-014 | **Write E2E tests** | QA Engineer | 8 | T-012, T-013 | Automated E2E test scripts for E2E-01 and E2E-02. |
| T-014.1 | Write E2E-01 test: SSE progress visualization during course generation | QA Engineer | 4 | T-012 | Test script |
| T-014.2 | Write E2E-02 test: network interruption recovery with polling fallback | QA Engineer | 3 | T-012 | Test script |
| T-014.3 | Execute manual QA checklist (steps 1-8) and document results | QA Engineer | 2 | T-012 | Signed-off QA report |
| T-015 | **Documentation and code review** | Tech Lead | 4 | All | Code review sign-off, updated architecture docs, README entry for event system. |
| T-015.1 | Update `ARCHITECTURE.md` with event notification system overview and sequence diagrams | Tech Lead | 2 | All | Architecture doc update |
| T-015.2 | Conduct code review of all backend changes (T-001 through T-010) | Tech Lead | 1 | T-001 to T-010 | Review sign-off |
| T-015.3 | Conduct code review of all frontend changes (T-011 through T-013) | Tech Lead | 1 | T-011 to T-013 | Review sign-off |
