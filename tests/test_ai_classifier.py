"""
Unit tests for AIClassifier — OpenAI client is always mocked.
Tests cover: fallback on error, JSON parsing edge cases, score clamping.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


def _make_classifier(raw_response: str):
    """Return an AIClassifier with a mocked LLM that returns raw_response."""
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = raw_response

    with patch("app.ai_classifier.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = mock_resp
        from app import ai_classifier as mod
        import importlib
        importlib.reload(mod)   # ensure fresh import with the mock in place
        classifier = mod.AIClassifier()
        # Keep the mock alive on the instance
        classifier.client = MockOpenAI.return_value
    return classifier


def _valid_response(category="Consulta general", lead_score=3):
    return json.dumps({
        "reasoning": "Razonamiento de prueba.",
        "category": category,
        "summary": "Resumen de prueba.",
        "lead_score": lead_score,
    })


# ---------------------------------------------------------------------------
# Normal classification
# ---------------------------------------------------------------------------

def test_classify_returns_correct_category():
    c = _make_classifier(_valid_response("Solicitud de visita", lead_score=7))
    result = c.classify_email("Subject", "Body", "test@test.com")
    assert result["category"] == "Solicitud de visita"
    assert result["priority"] == "alta"
    assert result["lead_score"] == 7


def test_classify_all_valid_categories():
    """Every category name must resolve to a known priority/color."""
    valid_categories = [
        "Oferta de compra",
        "Solicitud de visita",
        "Consulta de precio",
        "Documentación / trámites",
        "Consulta general",
        "Spam / irrelevante",
    ]
    for cat in valid_categories:
        c = _make_classifier(_valid_response(cat))
        result = c.classify_email("S", "B", "e@e.com")
        assert result["category"] == cat
        assert result["priority"] is not None
        assert result["color"] is not None


# ---------------------------------------------------------------------------
# Robustness / edge cases
# ---------------------------------------------------------------------------

def test_classify_strips_markdown_code_fences():
    raw = f"```json\n{_valid_response()}\n```"
    c = _make_classifier(raw)
    result = c.classify_email("S", "B", "e@e.com")
    assert result["category"] == "Consulta general"


def test_classify_handles_extra_text_after_json():
    raw = _valid_response() + "\n\nEspero que esto ayude."
    c = _make_classifier(raw)
    result = c.classify_email("S", "B", "e@e.com")
    assert result["category"] == "Consulta general"


def test_classify_unknown_category_falls_back_to_spam():
    raw = json.dumps({"reasoning": "r", "category": "Categoria Inventada", "summary": "s", "lead_score": 0})
    c = _make_classifier(raw)
    result = c.classify_email("S", "B", "e@e.com")
    assert result["category"] == "Spam / irrelevante"


def test_classify_case_insensitive_category_match():
    """Category match should be case-insensitive."""
    raw = json.dumps({"reasoning": "r", "category": "oferta de compra", "summary": "s", "lead_score": 10})
    c = _make_classifier(raw)
    result = c.classify_email("S", "B", "e@e.com")
    assert result["category"] == "Oferta de compra"


# ---------------------------------------------------------------------------
# Lead score clamping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (99,  10),
    (-5,   0),
    (5,    5),
    (10,  10),
    (0,    0),
])
def test_lead_score_clamped(score, expected):
    raw = json.dumps({"reasoning": "r", "category": "Consulta general", "summary": "s", "lead_score": score})
    c = _make_classifier(raw)
    result = c.classify_email("S", "B", "e@e.com")
    assert result["lead_score"] == expected


# ---------------------------------------------------------------------------
# Fallback on API errors
# ---------------------------------------------------------------------------

def test_classify_fallback_on_api_exception():
    with patch("app.ai_classifier.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = Exception("API down")
        from app import ai_classifier as mod
        import importlib
        importlib.reload(mod)
        classifier = mod.AIClassifier()
        classifier.client = MockOpenAI.return_value

    result = classifier.classify_email("S", "B", "e@e.com")
    assert result["category"] == "Spam / irrelevante"
    assert result["priority"] == "baja"
    assert result["lead_score"] is None


def test_classify_fallback_on_invalid_json():
    c = _make_classifier("Esto no es JSON válido {}{{")
    result = c.classify_email("S", "B", "e@e.com")
    assert result["category"] == "Spam / irrelevante"
