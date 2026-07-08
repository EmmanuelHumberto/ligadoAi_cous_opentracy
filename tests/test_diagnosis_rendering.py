"""Tests for rendered diagnosis summaries."""

from cous.measurements.diagnosis import diagnosis_summary_rows


def test_diagnosis_summary_rows_empty_when_no_diagnosis():
    assert diagnosis_summary_rows({"id": "m1"}) == []


def test_diagnosis_summary_rows_includes_primary_hypothesis_and_explanation():
    rows = diagnosis_summary_rows(
        {
            "diagnosis_status": "completed",
            "diagnosis_correlation_id": "corr-123",
            "diagnosis_completed_at": "2026-07-07T12:00:00+00:00",
            "diagnosis_result": {
                "hypotheses": [
                    {
                        "description": "Hipotese secundaria",
                        "confidence": 0.2,
                        "is_primary": False,
                    },
                    {
                        "description": "Atrito elevado no conjunto rotativo",
                        "confidence": 0.87,
                        "is_primary": True,
                    },
                ],
                "explanation": {
                    "narrative": "Assinatura eletromecanica degradada.",
                    "confidence": 0.81,
                },
            },
        }
    )

    assert ("Diagnostico", "completed") in rows
    assert ("Correlation ID", "corr-123") in rows
    assert (
        "Hipotese principal",
        "Atrito elevado no conjunto rotativo (87%)",
    ) in rows
    assert ("Explicacao", "Assinatura eletromecanica degradada. (81%)") in rows


def test_diagnosis_summary_rows_ignores_result_from_previous_correlation():
    rows = diagnosis_summary_rows(
        {
            "diagnosis_status": "queued",
            "diagnosis_correlation_id": "new-correlation",
            "diagnosis_result": {
                "correlation_id": "old-correlation",
                "hypotheses": [
                    {
                        "description": "Resultado antigo",
                        "confidence": 0.82,
                        "is_primary": True,
                    }
                ],
            },
        }
    )

    assert ("Diagnostico", "queued") in rows
    assert not any("Resultado antigo" in value for _key, value in rows)
