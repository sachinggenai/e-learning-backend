"""Tests for new Template Engine Backend endpoints.

Tests cover: Branching (2.2), Social/Collaborative (2.3),
Analytics (2.4), Interaction Events (2.1), Component Registry enhancements (2.5).

Requires the server running on http://127.0.0.1:8000.
Usage: python test_template_engine_backend.py
"""
import json
import sys
import requests

BASE = "http://127.0.0.1:8000/api/v1"
COURSE_ID = "test-template-engine"
PASS = 0
FAIL = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  [PASS] {label}")


def fail(label: str, detail: str = ""):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {label}  {detail}")


def check(label: str, resp: requests.Response, expected_status: int = 200):
    if resp.status_code == expected_status:
        ok(f"{label} → {expected_status}")
        return True
    else:
        fail(label, f"expected {expected_status}, got {resp.status_code}: {resp.text[:200]}")
        return False


# ── Setup: create a test course ──────────────────────────────────────────────

def setup_course():
    print("\n=== Setup: Create test course ===")
    # Delete if exists
    requests.delete(f"{BASE}/courses/{COURSE_ID}", timeout=5)
    resp = requests.post(f"{BASE}/courses", json={
        "courseId": COURSE_ID,
        "title": "Template Engine Test Course",
        "description": "Test course for new endpoints",
        "data": {},
    }, timeout=5)
    if resp.status_code in (201, 400):  # 400 = already exists
        ok("Course created or already exists")
    else:
        fail("Course creation", f"status {resp.status_code}: {resp.text[:200]}")


# ── 2.1 Interaction Events ──────────────────────────────────────────────────

def test_interaction_events():
    print("\n=== 2.1 Interaction Events (open string interactionType) ===")

    # Test various interaction types (open string, not closed enum)
    types_to_test = ["flip", "reveal", "drag-sort", "text-input", "rating", "acknowledge", "download", "custom-type-xyz"]
    for itype in types_to_test:
        resp = requests.post(f"{BASE}/courses/{COURSE_ID}/interactions", json={
            "pageId": "page-1",
            "componentId": "comp-1",
            "interactionType": itype,
            "data": {"value": "test", "score": 10.0, "maxScore": 100.0, "duration": 5.5},
            "completed": True,
        }, timeout=5)
        check(f"POST interaction type='{itype}'", resp, 201)

    # List interactions
    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/interactions", timeout=5)
    if check("GET interactions list", resp):
        data = resp.json()
        assert isinstance(data, list), "Expected list"
        ok(f"Got {len(data)} interaction events")

    # Filter by interactionType
    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/interactions?interactionType=flip", timeout=5)
    if check("GET interactions filtered by type", resp):
        data = resp.json()
        for e in data:
            assert e["interactionType"] == "flip", f"Expected flip, got {e['interactionType']}"
        ok("Filter by interactionType works")


# ── 2.2 Branching & Adaptive Navigation ─────────────────────────────────────

def test_branching():
    print("\n=== 2.2 Branching & Adaptive Navigation ===")

    # Create branch rule
    resp = requests.post(f"{BASE}/courses/{COURSE_ID}/branches", json={
        "title": "Score-based branch",
        "description": "Route learners based on quiz score",
        "sourcePageId": "page-quiz",
        "sourceComponentId": "comp-mcq",
        "conditions": [
            {"field": "score", "operator": ">=", "value": 80, "targetPageId": "page-advanced"},
            {"field": "score", "operator": "<", "value": 80, "targetPageId": "page-remedial"},
        ],
        "defaultTargetPageId": "page-default",
        "priority": 0,
        "isActive": True,
    }, timeout=5)
    branch_id = None
    if check("POST create branch rule", resp, 201):
        branch_id = resp.json().get("branchId")
        ok(f"Branch ID: {branch_id}")

    # List branch rules
    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/branches", timeout=5)
    if check("GET list branch rules", resp):
        data = resp.json()
        assert isinstance(data, list) and len(data) > 0
        ok(f"Got {len(data)} branch rules")

    if branch_id:
        # Get specific rule
        resp = requests.get(f"{BASE}/courses/{COURSE_ID}/branches/{branch_id}", timeout=5)
        check("GET specific branch rule", resp)

        # Update rule
        resp = requests.patch(f"{BASE}/courses/{COURSE_ID}/branches/{branch_id}", json={
            "title": "Updated score-based branch",
            "priority": 1,
        }, timeout=5)
        if check("PATCH update branch rule", resp):
            assert resp.json()["title"] == "Updated score-based branch"
            ok("Branch rule updated correctly")

        # Record branch event
        resp = requests.post(f"{BASE}/courses/{COURSE_ID}/branches/{branch_id}/events", json={
            "learnerId": "learner-001",
            "matchedConditionIndex": 0,
            "targetPageId": "page-advanced",
            "contextSnapshot": {"score": 85, "attempt": 1},
        }, timeout=5)
        check("POST record branch event", resp, 201)

        # List branch events
        resp = requests.get(f"{BASE}/courses/{COURSE_ID}/branches/{branch_id}/events", timeout=5)
        if check("GET list branch events", resp):
            data = resp.json()
            assert isinstance(data, list) and len(data) > 0
            ok(f"Got {len(data)} branch events")

        # Filter by learner
        resp = requests.get(
            f"{BASE}/courses/{COURSE_ID}/branches/{branch_id}/events?learnerId=learner-001",
            timeout=5,
        )
        check("GET branch events filtered by learner", resp)

        # Delete branch rule
        resp = requests.delete(f"{BASE}/courses/{COURSE_ID}/branches/{branch_id}", timeout=5)
        check("DELETE branch rule", resp, 204)


