"""
Tests for the snooze feature:
- POST /api/emails/{id}/snooze
- POST /api/emails/{id}/unsnooze
- GET /api/emails excludes snoozed by default
- GET /api/emails?snoozed=true returns only snoozed
- GET /api/stats includes snoozed count
- POST /api/sync wakes up expired snoozes
"""
import datetime
import uuid
import pytest
from unittest.mock import patch

import app.routes as routes_module


# ---------------------------------------------------------------------------
# POST /api/emails/{id}/snooze
# ---------------------------------------------------------------------------

class TestSnoozeEmail:
    def test_snooze_sets_snoozed_until(self, client, email_factory):
        email = email_factory()
        future = (datetime.datetime.utcnow() + datetime.timedelta(hours=2)).isoformat()

        r = client.post(
            f"/api/emails/{email.id}/snooze",
            json={"until": future},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["snoozed_until"] is not None

    def test_snooze_past_date_returns_400(self, client, email_factory):
        email = email_factory()
        past = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat()

        r = client.post(
            f"/api/emails/{email.id}/snooze",
            json={"until": past},
        )
        assert r.status_code == 400

    def test_snooze_invalid_format_returns_400(self, client, email_factory):
        email = email_factory()
        r = client.post(
            f"/api/emails/{email.id}/snooze",
            json={"until": "not-a-date"},
        )
        assert r.status_code == 400

    def test_snooze_nonexistent_email_returns_404(self, client):
        future = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat()
        r = client.post("/api/emails/99999/snooze", json={"until": future})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/emails/{id}/unsnooze
# ---------------------------------------------------------------------------

class TestUnsnoozeEmail:
    def test_unsnooze_clears_snoozed_until(self, client, db, email_factory):
        email = email_factory()
        email.snoozed_until = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
        db.commit()

        r = client.post(f"/api/emails/{email.id}/unsnooze")
        assert r.status_code == 200
        assert r.json()["snoozed_until"] is None

    def test_unsnooze_nonexistent_returns_404(self, client):
        r = client.post("/api/emails/99999/unsnooze")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/emails — snoozed filtering
# ---------------------------------------------------------------------------

class TestListEmailsSnoozeFilter:
    def test_snoozed_emails_excluded_from_inbox(self, client, db, email_factory):
        email_factory(subject="Visible")
        snoozed = email_factory(subject="Hidden")
        snoozed.snoozed_until = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
        db.commit()

        r = client.get("/api/emails")
        assert r.status_code == 200
        subjects = [e["subject"] for e in r.json()]
        assert "Visible" in subjects
        assert "Hidden" not in subjects

    def test_snoozed_true_returns_only_snoozed(self, client, db, email_factory):
        email_factory(subject="Normal")
        snoozed = email_factory(subject="Snoozed one")
        snoozed.snoozed_until = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
        db.commit()

        r = client.get("/api/emails?snoozed=true")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["subject"] == "Snoozed one"

    def test_expired_snooze_appears_in_inbox(self, client, db, email_factory):
        email = email_factory(subject="Expired snooze")
        # Snooze expired in the past
        email.snoozed_until = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        db.commit()

        r = client.get("/api/emails")
        assert r.status_code == 200
        subjects = [e["subject"] for e in r.json()]
        assert "Expired snooze" in subjects

    def test_expired_snooze_not_in_snoozed_list(self, client, db, email_factory):
        email = email_factory(subject="Was snoozed")
        email.snoozed_until = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
        db.commit()

        r = client.get("/api/emails?snoozed=true")
        assert r.status_code == 200
        assert r.json() == []


# ---------------------------------------------------------------------------
# GET /api/stats — includes snoozed count
# ---------------------------------------------------------------------------

class TestStatsIncludesSnoozed:
    def test_stats_snoozed_count(self, client, db, email_factory):
        email_factory()
        snoozed = email_factory()
        snoozed.snoozed_until = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        db.commit()

        r = client.get("/api/stats")
        assert r.status_code == 200
        assert r.json()["snoozed"] == 1


# ---------------------------------------------------------------------------
# POST /api/sync — wakes up expired snoozes
# ---------------------------------------------------------------------------

class TestSyncWakesUpSnooze:
    def test_sync_wakes_expired_snooze(self, client, db, email_factory, mock_accounts, mock_classifier):
        email = email_factory()
        email.snoozed_until = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
        db.commit()

        with patch.object(routes_module, "_ai_classifier", mock_classifier):
            r = client.post("/api/sync")

        assert r.status_code == 200
        db.refresh(email)
        assert email.snoozed_until is None

    def test_sync_does_not_wake_future_snooze(self, client, db, email_factory, mock_accounts, mock_classifier):
        email = email_factory()
        future = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
        email.snoozed_until = future
        db.commit()

        with patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        db.refresh(email)
        assert email.snoozed_until is not None
