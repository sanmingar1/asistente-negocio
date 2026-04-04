"""
portal_parser.py — Detect real estate portal sources and extract lead contact data.

Supports: Idealista, Fotocasa, Airbnb, Habitaclia, Pisos.com, Kyero, ThinkSpain.
"""
import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Portal domain → display name
PORTAL_DOMAINS: Dict[str, str] = {
    "idealista.com": "Idealista",
    "fotocasa.es": "Fotocasa",
    "fotocasa.com": "Fotocasa",
    "airbnb.com": "Airbnb",
    "airbnb.es": "Airbnb",
    "habitaclia.com": "Habitaclia",
    "pisos.com": "Pisos.com",
    "kyero.com": "Kyero",
    "thinkspain.com": "ThinkSpain",
}


def detect_source(sender_email: str) -> Optional[str]:
    """Return the portal display name if the sender is a known portal, else None."""
    if not sender_email:
        return None
    domain = sender_email.split("@")[-1].lower().strip()
    return PORTAL_DOMAINS.get(domain)


def extract_lead_data(body: str) -> Dict[str, Optional[str]]:
    """
    Extract structured lead data (name, phone, property_ref) from a portal email body.
    Returns a dict with keys: name, phone, property_ref (all Optional[str]).
    """
    result: Dict[str, Optional[str]] = {
        "name": None,
        "phone": None,
        "property_ref": None,
    }

    if not body:
        return {}

    # ── Phone ────────────────────────────────────────────────────────────────
    # Try labelled phone first
    phone_match = re.search(
        r"(?:tel[eé]fono|tel\.?|phone|móvil|mobile|contacto)[:\s]*([+\d][\d\s\-().]{7,17})",
        body, re.IGNORECASE,
    )
    if phone_match:
        result["phone"] = _clean_phone(phone_match.group(1))
    else:
        # Bare Spanish mobile/landline (starts 6xx, 7xx, 8xx, 9xx, or +34)
        bare = re.search(r"\b(\+34\s?)?([6-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{3})\b", body)
        if bare:
            result["phone"] = _clean_phone((bare.group(1) or "") + bare.group(2))

    # ── Name ─────────────────────────────────────────────────────────────────
    name_match = re.search(
        r"(?:nombre|name|de parte de|remitente|interesado)[:\s]+([A-ZÁÉÍÓÚÑÜÀ][^\n\r,;<]{2,50})",
        body, re.IGNORECASE,
    )
    if name_match:
        result["name"] = name_match.group(1).strip()[:80]

    # ── Property reference ────────────────────────────────────────────────────
    ref_match = re.search(
        r"(?:ref(?:erencia)?\.?|anuncio\s*(?:nº|n\.?º?|#)?|inmueble|propiedad)\s*[:#\-]?\s*(?:ref\.?\s+)?([A-Z0-9][\w\-]{2,20})",
        body, re.IGNORECASE,
    )
    if ref_match:
        result["property_ref"] = ref_match.group(1).strip()[:50]

    return result


def _clean_phone(raw: str) -> str:
    """Remove whitespace/dashes, keep digits and leading +."""
    cleaned = re.sub(r"[\s\-().]", "", raw)
    return cleaned[:20]
