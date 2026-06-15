"""Standalone test runner for US-BKND-AI-013 — Delete Page Proposal System.

Tests DependencyAnalyzer, propose_delete_page flow, confirm_delete_page flow,
page hash computation, and integration with ConfirmationTokenService.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.dependency_analyzer import DependencyAnalyzer
from app.services.ai.proposal_service import AIProposalService
from app.services.ai.confirmation_token_service import ConfirmationTokenService

passed = 0
failed = 0
failures = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        failures.append((name, detail))
        print(f"  FAIL: {name} -- {detail}")


async def main():
    global passed, failed

    # ═══════════════════════════════════════════════════════════════
    # DependencyAnalyzer Tests
    # ═══════════════════════════════════════════════════════════════
    print("=== DependencyAnalyzer Tests ===")

    # 1. Final assessment check
    analyzer = DependencyAnalyzer(AsyncMock())

    mock_page = MagicMock()
    mock_page.page_id = "page_1"
    mock_page.title = "Test Page"
    mock_page.order_index = 2

    mock_comp = MagicMock()
    mock_comp.component_type = "final-assessment"
    mock_comp.component_id = "comp_1"
    mock_page.components = [mock_comp]

    result = analyzer.check_final_assessment(mock_page)
    check("detects final assessment", len(result) == 1)
    check("correct category", result[0]["category"] == "final_assessment")
    check("correct severity", result[0]["severity"] == "warning")
    check("includes component_id", "comp_1" in result[0]["affected_ids"])

    # 2. No final assessment
    mock_comp2 = MagicMock()
    mock_comp2.component_type = "text-content"
    mock_comp2.component_id = "comp_2"
    mock_page2 = MagicMock()
    mock_page2.components = [mock_comp2]
    mock_page2.page_id = "page_2"

    result2 = analyzer.check_final_assessment(mock_page2)
    check("no false positive for text-content", len(result2) == 0)

    # 3. Empty components
    mock_page3 = MagicMock()
    mock_page3.components = []
    result3 = analyzer.check_final_assessment(mock_page3)
    check("handles empty components", len(result3) == 0)

    # ═══════════════════════════════════════════════════════════════
    # Page Hash Computation Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== Page Hash Tests ===")

    mock_db = AsyncMock()
    svc = AIProposalService(mock_db)

    # 4. Deterministic hash
    page = MagicMock()
    page.page_id = "page_001"
    page.title = "Test Page"
    page.order_index = 3
    page.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    page.components = []

    h1 = await svc._compute_page_hash(page)
    h2 = await svc._compute_page_hash(page)
    check("deterministic hash for same state", h1 == h2)
    check("hash is 64 char hex", len(h1) == 64)

    # 5. Different order produces different hash
    page2 = MagicMock()
    page2.page_id = "page_001"
    page2.title = "Test Page"
    page2.order_index = 4  # different order
    page2.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    page2.components = []

    h3 = await svc._compute_page_hash(page2)
    check("different order changes hash", h1 != h3)

    # 6. Different title produces different hash
    page3 = MagicMock()
    page3.page_id = "page_001"
    page3.title = "Different Title"
    page3.order_index = 3
    page3.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    page3.components = []

    h4 = await svc._compute_page_hash(page3)
    check("different title changes hash", h1 != h4)

    # 7. Components included in hash
    comp = MagicMock()
    comp.component_id = "comp_1"
    comp.component_type = "text-content"
    comp.order_index = 0
    comp.updated_at = datetime(2026, 6, 15, 10, 0, 0)

    page_with_comp = MagicMock()
    page_with_comp.page_id = "page_001"
    page_with_comp.title = "Test Page"
    page_with_comp.order_index = 3
    page_with_comp.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    page_with_comp.components = [comp]

    h5 = await svc._compute_page_hash(page_with_comp)
    check("components affect hash", h1 != h5)

    # 8. Hash with multiple components
    comp2 = MagicMock()
    comp2.component_id = "comp_2"
    comp2.component_type = "final-assessment"
    comp2.order_index = 1
    comp2.updated_at = datetime(2026, 6, 15, 10, 0, 0)

    page_multi = MagicMock()
    page_multi.page_id = "page_001"
    page_multi.title = "Test Page"
    page_multi.order_index = 3
    page_multi.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    page_multi.components = [comp, comp2]

    h6 = await svc._compute_page_hash(page_multi)
    check("multi-component hash differs from single", h5 != h6)

    # ═══════════════════════════════════════════════════════════════
    # Service Interface Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== Service Interface Tests ===")

    # 9. Methods exist with correct signatures
    check("has propose_delete_page", hasattr(svc, "propose_delete_page"))
    check("has confirm_delete_page", hasattr(svc, "confirm_delete_page"))
    check("has _compute_page_hash", hasattr(svc, "_compute_page_hash"))

    # 10. Method signatures
    import inspect
    propose_sig = inspect.signature(svc.propose_delete_page)
    propose_params = list(propose_sig.parameters.keys())
    for p in ["session_id", "user_id", "organization_id", "course_id", "page_id"]:
        check(f"propose_delete_page has {p} param", p in propose_params)

    confirm_sig = inspect.signature(svc.confirm_delete_page)
    confirm_params = list(confirm_sig.parameters.keys())
    for p in ["session_id", "proposal_id", "user_id", "course_id",
              "user_approved_delete", "confirmation_token"]:
        check(f"confirm_delete_page has {p} param", p in confirm_params)

    # ═══════════════════════════════════════════════════════════════
    # Router Schema Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== Router Schema Tests ===")

    from app.routers.ai_proposals import ProposeDeletePageRequest, ConfirmDeletePageRequest

    # 11. ProposeDeletePageRequest validation
    try:
        r = ProposeDeletePageRequest(session_id="s1", page_id="p1")
        check("ProposeDeletePageRequest valid", r.session_id == "s1")
    except Exception as e:
        check("ProposeDeletePageRequest valid", False, str(e))

    # 12. ProposeDeletePageRequest missing fields
    try:
        ProposeDeletePageRequest(session_id="s1")
        check("ProposeDeletePageRequest missing page_id rejected", False, "should reject")
    except Exception:
        check("ProposeDeletePageRequest missing page_id rejected", True)

    # 13. ConfirmDeletePageRequest validation
    try:
        r = ConfirmDeletePageRequest(
            session_id="s1", proposal_id="p1",
            user_approved_delete=True, confirmation_token="a" * 64,
        )
        check("ConfirmDeletePageRequest valid", r.user_approved_delete is True)
    except Exception as e:
        check("ConfirmDeletePageRequest valid", False, str(e))

    # 14. ConfirmDeletePageRequest with user_approved_delete=False
    try:
        r = ConfirmDeletePageRequest(
            session_id="s1", proposal_id="p1",
            user_approved_delete=False, confirmation_token="a" * 64,
        )
        check("ConfirmDeletePageRequest with false approval accepted at schema level",
              r.user_approved_delete is False)
    except Exception as e:
        check("ConfirmDeletePageRequest with false approval", False, str(e))

    # ═══════════════════════════════════════════════════════════════
    # Error Handling Tests
    # ═══════════════════════════════════════════════════════════════
    print("\n=== Error Handling Tests ===")

    from app.services.ai.proposal_service import (
        ProposalError, ProposalNotFoundError,
        ProposalStaleError, ProposalConflictError,
    )

    # 15. USER_CONFIRMATION_REQUIRED error
    e = ProposalError(
        "USER_CONFIRMATION_REQUIRED",
        "You must set user_approved_delete=true to confirm destructive deletion.",
        400,
    )
    check("USER_CONFIRMATION_REQUIRED code", e.code == "USER_CONFIRMATION_REQUIRED")
    check("USER_CONFIRMATION_REQUIRED status", e.http_status == 400)

    # 16. INVALID_CONFIRMATION_TOKEN error
    e = ProposalError(
        "INVALID_CONFIRMATION_TOKEN",
        "Confirmation token is invalid.",
        403,
    )
    check("INVALID_CONFIRMATION_TOKEN code", e.code == "INVALID_CONFIRMATION_TOKEN")
    check("INVALID_CONFIRMATION_TOKEN status", e.http_status == 403)

    # 17. ProposalNotFoundError
    e = ProposalNotFoundError("pid_123")
    check("ProposalNotFoundError code", e.code == "PROPOSAL_NOT_FOUND")
    check("ProposalNotFoundError status", e.http_status == 404)

    # 18. ProposalConflictError for page changed
    e = ProposalConflictError("Page has been modified since proposal.")
    check("ProposalConflictError code", e.code == "CONFLICT_DETECTED")
    check("ProposalConflictError status", e.http_status == 409)

    # 19. ProposalStaleError for expired
    e = ProposalStaleError("Delete proposal has expired.")
    check("ProposalStaleError code", e.code == "PROPOSAL_STALE")
    check("ProposalStaleError status", e.http_status == 410)

    # ═══════════════════════════════════════════════════════════════
    # Integration: ConfirmationTokenService + Proposal Flow
    # ═══════════════════════════════════════════════════════════════
    print("\n=== Integration Tests ===")

    # 20. Token generated for delete_page is valid
    token_svc = ConfirmationTokenService()
    result = await token_svc.generate_token(
        session_id="sess_001", proposal_id="prop_del_001",
        target_resource_type="page", target_resource_id="page_xyz",
        operation_type="delete_page", resource_hash="hash_abc",
    )
    check("delete token has 64 chars", len(result["token"]) == 64)
    check("delete token has expiry", result["expires_at"] > datetime.now(timezone.utc))

    # 21. Token validation verifies scope binding
    mock_proposal = MagicMock()
    mock_proposal.proposal_id = "prop_del_001"
    mock_proposal.session_id = "sess_001"
    mock_proposal.target_id = "page_xyz"
    mock_proposal.target_type = "page"
    mock_proposal.action_type = "delete_page"
    mock_proposal.status = "PENDING_CONFIRMATION"
    mock_proposal.confirmation_token_sha256 = result["token_hash"]
    mock_proposal.confirmation_token_expires_at = result["expires_at"]
    mock_proposal.base_hash = "hash_abc"

    is_valid, err = await token_svc.validate_token(
        proposal=mock_proposal,
        received_token=result["token"],
        user_approved=True,
    )
    check("delete token validates against proposal", is_valid and err is None)

    # 22. Expired token rejected
    mock_proposal_exp = MagicMock()
    mock_proposal_exp.proposal_id = "prop_del_001"
    mock_proposal_exp.session_id = "sess_001"
    mock_proposal_exp.target_id = "page_xyz"
    mock_proposal_exp.target_type = "page"
    mock_proposal_exp.action_type = "delete_page"
    mock_proposal_exp.status = "PENDING_CONFIRMATION"
    mock_proposal_exp.confirmation_token_sha256 = result["token_hash"]
    mock_proposal_exp.confirmation_token_expires_at = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    mock_proposal_exp.base_hash = "hash_abc"

    is_valid, err = await token_svc.validate_token(
        proposal=mock_proposal_exp,
        received_token=result["token"],
        user_approved=True,
    )
    check("expired delete token rejected", not is_valid and "CONFIRMATION_EXPIRED" in err)

    # 23. Hash verification for delete
    hash_match, hash_err = await token_svc.verify_resource_hash(
        proposal=mock_proposal,
        current_resource_hash="hash_abc",
    )
    check("resource hash matches", hash_match and hash_err is None)

    hash_match, hash_err = await token_svc.verify_resource_hash(
        proposal=mock_proposal,
        current_resource_hash="hash_changed",
    )
    check("resource hash mismatch detected", not hash_match and "RESOURCE_CHANGED" in hash_err)

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if failures:
        print("FAILURES:")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
