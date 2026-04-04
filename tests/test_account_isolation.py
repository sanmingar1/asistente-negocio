"""
Tests for Gmail account isolation (fix/account-isolation).

When the authenticated account changes, emails from the previous account
must be purged automatically on the next sync.
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock

from app.models import Email
import app.routes as routes_module


def _raw(gmail_id=None, sender_email="lead@example.com"):
    return {
        "gmail_id": gmail_id or str(uuid.uuid4()),
        "thread_id": "t1",
        "sender": "Lead",
        "sender_email": sender_email,
        "subject": "Consulta",
        "body_preview": "Hola",
        "body_full": "Hola",
        "received_at": None,
        "raw_labels": "[]",
    }


def _gmail_mock(account_email, emails=None):
    m = MagicMock()
    m.get_account_email.return_value = account_email
    m.fetch_emails.return_value = emails or []
    return m


def _classifier_mock():
    m = MagicMock()
    m.classify_email.return_value = {
        "category": "Consulta general", "priority": "media",
        "color": "green", "summary": "Test.", "lead_score": 3,
    }
    return m


class TestAccountIsolation:
    def test_emails_tagged_with_account_on_sync(self, client, db, mock_classifier):
        gmail = _gmail_mock("agente@inmobiliaria.com", [_raw()])
        with patch.object(routes_module, "_gmail_client", gmail), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        email = db.query(Email).filter(Email.is_demo == False).first()  # noqa: E712
        assert email is not None
        assert email.account_email == "agente@inmobiliaria.com"

    def test_same_account_keeps_existing_emails(self, client, db, email_factory, mock_classifier):
        email_factory(gmail_id="existing_001", account_email="agente@inmobiliaria.com")
        gmail = _gmail_mock("agente@inmobiliaria.com", [_raw("new_002")])
        with patch.object(routes_module, "_gmail_client", gmail), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            r = client.post("/api/sync")

        assert r.json()["new_emails"] == 1
        total = db.query(Email).filter(Email.is_demo == False).count()  # noqa: E712
        assert total == 2  # original + new

    def test_account_change_purges_old_emails(self, client, db, email_factory, mock_classifier):
        # Emails from old account
        email_factory(gmail_id="old_001", account_email="cuenta_a@gmail.com")
        email_factory(gmail_id="old_002", account_email="cuenta_a@gmail.com")

        # Sync with new account
        gmail = _gmail_mock("cuenta_b@gmail.com", [_raw("new_001")])
        with patch.object(routes_module, "_gmail_client", gmail), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            r = client.post("/api/sync")

        assert r.json()["new_emails"] == 1
        remaining = db.query(Email).filter(Email.is_demo == False).all()  # noqa: E712
        assert len(remaining) == 1
        assert remaining[0].account_email == "cuenta_b@gmail.com"

    def test_account_change_does_not_purge_demo_emails(self, client, db, email_factory, mock_classifier):
        # Demo emails have no account_email (is_demo=True)
        email_factory(gmail_id="demo_001", is_demo=True, account_email=None)
        email_factory(gmail_id="real_001", account_email="old@gmail.com")

        gmail = _gmail_mock("new@gmail.com", [])
        with patch.object(routes_module, "_gmail_client", gmail), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        # Demo email still there (not purged, different logic)
        demo = db.query(Email).filter(Email.gmail_id == "demo_001").first()
        assert demo is not None
        # Old real email purged
        old = db.query(Email).filter(Email.gmail_id == "real_001").first()
        assert old is None

    def test_null_account_emails_not_purged_on_first_sync(self, client, db, email_factory, mock_classifier):
        # Emails with no account_email (legacy) are never purged since foreign check
        # requires account_email IS NOT NULL AND != active
        email_factory(gmail_id="legacy_001", account_email=None)

        gmail = _gmail_mock("new@gmail.com", [])
        with patch.object(routes_module, "_gmail_client", gmail), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        legacy = db.query(Email).filter(Email.gmail_id == "legacy_001").first()
        assert legacy is not None

    def test_settings_exposes_active_account(self, client, db, email_factory):
        email_factory(gmail_id="real_001", account_email="agente@gmail.com", is_demo=False)
        r = client.get("/api/settings")
        assert r.status_code == 200
        assert r.json()["active_account"] == "agente@gmail.com"

    def test_settings_active_account_none_when_no_real_emails(self, client):
        r = client.get("/api/settings")
        assert r.json()["active_account"] is None
