"""
Unit tests for portal detection and contact data extraction.
No DB or HTTP involved — pure logic tests.
"""
import pytest
from app.portal_parser import detect_source, extract_lead_data


# ---------------------------------------------------------------------------
# Portal detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email,expected", [
    ("noreply@idealista.com",     "Idealista"),
    ("contacto@idealista.com",    "Idealista"),
    ("info@fotocasa.es",          "Fotocasa"),
    ("noreply@fotocasa.es",       "Fotocasa"),
    ("noreply@airbnb.com",        "Airbnb"),
    ("reply@airbnb.es",           "Airbnb"),
    ("contacto@habitaclia.com",   "Habitaclia"),
    ("noreply@pisos.com",         "Pisos.com"),
    ("info@kyero.com",            "Kyero"),
    ("noreply@thinkspain.com",    "ThinkSpain"),
])
def test_detect_known_portals(email, expected):
    assert detect_source(email) == expected


@pytest.mark.parametrize("email", [
    "cliente@gmail.com",
    "juan.garcia@hotmail.com",
    "notaria@perezasociados.com",
    "facturacion@vodafone.es",
    "",
])
def test_detect_unknown_returns_none(email):
    assert detect_source(email) is None


# ---------------------------------------------------------------------------
# Contact data extraction
# ---------------------------------------------------------------------------

def test_extract_name_and_phone():
    body = "Has recibido un mensaje de:\nNombre: Ana López\nTeléfono: 612 345 678"
    data = extract_lead_data(body)
    assert data.get("name") == "Ana López"
    assert "612" in (data.get("phone") or "")


def test_extract_property_ref():
    body = "Anuncio: Ref. 28374 - Piso en Calle Mayor 15"
    data = extract_lead_data(body)
    assert data.get("property_ref") is not None
    assert "28374" in data["property_ref"]


def test_extract_empty_body_returns_empty_dict():
    assert extract_lead_data("") == {}


def test_extract_no_match_returns_empty_dict():
    body = "Este es un correo sin datos de contacto estructurados."
    data = extract_lead_data(body)
    # Should return empty dict or dict with None values — no crash
    assert isinstance(data, dict)
