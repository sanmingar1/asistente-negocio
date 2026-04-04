"""
Tests for bulk email actions:
- POST /api/emails/bulk/archive
- POST /api/emails/bulk/read
"""
import pytest


class TestBulkArchive:
    def test_archives_multiple_emails(self, client, email_factory):
        e1 = email_factory(subject="Uno")
        e2 = email_factory(subject="Dos")
        e3 = email_factory(subject="Tres")

        r = client.post("/api/emails/bulk/archive", json={"ids": [e1.id, e2.id]})
        assert r.status_code == 200
        assert r.json()["archived"] == 2

        # e1 and e2 archived, e3 not
        inbox = client.get("/api/emails").json()
        inbox_ids = {e["id"] for e in inbox}
        assert e1.id not in inbox_ids
        assert e2.id not in inbox_ids
        assert e3.id in inbox_ids

    def test_archived_appear_in_archived_view(self, client, email_factory):
        e = email_factory()
        client.post("/api/emails/bulk/archive", json={"ids": [e.id]})

        archived = client.get("/api/emails?archived=true").json()
        assert any(x["id"] == e.id for x in archived)

    def test_empty_ids_returns_400(self, client):
        r = client.post("/api/emails/bulk/archive", json={"ids": []})
        assert r.status_code == 400

    def test_nonexistent_ids_archived_zero(self, client):
        r = client.post("/api/emails/bulk/archive", json={"ids": [99999]})
        assert r.status_code == 200
        assert r.json()["archived"] == 0

    def test_partial_ids_only_affects_existing(self, client, email_factory):
        e = email_factory()
        r = client.post("/api/emails/bulk/archive", json={"ids": [e.id, 99999]})
        assert r.status_code == 200
        assert r.json()["archived"] == 1


class TestBulkMarkRead:
    def test_marks_multiple_as_read(self, client, email_factory, db):
        e1 = email_factory(is_read=False)
        e2 = email_factory(is_read=False)

        r = client.post("/api/emails/bulk/read", json={"ids": [e1.id, e2.id]})
        assert r.status_code == 200
        assert r.json()["read"] == 2

        db.refresh(e1)
        db.refresh(e2)
        assert e1.is_read is True
        assert e2.is_read is True

    def test_already_read_still_counted(self, client, email_factory):
        e = email_factory(is_read=True)
        r = client.post("/api/emails/bulk/read", json={"ids": [e.id]})
        assert r.status_code == 200
        assert r.json()["read"] == 1

    def test_empty_ids_returns_400(self, client):
        r = client.post("/api/emails/bulk/read", json={"ids": []})
        assert r.status_code == 400

    def test_does_not_affect_other_emails(self, client, email_factory, db):
        e1 = email_factory(is_read=False)
        e2 = email_factory(is_read=False)

        client.post("/api/emails/bulk/read", json={"ids": [e1.id]})

        db.refresh(e2)
        assert e2.is_read is False
