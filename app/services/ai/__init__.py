"""AI services package.

This package contains all AI authoring services, organized as:
- mock_auth.py: Mock authentication service (US-BKND-AI-PR01)
- mock_authorization.py: Mock authorization service (US-BKND-AI-PR02)
- mock_tenancy.py: Mock multi-tenancy context (US-BKND-AI-PR03)
- mock_user_org_resolver.py: Mock user/org resolver (US-BKND-AI-PR05)
- config.py: AI configuration service (US-BKND-AI-002)
- error_envelope.py: Standardized AI error response format (US-BKND-AI-003)
- session_service.py: Session lifecycle management (US-BKND-AI-004 ✅)
- proposal_service.py: Proposal CRUD and lifecycle (US-BKND-AI-004 ✅)
- audit_service.py: Audit logging (US-BKND-AI-004 ✅)
- outbox_service.py: Outbox event management (US-BKND-AI-004 ✅)
- confirmation_token_service.py: Confirmation token system (US-BKND-AI-049 ✅)
- chat_orchestrator.py: LLM interaction loop (US-BKND-AI-023)
- validation_pipeline.py: Schema/business/SCORM/accessibility validation
- model_router.py: Provider routing with fallback (US-BKND-AI-026)
- ingestion_service.py: File upload and extraction (US-BKND-AI-016)
- rag_service.py: Similar course retrieval (US-BKND-AI-015)
- cost_tracker.py: Token counting and budget enforcement (US-BKND-AI-036)

TODO(AUTH): When real auth is implemented, some services here will move to
app/services/auth/ with proper JWT/OAuth integration.
"""
