# US-AI-024: Frontend AI Integration Layer

**Status:** Draft  
**Priority:** MUST (MVP)  
**Depends on:** US-AI-006 (AI Session Creation), US-AI-009 (Generic Proposal Lifecycle)  
**Source flow:** 17. Frontend AI Integration Layer  
**Epic Owner:** Technical Product Owner  

---

## 1. Functional Specification

### 1.1 User Story

As a Frontend Engineer, I want a dedicated AI integration layer in the frontend with session management, proposal rendering, and confirmation UI, so that users have a consistent AI authoring experience across all AI-powered features.

### 1.2 Overview

The frontend AI integration layer is the single entry point for all AI authoring interactions. It manages the full lifecycle of an AI session (create, refresh, expire, end), provides a shared API client for all `/api/v1/ai/*` endpoints, renders proposal previews with field-level diffs and validation messages, and enforces explicit user confirmation for destructive operations (deletes, batch applies).

This module must be implemented as an isolated add-on layer with zero impact on the existing manual authoring UI. When the `AI_AUTHORING_ENABLED` feature flag is off, no AI UI elements appear and the manual authoring experience is unchanged.

### 1.3 Actors

| Actor | Role |
|---|---|
| Author (User) | Initiates AI sessions; reviews proposals in modals/panels; confirms or rejects changes |
| Frontend AI Module | Manages session lifecycle in browser storage; calls AI API endpoints; renders proposals and confirmations; handles errors and session expiry |
| Backend AI APIs | `/api/v1/ai/sessions`, `/api/v1/ai/proposals/*`, `/api/v1/ai/chat`, `/api/v1/files/upload` |
| Existing Editor UI | Remains unchanged; receives refreshed course state after AI apply |

### 1.4 Functional Flows

#### Flow 1: AI Session Lifecycle (Frontend-Managed)

