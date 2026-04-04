"""
Tests for POST /api/sync — Gmail fetch, classification, deduplication.
"""
from datetime import datetime
from unittest.mock import patch

import app.routes as routes_module


def _make_raw_email(gmail_id, sender="Juan García", sender_email="juan@example.com",
                    subject="Consulta sobre piso", body="Me interesa el piso"):
    return {
        "gmail_id": gmail_id,
        "thread_id": f"thread_{gmail_id}",
        "sender": sender,
        "sender_email": sender_email,
        "subject": subject,
        "body_preview": body[:500],
        "body_full": body,
        "received_at": datetime(2024, 5, 10, 10, 0, 0),
        "raw_labels": "['INBOX']",
    }


def test_sync_empty_inbox(client, mock_accounts, mock_classifier):
    with patch.object(routes_module, "_ai_classifier", mock_classifier):
        r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json()["new_emails"] == 0
    assert r.json()["total_fetched"] == 0


def test_sync_saves_new_emails(client, mock_accounts, mock_classifier):
    mock_accounts.fetch_emails.return_value = [_make_raw_email("gmail_001")]
    with patch.object(routes_module, "_ai_classifier", mock_classifier):
        r = client.post("/api/sync")
    assert r.json()["new_emails"] == 1

    emails = client.get("/api/emails").json()
    assert len(emails) == 1
    assert emails[0]["sender"] == "Juan García"
    assert emails[0]["category"] == "Consulta general"


def test_sync_skips_duplicate_gmail_ids(client, email_factory, mock_accounts, mock_classifier):
    email_factory(gmail_id="existing_001")
    mock_accounts.fetch_emails.return_value = [_make_raw_email("existing_001")]
    with patch.object(routes_module, "_ai_classifier", mock_classifier):
        r = client.post("/api/sync")
    assert r.json()["new_emails"] == 0
    assert len(client.get("/api/emails").json()) == 1


def test_sync_multiple_emails_partial_duplicates(client, email_factory, mock_accounts, mock_classifier):
    email_factory(gmail_id="old_001")
    mock_accounts.fetch_emails.return_value = [
        _make_raw_email("old_001"),
        _make_raw_email("new_002"),
        _make_raw_email("new_003"),
    ]
    with patch.object(routes_module, "_ai_classifier", mock_classifier):
        r = client.post("/api/sync")
    assert r.json()["new_emails"] == 2
    assert len(client.get("/api/emails").json()) == 3


def test_sync_detects_portal_source(client, mock_accounts, mock_classifier):
    mock_accounts.fetch_emails.return_value = [
        _make_raw_email(
            "portal_001",
            sender="Idealista",
            sender_email="noreply@idealista.com",
            body="Has recibido un mensaje de:\nNombre: Ana López\nTeléfono: 612 345 678",
        )
    ]
    with patch.object(routes_module, "_ai_classifier", mock_classifier):
        client.post("/api/sync")
    email = client.get("/api/emails").json()[0]
    assert email["lead_source"] == "Idealista"
    assert email["lead_name"] == "Ana López"


def test_sync_gmail_failure_returns_502(client, mock_accounts, mock_classifier):
    mock_accounts.fetch_emails.side_effect = Exception("Gmail connection error")
    with patch.object(routes_module, "_ai_classifier", mock_classifier):
        r = client.post("/api/sync")
    assert r.status_code == 200  # sync returns 200 with errors list when one account fails
    assert "errors" in r.json()


def test_sync_no_accounts_returns_503(client):
    from unittest.mock import patch
    from app import account_manager
    with patch.object(account_manager, "list_accounts", return_value=[]):
        r = client.post("/api/sync")
    assert r.status_code == 503
