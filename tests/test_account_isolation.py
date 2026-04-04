"""
Tests for multi-account Gmail support.

With multi-account, emails from different accounts coexist in the DB.
Each email is tagged with account_email. Removing an account deletes its emails.
GET /api/emails?account=email filters by account.
"""
import uuid
import pytest
from unittest.mock import MagicMock, patch

from app.models import Email
from app import account_manager
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


def _classifier_mock():
    m = MagicMock()
    m.classify_email.return_value = {
        "category": "Consulta general", "priority": "media",
        "color": "green", "summary": "Test.", "lead_score": 3,
    }
    return m


class TestMultiAccount:
    def test_emails_tagged_with_account_on_sync(self, client, db, mock_accounts, mock_classifier):
        mock_accounts.fetch_emails.return_value = [_raw()]
        mock_accounts.get_account_email.return_value = "agente@inmobiliaria.com"

        with patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        email = db.query(Email).filter(Email.is_demo == False).first()  # noqa: E712
        assert email is not None
        assert email.account_email == "agente@inmobiliaria.com"

    def test_two_accounts_coexist(self, client, db, email_factory):
        """Emails from different accounts are kept simultaneously."""
        email_factory(gmail_id="acct_a_001", account_email="a@gmail.com")
        email_factory(gmail_id="acct_b_001", account_email="b@gmail.com")

        emails = client.get("/api/emails").json()
        assert len(emails) == 2

    def test_account_filter_shows_only_that_account(self, client, db, email_factory):
        email_factory(gmail_id="a_001", account_email="a@gmail.com")
        email_factory(gmail_id="b_001", account_email="b@gmail.com")

        r = client.get("/api/emails?account=a@gmail.com")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["account_email"] == "a@gmail.com"

    def test_remove_account_deletes_its_emails(self, client, db, email_factory):
        email_factory(gmail_id="a_001", account_email="a@gmail.com")
        email_factory(gmail_id="b_001", account_email="b@gmail.com")

        with patch.object(account_manager, "remove_account", return_value=True):
            r = client.delete("/api/accounts/a@gmail.com")

        assert r.status_code == 200
        assert r.json()["emails_deleted"] == 1

        remaining = db.query(Email).filter(Email.is_demo == False).all()  # noqa: E712
        assert len(remaining) == 1
        assert remaining[0].account_email == "b@gmail.com"

    def test_remove_nonexistent_account_returns_404(self, client):
        with patch.object(account_manager, "remove_account", return_value=False):
            r = client.delete("/api/accounts/nobody@gmail.com")
        assert r.status_code == 404

    def test_settings_exposes_connected_accounts(self, client):
        """Settings now exposes connected_accounts list, not active_account."""
        with patch.object(account_manager, "list_accounts", return_value=[]), \
             patch("app.routes.GmailClient"):
            r = client.get("/api/settings")
        assert r.status_code == 200
        assert "connected_accounts" in r.json()
        assert "active_account" not in r.json()

    def test_sync_preserves_emails_from_other_accounts(
        self, client, db, email_factory, mock_accounts, mock_classifier
    ):
        """Syncing account B does not delete emails from account A."""
        email_factory(gmail_id="a_001", account_email="a@gmail.com")
        mock_accounts.fetch_emails.return_value = [_raw("b_new_001")]
        mock_accounts.get_account_email.return_value = "b@gmail.com"

        with patch.object(routes_module, "_ai_classifier", mock_classifier):
            r = client.post("/api/sync")

        assert r.json()["new_emails"] == 1
        total = db.query(Email).filter(Email.is_demo == False).count()  # noqa: E712
        assert total == 2  # both a_001 and b_new_001 present
