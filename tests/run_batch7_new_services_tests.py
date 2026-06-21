"""Standalone tests for Batch 7 new services — PEND-024 through PEND-031.

Run: PYTHONPATH=. python tests/run_batch7_new_services_tests.py

Validates:
    PEND-024: KafkaEventPublisher
    PEND-025: FeedbackCollector + AIFeedbackRecord
    PEND-026: CacheService
    PEND-027: TemplateHarvester
    PEND-028: PromptRegistry + AIPromptVersion
    PEND-029: AIContentVersion + AIContentVersionRepository
    PEND-030: ConnectionManager, PresenceManager, ws_collaboration
    PEND-031: PatternClusterer
"""
from __future__ import annotations
import asyncio
import inspect
import uuid

passed = 0
failed = 0
failures: list[tuple[str, str]] = []

def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        failures.append((name, detail))

# ═══════════════════════════════════════════════════════════════════
# PEND-024: Kafka Publisher
# ═══════════════════════════════════════════════════════════════════

def test_pend024_publisher_class():
    """PEND024-01: KafkaEventPublisher class importable."""
    from app.events.kafka_publisher import KafkaEventPublisher
    check("PEND024-01: Class exists", KafkaEventPublisher is not None)

def test_pend024_has_methods():
    """PEND024-02: Has start, stop, publish, is_available."""
    from app.events.kafka_publisher import KafkaEventPublisher
    p = KafkaEventPublisher()
    for m in ["start", "stop", "publish", "is_available"]:
        check(f"PEND024-02: Has {m}", hasattr(p, m))

def test_pend024_topics_defined():
    """PEND024-03: 5 topics defined (proposals, sessions, chat, workflows, dead_letter)."""
    from app.events.kafka_publisher import TOPICS
    check("PEND024-03: 5 topics", len(TOPICS) == 5)
    for t in ["proposals", "sessions", "chat", "workflows", "dead_letter"]:
        check(f"PEND024-03: {t} topic", t in TOPICS)

def test_pend024_disabled_by_env():
    """PEND024-04: Disables when KAFKA_ENABLED=false."""
    import os
    old = os.getenv("KAFKA_ENABLED")
    os.environ["KAFKA_ENABLED"] = "false"
    try:
        from importlib import reload
        from app.events import kafka_publisher
        reload(kafka_publisher)
        p = kafka_publisher.KafkaEventPublisher()
        check("PEND024-04: Disabled when false", p._enabled == False)
    finally:
        if old:
            os.environ["KAFKA_ENABLED"] = old
        else:
            os.environ.pop("KAFKA_ENABLED", None)

# ═══════════════════════════════════════════════════════════════════
# PEND-025: RLHF Feedback Collector
# ═══════════════════════════════════════════════════════════════════

def test_pend025_model_exists():
    """PEND025-01: AIFeedbackRecord model importable."""
    from app.models.ai_feedback import AIFeedbackRecord
    check("PEND025-01: Model exists", AIFeedbackRecord is not None)

def test_pend025_model_fields():
    """PEND025-02: AIFeedbackRecord has required fields."""
    from app.models.ai_feedback import AIFeedbackRecord
    fields = [c.name for c in AIFeedbackRecord.__table__.columns]
    for f in ["proposal_id", "user_id", "action", "generated_content", "applied_content",
              "edit_distance", "edit_ratio", "prompt_version", "model_id"]:
        check(f"PEND025-02: Has {f}", f in fields)

def test_pend025_collector_class():
    """PEND025-03: FeedbackCollector class exists with record + get_acceptance_rate."""
    from app.services.ai.feedback_collector import FeedbackCollector
    check("PEND025-03: Class exists", FeedbackCollector is not None)
    check("PEND025-03: Has record", hasattr(FeedbackCollector, 'record'))
    check("PEND025-03: Has get_acceptance_rate", hasattr(FeedbackCollector, 'get_acceptance_rate'))