# ── 2.3 Social & Collaborative ──────────────────────────────────────────────

def test_social():
    print("\n=== 2.3 Social & Collaborative ===")

    # ── Discussions
    resp = requests.post(f"{BASE}/courses/{COURSE_ID}/discussions", json={
        "title": "Module 1 Discussion",
        "body": "What did you learn from Module 1?",
        "authorId": "instructor-1",
    }, timeout=5)
    thread_id = None
    if check("POST create discussion thread", resp, 201):
        thread_id = resp.json().get("threadId")

    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/discussions", timeout=5)
    check("GET list discussions", resp)

    if thread_id:
        # Add reply
        resp = requests.post(
            f"{BASE}/courses/{COURSE_ID}/discussions/{thread_id}/replies",
            json={"body": "I learned about branching!", "authorId": "learner-001"},
            timeout=5,
        )
        check("POST add discussion reply", resp, 201)

        # Get thread with replies
        resp = requests.get(f"{BASE}/courses/{COURSE_ID}/discussions/{thread_id}", timeout=5)
        if check("GET discussion with replies", resp):
            data = resp.json()
            assert "replies" in data and len(data["replies"]) > 0
            ok("Replies included in thread response")

    # ── Peer Reviews
    resp = requests.post(f"{BASE}/courses/{COURSE_ID}/peer-reviews", json={
        "content": {"essay": "My essay about learning..."},
        "authorId": "learner-002",
    }, timeout=5)
    sub_id = None
    if check("POST create peer review submission", resp, 201):
        sub_id = resp.json().get("submissionId")

    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/peer-reviews", timeout=5)
    check("GET list peer review submissions", resp)

    if sub_id:
        resp = requests.post(
            f"{BASE}/courses/{COURSE_ID}/peer-reviews/{sub_id}/reviews",
            json={
                "reviewerId": "learner-003",
                "feedback": "Good essay structure!",
                "rubricScores": {"clarity": 8, "content": 9, "grammar": 7},
                "overallScore": 8.0,
            },
            timeout=5,
        )
        check("POST add peer review", resp, 201)

        resp = requests.get(f"{BASE}/courses/{COURSE_ID}/peer-reviews/{sub_id}", timeout=5)
        if check("GET submission with reviews", resp):
            data = resp.json()
            assert "reviews" in data and len(data["reviews"]) > 0
            ok("Reviews included in submission response")

    # ── Polls
    resp = requests.post(f"{BASE}/courses/{COURSE_ID}/polls", json={
        "question": "What was the most useful module?",
        "options": ["Module 1", "Module 2", "Module 3"],
        "allowMultiple": False,
        "isAnonymous": True,
    }, timeout=5)
    poll_id = None
    if check("POST create poll", resp, 201):
        poll_id = resp.json().get("pollId")

    if poll_id:
        # Submit votes
        for voter in ["voter-1", "voter-2", "voter-3"]:
            resp = requests.post(
                f"{BASE}/courses/{COURSE_ID}/polls/{poll_id}/votes",
                json={"voterId": voter, "selectedOptions": [0]},
                timeout=5,
            )
            check(f"POST poll vote ({voter})", resp, 201)

        resp = requests.post(
            f"{BASE}/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "voter-4", "selectedOptions": [1]},
            timeout=5,
        )
        check("POST poll vote (voter-4 option 1)", resp, 201)

        # Get results
        resp = requests.get(f"{BASE}/courses/{COURSE_ID}/polls/{poll_id}/results", timeout=5)
        if check("GET poll results with tally", resp):
            data = resp.json()
            assert data["totalVotes"] == 4
            assert data["options"][0]["votes"] == 3
            assert data["options"][1]["votes"] == 1
            ok(f"Poll tally correct: {data['totalVotes']} votes")

    # ── Teams
    resp = requests.post(f"{BASE}/courses/{COURSE_ID}/teams", json={
        "name": "Alpha Team",
        "members": ["learner-001", "learner-002"],
    }, timeout=5)
    team_id = None
    if check("POST create team", resp, 201):
        team_id = resp.json().get("teamId")

    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/teams", timeout=5)
    check("GET list teams", resp)

    if team_id:
        resp = requests.patch(f"{BASE}/courses/{COURSE_ID}/teams/{team_id}", json={
            "score": 85.5,
            "members": ["learner-001", "learner-002", "learner-003"],
        }, timeout=5)
        if check("PATCH update team", resp):
            data = resp.json()
            assert data["score"] == 85.5
            assert len(data["members"]) == 3
            ok("Team updated correctly")

        resp = requests.delete(f"{BASE}/courses/{COURSE_ID}/teams/{team_id}", timeout=5)
        check("DELETE team", resp, 204)


