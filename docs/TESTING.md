# Testing

## Run Tests

- Full suite:
  - `pytest`
- Specific test file:
  - `pytest tests/test_dynamic_scorm_export.py`
- With coverage:
  - `pytest --cov=app tests/`

## Notes

- Prefer focused test runs during iteration.
- Keep regression checks on validation and SCORM export paths.