def test_pend025_edit_distance():
    """PEND025-04: Levenshtein distance computation works."""
    from app.services.ai.feedback_collector import FeedbackCollector
    d, r = FeedbackCollector._compute_edit_distance("hello", "hallo")
    check("PEND025-04: hello→hallo distance=1", d == 1)
    d2, r2 = FeedbackCollector._compute_edit_distance("abc", "abc")
    check("PEND025-04: abc→abc distance=0", d2 == 0)
    d3, r3 = FeedbackCollector._compute_edit_distance("", "test")
    check("PEND025-04: empty→test distance=4", d3 == 4)

# ═══════════════════════════════════════════════════════════════════
# PEND-026: Cache Service
# ═══════════════════════════════════════════════════════════════════

def test_pend026_cache_service_class():
    """PEND026-01: CacheService class importable."""
    from app.services.cache_service import CacheService
    check("PEND026-01: Class exists", CacheService is not None)

def test_pend026_has_methods():
    """PEND026-02: Has get, set, invalidate, invalidate_pattern, start, stop."""
    from app.services.cache_service import CacheService
    c = CacheService()
    for m in ["get", "set", "invalidate", "invalidate_pattern", "start", "stop", "is_available"]:
        check(f"PEND026-02: Has {m}", hasattr(c, m))

def test_pend026_uses_scan_not_keys():
    """PEND026-03: invalidate_pattern uses scan_iter, not keys()."""
    from app.services.cache_service import CacheService
    source = inspect.getsource(CacheService.invalidate_pattern)
    check("PEND026-03: Uses scan_iter", "scan_iter" in source)
    check("PEND026-03: No .keys(", ".keys(" not in source)

def test_pend026_ttl_constants():
    """PEND026-04: TTL constants defined."""
    from app.services.cache_service import TTL_PAGE_LIST, TTL_PAGE_FETCH, TTL_COURSE_STRUCTURE
    check("PEND026-04: TTL_PAGE_LIST=30", TTL_PAGE_LIST == 30)
    check("PEND026-04: TTL_PAGE_FETCH=60", TTL_PAGE_FETCH == 60)
    check("PEND026-04: TTL_COURSE_STRUCTURE=120", TTL_COURSE_STRUCTURE == 120)

# ═══════════════════════════════════════════════════════════════════
# PEND-027: Template Harvester
# ═══════════════════════════════════════════════════════════════════

def test_pend027_harvester_class():
    """PEND027-01: TemplateHarvester class importable."""
    from app.services.ai.template_harvester import TemplateHarvester
    check("PEND027-01: Class exists", TemplateHarvester is not None)

def test_pend027_has_analyze():
    """PEND027-02: Has analyze method."""
    from app.services.ai.template_harvester import TemplateHarvester
    h = TemplateHarvester()
    check("PEND027-02: Has analyze", hasattr(h, 'analyze'))
    check("PEND027-02: Has _extract_signature", hasattr(h, '_extract_signature'))
    check("PEND027-02: Has _check_novelty", hasattr(h, '_check_novelty'))

def test_pend027_known_component_types():
    """PEND027-03: KNOWN_COMPONENT_TYPES includes actual AI types."""
    from app.services.ai.template_harvester import KNOWN_COMPONENT_TYPES
    for t in ["text-content", "accordion", "quiz", "video-embed", "image-gallery"]:
        check(f"PEND027-03: {t} in known types", t in KNOWN_COMPONENT_TYPES)

def test_pend027_signature_extraction():
    """PEND027-04: _extract_signature uses 'components' field (verified against course_assembler.py:87)."""
    from app.services.ai.template_harvester import TemplateHarvester
    h = TemplateHarvester()
    sig = h._extract_signature({
        "components": [
            {"component_type": "text-content", "data": {"content": "Test"}},
            {"component_type": "quiz", "data": {"questions": 3}},
        ]
    })
    check("PEND027-04: component_count=2", sig["component_count"] == 2)
    check("PEND027-04: Has text-content", "text-content" in sig["component_types"])
    check("PEND027-04: Has quiz", "quiz" in sig["component_types"])
    check("PEND027-04: has_unknown_types=False", sig["has_unknown_types"] == False)

