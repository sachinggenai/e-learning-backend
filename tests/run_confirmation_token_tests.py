"""Standalone test runner for ConfirmationTokenService.
Runs all US-BKND-AI-049 tests without pytest (avoiding segfault).
"""
import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.ai.confirmation_token_service import (
    ConfirmationTokenService,
    ConfirmationTokenError,
    TokenExpiredError,
    TokenMismatchError,
    ResourceChangedError,
    ProposalNotInConfirmableStateError,
    ResourceNotFoundError,
    DESTRUCTIVE_OPERATIONS,
)

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


def _make_proposal(**overrides):
    props = {
        "proposal_id": "prop_001",
        "session_id": "sess_001",
        "course_id": "course_001",
        "target_id": "page_001",
        "target_type": "page",
        "action_type": "delete_page",
        "status": "PENDING_CONFIRMATION",
        "confirmation_token_sha256": None,
        "confirmation_token_expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "confirmation_ttl_override_minutes": None,
        "base_hash": "abc123def456",
        "before_snapshot": None,
    }
    props.update(overrides)
    record = MagicMock()
    for k, v in props.items():
        setattr(record, k, v)
    return record


async def main():
    global passed, failed
    service = ConfirmationTokenService()

    print("=== Token Generation Tests ===")
    # 1
    result = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
    )
    check("token is 64 hex chars", len(result["token"]) == 64)
    check("token_hash is 64 hex chars", len(result["token_hash"]) == 64)
    check("expires_at is in the future", result["expires_at"] > datetime.now(timezone.utc))

    # 2 Randomness
    r1 = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
    )
    r2 = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
    )
    check("tokens are unique", r1["token"] != r2["token"])
    check("hashes are unique", r1["token_hash"] != r2["token_hash"])

    # 3 Default TTL
    before = datetime.now(timezone.utc)
    result = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
    )
    after = datetime.now(timezone.utc)
    check(
        "default TTL ~15 minutes",
        before + timedelta(minutes=15) - timedelta(seconds=2) <= result["expires_at"]
        <= after + timedelta(minutes=15) + timedelta(seconds=2),
    )

    # 4 Custom TTL
    result = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
        ttl_minutes=5,
    )
    expected = datetime.now(timezone.utc) + timedelta(minutes=5)
    check("custom TTL of 5 min", abs((result["expires_at"] - expected).total_seconds()) < 3)

    # 5 Scope binding
    result = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
    )
    scope = service._build_scope_string(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page",
    )
    expected_hash = hmac.new(
        result["token"].encode(), scope.encode(), hashlib.sha256
    ).hexdigest()
    check("scope-bound hash matches", result["token_hash"] == expected_hash)

    # 6 Required fields
    try:
        await service.generate_token(
            session_id="", proposal_id="p1", target_resource_type="page",
            target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
        )
        check("empty session_id raises ValueError", False, "did not raise")
    except ValueError as e:
        check("empty session_id raises ValueError", "session_id" in str(e))

    # 7 Hex format
    result = await service.generate_token(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete_page", resource_hash="h1",
    )
    try:
        int(result["token"], 16)
        check("token is valid hex", True)
    except ValueError:
        check("token is valid hex", False)

    check("token is 256 bits (32 bytes)", len(bytes.fromhex(result["token"])) == 32)

    print("\n=== Token Validation Tests ===")

    # Use consistent IDs between token generation and mock proposal
    TEST_SESS = "sess_001"
    TEST_PROP = "prop_001"
    TEST_RES = "page_001"

    # 8 Happy path
    gen = await service.generate_token(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_resource_type="page",
        target_resource_id=TEST_RES, operation_type="delete_page", resource_hash="h1",
    )
    prop = _make_proposal(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
        confirmation_token_sha256=gen["token_hash"],
        confirmation_token_expires_at=gen["expires_at"],
    )
    is_valid, err = await service.validate_token(
        proposal=prop, received_token=gen["token"], user_approved=True,
    )
    check("happy path validation passes", is_valid and err is None)

    # 9 Also accepts 'pending' status
    gen2 = await service.generate_token(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_resource_type="page",
        target_resource_id=TEST_RES, operation_type="delete_page", resource_hash="h1",
    )
    prop = _make_proposal(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
        status="pending",
        confirmation_token_sha256=gen2["token_hash"],
        confirmation_token_expires_at=gen2["expires_at"],
    )
    is_valid, _ = await service.validate_token(
        proposal=prop, received_token=gen2["token"], user_approved=True,
    )
    check("accepts 'pending' status", is_valid)

    # 10 Expired token
    gen_exp = await service.generate_token(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_resource_type="page",
        target_resource_id=TEST_RES, operation_type="delete_page", resource_hash="h1",
    )
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    prop = _make_proposal(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
        confirmation_token_sha256=gen_exp["token_hash"],
        confirmation_token_expires_at=expired,
    )
    is_valid, err = await service.validate_token(
        proposal=prop, received_token=gen_exp["token"], user_approved=True,
    )
    check("expired token rejected", not is_valid and "CONFIRMATION_EXPIRED" in err)

    # 11 Wrong token
    prop = _make_proposal(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
        confirmation_token_sha256=gen["token_hash"],
    )
    is_valid, err = await service.validate_token(
        proposal=prop, received_token="1" * 64, user_approved=True,
    )
    check("wrong token rejected", not is_valid and "INVALID_CONFIRMATION_TOKEN" in err)

    # 12 Non-confirmable status
    for bad in ["applied", "expired", "rejected"]:
        prop = _make_proposal(session_id=TEST_SESS, proposal_id=TEST_PROP, status=bad)
        is_valid, err = await service.validate_token(
            proposal=prop, received_token="a" * 64, user_approved=True,
        )
        check(
            f"status '{bad}' rejected",
            not is_valid and "PROPOSAL_NOT_CONFIRMABLE" in err,
        )

    # 13 User approval required
    prop = _make_proposal(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
        confirmation_token_sha256=gen["token_hash"],
    )
    is_valid, err = await service.validate_token(
        proposal=prop, received_token=gen["token"], user_approved=False,
    )
    check("user_approved=False rejected", not is_valid and "USER_CONFIRMATION_REQUIRED" in err)

    # 14 Non-destructive operations
    for nd in ["create_page", "update_page"]:
        prop = _make_proposal(session_id=TEST_SESS, proposal_id=TEST_PROP, action_type=nd)
        is_valid, err = await service.validate_token(
            proposal=prop, received_token="a" * 64, user_approved=True,
        )
        check(
            f"non-destructive '{nd}' rejected",
            not is_valid and "NON_DESTRUCTIVE_OPERATION" in err,
        )

    # 15 Invalid token format
    for bad in ["", "abc", "x" * 64]:
        prop = _make_proposal(
            session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
            confirmation_token_sha256=gen["token_hash"],
        )
        is_valid, err = await service.validate_token(
            proposal=prop, received_token=bad, user_approved=True,
        )
        if bad:
            check(
                f"bad format '{bad[:20]}' rejected",
                not is_valid and "INVALID_TOKEN_FORMAT" in err,
            )

    # 16 No confirmation hash
    prop = _make_proposal(session_id=TEST_SESS, proposal_id=TEST_PROP, confirmation_token_sha256=None)
    is_valid, err = await service.validate_token(
        proposal=prop, received_token="a" * 64, user_approved=True,
    )
    check("no hash set rejected", not is_valid and "NO_CONFIRMATION_TOKEN_SET" in err)

    # 17 Admin override
    prop = _make_proposal(session_id=TEST_SESS, proposal_id=TEST_PROP, confirmation_token_sha256=None)
    is_valid, err = await service.validate_token(
        proposal=prop, received_token="invalid", user_approved=True,
        admin_override=True,
        admin_override_reason="This is a valid admin override reason for testing purposes",
    )
    check("admin override bypasses token", is_valid and err is None)

    # 18 Admin override short reason
    is_valid, err = await service.validate_token(
        proposal=prop, received_token="a" * 64, user_approved=True,
        admin_override=True, admin_override_reason="Too short",
    )
    check("short admin reason rejected", not is_valid and "ADMIN_OVERRIDE_REASON_TOO_SHORT" in err)

    # 19 Different scope fails
    gen3 = await service.generate_token(
        session_id=TEST_SESS, proposal_id=TEST_PROP, target_resource_type="page",
        target_resource_id=TEST_RES, operation_type="delete_page", resource_hash="h1",
    )
    prop = _make_proposal(
        session_id="sess_DIFFERENT",
        confirmation_token_sha256=gen3["token_hash"],
        confirmation_token_expires_at=gen3["expires_at"],
    )
    is_valid, err = await service.validate_token(
        proposal=prop, received_token=gen3["token"], user_approved=True,
    )
    check("different scope rejected", not is_valid and "INVALID_CONFIRMATION_TOKEN" in err)

    # 20 Security event logging
    with patch.object(service, "_log_security_event") as mock_log:
        prop = _make_proposal(
            session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
            confirmation_token_sha256=gen["token_hash"],
        )
        await service.validate_token(
            proposal=prop, received_token="f" * 64, user_approved=True,
        )
        check("security event logged on mismatch", mock_log.called and mock_log.call_count == 1)

    # 21 Security event NOT logged on expiry
    with patch.object(service, "_log_security_event") as mock_log:
        prop = _make_proposal(
            session_id=TEST_SESS, proposal_id=TEST_PROP, target_id=TEST_RES,
            confirmation_token_sha256=gen_exp["token_hash"],
            confirmation_token_expires_at=expired,
        )
        await service.validate_token(
            proposal=prop, received_token=gen_exp["token"], user_approved=True,
        )
        check("no security event on expiry", mock_log.call_count == 0)

    print("\n=== Resource Hash Tests ===")

    # 22 Happy hash verification
    prop = _make_proposal(base_hash="abc123")
    is_match, err = await service.verify_resource_hash(
        proposal=prop, current_resource_hash="abc123",
    )
    check("matching hashes verified", is_match and err is None)

    # 23 Hash mismatch
    is_match, err = await service.verify_resource_hash(
        proposal=prop, current_resource_hash="xyz789",
    )
    check("hash mismatch rejected", not is_match and "RESOURCE_CHANGED" in err)
    check("mismatch includes both hashes", "abc123" in err and "xyz789" in err)

    # 24 Missing base hash
    prop = _make_proposal(base_hash=None)
    is_match, err = await service.verify_resource_hash(
        proposal=prop, current_resource_hash="abc",
    )
    check("missing base_hash rejected", not is_match and "BASE_HASH_MISSING" in err)

    # 25 Deterministic hash computation
    h1 = service.compute_resource_hash({"a": 1, "b": 2})
    h2 = service.compute_resource_hash({"a": 1, "b": 2})
    check("deterministic hash", h1 == h2 and len(h1) == 64)

    # 26 Hash changes with data
    h1 = service.compute_resource_hash({"a": 1})
    h2 = service.compute_resource_hash({"a": 2})
    check("hash changes with state", h1 != h2)

    print("\n=== Scope String Tests ===")

    # 27 Deterministic scope
    s1 = service._build_scope_string(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete",
    )
    s2 = service._build_scope_string(
        session_id="s1", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete",
    )
    check("deterministic scope string", s1 == s2)
    check("scope includes session_id", "session_id=s1" in s1)
    check("scope includes proposal_id", "proposal_id=p1" in s1)
    check("scope includes all 5 fields", all(
        f in s1 for f in ["session_id", "proposal_id", "target_resource_type",
                          "target_resource_id", "operation_type"]
    ))

    # 28 Scope changes with input
    s3 = service._build_scope_string(
        session_id="s2", proposal_id="p1", target_resource_type="page",
        target_resource_id="r1", operation_type="delete",
    )
    check("scope changes with session_id", s1 != s3)

    # 29 Scope parts are sorted
    parts = s1.split(service.SCOPE_SEPARATOR)
    check("scope parts are sorted", parts == sorted(parts))

    print("\n=== Error Class Tests ===")

    e = TokenExpiredError(datetime.now(timezone.utc))
    check("TokenExpiredError code", e.code == "CONFIRMATION_EXPIRED")
    check("TokenExpiredError status", e.status_code == 410)

    e = TokenMismatchError()
    check("TokenMismatchError code", e.code == "INVALID_CONFIRMATION_TOKEN")
    check("TokenMismatchError status", e.status_code == 403)

    e = ResourceChangedError("base", "current")
    check("ResourceChangedError code", e.code == "RESOURCE_CHANGED")
    check("ResourceChangedError status", e.status_code == 409)
    check("ResourceChangedError base_hash", e.base_hash == "base")
    check("ResourceChangedError current_hash", e.current_hash == "current")

    e = ProposalNotInConfirmableStateError("applied")
    check("ProposalNotInConfirmableStateError code", e.code == "PROPOSAL_NOT_CONFIRMABLE")
    check("ProposalNotInConfirmableStateError status", e.status_code == 409)

    e = ResourceNotFoundError("page", "xyz")
    check("ResourceNotFoundError code", e.code == "RESOURCE_NOT_FOUND")
    check("ResourceNotFoundError status", e.status_code == 410)

    e = ConfirmationTokenError("CUSTOM", "msg", 418)
    check("ConfirmationTokenError code", e.code == "CUSTOM")
    check("ConfirmationTokenError status", e.status_code == 418)

    print("\n=== Target Resource Derivation Tests ===")

    prop = _make_proposal(action_type="delete_page", target_type="page", target_id="p1")
    check("page delete maps to 'page'", service._get_target_resource_type(prop) == "page")

    prop = _make_proposal(action_type="delete_course", target_type="course", target_id="c1")
    check("course delete maps to 'course'", service._get_target_resource_type(prop) == "course")

    prop = _make_proposal(action_type="batch_delete", target_type="batch", target_id=None)
    check("batch delete maps to 'batch'", service._get_target_resource_type(prop) == "batch")

    prop = _make_proposal(target_id="page_123")
    check("target ID from target_id", service._get_target_resource_id(prop) == "page_123")

    prop = _make_proposal(target_id=None, proposal_id="prop_xyz")
    check("target ID fallback to proposal_id", service._get_target_resource_id(prop) == "prop_xyz")

    print("\n=== Destructive Operations Set Tests ===")
    check("delete_page is destructive", "delete_page" in DESTRUCTIVE_OPERATIONS)
    check("delete_course is destructive", "delete_course" in DESTRUCTIVE_OPERATIONS)
    check("batch_delete is destructive", "batch_delete" in DESTRUCTIVE_OPERATIONS)
    check("delete_asset is destructive", "delete_asset" in DESTRUCTIVE_OPERATIONS)
    check("course_archive is destructive", "course_archive" in DESTRUCTIVE_OPERATIONS)
    check("create_page is NOT destructive", "create_page" not in DESTRUCTIVE_OPERATIONS)
    check("update_page is NOT destructive", "update_page" not in DESTRUCTIVE_OPERATIONS)

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
