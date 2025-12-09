import pytest
from unittest.mock import AsyncMock

from app.services.import_service import ImportService
from app.repositories.template_type_repo import TemplateTypeConflictError


class _FakeTemplateTypeRepo:
    def __init__(self):
        self.created = {}

    async def create(
        self,
        template_id: str,
        name: str,
        description: str,
        category: str,
        thumbnail=None,
        estimated_duration=None,
        rating: float = 0.0,
        usage_count: int = 0,
        can_be_page: bool = True,
        fields=None,
        is_active: bool = True,
    ):
        if template_id in self.created:
            raise TemplateTypeConflictError("dup")
        self.created[template_id] = {
            "template_id": template_id,
            "name": name,
            "description": description,
            "category": category,
            "fields": fields,
            "is_active": is_active,
            "usage_count": usage_count,
            "rating": rating,
            "can_be_page": can_be_page,
        }
        return self.created[template_id]


@pytest.mark.asyncio
async def test_harvest_deduplicates_on_schema_signature():
    repo = _FakeTemplateTypeRepo()
    service = ImportService(db_session=AsyncMock(), template_type_repo=repo)

    templates = [
        {"schema_signature": "sig1", "title": "A", "schema": {"fields": []}},
        {"schema_signature": "sig1", "title": "B", "schema": {"fields": []}},
    ]

    result = await service._harvest_templates(
        templates, source_job_id="job1", max_items=10
    )

    assert result["harvested"] == 1
    assert result["duplicates"] == 1
    assert repo.created["imported_sig1"]["category"] == "Imported"


@pytest.mark.asyncio
async def test_harvest_skips_errors_and_missing_signatures_with_cap():
    repo = _FakeTemplateTypeRepo()
    service = ImportService(db_session=AsyncMock(), template_type_repo=repo)

    templates = [
        {"schema_signature": "sig1", "title": "A", "schema": {}},
        {"error": "bad"},
        {"schema": {}},
    ]

    result = await service._harvest_templates(
        templates, source_job_id="job2", max_items=1
    )

    assert result["harvested"] == 1
    assert result["duplicates"] == 0
    assert result["skipped_errors"] == 1
    assert result["skipped_missing_signature"] == 1
    assert result["capped"] == 0
