# US-BKND-AI-030: Course Assembly into Existing Editor State

**Status:** ✅ COMPLETE
**Priority:** MUST
**Sprint:** 7
**Implemented:** 2026-06-15

## Summary

CourseAssembler service that bridges AI-generated proposal data and the existing manual course editor. Transforms proposals into PageRecord/ComponentRecord rows in the same tables used by manual authoring, ensuring AI-generated content is indistinguishable from manually-authored content in the editor.

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `app/services/ai/course_assembler.py` | NEW | CourseAssembler with assemble_create/update/delete/batch, validation, component type mapping, editor state retrieval |
| `tests/run_course_assembler_tests.py` | NEW | 29 tests covering validation, component mapping, error handling, editor state shape |

## Assembly Methods

| Method | What It Does |
|---|---|
| `assemble_create_page()` | Creates PageRecord + ComponentRecord[] with order management |
| `assemble_update_page()` | Updates title/layout, optionally replaces components |
| `assemble_delete_page()` | Deletes page and cascading components |
| `assemble_batch()` | Creates multiple pages, optional clear-existing |
| `get_editor_state()` | Returns editor-compatible course state (same shape as GET /courses/{id}) |

## Key Design Decisions

1. **Same-table writes** — AI proposals write to the same `pages` and `components` tables as manual authoring. No dual-write or separate AI storage.
2. **Component type registry** — 5 canonical types: text-content, tabs, accordion, click-reveal, final-assessment. Unknown types rejected at assembly time.
3. **Template-to-component mapping** — `TEMPLATE_TO_COMPONENT` dict maps template types to component types for assembly.
4. **Editor state compatibility** — `get_editor_state()` returns the exact same shape as `GET /api/v1/courses/{courseId}`.
5. **Title truncation** — Titles truncated to 200 chars to match PageRecord constraints.

## See Also

- [US-AI-030 Full Spec](../US-AI-030_COURSE_ASSEMBLY_INTO_EDITOR.md) — Complete specification
- [US-BKND-AI-019](US-BKND-AI-019_enriched.md) — Course Generation (uses CourseAssembler)
