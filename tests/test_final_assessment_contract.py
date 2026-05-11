import pytest
from pydantic import ValidationError

from app.models.course import Template
from app.services.scorm_export import SCORMExportService


def test_canonicalize_multi_select_alias():
    service = SCORMExportService()
    assert service._canonicalize_template_type("multi-select") == "multiple-select"


def test_canonicalize_final_assessment_supported():
    service = SCORMExportService()
    assert service._canonicalize_template_type("final-assessment") == "final-assessment"


def test_final_assessment_template_validation_accepts_mixed_questions():
    template = Template(
        id="tmpl_final_1",
        type="final-assessment",
        order=0,
        title="Final Assessment",
        data={
            "passingScore": 80,
            "questions": [
                {
                    "id": "q1",
                    "type": "mcq",
                    "question": "What is 2 + 2?",
                    "options": [
                        {"id": "a", "text": "3", "isCorrect": False},
                        {"id": "b", "text": "4", "isCorrect": True},
                    ],
                },
                {
                    "id": "q2",
                    "type": "true-false",
                    "question": "The Earth is round.",
                    "correctAnswer": True,
                },
                {
                    "id": "q3",
                    "type": "fill-in-blank",
                    "question": "Capital of France?",
                    "correctAnswers": ["Paris"],
                },
            ],
        },
    )

    assert template.type == "final-assessment"
    assert len(template.data.questions or []) == 3


def test_final_assessment_template_validation_rejects_invalid_fill_blank():
    with pytest.raises(ValidationError):
        Template(
            id="tmpl_final_bad",
            type="final-assessment",
            order=0,
            title="Final Assessment",
            data={
                "questions": [
                    {
                        "id": "q1",
                        "type": "fill-in-blank",
                        "question": "Capital of France?",
                    }
                ]
            },
        )