def test_pend027_novelty_with_empty():
    """PEND027-05: Novelty check with empty existing returns True."""
    from app.services.ai.template_harvester import TemplateHarvester
    h = TemplateHarvester()
    sig = {"text_signature": "text-content quiz"}
    is_novel, max_sim = h._check_novelty(sig, [])
    check("PEND027-05: Novel with empty existing", is_novel == True)
    check("PEND027-05: Similarity 0.0", max_sim == 0.0)

# ═══════════════════════════════════════════════════════════════════
# PEND-028: Prompt Registry
# ═══════════════════════════════════════════════════════════════════

def test_pend028_model_exists():
    """PEND028-01: AIPromptVersion model importable."""
    from app.models.ai_prompt_version import AIPromptVersion
    check("PEND028-01: Model exists", AIPromptVersion is not None)

def test_pend028_registry_class():
    """PEND028-02: PromptRegistry class exists."""
    from app.services.ai.prompt_registry import PromptRegistry
    check("PEND028-02: Class exists", PromptRegistry is not None)

def test_pend028_uses_sha256():
    """PEND028-03: Uses SHA-256 (not MD5) for user bucket hashing."""
    from app.services.ai.prompt_registry import PromptRegistry
    source = inspect.getsource(PromptRegistry._get_user_bucket)
    check("PEND028-03: Uses sha256", "sha256" in source)
    check("PEND028-03: No md5", "md5" not in source)

def test_pend028_deterministic_bucket():
    """PEND028-04: Same user+prompt = same bucket every time."""
    from app.services.ai.prompt_registry import PromptRegistry
    b1 = PromptRegistry._get_user_bucket("user-123", "chat")
    b2 = PromptRegistry._get_user_bucket("user-123", "chat")
    check("PEND028-04: Deterministic", b1 == b2)
    check("PEND028-04: In range 0-100", 0 <= b1 < 100)

# ═══════════════════════════════════════════════════════════════════
# PEND-029: Content Versioning
# ═══════════════════════════════════════════════════════════════════

def test_pend029_model_exists():
    """PEND029-01: AIContentVersion model importable."""
    from app.models.ai_content_version import AIContentVersion
    check("PEND029-01: Model exists", AIContentVersion is not None)

def test_pend029_model_fields():
    """PEND029-02: Has required fields including version_id, resource_type, content_snapshot, content_diff."""
    from app.models.ai_content_version import AIContentVersion
    fields = [c.name for c in AIContentVersion.__table__.columns]
    for f in ["version_id", "resource_type", "resource_id", "course_id", "version_number",
              "content_snapshot", "content_diff", "proposal_id"]:
        check(f"PEND029-02: Has {f}", f in fields)

def test_pend029_repo_class():
    """PEND029-03: AIContentVersionRepository exists with CRUD methods."""
    from app.repositories.ai_content_version_repo import AIContentVersionRepository
    check("PEND029-03: Class exists", AIContentVersionRepository is not None)
    check("PEND029-03: Has create_version", hasattr(AIContentVersionRepository, 'create_version'))
    check("PEND029-03: Has get_latest", hasattr(AIContentVersionRepository, 'get_latest'))
    check("PEND029-03: Has list_versions", hasattr(AIContentVersionRepository, 'list_versions'))
    check("PEND029-03: Has rollback_to", hasattr(AIContentVersionRepository, 'rollback_to'))

def test_pend029_size_guard():
    """PEND029-04: MAX_DIFF_SIZE constant defined (100KB)."""
    from app.repositories.ai_content_version_repo import MAX_DIFF_SIZE, MAX_VERSIONS_PER_RESOURCE
    check("PEND029-04: MAX_DIFF_SIZE=100000", MAX_DIFF_SIZE == 100_000)
    check("PEND029-04: MAX_VERSIONS_PER_RESOURCE=50", MAX_VERSIONS_PER_RESOURCE == 50)

# ═══════════════════════════════════════════════════════════════════
# PEND-030: WebSocket Collaboration
# ═══════════════════════════════════════════════════════════════════

