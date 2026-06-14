# US-AI-048: Dead Letter Queue and Failed AI Job Recovery

**Status:** Draft
**Priority:** SHOULD
**Depends on:** US-AI-034 (Durable Workflow Engine)
**Epic Owner:** Technical Product Owner

---

## 1. FUNCTIONAL SPECIFICATION

### 1.1 User Story

As a **Platform Operator**, I want a dead letter queue (DLQ) that captures every permanently failed workflow job with full context (input, checkpoint, error chain, retry history), so that I can inspect failures, diagnose root causes, selectively replay corrected jobs, and batch-redrive entire failure cohorts without losing data or causing duplicates.

As an **Author**, I want clear visibility when an AI job I initiated has failed permanently, along with the ability to request a manual retry or understand why it cannot be retried, so that I am not left wondering about the status of my work and can take appropriate action.

### 1.2 Overview

The Durable Workflow Engine (US-AI-034) provides retry logic within individual steps and transitions jobs to `failed` status when retries are exhausted. However, once a job reaches `failed`, the current system offers only:

1. A `POST /api/v1/workflows/{job_id}/retry` endpoint that resets a single failed job to `pending` for the entire state machine to re-execute from the last checkpoint.
2. A `GET /api/v1/workflows?status=failed` list view for admin inspection.

This is insufficient for production operations because:

- **No structured dead letter capture:** Failed jobs remain in the `workflow_jobs` table with `status=failed`, but there is no separate retention policy, archival strategy, or quarantine mechanism. A bug in a step can flood the table with millions of failed rows.
- **No failure classification:** All failures look alike. There is no taxonomy of failure codes, no severity rating, no grouping by root cause pattern.
- **No batch redrive:** An operator discovering that "LLM model X was down for 10 minutes" must individually retry each of the 50+ jobs that failed during that window. There is no `POST /api/v1/workflows/dead-letter/redrive?workflow_type=course_generation&failure_code=LLM_UNAVAILABLE` endpoint.
- **No failure analysis:** There is no aggregate view of "top 10 failure modes this week" or "failure rate by workflow type."
- **No notification integration:** When a critical job fails, there is no webhook, email, or Slack notification to the operator or the originating user.
- **No checkpoint download:** When a job fails mid-generation (e.g., page 17 of 50), the checkpoint data containing the 16 successfully generated pages is stored in the DB but cannot be downloaded as a recovery artifact.

This user story introduces the **Dead Letter Queue subsystem** as a first-class operational layer on top of the Durable Workflow Engine.

### 1.3 Core Functional Requirements

**FR-DLQ-01 (Automated Dead Letter Capture):** When a workflow job transitions to `failed` status (either by exhausting retries, hitting a timeout, or being explicitly dead-lettered), the orchestrator SHALL atomically:
  1. Copy the complete job record (all columns including `input`, `checkpoint_data`, `error`, `retry_count`, event log summary) into a dedicated `dead_letter_jobs` table.
  2. Set `dead_lettered_at` timestamp on the original `workflow_jobs` row (add column).
  3. Retain the original job row in `workflow_jobs` with `status=failed` for 7 days, after which it MAY be archived or pruned.
  4. The dead letter entry in `dead_letter_jobs` SHALL be immutable after creation — no UPDATE, only DELETE (manual purge) or INSERT (replay as new job).

**FR-DLQ-02 (Failure Classification Taxonomy):** Every dead letter entry SHALL carry a structured failure classification:
  ```json
  {
    "failure_code": "LLM_RATE_LIMITED",
    "failure_category": "llm_provider",
    "severity": "medium",
    "root_cause_summary": "Anthropic API rate limit exceeded on page 4/20",
    "failure_chain": [
      {"step": "generate_pages", "attempt": 1, "error": {"code": "LLM_RATE_LIMITED", "message": "429 Too Many Requests"}},
      {"step": "generate_pages", "attempt": 2, "error": {"code": "LLM_RATE_LIMITED", "message": "429 Too Many Requests"}},
      {"step": "generate_pages", "attempt": 3, "error": {"code": "LLM_RATE_LIMITED", "message": "429 Too Many Requests"}}
    ]
  }
  ```
  
  Failure categories SHALL be:
  - `llm_provider` — LLM API errors (rate limits, authentication, model overload, server errors)
  - `validation` — Content validation failures (schema violations, policy guardrails triggered)
  - `timeout` — Step execution exceeded timeout_s
  - `system` — Infrastructure errors (database connection lost, disk full, OOM)
  - `input_error` — Invalid input data, missing dependencies, stale references
  - `unknown` — Unclassified errors (catch-all for unexpected exceptions)

**FR-DLQ-03 (Dead Letter List API with Advanced Filtering):** Admin-facing API SHALL support listing dead letter entries with filters:
  - `failure_code`, `failure_category`, `severity`
  - `workflow_type`, date range (`dead_lettered_at`)
  - `search` over `root_cause_summary` (full-text search)
  - `group_by` parameter returning aggregated counts (e.g., group by failure_code or failure_category)
  - Cursor-based pagination (same pattern as US-AI-020).

**FR-DLQ-04 (Single-Job Redrive):** Admin SHALL be able to replay a single dead letter job by:
  1. Viewing the full dead letter entry (input, checkpoint, error chain, failure classification).
  2. Optionally modifying the input payload (e.g., fix a malformed parameter).
  3. Optionally modifying `generation_options` (e.g., switch from `claude-sonnet-4-20250514` to `claude-sonnet-4-20250614` after a model deprecation).
  4. Issuing a redrive command that creates a NEW `workflow_jobs` row with `status=pending` and a `redriven_from` pointer to the original dead letter entry.
  5. The original dead letter entry SHALL remain in the DLQ table with a `redriven_at` and `redrive_job_id` pointer.

