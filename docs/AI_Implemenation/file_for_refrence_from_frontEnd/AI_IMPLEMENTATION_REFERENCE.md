# AI Implementation Reference

Date: 2026-05-22
Branch: demo-course-AI

## 1. Goal for Current Demo

Show clear AI capability in the existing e-learning product without changing core manual workflows.

The AI flow should:
- Accept storyboard/content/instructions from user
- Decide which allowed templates to use
- Fill template data
- Build course directly in UI
- Allow user preview and export
- Allow follow-up chat instructions to refine course

## 2. Templates in Scope for Demo

Only these tested templates are in scope:
- Text Content
- Tabs
- Accordion
- Click & Reveal
- Final Assessment

## 3. Product Requirement Confirmed

Both ways of working must remain available:
- Manual course creation (existing behavior)
- AI-assisted course creation (new chatbot flow)

No replacement of manual workflow.

## 4. Architecture Direction (Confirmed)

Use a separated AI module architecture, but integrate with existing codebase/state and existing rendering/export paths.

### 4.1 Separation Principle

Keep AI logic separate from template rendering components:
- AI orchestration
- template planner
- schema validator
- course assembler

Templates remain mostly unchanged and consume normal data.

### 4.2 Core Layers

1) Dual Entry UI Layer
- Create Course (manual)
- Build with AI (chat)

2) AI Orchestration Layer
- Prompt builder
- Template planner (allowed templates only)
- Content generator
- Validation and correction pass

3) Template Capability Registry
- Per-template metadata and schema
- Extendable for future templates

4) Course Assembly Engine
- Converts AI plan into existing internal course/page/component structure

5) Review and Refinement Loop
- User edits manually in UI
- User sends follow-up AI instructions for targeted updates

6) Export Compatibility
- Keep existing export pipeline unchanged

## 5. Model Strategy Decisions

### 5.1 Preferred Quality Model
- Primary for quality-critical output: GPT-4.1

### 5.2 Speed/Cost Fallback
- Fallback for lighter prompts: GPT-4.1-mini

### 5.3 Single-Model Demo Choice
- If using one model only for demo: GPT-4.1

## 6. Future-Proof Model Selection Requirement

Model must be configurable so it can be changed later without refactor.

Recommended implementation:
- Frontend holds selected model in chat state
- Send model in each AI request
- Backend validates model against allowlist
- Backend auto-fallback to GPT-4.1 on failure

## 7. Suggested Model Config Shape

- id
- label
- capabilities (json mode, long context, tool calling)
- status (active, hidden, deprecated)
- costTier (high, medium, low)

## 8. Demo Guardrails

- Strict template whitelist (5 templates only)
- Strict JSON/schema validation before applying to UI
- Retry once with fix prompt if schema fails
- Keep generated changes reviewable by user before publish/export

## 9. Immediate Demo Narrative

Suggested story for stakeholders:
1) User provides storyboard
2) AI creates course draft using approved templates
3) User previews and tweaks in normal editor
4) User asks chatbot for refinements
5) Course exports through existing pipeline

## 10. Non-Goals for This Demo

- Full autonomous agent editing all product areas
- Unlimited template support at first release
- Replacing existing manual authoring mode

## 11. Next Implementation Document (Optional)

If needed next, create a technical spec with:
- API contracts for ai/models and ai/chat
- request/response examples
- validation schemas per template
- patch/update instruction format for follow-up chat edits
- rollout checklist and test cases