def test_pend030_router_exists():
    """PEND030-01: ws_collaboration router importable."""
    from app.routers.ws_collaboration import router
    check("PEND030-01: Router exists", router is not None)

def test_pend030_connection_manager():
    """PEND030-02: ConnectionManager has connect/disconnect/broadcast."""
    from app.routers.ws_collaboration import ConnectionManager
    m = ConnectionManager()
    check("PEND030-02: Has connect", hasattr(m, 'connect'))
    check("PEND030-02: Has disconnect", hasattr(m, 'disconnect'))
    check("PEND030-02: Has broadcast", hasattr(m, 'broadcast'))

def test_pend030_presence_manager():
    """PEND030-03: PresenceManager has user_joined/user_left/get_present_users."""
    from app.services.collaboration.presence_manager import PresenceManager
    check("PEND030-03: Class exists", PresenceManager is not None)
    p = PresenceManager()
    for m in ["user_joined", "user_left", "get_present_users", "broadcast_page_locked",
              "broadcast_page_unlocked", "broadcast_content_changed"]:
        check(f"PEND030-03: Has {m}", hasattr(p, m))

def test_pend030_auth_function():
    """PEND030-04: get_current_user_ws function exists."""
    from app.dependencies.auth_dependencies import get_current_user_ws
    check("PEND030-04: get_current_user_ws exists", get_current_user_ws is not None)

# ═══════════════════════════════════════════════════════════════════
# PEND-031: Pattern Clusterer
# ═══════════════════════════════════════════════════════════════════

def test_pend031_clusterer_class():
    """PEND031-01: PatternClusterer class importable."""
    from app.services.ai.pattern_clusterer import PatternClusterer
    check("PEND031-01: Class exists", PatternClusterer is not None)

def test_pend031_cluster_method():
    """PEND031-02: Has cluster method with min_courses param."""
    from app.services.ai.pattern_clusterer import PatternClusterer
    p = PatternClusterer()
    sig = inspect.signature(p.cluster)
    params = list(sig.parameters.keys())
    check("PEND031-02: Has min_courses param", "min_courses" in params)

def test_pend031_empty_cluster():
    """PEND031-03: cluster() with <3 courses returns empty."""
    from app.services.ai.pattern_clusterer import PatternClusterer
    p = PatternClusterer()
    result = p.cluster([], min_courses=3)
    check("PEND031-03: Empty input = empty output", result == [])

def test_pend031_auto_promote_threshold():
    """PEND031-04: auto_promote=True requires 5+ courses."""
    from app.services.ai.pattern_clusterer import PatternClusterer
    # Verify the threshold is hardcoded at 5
    source = inspect.getsource(PatternClusterer.cluster)
    check("PEND031-04: auto_promote >= 5", "unique_courses >= 5" in source)

# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    test_pend024_publisher_class()
    test_pend024_has_methods()
    test_pend024_topics_defined()
    test_pend024_disabled_by_env()
    test_pend025_model_exists()
    test_pend025_model_fields()
    test_pend025_collector_class()
    test_pend025_edit_distance()
    test_pend026_cache_service_class()
    test_pend026_has_methods()
    test_pend026_uses_scan_not_keys()
    test_pend026_ttl_constants()
    test_pend027_harvester_class()
    test_pend027_has_analyze()
    test_pend027_known_component_types()
    test_pend027_signature_extraction()
    test_pend027_novelty_with_empty()
    test_pend028_model_exists()
    test_pend028_registry_class()
    test_pend028_uses_sha256()
    test_pend028_deterministic_bucket()
    test_pend029_model_exists()
    test_pend029_model_fields()
    test_pend029_repo_class()
    test_pend029_size_guard()
    test_pend030_router_exists()
    test_pend030_connection_manager()
    test_pend030_presence_manager()
    test_pend030_auth_function()
    test_pend031_clusterer_class()
    test_pend031_cluster_method()
    test_pend031_empty_cluster()
    test_pend031_auto_promote_threshold()
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    if failures:
        for name, detail in failures:
            print(f"  FAIL: {name}")
            if detail:
                print(f"        {detail}")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