**FR-DLQ-05 (Batch Redrive):** Admin SHALL be able to redrive multiple dead letter jobs matching a filter query in a single operation:
  1. Specify a filter (e.g., `failure_code=LLM_RATE_LIMITED AND dead_lettered_at > '2026-06-13T00:00:00Z'`).
  2. Optionally provide input overrides (JSON merge patch applied to each job's input).
  3. Optionally limit the batch to N items (`max_items=50`).
  4. System creates individual `workflow_jobs` rows for each matching dead letter entry.
  5. Returns a `batch_redrive_id` for tracking.
  6. Batch redrive is asynchronous — the endpoint returns 202 with a batch redrive job that reports progress.

**FR-DLQ-06 (Failure Analysis Dashboard API):** Admin API SHALL expose aggregate failure metrics:
  - Count of dead letter entries by `failure_category` over a date range.
  - Count by `failure_code` (top-N).
  - Count by `workflow_type`.
  - Mean-time-to-failure-permanent (MTTF-P) in minutes — average time a job runs before being dead-lettered.
  - Failure rate trend: `(dead_lettered_count) / (total_completed + dead_lettered_count)` per day over the last 7/30 days.
  - Most frequently failed steps across all jobs.

**FR-DLQ-07 (Dead Letter Retention and Archival):**
  - Dead letter entries SHALL be retained for 90 days by default (configurable via `DLQ_RETENTION_DAYS`).
  - After retention period, entries SHALL be archived to cold storage (S3/Blob) and soft-deleted from the active DLQ table.
  - Archived entries SHALL be queryable via a separate API with degraded performance (expect 5-10s latency for archive queries).
  - Manual purge of individual dead letter entries SHALL be supported via admin API (`DELETE /api/v1/workflows/dead-letter/{entry_id}` with confirmation token).

**FR-DLQ-08 (Notification Integration):** On dead letter creation, the system SHALL:
  1. Emit a structured `dead_letter_created` event to the `workflow_job_events` table.
  2. If the originating job had a `webhook_url`, POST a dead-letter notification payload.
  3. Optionally (feature-flagged): send notification via configured channels (Slack webhook, email, PagerDuty) for dead letters with `severity=critical` or `severity=high`.

**FR-DLQ-09 (User-Facing Failure Visibility):** The frontend SHALL distinguish between:
  - `status: "failed"` with a retry button (job can be retried — dead letter NOT yet created, within retry window).
  - `status: "dead_lettered"` with a "View Details" link that shows the failure classification and checkpoint summary (dead letter created, job is in DLQ).
  - `status: "dead_lettered_redriven"` with a link to the replacement job (job was dead lettered and has been redriven — the replacement is now running).

**FR-DLQ-10 (Checkpoint Artifact Recovery):** For dead letter entries where `checkpoint_data` contains partial work (e.g., 16 out of 20 pages generated), the admin SHALL be able to:
  1. Download the checkpoint as a JSON file via `GET /api/v1/workflows/dead-letter/{entry_id}/checkpoint`.
  2. Use that checkpoint as input to a new workflow job (manual bootstrap via the regular `POST /api/v1/workflows` endpoint by an informed operator).

### 1.4 User Flow: Happy Path — Single Job Redrive

**Precondition:** An operator receives an alert that 12 course generation jobs failed with `LLM_RATE_LIMITED` between 14:00 and 14:05. The rate limit has been resolved.

**Phase 1 — Inspect Dead Letter Queue**
1. Operator calls `GET /api/v1/workflows/dead-letter?failure_code=LLM_RATE_LIMITED&dead_lettered_at.gte=2026-06-14T14:00:00Z&dead_lettered_at.lte=2026-06-14T14:05:00Z&limit=20`.
2. Response returns 12 entries. Each entry shows: `job_id`, `workflow_type`, `failure_code`, `severity`, `root_cause_summary`, `dead_lettered_at`, `original_retry_count`.
3. Operator clicks through to inspect a single job detail: `GET /api/v1/workflows/dead-letter/{entry_id}`.
4. Response includes full `input`, `checkpoint_data` (summarized), `failure_chain`, and `step_execution_metrics` (per-step timing).

**Phase 2 — Single Redrive**
1. Operator decides the input is still valid and clicks "Redrive" in the admin UI.
2. Frontend calls `POST /api/v1/workflows/dead-letter/{entry_id}/redrive` with body `{"input_overrides": {"generation_options": {"model": "claude-sonnet-4-20250614"}}}`.
3. Backend creates a new `WorkflowJob` row with `status=pending`, `input=input_original_merged_with_overrides`, `redriven_from=entry_id`.
4. Returns `{"redrive_job_id": "new-job-uuid", "status": "pending", "polling_url": "/api/v1/workflows/new-job-uuid"}`.
5. The new job enters the normal workflow engine lifecycle.
6. Original dead letter entry is updated: `redriven_at` set, `redrive_job_id` set.

**Phase 3 — Monitor Redriven Job**
1. Operator polls the new job status via `GET /api/v1/workflows/{new-job-uuid}`.
2. Job completes successfully. Operator verifies the course was generated.

### 1.5 User Flow: Happy Path — Batch Redrive

1. Operator queries: `GET /api/v1/workflows/dead-letter?failure_code=LLM_RATE_LIMITED&group_by=failure_code` — confirms all 12 jobs share the same failure code.
2. Operator calls `POST /api/v1/workflows/dead-letter/redrive-batch` with:
   ```json
   {
     "filter": {
       "failure_code": "LLM_RATE_LIMITED",
       "dead_lettered_at_gte": "2026-06-14T14:00:00Z",
       "dead_lettered_at_lte": "2026-06-14T14:05:00Z"
     },
     "input_overrides": {
       "generation_options": {"model": "claude-sonnet-4-20250614"}
     },
     "max_items": 50
   }
   ```
3. Returns HTTP 202 with:
   ```json
   {
     "batch_redrive_id": "batch-redrive-uuid",
     "total_matching": 12,
     "total_redriven": 12,
     "failed_items": [],
     "polling_url": "/api/v1/workflows/dead-letter/redrive-batches/{batch_redrive_id}"
   }
   ```
4. Operator polls `GET /api/v1/workflows/dead-letter/redrive-batches/{batch_redrive_id}` to see progress (each job creation logged, any failures recorded).
5. All 12 jobs enter the workflow engine and are picked up by the orchestrator.

### 1.6 Error Paths

| Scenario | Expected Behavior |
|---|---|
| Operator tries to redrive a dead letter entry that has already been redriven | API returns 409 Conflict with `{"code": "DLQ_ALREADY_REDRIVEN", "message": "Entry already redriven as job {job_id} at {timestamp}", "existing_redrive_job_id": "..."}` |
| Operator tries to redrive an archived (cold-stored) dead letter entry | API returns 400 with `{"code": "DLQ_ENTRY_ARCHIVED", "message": "Entry archived on {date}. Restore from archive first.", "archive_path": "s3://bucket/path/..."}` |
| Operator specifies a filter that matches 10,000 items but `max_items=100` | Only the first 100 are redriven; response includes `total_matching: 10000, total_redriven: 100, truncated: true` |
| Redrive batch encounters an error creating a job for an individual entry | The error is recorded in the batch's `failed_items` array with the entry ID and error message. Other entries continue to be processed. |
| Dead letter entry has `checkpoint_data` exceeding 1 MB | The checkpoint download endpoint (`GET .../checkpoint`) returns a pre-signed URL for an async-generated file rather than inline JSON. |
| Operator attempts to delete a dead letter entry without confirmation token | API returns 400 with `{"code": "CONFIRMATION_REQUIRED", "message": "Provide confirmation_token obtained from GET /.../dead-letter/{entry_id}/purge-confirmation"}` |
| Notification webhook delivery fails for a dead letter event | Failure is logged; the event is queued for retry (up to 3 attempts at 30s intervals). After exhaustion, the notification is silently dropped with a warning log. |

### 1.7 UI/UX Requirements

1. **Admin Dead Letter Queue Table View:**
   - Sortable columns: job_id, workflow_type, failure_code, severity, dead_lettered_at, redriven status.
   - Multi-select checkboxes with "Redrive Selected" action button.
   - "Group by" dropdown: failure_code, failure_category, workflow_type, severity.
   - Search box for full-text search over `root_cause_summary`.
   - Date range picker for `dead_lettered_at` filter.
   - Pagination controls (50 per page, page navigation).

2. **Admin Dead Letter Detail View:**
   - Tabbed layout: "Summary" (failure classification, timeline), "Input" (raw JSON viewer with copy), "Checkpoint" (download button, summary of partial work), "Failure Chain" (timeline of retry attempts with per-step timing), "Events" (full event log).
   - "Redrive" button in header area with optional "Edit Input" expandable editor.
   - "Download Checkpoint" button.
   - "Purge from DLQ" button with confirmation dialog.

3. **Admin Failure Analysis Dashboard:**
   - Bar chart: Top 10 failure codes this week.
   - Pie chart: Failure by category.
   - Line chart: Failure rate trend (daily).
   - Metric cards: Total dead lettered (7d / 30d), MTTF-P, most active failed workflow type.
   - Export to CSV button for all chart data.

4. **User-Facing Job Status Enhancement:**
   - When a job status is `failed`, show "This job failed. You can retry it." with a retry button.
   - When dead-lettered and not redriven, show "This job has been escalated to operations." with a support contact link.
   - When dead-lettered and redriven, show "This job was re-submitted as a new job. [View replacement job]" link.

---

## 2. TECHNICAL SPECIFICATION

### 2.1 API Contracts

#### 2.1.1 `POST /api/v1/workflows/dead-letter` — List Dead Letter Entries

```
GET /api/v1/workflows/dead-letter
Accept: application/json
```

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `failure_code` | string | No | — | Filter by exact failure code |
| `failure_category` | string | No | — | Filter by failure category: llm_provider, validation, timeout, system, input_error, unknown |
| `severity` | string | No | — | Filter by severity: low, medium, high, critical |
| `workflow_type` | string | No | — | Filter by workflow type |
| `dead_lettered_at_gte` | ISO8601 | No | — | Start of date range |
| `dead_lettered_at_lte` | ISO8601 | No | — | End of date range |
| `redriven` | boolean | No | — | Filter: true=only redriven entries, false=only not redriven |
| `search` | string | No | — | Full-text search over root_cause_summary |
| `group_by` | string | No | — | Group results: failure_code, failure_category, workflow_type, severity, none |
| `limit` | integer | No | 50 | Page size (1-200) |
| `cursor` | string | No | — | Opaque cursor for pagination |

**Response (200 OK):**
```json
{
  "items": [
    {
      "entry_id": "dlq-a1b2c3d4-...",
      "original_job_id": "job-550e8400-...",
      "workflow_type": "course_generation",
      "failure": {
        "failure_code": "LLM_RATE_LIMITED",
        "failure_category": "llm_provider",
        "severity": "medium",
        "root_cause_summary": "Anthropic API rate limit exceeded on page 4/20",
        "failure_chain_count": 3
      },
      "checkpoint_summary": {
        "pages_generated": 3,
        "pages_total": 20,
        "has_partial_work": true
      },
      "redrive": {
        "has_been_redriven": false,
        "redrive_job_id": null,
        "redriven_at": null
      },
      "dead_lettered_at": "2026-06-14T14:02:30Z",
      "original_created_at": "2026-06-14T14:00:00Z",
      "original_retry_count": 3
    }
  ],
  "total": 12,
  "next_cursor": "eyJpZCI6IDEyfQ==",
  "has_more": false,
  "grouped": null
}
```

**Response with group_by (200 OK):**
```json
{
  "items": [],
  "total": 12,
  "grouped": {
    "keys": ["LLM_RATE_LIMITED", "LLM_AUTH_ERROR", "STEP_TIMEOUT"],
    "counts": [8, 3, 1],
    "total_matching": 12
  },
  "has_more": false
}
```

**Error Responses:**
- 422: Invalid filter parameter (e.g., unrecognized `failure_category`)

#### 2.1.2 `GET /api/v1/workflows/dead-letter/{entry_id}` — Get Dead Letter Detail

```
GET /api/v1/workflows/dead-letter/{entry_id}
Accept: application/json
```

**Response (200 OK):**
```json
{
  "entry_id": "dlq-a1b2c3d4-...",
  "original_job_id": "job-550e8400-...",
  "workflow_type": "course_generation",
  "original_status": "failed",
  "failure": {
    "failure_code": "LLM_RATE_LIMITED",
    "failure_category": "llm_provider",
    "severity": "medium",
    "root_cause_summary": "Anthropic API rate limit exceeded on page 4/20",
    "failure_chain": [
      {
        "step": "generate_pages",
        "attempt": 1,
        "timestamp": "2026-06-14T14:01:00Z",
        "duration_ms": 2450,
        "error": {
          "code": "LLM_RATE_LIMITED",
          "message": "429 Too Many Requests: Rate limit exceeded for model claude-sonnet-4-20250514"
        }
      },
      {
        "step": "generate_pages",
        "attempt": 2,
        "timestamp": "2026-06-14T14:01:05Z",
        "duration_ms": 1100,
        "error": {
          "code": "LLM_RATE_LIMITED",
          "message": "429 Too Many Requests: Rate limit exceeded for model claude-sonnet-4-20250514"
        }
      },
      {
        "step": "generate_pages",
        "attempt": 3,
        "timestamp": "2026-06-14T14:01:10Z",
        "duration_ms": 980,
        "error": {
          "code": "LLM_RATE_LIMITED",
          "message": "429 Too Many Requests: Rate limit exceeded for model claude-sonnet-4-20250514"
        }
      }
    ],
    "final_error": {
      "code": "LLM_RATE_LIMITED",
      "message": "Exhausted 3 retries due to LLM rate limiting"
    }
  },
  "input": {
    "import_job_id": "550e8400-e29b-41d4-a716-446655440000",
    "generation_options": {
      "model": "claude-sonnet-4-20250514",
      "temperature": 0.3
    }
  },
  "checkpoint_data": {
    "import_job": {
      "course_id": "course-python-101",
      "pages": [{"title": "Introduction", "template_type": "content-text"}, "..."],
      "total_pages": 20
    },
    "pages_state": {
      "total": 20,
      "generated": 3,
      "results": [
        {"page_index": 0, "title": "Introduction", "template_type": "content-text"},
        {"page_index": 1, "title": "Getting Started", "template_type": "content-text"},
        {"page_index": 2, "title": "Variables", "template_type": "content-code"}
      ]
    }
  },
  "redrive": {
    "has_been_redriven": false,
    "redrive_job_id": null,
    "redriven_at": null
  },
  "events_summary": {
    "total_events": 12,
    "event_types": ["state_entered", "step_completed", "state_entered", "step_failed", "retry", "state_entered", "step_failed", "retry", "state_entered", "step_failed", "step_failed"],
    "first_event_at": "2026-06-14T14:00:01Z",
    "last_event_at": "2026-06-14T14:01:15Z"
  },
  "step_execution_metrics": {
    "validate_input": {"duration_ms": 850, "status": "success"},
    "generate_pages": {"duration_ms": 4675, "status": "failed", "attempts": 3}
  },
  "dead_lettered_at": "2026-06-14T14:02:30Z",
  "archived": false,
  "archive_path": null
}
```

**Error Responses:**
- 404: `{"code": "DLQ_ENTRY_NOT_FOUND", "field": "entry_id", "message": "No dead letter entry found with ID dlq-..."}`

#### 2.1.3 `POST /api/v1/workflows/dead-letter/{entry_id}/redrive` — Redrive Single Job

```
POST /api/v1/workflows/dead-letter/{entry_id}/redrive
Content-Type: application/json
Accept: application/json
```

**Request Body:**
```json
{
  "input_overrides": {
    "generation_options": {
      "model": "claude-sonnet-4-20250614"
    }
  },
  "reason": "Rate limit resolved, switched to newer model"
}
```

**Validation Rules:**
- `input_overrides` is optional; if provided, it is deep-merged into the original `input` (JSON Merge Patch, RFC 7396).
- `reason` is required, min length 10, max length 2000.

**Response (200 OK):**
```json
{
  "redrive_job_id": "new-job-uuid-...",
  "workflow_type": "course_generation",
  "status": "pending",
  "polling_url": "/api/v1/workflows/new-job-uuid-...",
  "original_entry_id": "dlq-a1b2c3d4-...",
  "created_at": "2026-06-14T15:00:00Z",
  "input_overrides_applied": true
}
```

**Error Responses:**
- 404: Entry not found
- 409: Entry already redriven (`existing_redrive_job_id` returned)
- 400: Entry archived (`archive_path` returned)

#### 2.1.4 `POST /api/v1/workflows/dead-letter/redrive-batch` — Batch Redrive

```
POST /api/v1/workflows/dead-letter/redrive-batch
Content-Type: application/json
Accept: application/json
```

**Request Body:**
```json
{
  "filter": {
    "failure_code": "LLM_RATE_LIMITED",
    "failure_category": null,
    "workflow_type": null,
    "dead_lettered_at_gte": "2026-06-14T14:00:00Z",
    "dead_lettered_at_lte": "2026-06-14T14:05:00Z",
    "severity": null,
    "search": null
  },
  "input_overrides": {
    "generation_options": {
      "model": "claude-sonnet-4-20250614"
    }
  },
  "max_items": 50,
  "reason": "Rate limit resolved; batch redrive for 14:00-14:05 window"
}
```

**Response (202 Accepted):**
```json
{
  "batch_redrive_id": "batch-uuid-...",
  "total_matching": 12,
  "total_redriven": 12,
  "failed_items": [],
  "polling_url": "/api/v1/workflows/dead-letter/redrive-batches/batch-uuid-...",
  "status": "processing",
  "created_at": "2026-06-14T15:00:00Z"
}
```

#### 2.1.5 `GET /api/v1/workflows/dead-letter/redrive-batches/{batch_id}` — Get Batch Redrive Status

```
GET /api/v1/workflows/dead-letter/redrive-batches/{batch_redrive_id}
Accept: application/json
```

**Response (200 OK):**
```json
{
  "batch_redrive_id": "batch-uuid-...",
  "status": "completed",
  "total_matching": 12,
  "total_redriven": 12,
  "failed_items": [],
  "items": [
    {
      "entry_id": "dlq-entry-1",
      "status": "created",
      "redrive_job_id": "new-job-1",
      "error": null
    },
    {
      "entry_id": "dlq-entry-2",
      "status": "created",
      "redrive_job_id": "new-job-2",
      "error": null
    }
  ],
  "created_at": "2026-06-14T15:00:00Z",
  "completed_at": "2026-06-14T15:00:05Z"
}
```

#### 2.1.6 `GET /api/v1/workflows/dead-letter/{entry_id}/checkpoint` — Download Checkpoint

```
GET /api/v1/workflows/dead-letter/{entry_id}/checkpoint
Accept: application/json
```

**Response (200 OK):**
Returns the raw `checkpoint_data` JSONB from the original dead letter entry.

If checkpoint exceeds 1 MB, returns a redirect (307) to a pre-signed download URL:
```json
{
  "status": "redirect",
  "download_url": "https://storage.example.com/dlq-checkpoints/entry-uuid-checkpoint.json?...",
  "expires_at": "2026-06-14T16:00:00Z"
}
```

#### 2.1.7 `DELETE /api/v1/workflows/dead-letter/{entry_id}` — Purge Dead Letter Entry

```
DELETE /api/v1/workflows/dead-letter/{entry_id}
Content-Type: application/json
```

**Request Body:**
```json
{
  "confirmation_token": "token-from-purge-confirmation-endpoint",
  "reason": "Entry contains PII that must be removed per GDPR request"
}
```

**Response (200 OK):**
```json
{
  "entry_id": "dlq-a1b2c3d4-...",
  "status": "purged",
  "purged_at": "2026-06-14T16:00:00Z"
}
```

**Error Responses:**
- 400: Invalid or missing confirmation token
- 409: Entry has been redriven — purge only allowed if `redrive_job` is also in terminal state or force flag is set

#### 2.1.8 `GET /api/v1/workflows/dead-letter/{entry_id}/purge-confirmation` — Get Purge Confirmation Token

```
GET /api/v1/workflows/dead-letter/{entry_id}/purge-confirmation
```

**Response (200 OK):**
```json
{
  "confirmation_token": "purge-token-abc-...",
  "expires_at": "2026-06-14T16:05:00Z",
  "entry_summary": {
    "workflow_type": "course_generation",
    "failure_code": "LLM_RATE_LIMITED",
    "dead_lettered_at": "2026-06-14T14:02:30Z",
    "has_redriven_job": false
  },
  "warnings": [
    "This action is irreversible. The dead letter entry will be permanently deleted.",
    "Archived copies in cold storage may still exist."
  ]
}
```

#### 2.1.9 `GET /api/v1/workflows/dead-letter/analysis/summary` — Failure Analysis Dashboard API

```
GET /api/v1/workflows/dead-letter/analysis/summary
Accept: application/json
```

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `date_from` | ISO8601 | No | 7 days ago | Start of analysis window |
| `date_to` | ISO8601 | No | now | End of analysis window |
| `workflow_type` | string | No | — | Filter to single workflow type |

**Response (200 OK):**
```json
{
  "date_from": "2026-06-07T00:00:00Z",
  "date_to": "2026-06-14T23:59:59Z",
  "total_dead_lettered": 87,
  "total_completed": 1523,
  "failure_rate": 0.054,
  "top_failure_codes": [
    {"code": "LLM_RATE_LIMITED", "count": 34, "percentage": 39.1},
    {"code": "STEP_TIMEOUT", "count": 18, "percentage": 20.7},
    {"code": "VALIDATION_ERROR", "count": 15, "percentage": 17.2},
    {"code": "LLM_AUTH_ERROR", "count": 12, "percentage": 13.8},
    {"code": "DATABASE_CONNECTION_LOST", "count": 8, "percentage": 9.2}
  ],
  "by_category": {
    "llm_provider": 46,
    "timeout": 18,
    "validation": 15,
    "system": 8,
    "unknown": 0
  },
  "by_workflow_type": {
    "course_generation": 62,
    "batch_content_repair": 18,
    "scorm_export": 7
  },
  "by_severity": {
    "critical": 3,
    "high": 12,
    "medium": 52,
    "low": 20
  },
  "failure_rate_trend": [
    {"date": "2026-06-07", "failed": 5, "completed": 200, "rate": 0.025},
    {"date": "2026-06-08", "failed": 3, "completed": 210, "rate": 0.014},
    {"date": "2026-06-09", "failed": 8, "completed": 195, "rate": 0.041},
    {"date": "2026-06-10", "failed": 45, "completed": 180, "rate": 0.250},
    {"date": "2026-06-11", "failed": 15, "completed": 220, "rate": 0.068},
    {"date": "2026-06-12", "failed": 6, "completed": 215, "rate": 0.028},
    {"date": "2026-06-13", "failed": 3, "completed": 190, "rate": 0.016},
    {"date": "2026-06-14", "failed": 2, "completed": 113, "rate": 0.018}
  ],
  "mttf_p_minutes": 4.7,
  "most_failed_steps": [
    {"step": "generate_pages", "failures": 62},
    {"step": "validate_course", "failures": 15},
    {"step": "package_assets", "failures": 7},
    {"step": "create_zip", "failures": 3}
  ]
}
```

### 2.2 Database Schema DDL

#### 2.2.1 `dead_letter_jobs` Table — Primary Dead Letter Queue

```sql
CREATE TABLE dead_letter_jobs (
    id                      BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    entry_id                UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    original_job_id         UUID          NOT NULL,

    -- Workflow metadata (denormalized from original job for query performance)
    workflow_type           VARCHAR(64)   NOT NULL,
    original_status         VARCHAR(32)   NOT NULL,

    -- Failure classification
    failure_code            VARCHAR(128)  NOT NULL,
    failure_category        VARCHAR(32)   NOT NULL
                            CHECK (failure_category IN (
                                'llm_provider', 'validation', 'timeout',
                                'system', 'input_error', 'unknown'
                            )),
    severity                VARCHAR(16)   NOT NULL DEFAULT 'medium'
                            CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    root_cause_summary      TEXT          NOT NULL DEFAULT '',

    -- Full failure chain (JSON array of per-attempt errors)
    failure_chain           JSONB         NOT NULL DEFAULT '[]'::jsonb,
    final_error             JSONB         NOT NULL DEFAULT '{}'::jsonb,

    -- Original job data (captured at dead-letter time)
    original_input          JSONB         NOT NULL,
    original_checkpoint     JSONB         NOT NULL DEFAULT '{}'::jsonb,
    original_result         JSONB         DEFAULT NULL,
    original_retry_count    INTEGER       NOT NULL DEFAULT 0,
    original_max_retries    INTEGER       NOT NULL DEFAULT 3,

    -- Checkpoint size tracking (for download routing)
    checkpoint_size_bytes   INTEGER       NOT NULL DEFAULT 0,

    -- Step execution metrics (aggregated from events)
    step_execution_metrics  JSONB         NOT NULL DEFAULT '{}'::jsonb,
    events_summary          JSONB         NOT NULL DEFAULT '{}'::jsonb,

    -- Redrive tracking
    has_been_redriven       BOOLEAN       NOT NULL DEFAULT FALSE,
    redrive_job_id          UUID          DEFAULT NULL,
    redriven_at             TIMESTAMPTZ   DEFAULT NULL,

    -- Timestamps
    dead_lettered_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    -- Soft-delete / archival
    archived                BOOLEAN       NOT NULL DEFAULT FALSE,
    archive_path            VARCHAR(1024) DEFAULT NULL,
    purged_at               TIMESTAMPTZ   DEFAULT NULL,

    -- Foreign key
    CONSTRAINT fk_dlq_original_job FOREIGN KEY (original_job_id)
        REFERENCES workflow_jobs(job_id) ON DELETE SET NULL
);

-- Indexes for common query patterns
CREATE INDEX idx_dlq_failure_code ON dead_letter_jobs (failure_code);
CREATE INDEX idx_dlq_failure_category ON dead_letter_jobs (failure_category);
CREATE INDEX idx_dlq_severity ON dead_letter_jobs (severity);
CREATE INDEX idx_dlq_workflow_type ON dead_letter_jobs (workflow_type);
CREATE INDEX idx_dlq_dead_lettered_at ON dead_letter_jobs (dead_lettered_at DESC);
CREATE INDEX idx_dlq_redriven ON dead_letter_jobs (has_been_redriven) WHERE has_been_redriven = FALSE;
CREATE INDEX idx_dlq_created_at ON dead_letter_jobs (created_at DESC);
CREATE INDEX idx_dlq_archived ON dead_letter_jobs (archived) WHERE archived = TRUE;

-- Composite indexes for filtered queries
CREATE INDEX idx_dlq_code_category ON dead_letter_jobs (failure_code, failure_category);
CREATE INDEX idx_dlq_type_lettered ON dead_letter_jobs (workflow_type, dead_lettered_at DESC);
CREATE INDEX idx_dlq_severity_lettered ON dead_letter_jobs (severity, dead_lettered_at DESC);

-- Full-text search index on root_cause_summary
CREATE INDEX idx_dlq_summary_fts ON dead_letter_jobs
    USING GIN (to_tsvector('english', root_cause_summary));
```

#### 2.2.2 `dead_letter_batch_redrives` Table — Batch Redrive Tracking

```sql
CREATE TABLE dead_letter_batch_redrives (
    id                  BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    batch_redrive_id    UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    -- The filter that defined this batch
    filter_spec         JSONB         NOT NULL,
    input_overrides     JSONB         DEFAULT NULL,
    max_items           INTEGER       NOT NULL DEFAULT 50,
    reason              TEXT          NOT NULL DEFAULT '',

    -- Execution status
    status              VARCHAR(32)   NOT NULL DEFAULT 'processing'
                        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'partially_completed')),
    total_matching      INTEGER       NOT NULL DEFAULT 0,
    total_redriven      INTEGER       NOT NULL DEFAULT 0,
    total_failed        INTEGER       NOT NULL DEFAULT 0,
    failed_items        JSONB         NOT NULL DEFAULT '[]'::jsonb,

    -- Results summary
    items               JSONB         NOT NULL DEFAULT '[]'::jsonb,

    -- Timing
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ   DEFAULT NULL,

    -- User context
    initiated_by_user_id VARCHAR(64)  DEFAULT NULL
);

CREATE INDEX idx_dlq_batch_status ON dead_letter_batch_redrives (status);
CREATE INDEX idx_dlq_batch_created ON dead_letter_batch_redrives (created_at DESC);
```

#### 2.2.3 Add Column to `workflow_jobs` Table

```sql
-- Add dead letter tracking columns to the existing workflow_jobs table
ALTER TABLE workflow_jobs
    ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS dead_letter_entry_id UUID DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS redriven_from_entry_id UUID DEFAULT NULL;

CREATE INDEX idx_wf_jobs_dl ON workflow_jobs (dead_lettered_at)
    WHERE dead_lettered_at IS NOT NULL;
```

#### 2.2.4 ORM Model: `app/models/dead_letter.py`

```python
"""ORM models for the Dead Letter Queue subsystem."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, Text, DateTime,
    JSON, ForeignKey, CheckConstraint, Index, Float,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from app.models.base import Base


class DeadLetterJob(Base):
    """Dead letter queue entry for permanently failed workflow jobs."""

    __tablename__ = "dead_letter_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, default=uuid.uuid4
    )
    original_job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflow_jobs.job_id", ondelete="SET NULL"),
        nullable=False,
    )

    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_status: Mapped[str] = mapped_column(String(32), nullable=False)

    failure_code: Mapped[str] = mapped_column(String(128), nullable=False)
    failure_category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    root_cause_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    failure_chain: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=list)
    final_error: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    original_input: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    original_checkpoint: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    original_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    original_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    checkpoint_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    step_execution_metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    events_summary: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    has_been_redriven: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redrive_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    redriven_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    dead_lettered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archive_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    purged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "failure_category IN ('llm_provider', 'validation', 'timeout', 'system', 'input_error', 'unknown')",
            name="ck_dlq_failure_category",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_dlq_severity",
        ),
        Index("idx_dlq_code_category", "failure_code", "failure_category"),
        Index("idx_dlq_type_lettered", "workflow_type", "dead_lettered_at"),
        Index("idx_dlq_severity_lettered", "severity", "dead_lettered_at"),
    )


class DeadLetterBatchRedrive(Base):
    """Tracks a batch redrive operation."""

    __tablename__ = "dead_letter_batch_redrives"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_redrive_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, default=uuid.uuid4
    )

    filter_spec: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_overrides: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    max_items: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    total_matching: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_redriven: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=list)
    items: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    initiated_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'partially_completed')",
            name="ck_dlq_batch_status",
        ),
        Index("idx_dlq_batch_status", "status"),
    )
```

### 2.3 Service / Module Design

The DLQ subsystem follows the same layered architecture as the workflow engine:

```
app/
  models/
    dead_letter.py              # ORM models
    dead_letter_dto.py          # Pydantic DTOs
  repositories/
    dead_letter_repository.py   # DB access layer
  services/
    workflow/
      dead_letter_service.py    # Business logic: capture, redrive, batch, analysis
      steps/
        dead_letter_capture.py  # Step registered with orchestrator for automated capture
  routers/
    dead_letter_admin.py        # Admin REST endpoints
```

#### 2.3.1 Failure Classification Strategy

The failure classifier is a pure function that takes the final error and the failure chain and produces a structured classification:

```python
# app/services/workflow/dead_letter_classifier.py

from typing import Dict, Any, List, Optional
from enum import Enum


class FailureCategory(str, Enum):
    LLM_PROVIDER = "llm_provider"
    VALIDATION = "validation"
    TIMEOUT = "timeout"
    SYSTEM = "system"
    INPUT_ERROR = "input_error"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Failure classification rules (ordered by specificity)
CLASSIFICATION_RULES: List[Dict[str, Any]] = [
    # LLM Provider errors
    {"patterns": ["LLM_RATE_LIMITED", "LLM_AUTH_ERROR", "LLM_QUOTA_EXCEEDED",
                  "LLM_MODEL_UNAVAILABLE", "LLM_CONTEXT_LENGTH", "LLM_SERVER_ERROR"],
     "category": FailureCategory.LLM_PROVIDER,
     "severity": Severity.MEDIUM,
     "severity_overrides": {"LLM_AUTH_ERROR": Severity.HIGH,
                            "LLM_QUOTA_EXCEEDED": Severity.CRITICAL}},
    # Validation errors
    {"patterns": ["VALIDATION_ERROR", "SCHEMA_VIOLATION", "POLICY_BLOCKED",
                  "CONTENT_FILTERED", "PII_DETECTED"],
     "category": FailureCategory.VALIDATION,
     "severity": Severity.MEDIUM,
     "severity_overrides": {"PII_DETECTED": Severity.HIGH,
                            "CONTENT_FILTERED": Severity.HIGH}},
    # Timeout
    {"patterns": ["STEP_TIMEOUT", "WORKFLOW_TIMEOUT", "DEADLINE_EXCEEDED"],
     "category": FailureCategory.TIMEOUT,
     "severity": Severity.LOW},
    # System errors
    {"patterns": ["DATABASE_ERROR", "CONNECTION_LOST", "DISK_FULL", "OOM",
                  "WORKER_CRASHED", "INTERNAL_ERROR"],
     "category": FailureCategory.SYSTEM,
     "severity": Severity.HIGH},
    # Input errors
    {"patterns": ["MISSING_INPUT", "INVALID_INPUT", "IMPORT_JOB_NOT_FOUND",
                  "INVALID_IMPORT_STATUS", "REFERENCE_NOT_FOUND"],
     "category": FailureCategory.INPUT_ERROR,
     "severity": Severity.LOW},
]


def classify_failure(
    final_error: Dict[str, Any],
    failure_chain: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Classify a failure into a structured (code, category, severity) tuple.

    Args:
        final_error: The final error dict from the job (code, message).
        failure_chain: List of per-attempt error dicts.

    Returns:
        Dict with failure_code, failure_category, severity, root_cause_summary.
    """
    error_code = final_error.get("code", "UNKNOWN")
    error_message = final_error.get("message", "")

    for rule in CLASSIFICATION_RULES:
        if error_code in rule["patterns"]:
            severity = rule.get("severity_overrides", {}).get(error_code, rule["severity"])
            return {
                "failure_code": error_code,
                "failure_category": rule["category"].value,
                "severity": severity.value,
                "root_cause_summary": _summarize(error_code, error_message, failure_chain),
            }

    return {
        "failure_code": error_code,
        "failure_category": FailureCategory.UNKNOWN.value,
        "severity": Severity.MEDIUM.value,
        "root_cause_summary": error_message or f"Unclassified error: {error_code}",
    }


def _summarize(
    error_code: str, error_message: str, failure_chain: List[Dict[str, Any]]
) -> str:
    """Generate a human-readable root cause summary."""
    if not failure_chain:
        return error_message
    first = failure_chain[0]
    step = first.get("step", "unknown")
    attempt_count = len(failure_chain)
    return f"{error_code} in step '{step}' after {attempt_count} attempt(s): {error_message}"
```

#### 2.3.2 Dead Letter Capture Hook

The capture is integrated into the `WorkflowOrchestrator` as an event hook that fires after a job transitions to `failed`. This is implemented as an event-driven hook rather than inline logic to keep the orchestrator clean:

```python
# app/services/workflow/dead_letter_capture.py

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import SessionLocal
from app.repositories.workflow_repository import WorkflowRepository
from app.repositories.dead_letter_repository import DeadLetterRepository
from app.services.workflow.dead_letter_classifier import classify_failure

logger = logging.getLogger(__name__)


class DeadLetterCaptureService:
    """Captures failed workflow jobs into the dead letter queue.

    This service is called as a hook from WorkflowOrchestrator when a job
    transitions to 'failed' status.
    """

    def __init__(self):
        self._enabled = True

    async def capture(self, job_id: UUID) -> Optional[Dict[str, Any]]:
        """Capture a failed job into the dead letter queue.

        Called from the orchestrator immediately after a job transitions to 'failed'.

        Args:
            job_id: UUID of the workflow job that just failed.

        Returns:
            The dead letter entry dict if capture succeeded, None if skipped.
        """
        if not self._enabled:
            logger.info("Dead letter capture disabled; skipping job %s", job_id)
            return None

        async with SessionLocal() as session:
            wf_repo = WorkflowRepository(session)
            dl_repo = DeadLetterRepository(session)

            # Load the job with its full context
            job = await wf_repo.get_job(job_id)
            if not job:
                logger.warning("Cannot capture dead letter for unknown job %s", job_id)
                return None

            # Don't double-capture
            if job.dead_lettered_at is not None:
                logger.info("Job %s already dead-lettered at %s", job_id, job.dead_lettered_at)
                return None

            # Build failure chain from events
            events = await wf_repo.get_events(job_id)
            failure_chain = _build_failure_chain(events, job.error)

            # Classify the failure
            classification = classify_failure(
                final_error=job.error or {"code": "UNKNOWN", "message": "No error details"},
                failure_chain=failure_chain,
            )

            # Build step execution metrics
            step_metrics = _build_step_metrics(events)

            # Build events summary
            events_summary = _build_events_summary(events)

            # Create dead letter entry
            entry = await dl_repo.create_entry(
                original_job_id=job_id,
                workflow_type=job.workflow_type,
                original_status="failed",
                failure_code=classification["failure_code"],
                failure_category=classification["failure_category"],
                severity=classification["severity"],
                root_cause_summary=classification["root_cause_summary"],
                failure_chain=failure_chain,
                final_error=job.error or {},
                original_input=job.input,
                original_checkpoint=job.checkpoint_data,
                original_result=job.result,
                original_retry_count=job.retry_count,
                original_max_retries=job.max_retries,
                checkpoint_size_bytes=_estimate_json_size(job.checkpoint_data),
                step_execution_metrics=step_metrics,
                events_summary=events_summary,
            )

            # Update the original job with dead letter marker
            await wf_repo.mark_dead_lettered(job_id, entry.entry_id)

            logger.info(
                "Captured job %s to dead letter queue (entry=%s, code=%s, cat=%s, sev=%s)",
                job_id, entry.entry_id, classification["failure_code"],
                classification["failure_category"], classification["severity"],
            )

            # Emit a dead_letter_created event on the original job
            await wf_repo.append_event(
                job_id=job_id,
                state=job.current_state,
                event_type="dead_letter_created",
                payload={
                    "dead_letter_entry_id": str(entry.entry_id),
                    "failure_code": classification["failure_code"],
                    "failure_category": classification["failure_category"],
                    "severity": classification["severity"],
                },
            )

            return {
                "entry_id": str(entry.entry_id),
                "failure_code": classification["failure_code"],
            }


def _build_failure_chain(
    events: list, final_error: Optional[Dict[str, Any]]
) -> list:
    """Extract the ordered list of failure attempts from the event log."""
    chain = []
    for event in events:
        if event.event_type in ("step_failed", "retry"):
            chain.append({
                "step": event.state,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "error": (event.payload or {}).get("error", {}),
            })
    return chain


def _build_step_metrics(events: list) -> Dict[str, Any]:
    """Aggregate per-step execution metrics from events."""
    metrics = {}
    for event in events:
        step = event.state
        if step not in metrics:
            metrics[step] = {"occurrences": 0, "failures": 0, "total_duration_ms": 0}
        metrics[step]["occurrences"] += 1
        if event.event_type == "step_failed":
            metrics[step]["failures"] += 1
        if event.payload and "duration_ms" in event.payload:
            metrics[step]["total_duration_ms"] += event.payload["duration_ms"]
    return metrics


def _build_events_summary(events: list) -> Dict[str, Any]:
    """Build a summary of events for the dead letter entry."""
    event_types = {}
    for event in events:
        et = event.event_type
        event_types[et] = event_types.get(et, 0) + 1
    return {
        "total_events": len(events),
        "event_types": event_types,
        "first_event_at": events[0].timestamp.isoformat() if events else None,
        "last_event_at": events[-1].timestamp.isoformat() if events else None,
    }


def _estimate_json_size(data: dict) -> int:
    """Rough estimate of JSON payload size in bytes."""
    import json
    return len(json.dumps(data, default=str))
```

#### 2.3.3 Dead Letter Repository

```python
# app/repositories/dead_letter_repository.py

from __future__ import annotations
import uuid
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, text, and_, or_, case
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.dead_letter import DeadLetterJob, DeadLetterBatchRedrive

logger = logging.getLogger(__name__)


REDRIVE_STATUS_CHECK = [
    "pending", "running", "paused", "complete", "failed", "cancelled"
]


class DeadLetterRepository:
    """Persistence layer for dead letter queue operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def create_entry(
        self,
        original_job_id: uuid.UUID,
        workflow_type: str,
        original_status: str,
        failure_code: str,
        failure_category: str,
        severity: str,
        root_cause_summary: str,
        failure_chain: List[Dict[str, Any]],
        final_error: Dict[str, Any],
        original_input: Dict[str, Any],
        original_checkpoint: Dict[str, Any],
        original_result: Optional[Dict[str, Any]],
        original_retry_count: int,
        original_max_retries: int,
        checkpoint_size_bytes: int,
        step_execution_metrics: Dict[str, Any],
        events_summary: Dict[str, Any],
    ) -> DeadLetterJob:
        entry = DeadLetterJob(
            original_job_id=original_job_id,
            workflow_type=workflow_type,
            original_status=original_status,
            failure_code=failure_code,
            failure_category=failure_category,
            severity=severity,
            root_cause_summary=root_cause_summary,
            failure_chain=failure_chain,
            final_error=final_error,
            original_input=original_input,
            original_checkpoint=original_checkpoint,
            original_result=original_result,
            original_retry_count=original_retry_count,
            original_max_retries=original_max_retries,
            checkpoint_size_bytes=checkpoint_size_bytes,
            step_execution_metrics=step_execution_metrics,
            events_summary=events_summary,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def get_entry(self, entry_id: uuid.UUID) -> Optional[DeadLetterJob]:
        stmt = select(DeadLetterJob).where(
            DeadLetterJob.entry_id == entry_id,
            DeadLetterJob.archived == False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_entry_by_original_job(
        self, original_job_id: uuid.UUID
    ) -> Optional[DeadLetterJob]:
        stmt = select(DeadLetterJob).where(
            DeadLetterJob.original_job_id == original_job_id,
        ).order_by(DeadLetterJob.dead_lettered_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_entries(
        self,
        *,
        failure_code: Optional[str] = None,
        failure_category: Optional[str] = None,
        severity: Optional[str] = None,
        workflow_type: Optional[str] = None,
        dead_lettered_at_gte: Optional[datetime] = None,
        dead_lettered_at_lte: Optional[datetime] = None,
        redriven: Optional[bool] = None,
        search: Optional[str] = None,
        group_by: Optional[str] = None,
        limit: int = 50,
        cursor_id: Optional[int] = None,
        cursor_dead_lettered_at: Optional[datetime] = None,
    ) -> Tuple[List[DeadLetterJob], int, Optional[str], Optional[Dict]]:
        """List dead letter entries with filtering, pagination, and optional grouping."""
        q = select(DeadLetterJob).where(DeadLetterJob.archived == False)

        # Apply filters
        conditions = []
        if failure_code:
            conditions.append(DeadLetterJob.failure_code == failure_code)
        if failure_category:
            conditions.append(DeadLetterJob.failure_category == failure_category)
        if severity:
            conditions.append(DeadLetterJob.severity == severity)
        if workflow_type:
            conditions.append(DeadLetterJob.workflow_type == workflow_type)
        if dead_lettered_at_gte:
            conditions.append(DeadLetterJob.dead_lettered_at >= dead_lettered_at_gte)
        if dead_lettered_at_lte:
            conditions.append(DeadLetterJob.dead_lettered_at <= dead_lettered_at_lte)
        if redriven is not None:
            conditions.append(DeadLetterJob.has_been_redriven == redriven)
        if search:
            conditions.append(
                DeadLetterJob.root_cause_summary.ilike(f"%{search}%")
            )
        if cursor_id is not None and cursor_dead_lettered_at is not None:
            conditions.append(
                or_(
                    DeadLetterJob.dead_lettered_at < cursor_dead_lettered_at,
                    and_(
                        DeadLetterJob.dead_lettered_at == cursor_dead_lettered_at,
                        DeadLetterJob.id < cursor_id,
                    ),
                )
            )

        if conditions:
            q = q.where(and_(*conditions))

        # Handle group_by mode
        if group_by and group_by != "none":
            return await self._list_grouped(q, group_by, conditions)

        # Count total
        count_q = select(func.count()).select_from(q.subquery())
        total = (await self.session.execute(count_q)).scalar() or 0

        q = q.order_by(DeadLetterJob.dead_lettered_at.desc(), DeadLetterJob.id.desc())
        q = q.limit(limit + 1)

        rows = list((await self.session.execute(q)).scalars().all())
        return rows, total, None, None

    async def _list_grouped(
        self, base_query, group_by: str, conditions: list
    ) -> Tuple[List, int, None, Dict]:
        """Return grouped aggregation instead of row data."""
        group_column = getattr(DeadLetterJob, group_by, None)
        if group_column is None:
            raise ValueError(f"Invalid group_by field: {group_by}")

        count_stmt = (
            select(group_column, func.count().label("count"))
            .select_from(base_query.subquery())
            .group_by(group_column)
            .order_by(func.count().desc())
        )
        result = await self.session.execute(count_stmt)
        rows = result.all()

        keys = [str(r[0]) for r in rows]
        counts = [int(r[1]) for r in rows]
        total = sum(counts)

        return [], total, None, {
            "keys": keys,
            "counts": counts,
            "total_matching": total,
        }

    # ── Redrive ────────────────────────────────────────────────────────────

    async def mark_redriven(
        self,
        entry_id: uuid.UUID,
        redrive_job_id: uuid.UUID,
    ) -> Optional[DeadLetterJob]:
        stmt = (
            update(DeadLetterJob)
            .where(
                DeadLetterJob.entry_id == entry_id,
                DeadLetterJob.has_been_redriven == False,
                DeadLetterJob.archived == False,
            )
            .values(
                has_been_redriven=True,
                redrive_job_id=redrive_job_id,
                redriven_at=datetime.utcnow(),
            )
            .returning(DeadLetterJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    # ── Purge ──────────────────────────────────────────────────────────────

    async def soft_delete_entry(self, entry_id: uuid.UUID) -> bool:
        stmt = (
            update(DeadLetterJob)
            .where(DeadLetterJob.entry_id == entry_id)
            .values(purged_at=datetime.utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    # ── Batch Redrive ──────────────────────────────────────────────────────

    async def create_batch_redrive(
        self,
        filter_spec: Dict[str, Any],
        input_overrides: Optional[Dict[str, Any]],
        max_items: int,
        reason: str,
        initiated_by_user_id: Optional[str] = None,
    ) -> DeadLetterBatchRedrive:
        batch = DeadLetterBatchRedrive(
            filter_spec=filter_spec,
            input_overrides=input_overrides or {},
            max_items=max_items,
            reason=reason,
            initiated_by_user_id=initiated_by_user_id,
        )
        self.session.add(batch)
        await self.session.commit()
        await self.session.refresh(batch)
        return batch

    async def get_batch_redrive(
        self, batch_id: uuid.UUID
    ) -> Optional[DeadLetterBatchRedrive]:
        stmt = select(DeadLetterBatchRedrive).where(
            DeadLetterBatchRedrive.batch_redrive_id == batch_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_batch_redrive(
        self,
        batch_id: uuid.UUID,
        **updates,
    ) -> Optional[DeadLetterBatchRedrive]:
        updates["completed_at"] = datetime.utcnow()
        stmt = (
            update(DeadLetterBatchRedrive)
            .where(DeadLetterBatchRedrive.batch_redrive_id == batch_id)
            .values(**updates)
            .returning(DeadLetterBatchRedrive)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    # ── Analysis / Aggregation ─────────────────────────────────────────────

    async def get_analysis_summary(
        self,
        date_from: datetime,
        date_to: datetime,
        workflow_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate failure statistics for the analysis dashboard."""
        conditions = [
            DeadLetterJob.dead_lettered_at >= date_from,
            DeadLetterJob.dead_lettered_at <= date_to,
            DeadLetterJob.archived == False,
        ]
        if workflow_type:
            conditions.append(DeadLetterJob.workflow_type == workflow_type)

        base_filter = and_(*conditions)

        # Total count
        count_stmt = select(func.count()).select_from(
            select(DeadLetterJob).where(base_filter).subquery()
        )
        total = (await self.session.execute(count_stmt)).scalar() or 0

        # Top failure codes
        codes_stmt = (
            select(
                DeadLetterJob.failure_code,
                func.count().label("count"),
            )
            .where(base_filter)
            .group_by(DeadLetterJob.failure_code)
            .order_by(func.count().desc())
            .limit(10)
        )
        codes_result = await self.session.execute(codes_stmt)
        top_codes = [
            {"code": r[0], "count": int(r[1]),
             "percentage": round(int(r[1]) / total * 100, 1) if total > 0 else 0}
            for r in codes_result.all()
        ]

        # By category
        cat_stmt = (
            select(DeadLetterJob.failure_category, func.count().label("count"))
            .where(base_filter)
            .group_by(DeadLetterJob.failure_category)
        )
        by_category = {r[0]: int(r[1]) for r in (await self.session.execute(cat_stmt)).all()}

        # By workflow_type
        type_stmt = (
            select(DeadLetterJob.workflow_type, func.count().label("count"))
            .where(base_filter)
            .group_by(DeadLetterJob.workflow_type)
        )
        by_workflow = {r[0]: int(r[1]) for r in (await self.session.execute(type_stmt)).all()}

        # By severity
        sev_stmt = (
            select(DeadLetterJob.severity, func.count().label("count"))
            .where(base_filter)
            .group_by(DeadLetterJob.severity)
        )
        by_severity = {r[0]: int(r[1]) for r in (await self.session.execute(sev_stmt)).all()}

        total_completed = await self._count_completed_jobs(date_from, date_to, workflow_type)

        return {
            "total_dead_lettered": total,
            "total_completed": total_completed,
            "failure_rate": round(total / (total + total_completed), 4) if (total + total_completed) > 0 else 0,
            "top_failure_codes": top_codes,
            "by_category": by_category,
            "by_workflow_type": by_workflow,
            "by_severity": by_severity,
        }

    async def _count_completed_jobs(
        self, date_from: datetime, date_to: datetime,
        workflow_type: Optional[str] = None,
    ) -> int:
        """Count workflow jobs that completed successfully in the period."""
        from app.models.workflow import WorkflowJob
        conditions = [
            WorkflowJob.status == "complete",
            WorkflowJob.completed_at >= date_from,
            WorkflowJob.completed_at <= date_to,
        ]
        if workflow_type:
            conditions.append(WorkflowJob.workflow_type == workflow_type)
        stmt = select(func.count()).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalar() or 0
```

### 2.4 Configuration Variables

```bash
# ── Dead Letter Queue Configuration ──────────────────────────────────────────────

# Enable/disable the dead letter queue subsystem entirely.
# When false, failed jobs remain in workflow_jobs with status=failed but are NOT
# copied to the dead_letter_jobs table.
DLQ_ENABLED=true

# Retention period in days for dead letter entries in the active table.
# Entries older than this are eligible for archival to cold storage.
DLQ_RETENTION_DAYS=90

# Retention period for original workflow_jobs rows after dead-letter capture.
# After this many days, the original failed job row MAY be pruned from workflow_jobs.
# The dead_letter_jobs entry preserves all context.
WORKFLOW_FAILED_JOB_RETENTION_DAYS=7

# Maximum number of items in a single batch redrive operation.
DLQ_BATCH_REDRIVE_MAX_ITEMS=500

# Cold storage archive path template.
# Supports {date} and {workflow_type} placeholders.
DLQ_ARCHIVE_PATH_TEMPLATE=s3://ai-dlq-archive/{date}/{workflow_type}/

# Feature flag: enable/disable DLQ admin API endpoints.
FEATURE_DEAD_LETTER_QUEUE=true

# Feature flag: enable/disable batch redrive operations specifically.
FEATURE_DLQ_BATCH_REDRIVE=true

# Notification webhooks for dead letter events (comma-separated).
# Only called for severity=high and severity=critical entries.
DLQ_NOTIFICATION_WEBHOOK_URLS=

# Max checkpoint size in bytes before the download endpoint uses a redirect
# to an async-generated pre-signed URL instead of inline response.
DLQ_CHECKPOINT_INLINE_MAX_BYTES=1048576  # 1 MB
```

### 2.5 Integration Points

#### 2.5.1 Hook into WorkflowOrchestrator (US-AI-034)

The dead letter capture hook is called from the `WorkflowOrchestrator._run_state_machine()` method after the orchestrator transitions a job to `failed`. The hook fires asynchronously and does not block the orchestrator loop.

In `app/services/workflow/orchestrator.py`, add after the dead-letter transition logic (around line 1340-1354 of the US-AI-034 orchestrator):

```python
# After permanently failing a job (line ~1354)
if current_state_name == "failed" or step_result.success is False:
    # ... existing transition to failed ...
    
    # NEW: Fire dead letter capture as a background task
    if os.getenv("DLQ_ENABLED", "true").lower() == "true":
        from app.services.workflow.dead_letter_capture import DeadLetterCaptureService
        capture_service = DeadLetterCaptureService()
        # Fire-and-forget: capture in background, don't block orchestrator
        asyncio.create_task(capture_service.capture(job.job_id))
```

#### 2.5.2 Register Router in `app/main.py`

```python
# Add to imports
from app.routers import dead_letter_admin

# Add to api_router includes
api_router.include_router(dead_letter_admin.router)
```

#### 2.5.3 Register ORM Models in `alembic/env.py`

```python
import app.models.dead_letter  # noqa: F401
```

#### 2.5.4 Feature Flag Integration

```python
# In app/utils/feature_flags.py, add:
'dlq_enabled': FeatureFlag(
    name='dlq_enabled',
    enabled=False,
    description='Enable the dead letter queue subsystem for failed workflow jobs',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
'dlq_batch_redrive': FeatureFlag(
    name='dlq_batch_redrive',
    enabled=False,
    description='Enable batch redrive operations for dead letter entries',
    environments=[Environment.DEVELOPMENT, Environment.QA, Environment.STAGING, Environment.PRODUCTION]
),
```

---

## 3. NON-FUNCTIONAL REQUIREMENTS

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| Dead letter capture latency (p95) | < 500ms from job transition to `failed` to entry persisted in `dead_letter_jobs` | Application tracing |
| Dead letter list query (filtered, 100k rows) p95 | < 1 second | Application metrics |
| Dead letter detail fetch p95 | < 200ms | Application metrics |
| Single-job redrive creation p95 | < 500ms (includes creating new workflow_job + updating DLQ entry) | Application metrics |
| Batch redrive throughput | > 50 jobs/second (sequential job creation, no parallelism) | Bench test |
| Analysis summary aggregation (30-day window, 50k rows) p95 | < 3 seconds | Application metrics |
| Checkpoint download for entries < 1 MB | < 100ms (inline JSON response) | Application metrics |
| Concurrent admin users supported | 10 simultaneous | Load test |
| Dead letter capture overhead on orchestrator | < 50ms blocking time per capture (capture runs in background fire-and-forget task) | Orchestrator metrics |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Admin-only access | All DLQ endpoints require admin role authorization (same dependency as US-AI-020) |
| Input/checkpoint data protection | `original_input` and `original_checkpoint` may contain course content with PII; they inherit the same access controls as the originating course |
| No SQL injection | All filter parameters use parameterized queries via SQLAlchemy ORM |
| Purge confirmation token | Tokens are HMAC-signed with a server-side secret and expire after 5 minutes |
| Idempotent redrive | Redrive operations include deduplication check: the same dead letter entry cannot be redriven twice (returns 409) |
| Audit trail for redrive/purge | Every redrive and purge operation is logged to `workflow_job_events` on the original job |

### 3.3 Reliability

| Requirement | Implementation |
|---|---|
| Capture at-most-once | The capture hook checks `job.dead_lettered_at IS NOT NULL` before creating a duplicate entry |
| Capture failure isolation | If capture fails (DB error, connection lost), the original job remains `failed` in `workflow_jobs`. Capture is retried once on the next orchestrator heartbeat cycle. |
| Batch redrive partial failure | Individual entry failures in a batch redrive do not fail the entire batch. Failed entries are recorded in `failed_items` and the batch continues. |
| Archival durability | Archived entries in S3/Blob are stored with server-side encryption and lifecycle policies matching `DLQ_RETENTION_DAYS` |
| Notification delivery | Notification webhook delivery uses exponential backoff (3 retries: 30s, 60s, 120s). After exhaustion, the notification is dropped and logged. |

### 3.4 Scalability

| Requirement | Target |
|---|---|
| Maximum dead letter entries | 1,000,000 rows in `dead_letter_jobs` before archival |
| Maximum batch redrive items | 500 per batch (configurable) |
| Concurrent capture operations | Up to `WORKFLOW_MAX_CONCURRENCY` (default 4) simultaneous capture operations |
| DLQ table growth per day | Estimate: 50-200 entries/day in production (based on 5% failure rate of ~3000 jobs/day) |
| Archival batch size | 10,000 entries per archival sweep |

### 3.5 Data Retention

| Data | Active Retention | Archive Retention | Action |
|---|---|---|---|
| `dead_letter_jobs` (not redriven) | 90 days | 1 year | Archive to S3, then purge from active table |
| `dead_letter_jobs` (redriven) | 30 days | 1 year | Archive to S3, then purge from active table |
| `dead_letter_batch_redrives` | 90 days | — | Purge after 90 days |
| Original `workflow_jobs` (failed) | 7 days | — | Purge (context preserved in DLQ) |

---

## 4. CURRENT STATE ASSESSMENT

### 4.1 What Exists (from US-AI-034)

The Durable Workflow Engine provides the foundation that the DLQ builds upon:

1. **`workflow_jobs` table** with status `failed` as a terminal state. When a job exhausts all retries, the orchestrator transitions it to `failed` with an error payload.

2. **`workflow_job_events` table** records every state transition, including `step_failed`, `retry`, and final failure events. These events provide the raw material for building the failure chain.

3. **`WorkflowOrchestrator`** in `app/services/workflow/orchestrator.py` handles retry logic and dead-letter transition (the orchestrator calls the state `failed` a dead-letter state in comments, but does NOT actually create a dead letter queue entry — it simply sets `status=failed`).

4. **`WorkflowOrchestrator._run_state_machine()`** contains the logic that determines when retries are exhausted and transitions to `failed` (lines 1317-1354 in US-AI-034).

5. **`POST /api/v1/workflows/{job_id}/retry`** endpoint allows manual retry of a single failed job by resetting it to `pending`.

6. **`GET /api/v1/workflows?status=failed`** allows listing failed jobs.

### 4.2 What Must Be Built

| Component | Description | Reference Pattern |
|---|---|---|
| `app/models/dead_letter.py` | ORM models for `dead_letter_jobs` and `dead_letter_batch_redrives` tables | `app/models/ai_audit.py` from US-AI-020 |
| `app/models/dead_letter_dto.py` | Pydantic DTOs for all DLQ API surfaces | `app/models/ai_audit_dto.py` from US-AI-020 |
| `app/repositories/dead_letter_repository.py` | Repository with filtered list, pagination, group-by, aggregation, CRUD | `app/repositories/ai_audit_repo.py` from US-AI-020 |
| `app/services/workflow/dead_letter_classifier.py` | Pure function for failure classification (code, category, severity) | New |
| `app/services/workflow/dead_letter_capture.py` | Async capture hook called from orchestrator when job fails | New |
| `app/services/workflow/dead_letter_service.py` | Business logic for list, detail, redrive, batch redrive, purge, analysis | `app/services/ai/audit_service.py` from US-AI-020 |
| `app/routers/dead_letter_admin.py` | REST API for all DLQ operations | `app/routers/ai_admin.py` from US-AI-020 |
| Alembic migration | Create `dead_letter_jobs` and `dead_letter_batch_redrives` tables; alter `workflow_jobs` to add DLQ columns | `alembic/versions/20260614_0001_add_ai_audit_tables.py` |

### 4.3 What Must Be Modified

| Component | Modification | Reason |
|---|---|---|
| `app/services/workflow/orchestrator.py` | Add fire-and-forget call to `DeadLetterCaptureService.capture()` after failed transition | To trigger automated dead letter capture |
| `app/repositories/workflow_repository.py` | Add `mark_dead_lettered()` method that sets `dead_lettered_at` and `dead_letter_entry_id` on the `workflow_jobs` row | To track which jobs have been captured |
| `app/utils/feature_flags.py` | Add `dlq_enabled` and `dlq_batch_redrive` feature flags | Feature gating |
| `app/main.py` | Import and include the `dead_letter_admin` router | Route registration |
| `alembic/env.py` | Import `app.models.dead_letter` | Alembic autodiscovery |

### 4.4 Key Assumptions

- The `DeadLetterCaptureService` runs as a fire-and-forget background task to avoid blocking the orchestrator poll loop
- The failure classifier rules are static configuration (not DB-driven) for MVP, but the `CLASSIFICATION_RULES` list is designed to be externalized to a config file or DB table in a future iteration
- Archival to cold storage (S3/Blob) is a Phase 2 concern; for MVP, the DLQ retains entries in the `dead_letter_jobs` table and supports manual purge
- HMAC-signed purge confirmation tokens rely on a `DLQ_PURGE_SECRET` environment variable; the system falls back to a simpler random-token approach if the secret is not configured

---

## 5. EXPANSION POINTS

### 5.1 Technical Expansion Points

1. **TECH-EXP-01 (Cold Storage Archival Service):** Implement a background scheduler that queries `dead_letter_jobs` for entries older than `DLQ_RETENTION_DAYS`, serializes them to Parquet or JSON Lines format, uploads to S3/GCS/Azure Blob, sets `archived=True` and `archive_path`, then purges from the active table. A separate `GET /api/v1/workflows/dead-letter/archive?date_from=...` endpoint would query archived entries by restoring them from cold storage on demand (expect 5-10s latency).

2. **TECH-EXP-02 (Failure Pattern Detection via ML):** Train a lightweight failure classifier that clusters dead letter entries by similar root causes using NLP on `root_cause_summary` and `failure_chain` text. Surface "You have 15 jobs failing with similar patterns to an issue resolved last week" recommendations in the admin UI. This could use a simple TF-IDF + cosine similarity approach or a small fine-tuned sentence transformer.

3. **TECH-EXP-03 (Automated Remediation Playbooks):** Introduce a `dlq_remediation_playbooks` table that maps `(failure_code, failure_category)` -> `{input_overrides_template, action: auto_redrive|notify_only|require_manual}`. When a dead letter entry matches a playbook with `action=auto_redrive`, the system automatically redrives it with the specified input overrides after a configurable cooldown period. This enables zero-touch recovery for known transient failures (e.g., auto-redrive all `LLM_RATE_LIMITED` entries after 5 minutes).

4. **TECH-EXP-04 (Dead Letter Event Stream to Kafka/SNS):** Publish every dead letter creation event to a Kafka topic or SNS topic for consumption by downstream observability, SIEM, and alerting systems. The event payload would include the full failure classification and a link to the DLQ entry detail endpoint.

### 5.2 Functional Expansion Points

1. **FUNC-EXP-01 (User-Initiated Redrive Request):** Authors (non-admin) who see a dead-lettered job in their UI can click "Request Redrive" which creates a support ticket or notification to the platform operator queue rather than executing the redrive directly. The operator reviews and approves/denies the request.

2. **FUNC-EXP-02 (Scheduled Batch Redrive):** Schedule recurring batch redrives via a cron expression. For example: "Every day at 02:00, redrive all dead letter entries with `failure_code=LLM_RATE_LIMITED` that are less than 24 hours old." This handles recurring transient failures without manual intervention.

3. **FUNC-EXP-03 (Dead Letter Impact Analysis):** For a given dead letter entry, show which downstream artifacts were affected: "This failed course generation means course 'Python 101' was never created. 3 authors are blocked waiting for this course. 2 scheduled publish dates are at risk." This requires integration with the course scheduling and author assignment data.

4. **FUNC-EXP-04 (Failure Trend Alerting):** Configure alert thresholds on failure rate: "Alert if failure rate exceeds 10% in any 1-hour window" or "Alert if any single `failure_code` accounts for more than 50% of failures in a 24-hour window." Alerts fire via the notification integration (Slack, email, PagerDuty).

---

## 6. VALIDATION AND TESTING

### 6.1 Unit Tests

**File:** `tests/unit/ai/test_dead_letter_classifier.py`

| ID | Test | Scenario | Given | Expected |
|---|---|---|---|---|
| DLQ-UT-01 | `test_classify_llm_rate_limited` | LLM rate limit error code | `final_error={"code":"LLM_RATE_LIMITED"}` | failure_category=llm_provider, severity=medium |
| DLQ-UT-02 | `test_classify_llm_auth_error` | LLM auth error (overridden severity) | `final_error={"code":"LLM_AUTH_ERROR"}` | failure_category=llm_provider, severity=high |
| DLQ-UT-03 | `test_classify_validation_error` | Content validation failure | `final_error={"code":"VALIDATION_ERROR"}` | failure_category=validation, severity=medium |
| DLQ-UT-04 | `test_classify_step_timeout` | Step timeout | `final_error={"code":"STEP_TIMEOUT"}` | failure_category=timeout, severity=low |
| DLQ-UT-05 | `test_classify_database_error` | DB connection lost | `final_error={"code":"DATABASE_ERROR"}` | failure_category=system, severity=high |
| DLQ-UT-06 | `test_classify_missing_input` | Missing input parameter | `final_error={"code":"MISSING_INPUT"}` | failure_category=input_error, severity=low |
| DLQ-UT-07 | `test_classify_unknown_code` | Unrecognized error code | `final_error={"code":"MYSTERY_ERROR"}` | failure_category=unknown, severity=medium |
| DLQ-UT-08 | `test_failure_chain_summary_includes_step` | Failure chain has 3 entries at step 'generate_pages' | `failure_chain=[{step:"generate_pages"},{step:"generate_pages"},{step:"generate_pages"}]` | root_cause_summary contains "after 3 attempt(s)" and "generate_pages" |
| DLQ-UT-09 | `test_classify_quota_exceeded_critical` | LLM quota exceeded (critical severity) | `final_error={"code":"LLM_QUOTA_EXCEEDED"}` | failure_category=llm_provider, severity=critical |

**File:** `tests/unit/ai/test_dead_letter_repository.py`

| ID | Test | Scenario | Given | Expected |
|---|---|---|---|---|
| DLQ-UT-10 | `test_create_entry` | Valid dead letter entry | Full entry data | Entry persisted with entry_id UUID, all fields match |
| DLQ-UT-11 | `test_get_entry_by_id` | Existing entry | Valid entry_id | Returns entry with matching fields |
| DLQ-UT-12 | `test_get_entry_not_found` | Non-existent entry_id | Random UUID | Returns None |
| DLQ-UT-13 | `test_list_entries_no_filters` | 10 entries, no filters | 10 entries in DB | Returns all 10, total=10 |
| DLQ-UT-14 | `test_list_entries_filter_failure_code` | 5 entries with LLM_RATE_LIMITED, 3 with VALIDATION_ERROR | Filter failure_code=LLM_RATE_LIMITED | 5 results, total=5 |
| DLQ-UT-15 | `test_list_entries_filter_date_range` | Entries spanning 3 days | Filter last 24h | Only entries within window returned |
| DLQ-UT-16 | `test_list_entries_group_by_category` | Entries with mixed categories | group_by=failure_category | grouped dict with keys and counts |
| DLQ-UT-17 | `test_list_entries_search_summary` | Entry with root_cause_summary containing specific phrase | search="rate limit" | Returns matching entries |
| DLQ-UT-18 | `test_mark_redriven_success` | Entry not yet redriven | mark_redriven(entry_id, new_job_id) | has_been_redriven=True, redrive_job_id set, redriven_at set |
| DLQ-UT-19 | `test_mark_redriven_already_redriven` | Entry already redriven | mark_redriven(entry_id, new_job_id) | Returns None (no rows updated) |
| DLQ-UT-20 | `test_get_analysis_summary` | Mixed entries over date range | get_analysis_summary(7 days) | Returns dict with totals, top codes, categories, trends |

**File:** `tests/unit/ai/test_dead_letter_service.py`

| ID | Test | Scenario | Given | Expected |
|---|---|---|---|---|
| DLQ-UT-21 | `test_redrive_single_creates_new_job` | Valid entry, valid overrides | redrive_single(entry_id, input_overrides={}) | New WorkflowJob created with status=pending, redriven_from set |
| DLQ-UT-22 | `test_redrive_single_already_redriven` | Entry already redriven | redrive_single(entry_id) | Raises DLEntryAlreadyRedrivenError |
| DLQ-UT-23 | `test_redrive_single_input_merge` | Original input has model=A, override model=B | redrive_single with override | New job input has model=B, all other fields from original preserved |
| DLQ-UT-24 | `test_batch_redrive_creates_multiple_jobs` | 5 matching entries, max_items=10 | redrive_batch(filter, overrides) | 5 new jobs created, batch_redrive_id returned |
| DLQ-UT-25 | `test_batch_redrive_respects_max_items` | 12 matching entries, max_items=5 | redrive_batch(filter, max_items=5) | 5 new jobs created, response has truncated=true |
| DLQ-UT-26 | `test_batch_redrive_partial_failure` | 4 entries, 1 fails to create job (DB error) | redrive_batch(filter) | 3 jobs created, failed_items has 1 entry, status=partially_completed |
| DLQ-UT-27 | `test_capture_integrates_with_orchestrator` | Mock orchestrator calls capture after failed transition | Simulate job failure | Dead letter entry created with correct failure_code |

### 6.2 Integration Tests

**File:** `tests/integration/ai/test_dead_letter_api.py`

| ID | Test | Scenario | HTTP | Expected |
|---|---|---|---|---|
| DLQ-IT-01 | `test_list_dead_letter_empty` | No dead letter entries | GET /api/v1/workflows/dead-letter | 200, items=[], total=0 |
| DLQ-IT-02 | `test_list_dead_letter_with_data` | Seed 5 entries via DB | GET /api/v1/workflows/dead-letter | 200, total=5 |
| DLQ-IT-03 | `test_list_dead_letter_filter_code` | 5 entries, 3 with specific code | GET with failure_code param | 200, total=3 |
| DLQ-IT-04 | `test_list_dead_letter_group_by` | Mixed entries | GET with group_by=failure_category | 200, grouped dict present |
| DLQ-IT-05 | `test_list_dead_letter_pagination` | 55 entries | GET limit=20, verify cursor | Page 1 has 20, hasMore=true, page 3 has 15, hasMore=false |
| DLQ-IT-06 | `test_get_dead_letter_detail` | Existing entry | GET /dead-letter/{entry_id} | 200, full detail with failure_chain, input, checkpoint |
| DLQ-IT-07 | `test_get_dead_letter_detail_not_found` | Non-existent entry_id | GET /dead-letter/{uuid} | 404 |
| DLQ-IT-08 | `test_redrive_single_success` | Entry not redriven before | POST /dead-letter/{entry_id}/redrive | 200, redrive_job_id returned, polling_url set |
| DLQ-IT-09 | `test_redrive_single_already_redriven` | Entry already redriven | POST /dead-letter/{entry_id}/redrive | 409, existing_redrive_job_id returned |
| DLQ-IT-10 | `test_batch_redrive_success` | 3 matching entries | POST /dead-letter/redrive-batch | 202, total_redriven=3, polling_url set |
| DLQ-IT-11 | `test_batch_redrive_status_poll` | After batch redrive | GET /dead-letter/redrive-batches/{batch_id} | 200, status=completed, items list populated |
| DLQ-IT-12 | `test_download_checkpoint_small` | Entry with checkpoint_data < 1 MB | GET /dead-letter/{entry_id}/checkpoint | 200, JSON body with checkpoint data |
| DLQ-IT-13 | `test_download_checkpoint_large` | Entry with checkpoint_data > 1 MB | GET /dead-letter/{entry_id}/checkpoint | 307 redirect to pre-signed URL |
| DLQ-IT-14 | `test_purge_with_confirmation` | Get confirmation token then delete | GET confirmation then DELETE | 200, purged_at set |
| DLQ-IT-15 | `test_purge_without_confirmation` | DELETE without confirmation token | DELETE /dead-letter/{entry_id} | 400, confirmation_required |
| DLQ-IT-16 | `test_analysis_summary` | Seeded entries over 30 days | GET /dead-letter/analysis/summary | 200, all aggregation fields present |
| DLQ-IT-17 | `test_analysis_summary_with_date_filter` | Filter last 7 days | GET with date_from/date_to | Results only within window |
| DLQ-IT-18 | `test_dlq_disabled_flag` | FEATURE_DEAD_LETTER_QUEUE=false | GET /dead-letter | 404 |

### 6.3 End-to-End Tests

**File:** `tests/e2e/test_dead_letter_workflow_e2e.py`

| ID | Test | Scenario | Given | Expected |
|---|---|---|---|---|
| DLQ-E2E-01 | `test_failed_job_auto_captured_to_dlq` | Course generation job with LLM returning errors on all retries | Submit workflow, wait for failed status | 1. Job transitions to failed. 2. Within 1 second, dead letter entry appears in DLQ list. 3. Entry has failure_code=LLM_RATE_LIMITED, failure_chain has 3 entries. 4. Original workflow_jobs row has dead_lettered_at set. |
| DLQ-E2E-02 | `test_redrive_single_restores_partial_work` | Job failed at page 4/20; 3 pages were in checkpoint | Redrive single entry | New job starts with fresh state machine but the operator can optionally copy checkpoint data. New job input is identical to original. |
| DLQ-E2E-03 | `test_batch_redrive_12_jobs` | 12 course generation jobs dead-lettered with same failure_code | POST batch redrive with filter matching all 12 | All 12 new jobs created with status=pending. Orchestrator picks them up. Each has redriven_from pointing to original DLQ entry. |

### 6.4 Manual QA Steps

1. **Automated Capture Verification:**
   - Deploy a workflow job that is configured to always fail (mock LLM returns errors).
   - Submit the job and verify it transitions to `failed`.
   - Wait 2 seconds, then query `GET /api/v1/workflows/dead-letter`.
   - Verify the entry appears with correct failure classification.
   - Query the original job's events and verify a `dead_letter_created` event exists.

2. **Single Redrive Workflow:**
   - From step 1, note the `entry_id` of the dead letter entry.
   - Call `POST /api/v1/workflows/dead-letter/{entry_id}/redrive` with a corrected `input_overrides`.
   - Verify a new `workflow_job` is created with `status=pending`.
   - Verify the original DLQ entry now has `has_been_redriven=true`.
   - Verify calling redrive again returns 409.

3. **Batch Redride Stress Test:**
   - Create 100 dead letter entries via DB seeding (direct INSERT).
   - Call `POST /api/v1/workflows/dead-letter/redrive-batch` with `max_items=50`.
   - Verify the batch creates exactly 50 new workflow jobs.
   - Verify the batch response shows `total_matching=100, total_redriven=50, truncated=true`.

4. **Purge with Confirmation:**
   - Call `GET /api/v1/workflows/dead-letter/{entry_id}/purge-confirmation`.
   - Copy the `confirmation_token`.
   - Call `DELETE /api/v1/workflows/dead-letter/{entry_id}` with the token in the body.
   - Verify the entry is soft-deleted (`purged_at` set).
   - Verify calling GET on the entry returns 404.

5. **Analysis Dashboard Validation:**
   - Seed 30 days of dead letter entries with varying failure codes, categories, workflow types.
   - Query `GET /api/v1/workflows/dead-letter/analysis/summary`.
   - Validate counts match the seeded data.
   - Validate the trend array has expected daily breakdown.

6. **Feature Flag Gating:**
   - Set `FEATURE_DEAD_LETTER_QUEUE=false`.
   - Verify all DLQ endpoints return 404.
   - Submit a workflow job that fails. Verify it does NOT create a dead letter entry.
   - Set `FEATURE_DEAD_LETTER_QUEUE=true`.
   - Verify DLQ endpoints return 200 and capture resumes.

---

## 7. DEFINITION OF DONE

### 7.1 Acceptance Checklist

1. [ ] **FR-DLQ-01:** When a workflow job transitions to `failed` (retries exhausted, timeout, or explicit dead-letter), the `DeadLetterCaptureService` creates a row in `dead_letter_jobs` within 1 second. The original `workflow_jobs` row has `dead_lettered_at` and `dead_letter_entry_id` set.

2. [ ] **FR-DLQ-02:** Every dead letter entry has a valid `failure_code`, `failure_category`, `severity`, `root_cause_summary`, and `failure_chain` array. The failure classifier correctly maps known error codes to their category and severity per the rules table.

3. [ ] **FR-DLQ-03:** `GET /api/v1/workflows/dead-letter` supports all specified filters (failure_code, failure_category, severity, workflow_type, date range, redriven status, search, group_by) with cursor-based pagination. Group_by returns aggregated key-count pairs, not individual rows.

4. [ ] **FR-DLQ-04:** `POST /api/v1/workflows/dead-letter/{entry_id}/redrive` creates a new `WorkflowJob` with `status=pending`, `redriven_from=<entry_id>`, deep-merges `input_overrides` into the original input. Returns 409 if entry already redriven.

5. [ ] **FR-DLQ-05:** `POST /api/v1/workflows/dead-letter/redrive-batch` accepts a filter spec, creates new jobs for matching entries up to `max_items`, returns 202 with `batch_redrive_id`. `GET /.../redrive-batches/{id}` returns progress. Individual failures do not fail the entire batch.

6. [ ] **FR-DLQ-06:** `GET /api/v1/workflows/dead-letter/analysis/summary` returns aggregated failure metrics: total counts, top failure codes, breakdowns by category/workflow_type/severity, failure rate trend (daily array), MTTF-P, and most-failed-steps.

7. [ ] **FR-DLQ-07:** Dead letter entries older than `DLQ_RETENTION_DAYS` are eligible for archival (background job structure exists; actual S3 archival is Phase 2). `DELETE /api/v1/workflows/dead-letter/{entry_id}` with confirmation token soft-deletes the entry.

8. [ ] **FR-DLQ-08:** On dead letter creation, a `dead_letter_created` event is appended to `workflow_job_events`. If the original job had a `webhook_url`, a notification payload is POSTed. Severity=critical entries fire optional notification webhooks.

9. [ ] **FR-DLQ-09:** The job status response (`GET /api/v1/workflows/{job_id}`) includes `dead_lettered_at` and `dead_letter_entry_id` when the job has been captured. (Frontend integration is tracked separately.)

10. [ ] **FR-DLQ-10:** `GET /api/v1/workflows/dead-letter/{entry_id}/checkpoint` returns the checkpoint data inline for entries < 1 MB, or redirects to a pre-signed URL for larger entries.

11. [ ] All unit tests pass (DLQ-UT-01 through DLQ-UT-27). Coverage > 85% for new code.

12. [ ] All integration tests pass (DLQ-IT-01 through DLQ-IT-18). All E2E tests pass (DLQ-E2E-01 through DLQ-E2E-03).

13. [ ] Alembic migration creates `dead_letter_jobs` and `dead_letter_batch_redrives` tables, adds columns to `workflow_jobs`. Migration downgrade reverses all changes.

14. [ ] Feature flags `FEATURE_DEAD_LETTER_QUEUE` and `FEATURE_DLQ_BATCH_REDRIVE` correctly gate the DLQ subsystem. When disabled, all DLQ endpoints return 404 and capture is skipped.

15. [ ] Existing US-AI-034 test suite passes with no regressions (the orchestrator change should not break any existing tests).

16. [ ] OpenAPI spec renders all new routes with correct request/response schemas under "Dead Letter Queue" tag.

---

## 8. TASKS AND SUB-TASKS

### Task 8.1 — DB Schema and Alembic Migration (3 SP)

**Files to create/modify:**
- `app/models/dead_letter.py` (new) — ORM models for `DeadLetterJob` and `DeadLetterBatchRedrive`
- `alembic/versions/20260614_0002_create_dead_letter_tables.py` (new)
- `app/models/__init__.py` (modify) — register new models

**Acceptance Criteria:**
- `DeadLetterJob` ORM model with all columns matching section 2.2.1.
- `DeadLetterBatchRedrive` ORM model with all columns matching section 2.2.2.
- Alembic migration creates both tables with CHECK constraints, foreign keys, partial indexes, GIN full-text index.
- Alembic migration adds `dead_lettered_at`, `dead_letter_entry_id`, `redriven_from_entry_id` columns to `workflow_jobs` table.
- Down-migration drops columns from `workflow_jobs` and drops `dead_letter_jobs` and `dead_letter_batch_redrives` tables.
- Models registered in `app/models/__init__.py` and `alembic/env.py`.
- `Base.metadata.create_all` picks up the new tables.

### Task 8.2 — Pydantic DTOs (1 SP)

**File:** `app/models/dead_letter_dto.py` (new)

**Acceptance Criteria:**
- Request DTOs: `RedriveRequest`, `BatchRedriveRequest`, `PurgeRequest`, `ListDeadLetterParams`, `AnalysisParams`.
- Response DTOs: `DeadLetterEntryOut`, `DeadLetterDetailOut`, `DeadLetterListOut`, `RedriveResponse`, `BatchRedriveResponse`, `BatchRedriveStatusOut`, `CheckpointResponse`, `PurgeConfirmationOut`, `PurgeResponse`, `AnalysisSummaryOut`, `FailureTrendPoint`.
- All DTOs use `Pydantic v2` style with `model_config = {"from_attributes": True}` where applicable.
- Field constraints match API contracts (min/max lengths, regex patterns for UUID, ISO8601 strings).

### Task 8.3 — Failure Classification Module (1 SP)

**File:** `app/services/workflow/dead_letter_classifier.py` (new)

**Acceptance Criteria:**
- `classify_failure(final_error, failure_chain)` function implemented.
- Classification rules table covers all known error codes from US-AI-034 and common LLM provider codes.
- `FailureCategory` and `Severity` string enums defined.
- `_summarize()` helper generates human-readable root cause summary.
- Pure function with no IO dependencies — fully unit testable.
- Unit tests pass: DLQ-UT-01 through DLQ-UT-09.

### Task 8.4 — Dead Letter Repository (2 SP)

**File:** `app/repositories/dead_letter_repository.py` (new)

**Acceptance Criteria:**
- `create_entry()` persists a new dead letter job entry.
- `get_entry()` fetches by entry_id (excludes archived entries).
- `get_entry_by_original_job()` fetches the most recent DLQ entry for a given original job_id.
- `list_entries()` supports all 8 filter parameters + cursor pagination + group_by mode.
- `mark_redriven()` atomically sets redrive fields (fails if already redriven).
- `soft_delete_entry()` sets purged_at (soft delete).
- `create_batch_redrive()`, `get_batch_redrive()`, `update_batch_redrive()` for batch operations.
- `get_analysis_summary()` returns all aggregation fields with proper counts.
- Unit tests pass: DLQ-UT-10 through DLQ-UT-20.

### Task 8.5 — Dead Letter Capture Service (2 SP)

**Files:**
- `app/services/workflow/dead_letter_capture.py` (new)
- `app/services/workflow/dead_letter_service.py` (new)

**Acceptance Criteria:**
- `DeadLetterCaptureService.capture(job_id)` is called from the orchestrator after a failed transition.
- Capture is fire-and-forget (runs in `asyncio.create_task`).
- Capture idempotent: checks `dead_lettered_at` before creating entry; if already set, skips.
- Capture builds `failure_chain` from `workflow_job_events`.
- Capture builds `step_execution_metrics` and `events_summary` from events.
- `DeadLetterService.redrive_single()` creates a new `WorkflowJob` with input merge, updates DLQ entry.
- `DeadLetterService.redrive_batch()` iterates matching entries, creates jobs, tracks failures.
- `DeadLetterService.get_analysis_summary()` delegates to repository.
- Unit tests pass: DLQ-UT-21 through DLQ-UT-27.

### Task 8.6 — Modifications to WorkflowOrchestrator (1 SP)

**File modified:** `app/services/workflow/orchestrator.py`

**Acceptance Criteria:**
- After the orchestrator transitions a job to `failed`, it calls `DeadLetterCaptureService.capture(job_id)` as a fire-and-forget background task.
- The capture call is gated by `DLQ_ENABLED` env var (default `true`).
- If capture throws an exception, it is logged at ERROR level but does NOT crash the orchestrator loop.
- `mark_dead_lettered()` method added to `WorkflowRepository`.
- Existing orchestrator unit tests pass with no regressions.

### Task 8.7 — Admin REST Router (3 SP)

**File:** `app/routers/dead_letter_admin.py` (new)

**Acceptance Criteria:**
- `GET /api/v1/workflows/dead-letter` — list with all filters, group_by, cursor pagination.
- `GET /api/v1/workflows/dead-letter/{entry_id}` — full detail with failure chain, input, checkpoint.
- `POST /api/v1/workflows/dead-letter/{entry_id}/redrive` — single redrive with input_overrides.
- `POST /api/v1/workflows/dead-letter/redrive-batch` — batch redrive, returns 202.
- `GET /api/v1/workflows/dead-letter/redrive-batches/{batch_id}` — batch status poll.
- `GET /api/v1/workflows/dead-letter/{entry_id}/checkpoint` — checkpoint download (inline or redirect).
- `GET /api/v1/workflows/dead-letter/{entry_id}/purge-confirmation` — get HMAC-signed token.
- `DELETE /api/v1/workflows/dead-letter/{entry_id}` — purge with confirmation token.
- `GET /api/v1/workflows/dead-letter/analysis/summary` — failure analysis dashboard data.
- All endpoints gated by `require_feature_async("dlq_enabled")`.
- Batch redrive endpoint additionally gated by `require_feature_async("dlq_batch_redrive")`.
- Admin authorization dependency reused from US-AI-020 pattern.
- Router registered in `app/main.py`.
- Integration tests pass: DLQ-IT-01 through DLQ-IT-18.

### Task 8.8 — Feature Flags and Configuration (1 SP)

**Files modified:**
- `app/utils/feature_flags.py` — add `dlq_enabled` and `dlq_batch_redrive` flags
- `app/main.py` — register the dead_letter_admin router
- `render.yaml` / `.env.example` — add DLQ env vars

**Acceptance Criteria:**
- `dlq_enabled` flag registered in `_initialize_flags()`, enabled for all environments.
- `dlq_batch_redrive` flag registered, enabled for all environments.
- `DLQ_ENABLED` env var controls whether capture runs at all (app-level kill switch, defaults to `true`).
- `DLQ_RETENTION_DAYS`, `DLQ_BATCH_REDRIVE_MAX_ITEMS`, `DLQ_ARCHIVE_PATH_TEMPLATE`, `DLQ_CHECKPOINT_INLINE_MAX_BYTES`, `DLQ_NOTIFICATION_WEBHOOK_URLS` documented in `.env.example`.
- All env vars documented with defaults and descriptions.

### Task 8.9 — Test Suite (3 SP)

**Files:**
- `tests/unit/ai/test_dead_letter_classifier.py`
- `tests/unit/ai/test_dead_letter_repository.py`
- `tests/unit/ai/test_dead_letter_service.py`
- `tests/integration/ai/test_dead_letter_api.py`
- `tests/e2e/test_dead_letter_workflow_e2e.py`

**Acceptance Criteria:**
- All unit tests from section 6.1 pass (DLQ-UT-01 through DLQ-UT-27).
- All integration tests from section 6.2 pass (DLQ-IT-01 through DLQ-IT-18).
- All E2E tests from section 6.3 pass (DLQ-E2E-01 through DLQ-E2E-03).
- Tests use same patterns as existing test suite (pytest-asyncio, AsyncSession fixtures, TestClient with dependency overrides).
- E2E tests mock `LLMClient` to simulate controlled failures.
- Coverage > 85% for all new code.
- Existing US-AI-034 tests pass with no regressions (verifies orchestrator modification is backward-compatible).

### Task 8.10 — Documentation and Runbook (1 SP)

**Files:** Updates to existing docs or new ops runbook

**Acceptance Criteria:**
- OpenAPI spec renders correctly with new "Dead Letter Queue" tag and all endpoint schemas.
- Operations runbook documents:
  - How to inspect the DLQ via API (curl examples for each endpoint).
  - How to redrive a single job and a batch of jobs.
  - How to configure retention and archival.
  - How to troubleshoot missing dead letter entries.
  - How to purge entries for GDPR compliance.
  - Severe failure response procedures (what to do when critical failures spike).

---

## References

- **US-AI-034** — Durable Workflow Engine (direct dependency; provides `workflow_jobs`, `workflow_job_events`, `WorkflowOrchestrator`)
- **US-AI-020** — Admin Audit, Compliance, and Recovery Views (reference pattern for admin API structure, cursor pagination, authorization, feature flags)
- **`app/services/workflow/orchestrator.py`** — Location of orchestrator state machine logic that triggers dead letter capture
- **`app/repositories/workflow_repository.py`** — Existing repository pattern to extend with `mark_dead_lettered()`
- **`app/utils/feature_flags.py`** — Feature flag infrastructure
- **`app/utils/error_envelope.py`** — Standard error response format
- **`app/models/ai_audit.py`** — Reference pattern for JSONB-heavy ORM models with CHECK constraints
