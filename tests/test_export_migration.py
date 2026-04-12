from app.services.export_migration import ExportMigrationService


def test_migrate_templates_payload_to_pages_components():
    service = ExportMigrationService()
    legacy = {
        "courseId": "legacy-1",
        "title": "Legacy",
        "templates": [
            {
                "id": "t1",
                "type": "content-text",
                "order": 0,
                "title": "Slide 1",
                "data": {"content": "Hello"},
            }
        ],
    }

    migrated, report = service.migrate_course_payload(legacy)

    assert report.migrated is True
    assert migrated["exportVersion"] == "1.0"
    assert "pages" in migrated
    assert len(migrated["pages"]) == 1
    assert migrated["pages"][0]["components"][0]["componentType"] == "content-text"


def test_migration_backfills_export_keys():
    service = ExportMigrationService()
    payload = {"courseId": "c1", "pages": []}

    migrated, _ = service.migrate_course_payload(payload)

    assert "themeTokens" in migrated
    assert "customCss" in migrated
    assert "assets" in migrated
    assert "supportedComponentTypes" in migrated


def test_assess_migration_risk_detects_legacy_and_custom_css():
    service = ExportMigrationService()
    payload = {
        "courseId": "risk-1",
        "templates": [{"id": str(i)} for i in range(45)],
        "customCss": ".x { color: red; }",
    }

    risk = service.assess_migration_risk(payload)

    assert risk["riskLevel"] in {"medium", "high"}
    assert risk["hasLegacyTemplates"] is True
    assert risk["componentCount"] == 45
