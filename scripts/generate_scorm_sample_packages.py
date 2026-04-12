"""Generate the two contract-required SCORM sample packages.

Modes:
1. Persisted export mode (default in integrated environments)
     python scripts/generate_scorm_sample_packages.py \
         --base-url http://localhost:8000 \
         --assessment-course-id <course-id> \
         --branching-course-id <course-id> \
         --output-dir artifacts/scorm-samples

2. Direct export mode (DB-independent fallback)
     python scripts/generate_scorm_sample_packages.py \
         --base-url http://localhost:8000 \
         --use-builtins \
         --output-dir artifacts/scorm-samples
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict


def _download_export_persisted(base_url: str, course_id: str, output_path: str) -> None:
    url = f"{base_url.rstrip('/')}/api/v1/export/scorm/{course_id}?format=scorm_1_2"
    req = urllib.request.Request(url=url, method="POST")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=120) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(
                f"Export failed for course '{course_id}' with status {status}"
            )
        payload = response.read()

    with open(output_path, "wb") as f:
        f.write(payload)


def _download_export_direct(base_url: str, course_payload: Dict[str, Any], output_path: str) -> None:
    url = f"{base_url.rstrip('/')}/api/v1/export"
    body = json.dumps({"course": json.dumps(course_payload)}).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=120) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"Direct export failed with status {status}")
        payload = response.read()

    with open(output_path, "wb") as f:
        f.write(payload)


def _built_in_assessment_course() -> Dict[str, Any]:
    return {
        "courseId": "sample-assessment",
        "title": "Assessment Heavy Sample",
        "description": "Generated sample with assessment templates",
        "author": "backend-script",
        "templates": [
            {
                "id": "tpl-a1",
                "type": "mcq",
                "order": 0,
                "title": "MCQ Block",
                "data": {
                    "content": "Choose the best answer.",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "2 + 2 = ?",
                            "options": [
                                {"id": "o1", "text": "4", "isCorrect": True},
                                {"id": "o2", "text": "5", "isCorrect": False},
                            ],
                        }
                    ],
                },
            },
            {
                "id": "tpl-a2",
                "type": "mcq",
                "order": 1,
                "title": "Assessment Quiz 2",
                "data": {
                    "content": "Choose the best answer.",
                    "questions": [
                        {
                            "id": "q2",
                            "question": "Earth is a?",
                            "options": [
                                {"id": "o1", "text": "Planet", "isCorrect": True},
                                {"id": "o2", "text": "Star", "isCorrect": False},
                            ],
                        }
                    ],
                },
            },
            {
                "id": "tpl-a3",
                "type": "content-text",
                "order": 2,
                "title": "Assessment Summary",
                "data": {
                    "content": "You completed the assessment-heavy sample course.",
                },
            },
        ],
    }


def _built_in_branching_course() -> Dict[str, Any]:
    return {
        "courseId": "sample-branching",
        "title": "Branching Heavy Sample",
        "description": "Generated sample with scenario and navigation templates",
        "author": "backend-script",
        "templates": [
            {
                "id": "tpl-b1",
                "type": "scenario",
                "order": 0,
                "title": "Scenario",
                "data": {
                    "content": "A customer reports an issue.",
                    "scenarioText": "How do you respond?",
                    "options": [
                        {"text": "Listen first", "feedback": "Great choice"},
                        {"text": "Dismiss quickly", "feedback": "Poor choice"},
                    ],
                },
            },
            {
                "id": "tpl-b2",
                "type": "accordion",
                "order": 1,
                "title": "Details",
                "data": {
                    "content": "Fallback details",
                    "panels": [
                        {"id": "p1", "title": "Step 1", "content": "Acknowledge"},
                        {"id": "p2", "title": "Step 2", "content": "Resolve"},
                    ],
                },
            },
            {
                "id": "tpl-b3",
                "type": "tabs",
                "order": 2,
                "title": "Paths",
                "data": {
                    "content": "Fallback path content",
                    "tabs": [
                        {"title": "Path A", "content": "Escalate"},
                        {"title": "Path B", "content": "Self-serve"},
                    ],
                },
            },
        ],
    }



def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate assessment-heavy and branching-heavy SCORM sample packages."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--assessment-course-id",
        help="Course ID for assessment-heavy sample package",
    )
    parser.add_argument(
        "--branching-course-id",
        help="Course ID for branching-heavy sample package",
    )
    parser.add_argument(
        "--use-builtins",
        action="store_true",
        help="Generate samples via direct export endpoint using built-in payloads (no DB dependency)",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/scorm-samples",
        help="Output directory for generated zip files",
    )
    return parser.parse_args()



def main() -> int:
    args = _parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    assessment_label = args.assessment_course_id or "assessment"
    branching_label = args.branching_course_id or "branching"

    assessment_course_payload = None
    branching_course_payload = None
    if args.use_builtins:
        assessment_course_payload = _built_in_assessment_course()
        branching_course_payload = _built_in_branching_course()
        assessment_label = assessment_course_payload.get("courseId", assessment_label)
        branching_label = branching_course_payload.get("courseId", branching_label)

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    assessment_zip = os.path.join(
        args.output_dir,
        f"assessment-heavy-{assessment_label}-{stamp}.zip",
    )
    branching_zip = os.path.join(
        args.output_dir,
        f"branching-heavy-{branching_label}-{stamp}.zip",
    )

    try:
        if args.use_builtins:
            _download_export_direct(args.base_url, assessment_course_payload, assessment_zip)
            print(f"Created (direct): {assessment_zip}")

            _download_export_direct(args.base_url, branching_course_payload, branching_zip)
            print(f"Created (direct): {branching_zip}")
        else:
            if not args.assessment_course_id or not args.branching_course_id:
                raise ValueError(
                    "Provide both --assessment-course-id and --branching-course-id, "
                    "or use --use-builtins"
                )

            _download_export_persisted(args.base_url, args.assessment_course_id, assessment_zip)
            print(f"Created (persisted): {assessment_zip}")

            _download_export_persisted(args.base_url, args.branching_course_id, branching_zip)
            print(f"Created (persisted): {branching_zip}")

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP error: {exc.code} {exc.reason}\n{body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