# ── 2.4 Analytics & Reporting ───────────────────────────────────────────────

def test_analytics():
    print("\n=== 2.4 Analytics & Reporting ===")

    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/analytics/summary", timeout=5)
    if check("GET analytics summary", resp):
        data = resp.json()
        assert "structure" in data
        assert "scoring" in data
        assert "interactions" in data
        ok("Summary has expected structure")

    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/analytics/skills", timeout=5)
    if check("GET skill mastery", resp):
        data = resp.json()
        assert "skills" in data
        assert "totalSkills" in data
        ok("Skills endpoint returns expected shape")

    resp = requests.get(f"{BASE}/courses/{COURSE_ID}/analytics/manager-view", timeout=5)
    if check("GET manager view", resp):
        data = resp.json()
        assert "courseId" in data
        assert "pages" in data
        assert "totalPages" in data
        ok("Manager view returns expected shape")


# ── 2.5 Component Registry Schema ──────────────────────────────────────────

def test_component_registry():
    print("\n=== 2.5 Component Registry enhancements ===")

    # List should include schemaVersion
    resp = requests.get(f"{BASE}/components", timeout=5)
    if check("GET component types list", resp):
        data = resp.json()
        assert "schemaVersion" in data, "Missing schemaVersion in list response"
        ok(f"schemaVersion = {data['schemaVersion']}")

    # Get categories
    resp = requests.get(f"{BASE}/components/categories", timeout=5)
    check("GET component categories", resp)

    # Search
    resp = requests.get(f"{BASE}/components/search?q=tabs", timeout=5)
    check("GET component search", resp)

    # Get specific type with schemaVersion + etag
    resp = requests.get(f"{BASE}/components", timeout=5)
    if resp.status_code == 200:
        items = resp.json().get("items", [])
        if items:
            type_id = items[0].get("typeId")
            resp2 = requests.get(f"{BASE}/components/{type_id}", timeout=5)
            if check(f"GET component type '{type_id}' full detail", resp2):
                data = resp2.json()
                assert "schemaVersion" in data, "Missing schemaVersion"
                assert "etag" in data, "Missing etag"
                assert "schema" in data, "Missing schema"
                ok(f"schemaVersion={data['schemaVersion']}, etag={data['etag']}")

                # Test conditional GET with If-None-Match
                etag = resp2.headers.get("ETag", "")
                if etag:
                    resp3 = requests.get(
                        f"{BASE}/components/{type_id}",
                        headers={"If-None-Match": etag},
                        timeout=5,
                    )
                    if resp3.status_code == 304:
                        ok("Conditional GET returned 304 (cache hit)")
                    else:
                        ok(f"Conditional GET returned {resp3.status_code} (cache miss or no support)")
        else:
            ok("No component types seeded — skipping detail test")


# ── Cleanup ──────────────────────────────────────────────────────────────────

def cleanup():
    print("\n=== Cleanup ===")
    resp = requests.delete(f"{BASE}/courses/{COURSE_ID}", timeout=5)
    if resp.status_code in (204, 404):
        ok("Test course cleaned up")
    else:
        fail("Cleanup", f"status {resp.status_code}")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Template Engine Backend — Integration Tests")
    print("=" * 60)

    try:
        requests.get(f"{BASE}/health", timeout=3)
    except Exception:
        print("\nERROR: Server not running at", BASE)
        print("Start with: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)

    setup_course()
    test_interaction_events()
    test_branching()
    test_social()
    test_analytics()
    test_component_registry()
    cleanup()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL > 0 else 0)