1. User is on a course editor page. A "Build with AI" or "AI Chat" button is visible only when `AI_AUTHORING_ENABLED` feature flag is true and the user has permission.
2. User clicks "Build with AI". Frontend calls `POST /api/v1/ai/sessions` with `{ courseId, organizationId }`.
3. Frontend receives `{ sessionId, courseId, expiresAt, state }`. It stores `sessionId` and `expiresAt` in `sessionStorage` (scoped to the AI panel's lifetime).
4. Frontend attaches an `Authorization: Bearer <token>` header containing the session token to all subsequent `/api/v1/ai/*` requests.
5. On page reload, frontend calls `GET /api/v1/ai/sessions/{sessionId}` to rehydrate the session. If the session is expired, frontend clears local session data and prompts the user to restart AI mode with a clear message.
6. When the user closes the AI panel or navigates away, frontend may call `DELETE /api/v1/ai/sessions/{sessionId}` (best-effort; session TTL handles cleanup server-side).
7. Frontend renders a session timer showing remaining time. When the session is within 5 minutes of expiry, a warning banner appears. On expiry, the chat input is disabled and a "Session expired — click to restart" button is shown.

#### Flow 2: Proposal Review and Apply

1. The AI chat orchestrator (US-AI-023) returns a chat response that may contain proposal metadata (proposal IDs, operation types, preview data).
2. Frontend inspects the chat response for `proposals[]` array. If present, the frontend renders an inline proposal preview card below the AI message.
3. The proposal preview card shows:
   - Operation type (`CREATE_PAGE`, `UPDATE_PAGE`, `DELETE_PAGE`)
   - Page title and template type
   - For updates: before/after diff with changed fields highlighted in green (added) and red (removed)
   - Validation messages (errors block apply; warnings are informational)
   - Dependency warnings for destructive operations
4. User reviews the proposal and clicks either "Apply" or "Reject".
5. If "Apply", frontend calls the appropriate apply endpoint (e.g., `POST /api/v1/ai/proposals/confirm-delete` with `{ sessionId, proposalId, userApprovedDelete: true }`).
6. If the apply succeeds, frontend refreshes course state via `GET /api/v1/courses/{courseId}` (reusing existing `CourseContext` or equivalent) and removes the proposal card.
7. If the apply fails with a conflict (409), frontend shows an inline error and prompts the user to re-propose.
8. If "Reject", frontend dismisses the proposal card. The backend proposal will eventually expire.

#### Flow 3: Destructive Confirmation Modal

1. When the proposal operation type is `DELETE_PAGE` or `BATCH_DELETE`, the frontend MUST NOT call the apply endpoint directly from the proposal card.
2. Instead, the proposal card shows a "Review & Confirm" button that opens a destructive confirmation modal.
3. The modal displays:
   - Warning icon and "Destructive Action" header text
   - Page title being deleted
   - Component summary (component types and count)
   - Dependency warnings from the backend response (e.g., "2 branching rules reference this page")
   - Irreversible action notice: "This action cannot be undone. All page content will be permanently deleted."
   - A confirmation input field where the user must type the word "DELETE" (case-insensitive) to enable the confirm button
   - "Cancel" button (primary safe action) and "Delete" button (red/destructive style, disabled until confirmation text is typed)
4. The modal cannot be dismissed by clicking outside or pressing Escape when the delete is pending — the user must explicitly cancel.
5. When the user types "DELETE" and clicks the red button, frontend calls the confirmation endpoint.
6. On success, the modal closes, the page is removed from the page list, and a success toast is shown.
7. On error (expired token, page changed), the modal shows the specific error with an action button ("Re-propose" or "Cancel").

#### Flow 4: File Ingestion Upload and Review

1. From the AI chat panel, the user can click a paperclip/upload icon to open a file picker (PDF, DOCX only; validated client-side).
2. File selection triggers `POST /api/v1/files/upload` with `multipart/form-data` containing the file, `sessionId`, and `courseId`.
3. Frontend shows an upload progress bar (derived from `XMLHttpRequest.upload.onprogress` or fetch-based equivalent).
4. Backend returns `{ uploadId, filename, status: "uploaded" }`.
5. Frontend polls `GET /api/v1/imports/jobs/{jobId}` or receives the extraction preview when ready.
6. Frontend renders the extraction preview as a page breakdown table:
   - Column: Page Title (editable inline), Suggested Template (dropdown), Source Sections (indices), Rationale
   - Row actions: Edit title, Change template type, Delete row, Split/Merge buttons
   - Drag-and-drop reordering of rows
7. User reviews the breakdown, makes adjustments, and clicks "Approve Breakdown".
8. Frontend sends `POST /api/v1/files/approve` with the adjusted page plan.
9. Backend generates content and returns validation results. Frontend shows per-page validation status (green checkmark / yellow warning / red error).
10. User clicks "Confirm & Create" for batch apply. Frontend calls the batch apply endpoint.
11. On success, frontend redirects to the course editor with all pages loaded.

#### Flow 5: Feature Flag Gating and Manual Authoring Preservation

1. On app bootstrap, frontend reads `AI_AUTHORING_ENABLED` from a configuration endpoint or environment variable. Store in a global config store.
2. If `AI_AUTHORING_ENABLED` is false:
   - The "Build with AI" button is not rendered.
   - The AI chat panel is not rendered.
   - Any stale AI session data in `sessionStorage` is cleared.
   - The manual course editor, page list, preview, and export screens are completely unchanged.
3. If `AI_AUTHORING_ENABLED` is true:
   - The "Build with AI" button appears in the course editor toolbar.
   - The AI chat panel is collapsed by default; user clicks to open.
   - After AI proposals are applied, the existing editor re-renders the course data from the API (identical render path as manual authoring).
4. The frontend never routes AI operations through legacy API paths. All AI calls go through the new `/api/v1/ai/*` endpoints via the `src/ai/` module.

### 1.5 Error Handling Matrix

| Error | Frontend Behavior | User Message |
|---|---|---|
| Session expired (403 SESSION_EXPIRED) | Clear session storage; disable AI panel; show restart button | "Your AI session has expired. Click to start a new session." |
| Proposal apply conflict (409 PAGE_CHANGED) | Keep proposal card; show error inline with "Re-propose" button | "This page was changed since the proposal. Please review and try again." |
| Confirmation token expired (410 CONFIRMATION_EXPIRED) | Dismiss modal; show error toast | "The confirmation window expired. Please re-propose the deletion." |
| Validation errors on proposal | Show red error badges on proposal card; block apply button | "This proposal has blocking errors. Review the validation messages below." |
| Network error / backend down | Show non-blocking banner; keep session alive; retry button | "Connection issue. Check your connection and retry." |
| Rate limit (429) | Show warning; disable AI panel for retry-after duration | "You've reached the rate limit. Please wait X minutes before trying again." |
| AI feature flag disabled (FEATURE_NOT_AVAILABLE) | Hide all AI UI; clear session storage | (No user-facing message; AI simply isn't present) |
| Upload failed / unsupported file type | Show inline error on upload area | "Unsupported file type. Please upload a PDF or DOCX file." |
| Extraction failed (scanned doc) | Show error on upload review screen | "This document appears to be scanned. Please upload a text-based PDF." |

---

## 2. Technical Specification

### 2.1 Frontend Module Architecture

All AI integration code lives in `src/ai/` — an isolated directory with its own API client, components, hooks, state management, and types. The module never imports from legacy services directly and never modifies existing editor components.

```
src/ai/
├── api/
│   ├── client.ts                  # Shared AI HTTP client (axios/fetch wrapper with session auth header)
│   ├── sessions.ts                # createSession, getSession, deleteSession
│   ├── proposals.ts               # proposeCreatePage, proposeUpdatePage, proposeDeletePage, confirmDelete
│   ├── chat.ts                    # sendChatMessage (stream or single response)
│   └── ingestion.ts              # uploadFile, pollJob, approveBreakdown
├── components/
│   ├── AIPanel.tsx               # Root AI panel container (collapsible sidebar or bottom panel)
│   ├── AISessionBanner.tsx       # Session expiry countdown banner
│   ├── ChatWindow.tsx            # Chat message list and input
│   ├── ChatMessage.tsx           # Single chat bubble (user or assistant)
│   ├── ProposalCard.tsx          # Inline proposal preview with diff, validation, apply/reject buttons
│   ├── ProposalDiff.tsx          # Before/after diff renderer with field-level highlighting
│   ├── ValidationBadge.tsx       # Validation status icon (error/warning/info)
│   ├── ConfirmationModal.tsx     # Destructive action confirmation modal with "DELETE" text input
│   ├── FileUploadArea.tsx        # Drag-and-drop file upload with progress bar
│   ├── ExtractionPreview.tsx     # Page breakdown table with edit/merge/split/reorder actions
│   ├── BatchValidationSummary.tsx # Per-page validation status in batch operations
│   └── AIToolbarButton.tsx       # "Build with AI" / "AI Chat" button in course editor toolbar
├── hooks/
│   ├── useAISession.ts           # Session lifecycle hook (create, refresh, expire, clear)
│   ├── useChat.ts                # Chat state hook (messages, send, loading, error)
│   ├── useProposal.ts            # Proposal state hook (proposals list, apply, reject)
│   └── useFileIngestion.ts       # File upload and extraction state hook
├── stores/
│   ├── aiSessionStore.ts         # Zustand/Redux store or context for session state
│   └── aiProposalStore.ts        # Zustand/Redux store or context for active proposals
├── types/
│   ├── session.ts                # AISession, SessionState
│   ├── proposal.ts               # AIProposal, ProposalOperation, ValidationMessage, DependencyWarning
│   ├── chat.ts                   # ChatMessage, ChatTurn, ChatResponse
│   └── ingestion.ts             # UploadJob, ExtractionResult, ProposedPage
└── utils/
    ├── sessionStorage.ts         # sessionStorage read/write helpers with expiry checks
    ├── diffRenderer.ts           # Computes field-level diffs between before/after objects
    └── errorFormatter.ts         # Normalizes backend error shapes into user-facing messages
```

### 2.2 TypeScript Type Definitions

**`src/ai/types/session.ts`:**

```typescript
export interface AISession {
  sessionId: string;
  courseId: string;
  organizationId: string;
  createdAt: string;           // ISO-8601
  expiresAt: string;           // ISO-8601
  state: Record<string, unknown>;
}

export interface SessionState {
  session: AISession | null;
  status: 'idle' | 'loading' | 'active' | 'expired' | 'error';
  error: string | null;
  remainingMs: number;         // Countdown in milliseconds
}

export interface CreateSessionRequest {
  courseId: string;
  organizationId?: string;
}

export interface CreateSessionResponse {
  sessionId: string;
  courseId: string;
  organizationId: string;
  createdAt: string;
  expiresAt: string;
  state: Record<string, unknown>;
}
```

**`src/ai/types/proposal.ts`:**

```typescript
export type ProposalOperation =
  | 'create_page'
  | 'update_page'
  | 'delete_page'
  | 'batch_create'
  | 'batch_update'
  | 'batch_delete';

export type ProposalStatus =
  | 'PENDING_REVIEW'
  | 'PENDING_CONFIRMATION'
  | 'APPROVED'
  | 'APPLYING'
  | 'APPLIED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'FAILED';

export interface ValidationMessage {
  severity: 'error' | 'warning' | 'info';
  field: string;
  message: string;
}

export interface DependencyWarning {
  category: string;    // 'branching' | 'scoring' | 'navigation' | 'final_assessment' | 'export'
  severity: string;    // 'info' | 'warning' | 'error'
  message: string;
  affectedIds: string[];
}

export interface ProposalDiff {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  changedFields: string[];
}

export interface AIProposal {
  proposalId: string;
  sessionId: string;
  courseId: string;
  pageId: string | null;
  operation: ProposalOperation;
  status: ProposalStatus;
  previewData: Record<string, unknown> | null;
  diff: ProposalDiff | null;
  validationMessages: ValidationMessage[];
  dependencyWarnings: DependencyWarning[];
  confirmationRequired: boolean;
  confirmationTokenExpiresAt: string | null;
  baseHash: string | null;
  createdAt: string;
  expiresAt: string;
}

// Props for the ProposalCard component
export interface ProposalCardProps {
  proposal: AIProposal;
  onApply: (proposalId: string) => Promise<void>;
  onReject: (proposalId: string) => void;
  onConfirmDelete: (proposalId: string) => void;  // Opens confirmation modal
}

// Props for the ConfirmationModal component
export interface ConfirmationModalProps {
  proposal: AIProposal;
  isOpen: boolean;
  onConfirm: (proposalId: string) => Promise<void>;
  onCancel: () => void;
}
```

**`src/ai/types/chat.ts`:**

```typescript
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  proposals?: AIProposal[];     // Proposals attached to assistant messages
  toolCalls?: ToolCallTrace[];  // Optional tool call trace for debugging
  isLoading?: boolean;          // True while streaming/processing
}

export interface ToolCallTrace {
  toolName: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  durationMs: number;
  status: 'success' | 'error';
}

export interface ChatRequest {
  sessionId: string;
  courseId: string;
  prompt: string;
  mode?: 'authoring' | 'refine' | 'question';
  selectedContext?: {
    pageId?: string;
    componentIds?: string[];
  };
}

export interface ChatResponse {
  turnId: string;
  message: string;
  proposals: AIProposal[];
  toolCalls: ToolCallTrace[];
  sessionState: {
    remainingMs: number;
    proposalCount: number;
  };
}
```

**`src/ai/types/ingestion.ts`:**

```typescript
export interface UploadJob {
  uploadId: string;
  filename: string;
  status: 'uploaded' | 'extracting' | 'ready_for_review' | 'generating' | 'ready_for_apply' | 'completed' | 'failed';
  progress: number;             // 0.0 to 1.0
  errorMessage: string | null;
}

export interface ExtractedSection {
  index: number;
  heading: string;
  headingLevel: number;
  textContent: string;
  tableCount: number;
  imageCount: number;
}

export interface ExtractionResult {
  filename: string;
  totalSections: number;
  sections: ExtractedSection[];
  issues: Array<{ severity: string; message: string; action: string }>;
}

export interface ProposedPage {
  pageTitle: string;
  suggestedTemplate: string;
  sourceIndices: number[];
  rationale: string;
  validationStatus?: 'valid' | 'warning' | 'error';
  validationMessages?: ValidationMessage[];
}

export interface ApproveBreakdownRequest {
  sessionId: string;
  uploadId: string;
  proposedPages: ProposedPage[];
}
```

### 2.3 API Client

**`src/ai/api/client.ts`:**

```typescript
const AI_BASE_URL = '/api/v1/ai';

class AIClient {
  private baseUrl: string;
  private getSessionToken: () => string | null;

  constructor(getSessionToken: () => string | null) {
    this.baseUrl = AI_BASE_URL;
    this.getSessionToken = getSessionToken;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: { headers?: Record<string, string> }
  ): Promise<T> {
    const token = this.getSessionToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    };

    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      throw new AIApiError(
        response.status,
        errorBody.code || 'UNKNOWN_ERROR',
        errorBody.message || response.statusText,
        errorBody.details || {}
      );
    }

    return response.json();
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>('GET', path);
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('POST', path, body);
  }

  delete<T>(path: string): Promise<T> {
    return this.request<T>('DELETE', path);
  }

  /** Upload file with progress tracking via XHR */
  async uploadFile(
    url: string,
    formData: FormData,
    onProgress?: (percent: number) => void
  ): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const token = this.getSessionToken();

      xhr.open('POST', `${this.baseUrl}${url}`);
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          const errorBody = JSON.parse(xhr.responseText || '{}');
          reject(new AIApiError(
            xhr.status,
            errorBody.code || 'UPLOAD_ERROR',
            errorBody.message || 'Upload failed',
            errorBody.details || {}
          ));
        }
      };

      xhr.onerror = () => reject(new AIApiError(0, 'NETWORK_ERROR', 'Network error'));
      xhr.send(formData);
    });
  }
}

class AIApiError extends Error {
  constructor(
    public statusCode: number,
    public code: string,
    message: string,
    public details: Record<string, unknown>
  ) {
    super(message);
    this.name = 'AIApiError';
  }

  get isSessionExpired(): boolean {
    return this.code === 'SESSION_EXPIRED';
  }

  get isConflict(): boolean {
    return this.code === 'PAGE_CHANGED' || this.code === 'DUPLICATE_PROPOSAL';
  }

  get isRateLimited(): boolean {
    return this.statusCode === 429;
  }

  get retryAfterMs(): number {
    return (this.details?.retryAfter as number) ?? 0;
  }
}
```

### 2.4 API Contracts (Frontend Calls)

#### Session Management

**POST /api/v1/ai/sessions** — Create a new session.

Request:
```json
{
  "courseId": "course_abc123",
  "organizationId": "org_xyz789"
}
```

Response 201:
```json
{
  "sessionId": "sess_def456",
  "courseId": "course_abc123",
  "organizationId": "org_xyz789",
  "createdAt": "2026-06-14T10:00:00Z",
  "expiresAt": "2026-06-15T10:00:00Z",
  "state": {
    "pageCount": 5,
    "courseTitle": "Introduction to Data Science"
  }
}
```

**GET /api/v1/ai/sessions/{sessionId}** — Rehydrate session on page reload.

Response 200:
```json
{
  "sessionId": "sess_def456",
  "courseId": "course_abc123",
  "organizationId": "org_xyz789",
  "expiresAt": "2026-06-15T10:00:00Z",
  "state": { "pageCount": 5, "courseTitle": "Introduction to Data Science" },
  "activeProposalIds": ["prop_001", "prop_002"]
}
```

Response 404 (expired or not found):
```json
{
  "code": "SESSION_NOT_FOUND",
  "field": "sessionId",
  "message": "Session not found or expired."
}
```

**DELETE /api/v1/ai/sessions/{sessionId}** — End session.

Response 200:
```json
{ "deleted": true, "sessionId": "sess_def456" }
```

#### Chat

**POST /api/v1/ai/chat** — Send a chat message and get assistant response (may include proposals).

Request:
```json
{
  "sessionId": "sess_def456",
  "courseId": "course_abc123",
  "prompt": "Create a new page about data types with a text-content template",
  "mode": "authoring",
  "selectedContext": {}
}
```

Response 200:
```json
{
  "turnId": "turn_789",
  "message": "I've created a proposal for a new page on data types. Here's a preview: ...",
  "proposals": [
    {
      "proposalId": "prop_001",
      "operation": "create_page",
      "status": "PENDING_REVIEW",
      "pageId": null,
      "previewData": {
        "title": "Understanding Data Types",
        "templateType": "text-content",
        "data": { "content": "Data types define the kind of values..." }
      },
      "diff": null,
      "validationMessages": [],
      "dependencyWarnings": [],
      "confirmationRequired": false,
      "confirmationTokenExpiresAt": null,
      "baseHash": null,
      "createdAt": "2026-06-14T10:01:00Z",
      "expiresAt": "2026-06-15T10:01:00Z"
    }
  ],
  "toolCalls": [
    {
      "toolName": "propose_create_page",
      "input": { "title": "Understanding Data Types", "templateType": "text-content", "data": {} },
      "output": { "proposalId": "prop_001", "validationStatus": "valid" },
      "durationMs": 1200,
      "status": "success"
    }
  ],
  "sessionState": {
    "remainingMs": 85400000,
    "proposalCount": 1
  }
}
```

#### Proposals

**POST /api/v1/ai/proposals/{proposalId}/apply** — Apply a proposal (for create/update).

Request:
```json
{
  "sessionId": "sess_def456",
  "userConfirmed": true
}
```

Response 200:
```json
{
  "status": "created",
  "pageId": "page_new_001",
  "proposalId": "prop_001",
  "message": "Page 'Understanding Data Types' has been created."
}
```

**POST /api/v1/ai/proposals/{proposalId}/confirm-delete** — Confirm a delete proposal.

Request:
```json
{
  "sessionId": "sess_def456",
  "userApprovedDelete": true
}
```

Response 200:
```json
{
  "status": "deleted",
  "pageId": "page_002",
  "pageTitle": "Outdated Module",
  "proposalId": "prop_003",
  "message": "Page 'Outdated Module' has been deleted."
}
```

#### File Ingestion

**POST /api/v1/files/upload** — Upload a file for ingestion.

Content-Type: `multipart/form-data`

Fields:
- `file`: binary file data
- `sessionId`: string
- `courseId`: string
- `description`: optional string

Response 200:
```json
{
  "uploadId": "upload_001",
  "filename": "course_outline.pdf",
  "status": "uploaded",
  "extraction": {
    "totalSections": 5,
    "sections": [
      { "index": 0, "heading": "Module 1: Introduction", "headingLevel": 1, "textContent": "...", "tableCount": 0, "imageCount": 1 }
    ],
    "issues": []
  }
}
```

**POST /api/v1/files/approve** — Approve the page breakdown for content generation.

Request:
```json
{
  "sessionId": "sess_def456",
  "uploadId": "upload_001",
  "proposedPages": [
    {
      "pageTitle": "Module 1: Introduction",
      "suggestedTemplate": "text-content",
      "sourceIndices": [0],
      "rationale": "Introductory overview"
    }
  ]
}
```

Response 200:
```json
{
  "batchProposalId": "batch_001",
  "pages": [
    {
      "pageTitle": "Module 1: Introduction",
      "templateType": "text-content",
      "validationStatus": "valid",
      "validationMessages": []
    }
  ],
  "allValid": true
}
```

**POST /api/v1/ai/proposals/batch-apply** — Apply the batch proposal (all-or-nothing).

Request:
```json
{
  "sessionId": "sess_def456",
  "batchProposalId": "batch_001",
  "userConfirmed": true
}
```

Response 200:
```json
{
  "status": "applied",
  "courseId": "course_abc123",
  "pagesCreated": 5,
  "message": "Course created with 5 pages from file ingestion."
}
```

### 2.5 Frontend Hooks Signatures

**`useAISession.ts`:**

```typescript
interface UseAISessionReturn {
  session: AISession | null;
  status: SessionState['status'];
  error: string | null;
  remainingMs: number;
  createSession: (courseId: string, orgId?: string) => Promise<void>;
  refreshSession: () => Promise<void>;
  endSession: () => Promise<void>;
  clearSession: () => void;
}

function useAISession(): UseAISessionReturn
```

Implementation notes:
- `createSession`: calls `POST /api/v1/ai/sessions`, stores result in `sessionStorage` under key `ai_session_{courseId}`, sets up a `setInterval` to update `remainingMs` every second.
- `refreshSession`: reads `sessionId` from `sessionStorage`, calls `GET /api/v1/ai/sessions/{sessionId}`, updates state. If 404, sets status to `expired`.
- `endSession`: calls `DELETE /api/v1/ai/sessions/{sessionId}`, clears `sessionStorage`, resets state.
- `clearSession`: removes `sessionStorage` entry without API call (used on logout).
- When `remainingMs` drops to 0, status transitions to `expired`.
- On component unmount, clears the interval timer.

**`useChat.ts`:**

```typescript
interface UseChatReturn {
  messages: ChatMessage[];
  isSending: boolean;
  error: string | null;
  sendMessage: (prompt: string, context?: ChatRequest['selectedContext']) => Promise<void>;
  clearMessages: () => void;
}

function useChat(sessionId: string | null, courseId: string | null): UseChatReturn
```

Implementation notes:
- `sendMessage`: adds optimistic user message with `isLoading: false`, sets `isSending = true`, calls `POST /api/v1/ai/chat`. On response, adds assistant message with any proposals. On error, marks the user message with `isError` state.
- `clearMessages`: resets the messages array (used on session restart).
- Messages are stored in component state only (not persisted — session recovery re-fetches from backend).

**`useProposal.ts`:**

```typescript
interface UseProposalReturn {
  proposals: AIProposal[];
  applyProposal: (proposalId: string) => Promise<void>;
  rejectProposal: (proposalId: string) => void;
  confirmDelete: (proposalId: string) => Promise<void>;
  isApplying: boolean;
}

function useProposal(sessionId: string | null): UseProposalReturn
```

**`useFileIngestion.ts`:**

```typescript
interface UseFileIngestionReturn {
  uploadJob: UploadJob | null;
  extractionResult: ExtractionResult | null;
  proposedPages: ProposedPage[];
  uploadProgress: number;
  isUploading: boolean;
  isApproving: boolean;
  error: string | null;
  uploadFile: (file: File, description?: string) => Promise<void>;
  updateProposedPages: (pages: ProposedPage[]) => void;
  approveBreakdown: () => Promise<void>;
  reset: () => void;
}

function useFileIngestion(sessionId: string, courseId: string): UseFileIngestionReturn
```

### 2.6 Key Component Behaviors

#### `ConfirmationModal.tsx`

```typescript
interface ConfirmationModalProps {
  proposal: AIProposal;
  isOpen: boolean;
  onConfirm: (proposalId: string) => Promise<void>;
  onCancel: () => void;
}

// Behavior:
// - Displays as a centered overlay with backdrop (semi-transparent black, z-index 1000)
// - Backdrop click does NOT close (prevents accidental dismiss)
// - Escape key does NOT close (unless user has not started typing)
// - Renders:
//   1. Header: "Delete Page" with warning icon (red triangle or trash icon)
//   2. Page info: title, template type, component count
//   3. Dependency warnings section (if any): yellow warning boxes with details
//   4. Irreversible action notice in red-bordered box
//   5. Confirmation text input: "Type DELETE to confirm:" — case-insensitive match
//   6. Two buttons: "Cancel" (outlined, left) and "Delete" (red filled, right, disabled until text matches)
// - isLoading state: button shows spinner, input is disabled
// - On success: close modal, show success toast
// - On error: show inline error message inside modal, keep modal open
// - Error states: CONFIRMATION_EXPIRED, PAGE_CHANGED, PAGE_ALREADY_DELETED
```

#### `ProposalCard.tsx`

```typescript
// Renders within the chat message flow, below the assistant message text.
// Visual states:
//   1. Default: shows operation type badge, page title, validation badges, Apply/Reject buttons
//   2. Update proposal: shows ProposalDiff with field-level highlighting
//   3. Delete proposal: shows "Review & Confirm" button instead of Apply (opens ConfirmationModal)
//   4. Applying: Apply button shows spinner, disabled
//   5. Applied: green success banner, "View in Editor" link
//   6. Rejected: grey dismissed state, fade out
//   7. Error: red error banner with retry button
//   8. Has validation errors: red error badges above Apply button; Apply button disabled
```

#### `ProposalDiff.tsx`

```typescript
interface ProposalDiffProps {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  changedFields: string[];
}

// Renders a side-by-side or unified diff view:
// - For each changed field, show:
//   - Field path (e.g., "data.content")
//   - Before value (strikethrough, red background)
//   - After value (green background)
// - Unchanged fields shown in a collapsed "Unchanged fields" accordion (N fields)
// - Top-level summary: "X fields changed, Y fields unchanged"
// - Uses the `diffRenderer.ts` utility to compute the diff from before/after objects
```

#### `ExtractionPreview.tsx`

```typescript
interface ExtractionPreviewProps {
  sections: ExtractedSection[];
  proposedPages: ProposedPage[];
  onChange: (pages: ProposedPage[]) => void;
  onApprove: () => void;
  isApproving: boolean;
}

// Renders a data table:
// Col 1: # (row number, auto-updated on reorder)
// Col 2: Page Title (editable text input)
// Col 3: Template Type (dropdown: text-content, tabs, accordion, click-reveal, final-assessment)
// Col 4: Source Sections (comma-separated section indices, non-editable)
// Col 5: Rationale (read-only text)
// Col 6: Actions (Delete row, Split row, Merge with next)
// - Drag-and-drop reorder via @dnd-kit or react-beautiful-dnd
// - "Add Page" button at bottom
// - "Approve Breakdown" button (disabled if no pages)
```

### 2.7 Session Storage Contract

The frontend stores AI session data in `sessionStorage` (not `localStorage`), scoped to the browser tab:

```
Key: `ai_session_{courseId}`
Value: JSON string of:
{
  sessionId: string;
  courseId: string;
  createdAt: string;    // ISO-8601
  expiresAt: string;    // ISO-8601
}

Key: `ai_proposals_{courseId}` (optional — cache for proposal UI recovery)
Value: JSON string of proposal ID array
```

On page load:
1. Read `ai_session_{courseId}` from sessionStorage.
2. If found and `expiresAt` is in the future, call `GET /api/v1/ai/sessions/{sessionId}` to rehydrate.
3. If the API returns 404 (expired/cleaned), clear sessionStorage and set status to `expired`.
4. If the API returns 200, set session as active.
5. If not found or `expiresAt` is past, session status is `idle`; wait for user to initiate.

On logout:
1. Call `DELETE /api/v1/ai/sessions/{sessionId}` (fire-and-forget).
2. Clear all `ai_session_*` and `ai_proposals_*` keys from sessionStorage.

### 2.8 Feature Flag Integration

The existing `FeatureFlagService` in `app/utils/feature_flags.py` exposes `ai_suggestions` flag. A new `AI_AUTHORING_ENABLED` environment variable must be added:

**.env addition:**
```ini
AI_AUTHORING_ENABLED=true
```

On the frontend, read this flag from a configuration endpoint or build-time env:

```typescript
// src/config/ai.ts
export const AI_AUTHORING_ENABLED = 
  import.meta.env.VITE_AI_AUTHORING_ENABLED === 'true' || false;

// For runtime config, add a backend endpoint:
// GET /api/v1/ai/config
// Response: { aiAuthoringEnabled: boolean, maxSessionDurationMinutes: number, allowedFileTypes: string[] }
```

The `AIToolbarButton` component conditionally renders based on this flag:

```typescript
function AIToolbarButton({ onClick }: { onClick: () => void }) {
  const aiEnabled = useAIConfig().aiAuthoringEnabled;
  if (!aiEnabled) return null;
  return (
    <button className="toolbar-btn ai-button" onClick={onClick}>
      <SparklesIcon /> Build with AI
    </button>
  );
}
```

### 2.9 Error Envelope Normalization

The frontend AI client normalizes all backend errors into a consistent shape:

```typescript
interface NormalizedError {
  statusCode: number;
  code: string;                    // e.g., 'SESSION_EXPIRED', 'PAGE_NOT_FOUND'
  message: string;                 // User-facing message
  field?: string;                  // Field that caused the error
  details: Record<string, unknown>; // Additional context
  retryable: boolean;              // Whether the user can retry the action
  isSessionExpired: boolean;
  isConflict: boolean;
  isRateLimited: boolean;
}
```

Mapping from backend error envelope (`app/utils/error_envelope.py`):

| Backend Error Code | Frontend Code | Retryable | User Message |
|---|---|---|---|
| SESSION_EXPIRED | SESSION_EXPIRED | false | "Your AI session expired. Please start a new session." |
| SESSION_NOT_FOUND | SESSION_EXPIRED | false | "Your AI session was not found. Please start a new session." |
| PAGE_NOT_FOUND | PAGE_NOT_FOUND | false | "The requested page was not found. It may have been deleted." |
| PAGE_NOT_IN_SCOPE | PERMISSION_DENIED | false | "This page is not part of the current course scope." |
| DUPLICATE_PROPOSAL | CONFLICT | true | "A pending proposal already exists for this action. Please review it." |
| CONFIRMATION_EXPIRED | CONFIRMATION_EXPIRED | true | "The confirmation window has expired. Please try again." |
| INVALID_CONFIRMATION_TOKEN | PERMISSION_DENIED | false | "Invalid confirmation. Please re-propose the action." |
| PAGE_CHANGED | CONFLICT | true | "The page was modified since the proposal. Please re-propose." |
| PAGE_ALREADY_DELETED | GONE | false | "This page was already deleted." |
| PROPOSAL_ALREADY_APPLIED | CONFLICT | false | "This proposal has already been applied." |
| USER_CONFIRMATION_REQUIRED | VALIDATION_ERROR | true | "You must explicitly confirm this action." |
| VALIDATION_ERROR | VALIDATION_ERROR | true | "One or more fields failed validation. Check the messages above." |
| FEATURE_NOT_AVAILABLE | FEATURE_DISABLED | false | "This AI feature is not available." |
| RATE_LIMIT_EXCEEDED | RATE_LIMITED | true | "Too many requests. Please wait X minutes and try again." |
| SERVER_ERROR | SERVER_ERROR | true | "The server encountered an error. Please try again." |
| PROVIDER_TIMEOUT | SERVICE_UNAVAILABLE | true | "The AI service is temporarily unavailable. Please try again." |

### 2.10 Main Application Registration

In the frontend app root (e.g., `src/App.tsx` or `src/main.tsx`):

```typescript
// Lazy-load the AI module only when the feature flag is enabled
const AIPanel = React.lazy(() => import('./ai/components/AIPanel'));

function App() {
  const aiConfig = useAIConfig();

  return (
    <CourseEditorProvider>
      {/* Existing editor routes */}
      <Routes>
        <Route path="/courses/:courseId" element={<CourseEditor />} />
        {/* ... existing routes unchanged ... */}
      </Routes>

      {/* AI integration — injected only when enabled */}
      {aiConfig.aiAuthoringEnabled && (
        <Suspense fallback={null}>
          <AIPanel />
        </Suspense>
      )}
    </CourseEditorProvider>
  );
}
```

The `AIPanel` component registers itself in the editor layout via a portal or slot system:

```typescript
// AIPanel.tsx — renders as a collapsible sidebar or bottom panel
function AIPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const { session, createSession, status: sessionStatus } = useAISession();
  const { messages, sendMessage } = useChat(session?.sessionId ?? null, session?.courseId ?? null);
  const { proposals, applyProposal } = useProposal(session?.sessionId ?? null);

  if (sessionStatus === 'expired') {
    return <AISessionExpiredBanner onRestart={() => createSession(currentCourseId)} />;
  }

  if (!isOpen) {
    return <AIToolbarButton onClick={() => setIsOpen(true)} />;
  }

  return (
    <AIPanelContainer onClose={() => setIsOpen(false)}>
      <AISessionBanner remainingMs={remainingMs} />
      <ChatWindow messages={messages} onSend={sendMessage} />
      {proposals.map(p => (
        <ProposalCard
          key={p.proposalId}
          proposal={p}
          onApply={applyProposal}
          onReject={rejectProposal}
          onConfirmDelete={(id) => setDeleteProposalId(id)}
        />
      ))}
      <FileUploadArea sessionId={session?.sessionId} courseId={session?.courseId} />
      <ConfirmationModal
        proposal={deleteProposal}
        isOpen={deleteProposalId !== null}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteProposalId(null)}
      />
    </AIPanelContainer>
  );
}
```

---

## 3. Non-Functional Requirements

### 3.1 Performance

| Requirement | Target | Measurement |
|---|---|---|
| AI panel initial render | < 200 ms | First paint from click to visible panel |
| Chat message send -> response rendered | < 500 ms (time to first token), < 5 s (full response) | End-to-end from user click to assistant message rendered |
| Proposal card render | < 100 ms | Time from response received to card visible |
| Diff computation | < 50 ms for typical page (20 fields) | `diffRenderer.ts` execution time |
| Confirmation modal open | < 100 ms | Click to modal visible |
| File upload progress updates | >= 1 update per 200 ms | Progress callback frequency |
| Session expiry countdown accuracy | within 1 second | `setInterval` tick rate |
| AI panel memory footprint | < 5 MB | Heap allocation attributed to `src/ai/` module |

### 3.2 Security

| Requirement | Implementation |
|---|---|
| Session token storage | `sessionStorage` only (not persisted to disk; cleared on tab close) |
| Session token in HTTP headers | `Authorization: Bearer <token>` — never in URL params or POST body |
| Confirmation token display | Never displayed to user in UI; stored in component state only |
| Destructive action guard | Must type "DELETE" to enable confirm button — prevents accidental clicks |
| File type validation | Client-side check for `application/pdf` and `application/vnd.openxmlformats-officedocument.wordprocessingml.document` MIME types before upload |
| File size limit | Reject files > 50 MB client-side before upload (backend also enforces) |
| XSS prevention | All AI-generated HTML content sanitized via DOMPurify before rendering in preview |
| Input sanitization | User prompt text sanitized for HTML before rendering in chat bubbles |
| CSRF protection | `Authorization` header with bearer token provides implicit CSRF protection |
| Feature flag hiding | When `AI_AUTHORING_ENABLED=false`, no AI UI renders and no AI API calls are made |
| Session storage cleanup | On logout, all `ai_session_*` and `ai_proposals_*` keys cleared |

### 3.3 Data Integrity

| Requirement | Implementation |
|---|---|
| Proposal apply idempotency | Apply button disabled after first click; show spinner; on error, enable again |
| Optimistic updates | Never apply optimistic page mutations — wait for API confirmation before updating UI |
| Session consistency | On page reload, always re-fetch session state from API before rendering AI panel |
| Upload resumability | Not implemented in MVP — failed uploads must be re-selected |
| Chat message persistence | Messages stored in component state only; on session recovery, backend provides last turn context |

### 3.4 Availability

| Requirement | Implementation |
|---|---|
| Graceful degradation when AI backend is down | AI panel shows "Service unavailable" with retry button; manual editor remains fully functional |
| Feature flag runtime change | Fetch `GET /api/v1/ai/config` every 5 minutes or on page navigation to detect flag changes |
| Upload network failure | Show error with retry button; upload state is lost (must re-select file) |
| Session expiry during chat | Show countdown at 5 minutes; on expiry, disable input and show restart button (messages preserved) |
| Concurrent session conflict | If another tab creates a session, the current tab detects on next API call and handles gracefully |

### 3.5 Observability

| Requirement | Implementation |
|---|---|
| AI API call logging | Every AI API call logs to browser console in development: `[AI] POST /api/v1/ai/chat 200 1.2s` |
| Error tracking | All AIApiError instances reported to error tracking service (Sentry, etc.) with sessionId, operation, error code |
| Performance marks | `performance.mark()` and `performance.measure()` for key operations: session create, chat send, proposal apply |
| Feature flag state | Logged on app init: `[AI] AI_AUTHORING_ENABLED = true` |
| Upload telemetry | Upload file size, type, duration logged for analytics |

---

## 4. Current State

### 4.1 What Exists Today

1. **Backend AI endpoints (planned, not yet implemented):**
   - `POST /api/v1/ai/sessions`, `GET /api/v1/ai/sessions/{sessionId}`, `DELETE /api/v1/ai/sessions/{sessionId}` (US-AI-006).
   - `POST /api/v1/ai/proposals/*` (US-AI-009, US-AI-011, US-AI-012, US-AI-013).
   - `POST /api/v1/ai/chat` (US-AI-023).
   - `POST /api/v1/files/upload`, `POST /api/v1/files/approve` (US-AI-016, US-AI-017, US-AI-019).

2. **Existing frontend structure:**
   - `src/services/*` — service-layer architecture with `httpClient` for API calls.
   - `src/export-runtime/*` — SCORM export runtime renderer implementations (18 template types).
   - `src/context/CourseContext.tsx` — course state management (legacy, being deprecated).
   - Feature flag reading from `import.meta.env.VITE_*` environment variables.

3. **Feature flags:** `app/utils/feature_flags.py` has an `ai_suggestions` flag but no `AI_AUTHORING_ENABLED` env var.

4. **Error envelopes:** `app/utils/error_envelope.py` provides normalized error shapes with `code`, `field`, `message`, `details`.

5. **Architecture documentation:**
   - `docs/FRONTEND_INTEGRATION_BRIEF_2026-04-12.md` describes SCORM player integration.
   - `docs/AI_Implemenation/PRODUCTION_READY_AI_AUTHORING_ARCHITECTURE.md` describes the full AI system architecture with frontend/backend separation.
   - `docs/AI_Implemenation/01_SystemArchitecture/*.mmd` contains Mermaid flow diagrams for all AI workflows.
   - `docs/AI_Implemenation/file_for_refrence_from_frontEnd/AI_IMPLEMENTATION_REFERENCE.md` contains demo-scoped architecture decisions.

6. **No frontend AI module exists today.** The directory `src/ai/` does not exist. No React components, hooks, API clients, or TypeScript types for AI are implemented.

### 4.2 What is Missing

1. All files under `src/ai/` — the entire isolated AI integration module.
2. TypeScript types for session, proposal, chat, and ingestion domains.
3. AI API client with session auth header injection and normalized error handling.
4. Session lifecycle hook with `sessionStorage` persistence and expiry countdown.
5. Chat hook with optimistic message rendering and proposal extraction.
6. Proposal hook with apply/reject/confirm operations.
7. File ingestion hook with upload progress and breakdown approval.
8. All AI UI components: `AIPanel`, `ChatWindow`, `ChatMessage`, `ProposalCard`, `ProposalDiff`, `ConfirmationModal`, `FileUploadArea`, `ExtractionPreview`, `AISessionBanner`, `ValidationBadge`, `BatchValidationSummary`, `AIToolbarButton`.
9. Diff computation utility (`diffRenderer.ts`).
10. Error formatter utility mapping backend error codes to user-facing messages.
11. Feature flag integration for `AI_AUTHORING_ENABLED`.
12. Lazy-load integration point in the app root.
13. Unit tests for hooks, API client, diff renderer, and error formatter.
14. Component tests for all AI components.
15. Integration tests for the full AI flow with mocked backend responses.

### 4.3 Dependencies on Earlier Stories

| Story | Dependency |
|---|---|
| US-AI-002 | `AI_AUTHORING_ENABLED` feature flag and model config |
| US-AI-003 | Isolated AI API module structure (`/api/v1/ai/*`) |
| US-AI-004 | AI persistence (sessions, proposals tables) |
| US-AI-005 | Tool schema definitions (for proposal type rendering) |
| US-AI-006 | Session lifecycle endpoints (`POST/GET/DELETE /api/v1/ai/sessions`) |
| US-AI-009 | Generic proposal lifecycle (statuses, preview data, validation) |
| US-AI-011 | Create page proposal endpoint |
| US-AI-012 | Update page proposal endpoint |
| US-AI-013 | Delete page proposal and confirmation endpoints |
| US-AI-016 | File upload endpoint |
| US-AI-017 | Document extraction and page-plan review endpoint |
| US-AI-019 | Full course from file (batch proposal apply) |
| US-AI-023 | Chat endpoint (`POST /api/v1/ai/chat`) |

---

## 5. Expansion Points

### 5.1 Streaming Chat Responses (Post-MVP)

Instead of waiting for the full chat response, the chat endpoint could stream responses using Server-Sent Events (SSE) or WebSockets. The frontend would show tokens as they arrive, with proposals appearing inline as they are created. This requires:
- Backend support for streaming chat responses (US-AI-023 enhancement).
- Frontend `ChatWindow` to handle partial message rendering.
- Proposal objects to be embedded in stream events rather than only in the final response.

### 5.2 Undo/Redo for Applied Proposals (Post-MVP)

After a proposal is applied, show an "Undo" toast for 10 seconds. Undo creates a reverse proposal (e.g., delete page if created, restore page if deleted). This requires:
- Backend support for undo proposals (US-AI-040 enhancement).
- Frontend toast system with undo action callback.
- 10-second undo window stored in proposal state.

### 5.3 Keyboard Shortcuts for AI Panel (Post-MVP)

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+A` | Toggle AI panel open/closed |
| `Ctrl+Enter` | Send chat message |
| `Escape` | Close panel or dismiss modal (non-destructive only) |
| `Ctrl+Shift+Enter` | Apply current proposal |

### 5.4 Multi-Tab Session Sync (Post-MVP)

If the user opens the same course in multiple tabs, sync the AI session across tabs using `BroadcastChannel` API:
- Tab A creates session -> broadcasts `sessionCreated` event.
- Tab B receives event and rehydrates from the same session.
- Proposal applied in Tab A -> invalidates proposals in Tab B.

### 5.5 Dark Mode for AI Panel (Post-MVP)

The AI panel should respect the application's theme system. Currently the app has `default`, `dark`, `light`, `corporate` theme types (from `app/models/course.py`). All AI components should use CSS custom properties for theming.

### 5.6 Mobile Responsive AI Panel (Post-MVP)

On mobile viewports (< 768px), the AI panel should render as a full-screen overlay rather than a sidebar. The chat input should auto-focus on open, and the confirmation modal should use a bottom-sheet pattern instead of a centered modal.

### 5.7 AI Panel History Persistence (Post-MVP)

Store chat history per session in IndexedDB so that when a user returns to a course, they can see the previous AI conversation. The backend already persists the last turn; this extension adds full conversation history client-side.

---

## 6. Validation and Test Scenarios

### 6.1 Unit Tests (Hooks and API Client)

```typescript
// File: src/ai/__tests__/api/client.test.ts

describe('AIClient', () => {
  it('injects Authorization header when session token is available', async () => {
    // Mock fetch, create AIClient with getSessionToken returning 'test-token'
    // Call client.get('/sessions/test-id')
    // Verify fetch called with headers.Authorization === 'Bearer test-token'
  });

  it('does not inject Authorization header when no token', async () => {
    // Mock getSessionToken returning null
    // Verify fetch called without Authorization header
  });

  it('throws AIApiError with normalized fields on 403', async () => {
    // Mock fetch returning 403 with { code: 'SESSION_EXPIRED', message: '...' }
    // Verify error.code === 'SESSION_EXPIRED'
    // Verify error.isSessionExpired === true
    // Verify error.statusCode === 403
  });

  it('throws AIApiError with retryable=true on 409', async () => {
    // Mock fetch returning 409 with { code: 'PAGE_CHANGED', ... }
    // Verify error.retryable === true
    // Verify error.isConflict === true
  });

  it('throws AIApiError with retryAfterMs from details on 429', async () => {
    // Mock fetch returning 429 with { code: 'RATE_LIMIT_EXCEEDED', details: { retryAfter: 3600 } }
    // Verify error.isRateLimited === true
    // Verify error.retryAfterMs === 3600000
  });

  it('handles network errors gracefully', async () => {
    // Mock fetch throwing TypeError
    // Verify AIApiError with statusCode 0 and code 'NETWORK_ERROR'
  });
});

// File: src/ai/__tests__/hooks/useAISession.test.ts

describe('useAISession', () => {
  it('creates session and stores in sessionStorage', async () => {
    // Mock POST /api/v1/ai/sessions returning valid session
    // Call createSession('course-1')
    // Verify sessionStorage has 'ai_session_course-1'
  });

  it('sets status to expired when API returns 404 on refresh', async () => {
    // Mock GET /api/v1/ai/sessions/{id} returning 404
    // Call refreshSession()
    // Verify status === 'expired'
  });

  it('counts down remaining time', async () => {
    // Create session with expiresAt = now + 10s
    // Advance timer by 3s
    // Verify remainingMs ≈ 7000
  });

  it('clears session storage on endSession', async () => {
    // Create session, then call endSession
    // Verify sessionStorage no longer has ai_session_*
  });

  it('handles API error during createSession', async () => {
    // Mock POST returning 500
    // Call createSession and expect error
    // Verify status === 'error' and error message is set
  });

  it('does not create session when feature flag is disabled', async () => {
    // Mock aiConfig.aiAuthoringEnabled = false
    // Verify createSession throws FEATURE_DISABLED
  });
});

// File: src/ai/__tests__/hooks/useChat.test.ts

describe('useChat', () => {
  it('sends message and receives response with proposals', async () => {
    // Mock POST /api/v1/ai/chat returning message + proposals
    // Call sendMessage('Create a page')
    // Verify messages array has user message then assistant message
    // Verify assistant message has proposals array with 1 entry
  });

  it('shows optimistic user message immediately', async () => {
    // Call sendMessage(), verify user message in messages before API resolves
  });

  it('sets isSending while waiting for response', async () => {
    // Create a deferred promise for the API call
    // Call sendMessage(), verify isSending === true
    // Resolve, verify isSending === false
  });

  it('handles errors without losing previous messages', async () => {
    // Send message that fails with 500
    // Verify error is set, previous messages remain, isSending is false
  });

  it('does not send when sessionId is null', async () => {
    // Call useChat(null, null), send message
    // Verify fetch is not called
  });

  it('clears messages on clearMessages', async () => {
    // Send a message, then call clearMessages
    // Verify messages array is empty
  });
});

// File: src/ai/__tests__/hooks/useProposal.test.ts

describe('useProposal', () => {
  it('adds proposals from chat response to state', async () => {
    // Simulate receiving a chat response with proposals
    // Verify proposals array is populated
  });

  it('removes proposal from state on reject', async () => {
    // Add proposal, then reject it
    // Verify proposal removed from state
  });

  it('calls apply endpoint and removes on success', async () => {
    // Mock POST /api/v1/ai/proposals/{id}/apply
    // Call applyProposal('prop-1')
    // Verify endpoint called with sessionId and userConfirmed: true
    // Verify proposal removed from state on success
  });

  it('sets isApplying while apply is in flight', async () => {
    // Create deferred promise, call applyProposal
    // Verify isApplying === true, then false after resolve
  });

  it('keeps proposal in state on apply error', async () => {
    // Mock apply returning 409
    // Call applyProposal, verify proposal still in state, error is set
  });
});

// File: src/ai/__tests__/hooks/useFileIngestion.test.ts

describe('useFileIngestion', () => {
  it('uploads file with progress tracking', async () => {
    // Mock XHR upload with progress events
    // Call uploadFile, simulate progress
    // Verify uploadProgress updates correctly
  });

  it('rejects unsupported file types client-side before upload', async () => {
    // Try uploading .exe file
    // Verify error is set, upload not called
  });

  it('rejects files over 50MB before upload', async () => {
    // Create 51MB Blob, try uploading
    // Verify error is set, upload not called
  });

  it('parses extraction result into proposed pages', async () => {
    // Mock upload response with extraction result
    // Verify proposedPages is populated from extraction.sections
  });

  it('calls approve with modified proposed pages', async () => {
    // Upload, modify proposed pages, call approveBreakdown
    // Verify POST /api/v1/files/approve called with correct body
  });

  it('resets state on reset call', async () => {
    // Upload, then reset
    // Verify uploadJob, extractionResult, proposedPages all null
  });
});
```

### 6.2 Component Tests

```typescript
// File: src/ai/__tests__/components/ConfirmationModal.test.tsx

describe('ConfirmationModal', () => {
  it('renders proposal details: title, template type, warnings', () => {
    // Render with a delete proposal
    // Verify page title shown, template type shown, dependency warnings shown
  });

  it('has confirm button disabled until DELETE is typed', () => {
    // Render modal
    // Verify Delete button is disabled
    // Type "DELETE" in confirmation input
    // Verify Delete button becomes enabled
    // Clear input, verify button disabled again
  });

  it('shows irreversible action notice', () => {
    // Verify red-bordered box with "cannot be undone" text is visible
  });

  it('calls onConfirm with proposalId when Delete clicked', async () => {
    // Type DELETE, click Delete
    // Verify onConfirm called with proposalId
  });

  it('calls onCancel when Cancel clicked', () => {
    // Click Cancel
    // Verify onCancel called
  });

  it('shows loading state during confirmation', () => {
    // Render with onConfirm returning pending promise
    // Type DELETE, click Delete
    // Verify button shows spinner, input is disabled
  });

  it('shows inline error when confirmation fails', async () => {
    // Mock onConfirm throwing AIApiError with CONFIRMATION_EXPIRED
    // Type DELETE, click Delete
    // Verify error message shown, modal still open
  });

  it('cannot be dismissed by clicking backdrop', () => {
    // Click on modal backdrop
    // Verify onCancel NOT called
  });

  it('cannot be dismissed by pressing Escape', () => {
    // Press Escape key
    // Verify onCancel NOT called
  });

  it('renders dependency warnings with severity icons', () => {
    // Render with proposal that has multiple dependency warnings
    // Verify each warning has correct severity icon (error/warning/info)
  });

  it('renders empty state when no dependency warnings', () => {
    // Render proposal with empty dependencyWarnings
    // Verify warnings section is not rendered
  });
});

// File: src/ai/__tests__/components/ProposalCard.test.tsx

describe('ProposalCard', () => {
  it('renders operation type badge', () => {
    // Render with create_page proposal
    // Verify "CREATE" badge shown
  });

  it('renders page title and template type', () => { /* ... */ });
  it('shows Apply and Reject buttons for non-destructive proposals', () => { /* ... */ });
  it('shows Review & Confirm button instead of Apply for delete proposals', () => { /* ... */ });
  it('disables Apply button when validation errors exist', () => { /* ... */ });
  it('shows validation error badges with count', () => { /* ... */ });
  it('shows validation warning badges with count', () => { /* ... */ });
  it('calls onApply when Apply clicked', () => { /* ... */ });
  it('calls onReject when Reject clicked', () => { /* ... */ });
  it('shows loading spinner during apply', () => { /* ... */ });
  it('shows success state after apply', () => { /* ... */ });
  it('shows error state with retry button on apply failure', () => { /* ... */ });
  it('renders ProposalDiff for update proposals', () => { /* ... */ });
});

// File: src/ai/__tests__/components/ProposalDiff.test.tsx

describe('ProposalDiff', () => {
  it('renders before and after values for changed fields', () => { /* ... */ });
  it('highlights added fields in green', () => { /* ... */ });
  it('highlights removed fields in red with strikethrough', () => { /* ... */ });
  it('shows field paths for each change', () => { /* ... */ });
  it('collapses unchanged fields in accordion', () => { /* ... */ });
  it('shows summary count of changed vs unchanged fields', () => { /* ... */ });
  it('handles empty before object (create page diff)', () => { /* ... */ });
  it('handles nested object diffs', () => { /* ... */ });
  it('handles array diffs (component list changes)', () => { /* ... */ });
});

// File: src/ai/__tests__/components/ExtractionPreview.test.tsx

describe('ExtractionPreview', () => {
  it('renders a row for each proposed page', () => { /* ... */ });
  it('allows inline editing of page titles', () => { /* ... */ });
  it('allows template type selection via dropdown', () => { /* ... */ });
  it('supports drag-and-drop reordering', () => { /* ... */ });
  it('allows deletion of rows', () => { /* ... */ });
  it('disables Approve button when no proposed pages', () => { /* ... */ });
  it('shows loading state during approve', () => { /* ... */ });
  it('shows error state if approve fails', () => { /* ... */ });
  it('shows per-row validation status after approve response', () => { /* ... */ });
  it('adds new empty row on Add Page button click', () => { /* ... */ });
});

// File: src/ai/__tests__/components/ChatWindow.test.tsx

describe('ChatWindow', () => {
  it('renders message list with user and assistant messages', () => { /* ... */ });
  it('scrolls to bottom on new message', () => { /* ... */ });
  it('disables input while isSending', () => { /* ... */ });
  it('shows typing indicator while waiting for response', () => { /* ... */ });
  it('renders ProposalCard below assistant messages with proposals', () => { /* ... */ });
  it('shows error state when send fails', () => { /* ... */ });
  it('renders empty state when no messages', () => { /* ... */ });
  it('renders session expiry warning at 5 minutes', () => { /* ... */ });
  it('disables input when session is expired', () => { /* ... */ });
  it('shows restart button when session is expired', () => { /* ... */ });
  it('sends message on Enter (without Shift)', () => { /* ... */ });
  it('inserts newline on Shift+Enter', () => { /* ... */ });
});
```

### 6.3 Integration Tests (Mocked API)

```typescript
// File: src/ai/__tests__/integration/aiFlow.test.tsx

describe('AI Integration Flow', () => {
  it('full happy path: create session -> send chat -> apply proposal', async () => {
    // 1. Render app with AI enabled
    // 2. Click "Build with AI"
    // 3. Mock POST /api/v1/ai/sessions -> session created
    // 4. Mock POST /api/v1/ai/chat -> message + create_page proposal
    // 5. Verify ProposalCard appears with Apply button
    // 6. Mock POST /api/v1/ai/proposals/{id}/apply -> success
    // 7. Click Apply
    // 8. Verify proposal card shows success state
    // 9. Verify course state refreshes
  });

  it('delete flow: proposal -> confirmation modal -> confirm', async () => {
    // 1. Send chat message requesting page deletion
    // 2. Mock POST /api/v1/ai/chat -> message + delete_page proposal
    // 3. Verify ProposalCard shows "Review & Confirm" button
    // 4. Click "Review & Confirm"
    // 5. Verify ConfirmationModal opens with warnings
    // 6. Type "DELETE", click Delete
    // 7. Verify proposal removed from list
  });

  it('expired session during chat shows restart prompt', async () => {
    // 1. Create session
    // 2. Mock all API calls returning 403 SESSION_EXPIRED
    // 3. Send message
    // 4. Verify session banner shows "Session expired"
    // 5. Verify chat input is disabled
    // 6. Click restart
    // 7. Mock POST /api/v1/ai/sessions -> new session
    // 8. Verify session is active again, input enabled
  });

  it('validation errors block proposal apply', async () => {
    // 1. Chat response with proposal that has validation errors
    // 2. Verify ProposalCard shows error badges
    // 3. Verify Apply button is disabled
  });

  it('file ingestion flow: upload -> review -> approve -> apply', async () => {
    // 1. Open AI panel, click upload
    // 2. Select PDF file
    // 3. Mock upload with progress -> extraction result
    // 4. Verify ExtractionPreview appears with pages
    // 5. Edit page title, change template type
    // 6. Click "Approve Breakdown"
    // 7. Mock POST /api/v1/files/approve -> batch proposal
    // 8. Verify apply button appears
    // 9. Click apply -> success
    // 10. Verify redirected to course editor
  });

  it('AI feature flag disabled hides all AI UI', async () => {
    // 1. Render with AI_AUTHORING_ENABLED = false
    // 2. Verify "Build with AI" button is not rendered
    // 3. Verify AI panel is not rendered
    // 4. Verify manual editor is unchanged
  });

  it('page reload rehydrates session from API', async () => {
    // 1. Create session, stored in sessionStorage
    // 2. Simulate page reload (remount components)
    // 3. Verify GET /api/v1/ai/sessions/{id} called on mount
    // 4. Verify session is active, chat history empty (re-fetched from backend)
  });

  it('concurrent delete proposal conflict shows error', async () => {
    // 1. Chat returns delete proposal
    // 2. Open confirmation modal
    // 3. Mock confirm endpoint returning 409 PAGE_CHANGED
    // 4. Confirm
    // 5. Verify modal shows error with "Re-propose" button
  });

  it('rate limited during chat shows rate limit error', async () => {
    // 1. Mock POST /api/v1/ai/chat returning 429
    // 2. Send message
    // 3. Verify error message shows retry guidance
    // 4. Verify retryAfterMs used for countdown
  });
});
```

### 6.4 E2E Scenarios (Cypress/Playwright)

**Scenario 1: AI-assisted page creation and apply (happy path)**
1. Navigate to course editor page.
2. Click "Build with AI" button — AI panel opens on the right.
3. Chat input is focused. Type "Create a new welcome page for this course."
4. AI responds with a proposal card showing page preview.
5. Proposal shows "CREATE" badge, page title, template type "text-content", no validation errors.
6. Click "Apply" — button shows spinner.
7. Apply succeeds — proposal card shows green success banner.
8. Course page list refreshes — new page appears at the bottom.
9. Click "Cancel" in the editor — navigate away and back.
10. AI panel session is still active (sessionStorage persisted across navigation).

**Scenario 2: Delete page with destructive confirmation**
1. Open AI panel, type "Delete the page 'Old Content'."
2. AI lists pages, resolves target, returns delete proposal.
3. Proposal card shows "DELETE" badge with "Review & Confirm" button.
4. Click "Review & Confirm" — confirmation modal opens.
5. Modal shows page title, component count (3 components), warning: "This page contains assessment components."
6. Modal shows irreversible action notice.
7. Type "DELETE" in confirmation input — Delete button becomes enabled.
8. Click Delete — spinner shown, modal closes on success.
9. Page removed from course page list.
10. Success toast appears: "Page 'Old Content' has been deleted."

**Scenario 3: Session expiry mid-session**
1. Open AI panel, send message, get response.
2. Mock server time to advance past session expiry.
3. Session banner shows "Session will expire in 4 minutes..." countdown.
4. At 0:00, banner changes to "Session expired."
5. Chat input is disabled with placeholder "Session expired. Click to restart."
6. Click "Restart Session" — new session created, input re-enabled.
7. Previous chat messages are cleared (session is fresh).

**Scenario 4: File upload with page breakdown review**
1. Open AI panel, click upload button.
2. File picker opens — select a PDF (course_outline.pdf).
3. Upload progress bar fills to 100%.
4. Extraction preview table appears with 4 proposed pages.
5. Edit page title "Intro" -> "Module 1: Introduction".
6. Change template type "text-content" -> "tabs" for page 3.
7. Drag page 4 to position 2.
8. Click "Approve Breakdown" — spinner shown.
9. Generation succeeds — batch validation shows all 4 pages valid.
10. Click "Confirm & Create" — success, course editor loads with 4 new pages.

**Scenario 5: Validation errors prevent apply**
1. Send chat message: "Create a final assessment with 1 question."
2. AI returns proposal for final assessment page with 1 question.
3. Proposal card shows red error badge: "1 blocking error".
4. Error message: "Final assessment requires at least 3 questions."
5. Apply button is disabled.
6. User clicks "Reject" — proposal dismissed.
7. User types: "Make it 5 questions instead."
8. New proposal created with 5 questions — valid, Apply enabled.

**Scenario 6: AI feature flag disabled**
1. Navigate to course editor with `AI_AUTHORING_ENABLED=false`.
2. Verify "Build with AI" button is not in toolbar.
3. Verify no AI UI elements are visible anywhere in the editor.
4. Manual authoring (add page, edit, delete, reorder) works identically to pre-AI baseline.
5. Navigate to course list — verify no AI-related UI.

### 6.5 Accessibility Tests

```typescript
describe('AI Panel Accessibility', () => {
  it('all interactive elements are keyboard navigable', () => { /* Tab through all controls */ });
  it('chat input has accessible label', () => { /* aria-label="AI chat message input" */ });
  it('proposal cards have role="region" and aria-label', () => { /* ... */ });
  it('confirmation modal traps focus', () => { /* Tab cycles within modal only */ });
  it('confirmation modal has role="alertdialog"', () => { /* ... */ });
  it('validation errors are announced by screen reader', () => { /* aria-live="polite" */ });
  it('session expiry countdown is announced', () => { /* aria-live="assertive" at 5 min */ });
  it('upload progress is announced', () => { /* role="progressbar" with aria-valuenow */ });
  it('diff view uses appropriate heading levels', () => { /* ... */ });
  it('all icons have aria-hidden or accessible labels', () => { /* ... */ });
});
```

---

## 7. Definition of Done

### 7.1 Code Complete

- [ ] `src/ai/api/client.ts` — shared AI HTTP client with session auth, error normalization, upload progress via XHR.
- [ ] `src/ai/api/sessions.ts` — createSession, getSession, deleteSession functions.
- [ ] `src/ai/api/proposals.ts` — proposeCreatePage, proposeUpdatePage, proposeDeletePage, confirmDelete functions (frontend API wrappers).
- [ ] `src/ai/api/chat.ts` — sendChatMessage function.
- [ ] `src/ai/api/ingestion.ts` — uploadFile, pollJob, approveBreakdown functions.
- [ ] `src/ai/types/session.ts` — AISession, SessionState, CreateSessionRequest/Response types.
- [ ] `src/ai/types/proposal.ts` — AIProposal, ProposalOperation, ProposalStatus, ProposalDiff, ValidationMessage, DependencyWarning types.
- [ ] `src/ai/types/chat.ts` — ChatMessage, ChatRequest, ChatResponse, ToolCallTrace types.
- [ ] `src/ai/types/ingestion.ts` — UploadJob, ExtractionResult, ProposedPage types.
- [ ] `src/ai/hooks/useAISession.ts` — session lifecycle hook.
- [ ] `src/ai/hooks/useChat.ts` — chat state hook.
- [ ] `src/ai/hooks/useProposal.ts` — proposal state hook.
- [ ] `src/ai/hooks/useFileIngestion.ts` — file upload and extraction hook.
- [ ] `src/ai/stores/aiSessionStore.ts` — session state store (Zustand/Context).
- [ ] `src/ai/stores/aiProposalStore.ts` — proposal state store.
- [ ] `src/ai/components/AIPanel.tsx` — root panel container.
- [ ] `src/ai/components/AISessionBanner.tsx` — session expiry countdown banner.
- [ ] `src/ai/components/AIToolbarButton.tsx` — "Build with AI" button.
- [ ] `src/ai/components/ChatWindow.tsx` — message list and input.
- [ ] `src/ai/components/ChatMessage.tsx` — single chat bubble.
- [ ] `src/ai/components/ProposalCard.tsx` — inline proposal preview.
- [ ] `src/ai/components/ProposalDiff.tsx` — field-level before/after diff.
- [ ] `src/ai/components/ValidationBadge.tsx` — validation status icon.
- [ ] `src/ai/components/ConfirmationModal.tsx` — destructive confirmation modal.
- [ ] `src/ai/components/FileUploadArea.tsx` — drag-and-drop upload with progress.
- [ ] `src/ai/components/ExtractionPreview.tsx` — page breakdown review table.
- [ ] `src/ai/components/BatchValidationSummary.tsx` — per-page validation status.
- [ ] `src/ai/utils/sessionStorage.ts` — sessionStorage helpers.
- [ ] `src/ai/utils/diffRenderer.ts` — diff computation utility.
- [ ] `src/ai/utils/errorFormatter.ts` — error normalization utility.
- [ ] Integration point in `src/App.tsx` or equivalent (lazy-loaded AI module).
- [ ] Environment variable `VITE_AI_AUTHORING_ENABLED` or runtime config endpoint integration.
- [ ] `.env.example` updated with `VITE_AI_AUTHORING_ENABLED`.

### 7.2 Tests Pass

- [ ] All unit tests pass (40+ tests across hooks, API client, utilities).
- [ ] All component tests pass (30+ tests across all AI components).
- [ ] All integration tests pass (10+ full-flow tests with mocked API).
- [ ] All accessibility tests pass (10+ tests).
- [ ] Existing manual authoring tests still pass (regression: no changes to existing components).
- [ ] Test coverage >= 80% for `src/ai/` directory (aim for 90%+ for hooks and utilities).

### 7.3 Manual Authoring Preservation

- [ ] With `AI_AUTHORING_ENABLED=false`, no AI UI elements are rendered.
- [ ] With `AI_AUTHORING_ENABLED=true`, manual editor works identically to baseline.
- [ ] Creating a page manually still works with AI panel open.
- [ ] Editing a page in the editor while AI panel is open does not break either.
- [ ] Deleting a page manually (non-AI) still works via existing `DELETE` endpoint.
- [ ] Export functionality unchanged.
- [ ] Preview functionality unchanged.

### 7.4 Security

- [ ] Session token stored in `sessionStorage` only (not `localStorage`).
- [ ] Session token sent via `Authorization: Bearer` header (never in URL or body).
- [ ] Confirmation modal cannot be dismissed accidentally.
- [ ] Destructive delete requires typing "DELETE" — no single-click delete.
- [ ] AI-generated HTML is sanitized before rendering in preview.
- [ ] User input is sanitized before rendering in chat bubbles.
- [ ] File type and size validated client-side before upload.
- [ ] Session storage cleared on logout.

### 7.5 Operational Readiness

- [ ] AI module is lazy-loaded (code-split from main bundle).
- [ ] Feature flag can be changed without redeploying frontend (runtime config endpoint).
- [ ] All AI API calls log timing in development mode.
- [ ] Error tracking integration (Sentry/LogRocket) for AIApiError events.
- [ ] Performance marks for key operations.
- [ ] Session expiry banner warns at 5 minutes.
- [ ] Degraded mode when AI backend is unreachable (manual editor still works).

### 7.6 Documentation

- [ ] `src/ai/README.md` documents module structure, key hooks, and component API.
- [ ] TypeScript types are exported from `src/ai/index.ts` for external consumption.
- [ ] Storybook stories for all AI components (optional, recommended).
- [ ] Environment variables documented in frontend `.env.example`.

---

## 8. Tasks

### Task 1: Define TypeScript Types for All AI Domains

**Files to create:**
- `src/ai/types/session.ts`
- `src/ai/types/proposal.ts`
- `src/ai/types/chat.ts`
- `src/ai/types/ingestion.ts`
- `src/ai/types/index.ts` (barrel export)

**Acceptance:**
- All types defined as shown in section 2.2.
- Types use `interface` for objects and `type` for unions/literals.
- All types are exported from barrel file.
- JSDoc comments on all fields.

**Effort:** 1 hour  
**Dependencies:** US-AI-006, US-AI-009 API contract definitions

---

### Task 2: Implement AI API Client with Session Auth and Error Normalization

**Files to create:**
- `src/ai/api/client.ts`
- `src/ai/api/index.ts`

**Acceptance:**
- `AIClient` class with `get`, `post`, `delete`, `uploadFile` methods.
- Injects `Authorization: Bearer <token>` header when session token is available.
- `uploadFile` uses XHR with progress callback support.
- `AIApiError` class with `isSessionExpired`, `isConflict`, `isRateLimited`, `retryAfterMs` helpers.
- Error normalization maps backend error codes (section 2.9).
- All methods return typed promises.

**Effort:** 2 hours  
**Dependencies:** Task 1 (types)

---

### Task 3: Implement API Functions for Each Domain

**Files to create:**
- `src/ai/api/sessions.ts`
- `src/ai/api/proposals.ts`
- `src/ai/api/chat.ts`
- `src/ai/api/ingestion.ts`

**Acceptance:**
- Each module exports typed async functions that use `AIClient`.
- `sessions.ts`: `createSession`, `getSession`, `deleteSession`.
- `proposals.ts`: `applyProposal`, `confirmDeleteProposal`, `rejectProposal`.
- `chat.ts`: `sendChatMessage`.
- `ingestion.ts`: `uploadFile`, `approveBreakdown`.

**Effort:** 1.5 hours  
**Dependencies:** Task 2 (client)

---

### Task 4: Implement Utility Functions

**Files to create:**
- `src/ai/utils/sessionStorage.ts`
- `src/ai/utils/diffRenderer.ts`
- `src/ai/utils/errorFormatter.ts`
- `src/ai/utils/index.ts`

**Acceptance:**
- `sessionStorage.ts`: `saveSession`, `loadSession`, `clearSession`, `clearAllSessions` functions. Handles JSON parse errors gracefully.
- `diffRenderer.ts`: `computeDiff(before, after)` returns `{ changedFields: string[], beforeValues: Record<string, unknown>, afterValues: Record<string, unknown> }`. Handles nested objects, arrays, null/undefined. Deterministic ordering.
- `errorFormatter.ts`: `formatError(error: AIApiError): NormalizedError` with user-facing message mapping from section 2.9.
- All functions have unit tests.

**Effort:** 2.5 hours  
**Dependencies:** Tasks 1, 2

---

### Task 5: Implement Session Lifecycle Hook

**File to create:**
- `src/ai/hooks/useAISession.ts`
- `src/ai/stores/aiSessionStore.ts`

**Acceptance:**
- `createSession(courseId, orgId?)`: calls API, stores in `sessionStorage`, starts countdown interval.
- `refreshSession()`: reads token from storage, calls `GET /api/v1/ai/sessions/{id}`, handles 404 => expired.
- `endSession()`: calls `DELETE`, clears storage, stops interval.
- `clearSession()`: removes storage without API call.
- `remainingMs` updates every 1 second via `setInterval`.
- Session transitions: `idle` -> `loading` -> `active` -> `expired`/`error`.
- Expired sessions show "restart" prompt (component responsibility).
- Storage operations use `sessionStorage.ts` utility.

**Effort:** 3 hours  
**Dependencies:** Tasks 3, 4

---

### Task 6: Implement Chat Hook

**File to create:**
- `src/ai/hooks/useChat.ts`

**Acceptance:**
- `sendMessage(prompt, context?)`: adds optimistic user message, calls chat API, appends assistant response.
- Assistant response parsed for proposals (attached to message).
- `isSending` reflects API call state.
- `messages` array persists across re-renders (component state).
- Errors handled gracefully (previous messages preserved).
- Does not send when `sessionId` is null.
- `clearMessages()` resets state.

**Effort:** 2.5 hours  
**Dependencies:** Task 5 (session)

---

### Task 7: Implement Proposal Hook

**File to create:**
- `src/ai/hooks/useProposal.ts`
- `src/ai/stores/aiProposalStore.ts`

**Acceptance:**
- Proposals are extracted from chat responses and added to state.
- `applyProposal(proposalId)`: calls apply endpoint, removes from state on success, keeps on error.
- `rejectProposal(proposalId)`: removes from state (local only; backend TTL cleans up).
- `confirmDelete(proposalId)`: calls confirm-delete endpoint.
- `isApplying` reflects apply call state.
- Duplicate proposal IDs are handled (existing proposal updated, not duplicated).

**Effort:** 2 hours  
**Dependencies:** Tasks 3, 5

---

### Task 8: Implement File Ingestion Hook

**File to create:**
- `src/ai/hooks/useFileIngestion.ts`

**Acceptance:**
- `uploadFile(file, description?)`: validates file type and size, calls `uploadFile` with XHR progress.
- `updateProposedPages(pages)`: updates editable page breakdown state.
- `approveBreakdown()`: calls approve endpoint, returns batch proposal.
- File validation: reject non-PDF/DOCX, reject >50MB.
- Progress tracking from XHR `onprogress`.
- Reset function clears all state.

**Effort:** 2 hours  
**Dependencies:** Tasks 3, 5

---

### Task 9: Build Core AI UI Components

**Files to create:**
- `src/ai/components/AIPanel.tsx`
- `src/ai/components/AISessionBanner.tsx`
- `src/ai/components/AIToolbarButton.tsx`
- `src/ai/components/ChatWindow.tsx`
- `src/ai/components/ChatMessage.tsx`

**Acceptance:**
- `AIPanel`: collapsible panel (sidebar or bottom), orchestrates all sub-components, handles lazy loading.
- `AISessionBanner`: shows remaining time, warning at 5 min, expired state with restart button.
- `AIToolbarButton`: conditionally rendered based on feature flag, sparkle icon, opens panel.
- `ChatWindow`: scrollable message list, input area with Send button, Enter to send (Shift+Enter for newline).
- `ChatMessage`: renders user and assistant bubbles. Assistant messages render proposals inline if present.
- All components have loading, empty, error, and edge-case states.
- CSS uses existing design system variables; no layout breaking.

**Effort:** 5 hours  
**Dependencies:** Tasks 5, 6, 7

---

### Task 10: Build Proposal and Confirmation Components

**Files to create:**
- `src/ai/components/ProposalCard.tsx`
- `src/ai/components/ProposalDiff.tsx`
- `src/ai/components/ValidationBadge.tsx`
- `src/ai/components/ConfirmationModal.tsx`

**Acceptance:**
- `ProposalCard`: operation badge, page info, validation badges, diff for updates, Apply/Reject buttons, success/error states.
- `ProposalDiff`: side-by-side field-level diffs with color coding. Collapsed unchanged fields.
- `ValidationBadge`: severity-colored icon with count tooltip.
- `ConfirmationModal`: centered overlay, no backdrop dismiss, "DELETE" text input to enable destructive button, dependency warnings, irreversible notice, loading/error states.
- Focus trap inside confirmation modal.
- Keyboard navigation: Tab cycles within modal, Space to toggle checkbox/button.

**Effort:** 6 hours  
**Dependencies:** Task 4 (diffRenderer), Task 7 (proposals)

---

### Task 11: Build Ingestion UI Components

**Files to create:**
- `src/ai/components/FileUploadArea.tsx`
- `src/ai/components/ExtractionPreview.tsx`
- `src/ai/components/BatchValidationSummary.tsx`

**Acceptance:**
- `FileUploadArea`: drag-and-drop zone, file picker button, progress bar during upload, error state for invalid files, success state with filename.
- `ExtractionPreview`: editable table with drag-and-drop reorder, inline editing, template dropdown, delete row, add page.
- `BatchValidationSummary`: per-page status table with icons, overall valid/invalid indicator.

**Effort:** 5 hours  
**Dependencies:** Task 8 (ingestion hook), Task 10 (ValidationBadge)

---

### Task 12: Register AI Module in Application Root

**Files to modify:**
- `src/App.tsx` or equivalent app root
- `src/config/ai.ts` (new)

**Acceptance:**
- AI module is lazy-loaded via `React.lazy()`.
- `AIPanel` is rendered when `AI_AUTHORING_ENABLED` is true.
- No AI code is imported in the main bundle when `AI_AUTHORING_ENABLED` is false (tree-shaken).
- A runtime config endpoint (`GET /api/v1/ai/config`) is polled every 5 minutes for flag changes.
- Existing editor routes and components are completely unchanged.

**Effort:** 1.5 hours  
**Dependencies:** Tasks 9, 10, 11

---

### Task 13: Write Unit Tests for Hooks and Utilities

**Files to create:**
- `src/ai/__tests__/api/client.test.ts`
- `src/ai/__tests__/hooks/useAISession.test.ts`
- `src/ai/__tests__/hooks/useChat.test.ts`
- `src/ai/__tests__/hooks/useProposal.test.ts`
- `src/ai/__tests__/hooks/useFileIngestion.test.ts`
- `src/ai/__tests__/utils/diffRenderer.test.ts`
- `src/ai/__tests__/utils/sessionStorage.test.ts`
- `src/ai/__tests__/utils/errorFormatter.test.ts`

**Acceptance:**
- All test scenarios from section 6.1 are covered.
- Tests use `vi.mock()` or `jest.mock()` for API calls.
- Tests run in CI without real backend.
- Coverage >= 85% for utility functions.
- Coverage >= 80% for hooks.

**Effort:** 6 hours  
**Dependencies:** Tasks 4, 5, 6, 7, 8

---

### Task 14: Write Component Tests

**Files to create:**
- `src/ai/__tests__/components/ConfirmationModal.test.tsx`
- `src/ai/__tests__/components/ProposalCard.test.tsx`
- `src/ai/__tests__/components/ProposalDiff.test.tsx`
- `src/ai/__tests__/components/ChatWindow.test.tsx`
- `src/ai/__tests__/components/ExtractionPreview.test.tsx`

**Acceptance:**
- All test scenarios from section 6.2 are covered.
- Tests use `@testing-library/react` and `@testing-library/user-event`.
- All component states covered: loading, empty, error, success, edge cases.
- Accessibility assertions included.

**Effort:** 6 hours  
**Dependencies:** Tasks 9, 10, 11

---

### Task 15: Write Integration Tests

**File to create:**
- `src/ai/__tests__/integration/aiFlow.test.tsx`

**Acceptance:**
- All integration scenarios from section 6.3 are covered.
- Tests use mocked API responses with `msw` (Mock Service Worker).
- Full flow tests: session creation -> chat -> proposal -> apply -> success.
- Error flow tests: session expiry, validation errors, page conflicts, rate limiting.
- Feature flag toggle tests.

**Effort:** 4 hours  
**Dependencies:** Tasks 13, 14

---

### Task 16: Documentation and Environment Configuration

**Files to modify/create:**
- `.env.example` (add `VITE_AI_AUTHORING_ENABLED`)
- `src/ai/README.md` (new — module documentation)
- `src/ai/index.ts` (new — public API barrel export)

**Acceptance:**
- Environment variable documented in `.env.example`.
- README explains module structure, how to use hooks, and component API.
- Barrel file exports all public types, hooks, and components.
- Storybook stories for key components (optional).

**Effort:** 1.5 hours  
**Dependencies:** All prior tasks

---

## Summary

| Metric | Value |
|---|---|
| New files | ~30 files |
| Modified files | 3-4 files (app root, config) |
| New directories | `src/ai/` with 8 subdirectories |
| New API endpoints consumed | 6+ (`/api/v1/ai/sessions`, `/api/v1/ai/chat`, `/api/v1/ai/proposals/*`, `/api/v1/files/*`) |
| New React components | 12 |
| New hooks | 4 |
| Total estimated effort | ~51 hours |
| Key non-regression invariant | Manual authoring UI is unchanged when AI is disabled |
| Key risk | Backend AI endpoints (US-AI-006, US-AI-009, US-AI-011, US-AI-012, US-AI-013, US-AI-023) must be available for integration testing |
