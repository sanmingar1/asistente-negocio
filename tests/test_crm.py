"""
Tests for the CRM contacts feature:
- POST /api/contacts          (create)
- PATCH /api/contacts/{email} (update name/phone)
- DELETE /api/contacts/{email} (delete contact)
- GET /api/contacts
- GET /api/contacts/{email}
- PUT /api/contacts/{email}/stage
- POST /api/contacts/{email}/notes
- DELETE /api/contacts/{email}/notes/{id}
- Contact auto-upsert during sync
"""
import uuid
import pytest
from unittest.mock import MagicMock, patch

from app.models import Contact, ContactNote
import app.routes as routes_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_contact(db, email="alice@example.com", name="Alice", phone=None,
                 lead_source=None, pipeline_stage="lead"):
    c = Contact(email=email, name=name, phone=phone,
                lead_source=lead_source, pipeline_stage=pipeline_stage)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# GET /api/contacts
# ---------------------------------------------------------------------------

class TestListContacts:
    def test_empty_returns_list(self, client):
        r = client.get("/api/contacts")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_contact_with_email_count(self, client, db, email_factory):
        make_contact(db, email="bob@example.com", name="Bob")
        email_factory(sender_email="bob@example.com")
        email_factory(sender_email="bob@example.com")

        r = client.get("/api/contacts")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["email"] == "bob@example.com"
        assert data[0]["name"] == "Bob"
        assert data[0]["email_count"] == 2

    def test_last_contact_is_most_recent_email(self, client, db, email_factory):
        from datetime import datetime
        make_contact(db, email="carol@example.com")
        email_factory(sender_email="carol@example.com",
                      received_at=datetime(2024, 1, 1))
        email_factory(sender_email="carol@example.com",
                      received_at=datetime(2024, 6, 15))

        r = client.get("/api/contacts")
        assert r.status_code == 200
        assert "2024-06-15" in r.json()[0]["last_contact"]

    def test_multiple_contacts(self, client, db):
        make_contact(db, email="a@example.com")
        make_contact(db, email="b@example.com")
        r = client.get("/api/contacts")
        assert r.status_code == 200
        assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# GET /api/contacts/{email}
# ---------------------------------------------------------------------------

class TestGetContact:
    def test_returns_404_for_unknown(self, client):
        r = client.get("/api/contacts/unknown%40example.com")
        assert r.status_code == 404

    def test_returns_contact_with_emails_and_notes(self, client, db, email_factory):
        make_contact(db, email="dave@example.com", name="Dave")
        email_factory(sender_email="dave@example.com", subject="Hola")
        note = ContactNote(contact_email="dave@example.com", body="Nota de prueba")
        db.add(note)
        db.commit()

        r = client.get("/api/contacts/dave%40example.com")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Dave"
        assert len(data["emails"]) == 1
        assert data["emails"][0]["subject"] == "Hola"
        assert len(data["notes"]) == 1
        assert data["notes"][0]["body"] == "Nota de prueba"

    def test_emails_ordered_newest_first(self, client, db, email_factory):
        from datetime import datetime
        make_contact(db, email="eve@example.com")
        email_factory(sender_email="eve@example.com",
                      subject="Primero", received_at=datetime(2024, 1, 1))
        email_factory(sender_email="eve@example.com",
                      subject="Último", received_at=datetime(2024, 12, 31))

        r = client.get("/api/contacts/eve%40example.com")
        assert r.status_code == 200
        emails = r.json()["emails"]
        assert emails[0]["subject"] == "Último"
        assert emails[1]["subject"] == "Primero"


# ---------------------------------------------------------------------------
# PUT /api/contacts/{email}/stage
# ---------------------------------------------------------------------------

class TestUpdateStage:
    def test_valid_stage_update(self, client, db):
        make_contact(db, email="frank@example.com", pipeline_stage="lead")
        r = client.put(
            "/api/contacts/frank%40example.com/stage",
            json={"stage": "visita"},
        )
        assert r.status_code == 200
        assert r.json()["pipeline_stage"] == "visita"

    def test_all_valid_stages(self, client, db):
        for stage in ["lead", "visita", "oferta", "cerrado", "descartado"]:
            make_contact(db, email=f"test_{stage}@example.com", pipeline_stage="lead")
            r = client.put(
                f"/api/contacts/test_{stage}%40example.com/stage",
                json={"stage": stage},
            )
            assert r.status_code == 200

    def test_invalid_stage_returns_400(self, client, db):
        make_contact(db, email="grace@example.com")
        r = client.put(
            "/api/contacts/grace%40example.com/stage",
            json={"stage": "invalido"},
        )
        assert r.status_code == 400

    def test_unknown_contact_returns_404(self, client):
        r = client.put(
            "/api/contacts/nobody%40example.com/stage",
            json={"stage": "visita"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/contacts/{email}/notes
# ---------------------------------------------------------------------------

class TestAddNote:
    def test_add_note(self, client, db):
        make_contact(db, email="henry@example.com")
        r = client.post(
            "/api/contacts/henry%40example.com/notes",
            json={"body": "Muy interesado en el ático"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["body"] == "Muy interesado en el ático"
        assert data["contact_email"] == "henry@example.com"
        assert "id" in data

    def test_empty_note_returns_400(self, client, db):
        make_contact(db, email="iris@example.com")
        r = client.post(
            "/api/contacts/iris%40example.com/notes",
            json={"body": "   "},
        )
        assert r.status_code == 400

    def test_unknown_contact_returns_404(self, client):
        r = client.post(
            "/api/contacts/nobody%40example.com/notes",
            json={"body": "Nota"},
        )
        assert r.status_code == 404

    def test_multiple_notes_appear_in_profile(self, client, db):
        make_contact(db, email="jack@example.com")
        client.post("/api/contacts/jack%40example.com/notes", json={"body": "Nota 1"})
        client.post("/api/contacts/jack%40example.com/notes", json={"body": "Nota 2"})

        r = client.get("/api/contacts/jack%40example.com")
        assert len(r.json()["notes"]) == 2


# ---------------------------------------------------------------------------
# DELETE /api/contacts/{email}/notes/{id}
# ---------------------------------------------------------------------------

class TestDeleteNote:
    def test_delete_note(self, client, db):
        make_contact(db, email="kate@example.com")
        note = ContactNote(contact_email="kate@example.com", body="Borrar esto")
        db.add(note)
        db.commit()
        db.refresh(note)

        r = client.delete(f"/api/contacts/kate%40example.com/notes/{note.id}")
        assert r.status_code == 200
        assert r.json()["deleted"] == note.id

        # Verify it's gone
        r2 = client.get("/api/contacts/kate%40example.com")
        assert r2.json()["notes"] == []

    def test_delete_wrong_contact_returns_404(self, client, db):
        make_contact(db, email="liam@example.com")
        make_contact(db, email="other@example.com")
        note = ContactNote(contact_email="other@example.com", body="Not yours")
        db.add(note)
        db.commit()
        db.refresh(note)

        # Try to delete note using liam's URL
        r = client.delete(f"/api/contacts/liam%40example.com/notes/{note.id}")
        assert r.status_code == 404

    def test_delete_nonexistent_note_returns_404(self, client, db):
        make_contact(db, email="mia@example.com")
        r = client.delete("/api/contacts/mia%40example.com/notes/99999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/contacts/{email} — delete contact
# ---------------------------------------------------------------------------

class TestDeleteContact:
    def test_delete_contact(self, client, db):
        make_contact(db, email="del@example.com")
        r = client.delete("/api/contacts/del%40example.com")
        assert r.status_code == 200
        assert r.json()["deleted"] == "del@example.com"
        # Verify gone
        r2 = client.get("/api/contacts/del%40example.com")
        assert r2.status_code == 404

    def test_delete_also_removes_notes(self, client, db):
        make_contact(db, email="dnotes@example.com")
        note = ContactNote(contact_email="dnotes@example.com", body="Nota")
        db.add(note); db.commit(); db.refresh(note)
        client.delete("/api/contacts/dnotes%40example.com")
        assert db.query(ContactNote).filter(ContactNote.contact_email == "dnotes@example.com").count() == 0

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/contacts/noexiste%40example.com")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/contacts — create manually
# ---------------------------------------------------------------------------

class TestCreateContact:
    def test_create_contact(self, client):
        r = client.post("/api/contacts", json={"email": "nuevo@example.com", "name": "Nuevo"})
        assert r.status_code == 200
        assert r.json()["email"] == "nuevo@example.com"
        assert r.json()["pipeline_stage"] == "lead"

    def test_create_with_name_and_phone(self, client):
        r = client.post("/api/contacts", json={"email": "full@example.com", "name": "Ana", "phone": "600111222"})
        assert r.status_code == 200
        assert r.json()["name"] == "Ana"
        assert r.json()["phone"] == "600111222"

    def test_create_invalid_email_returns_400(self, client):
        r = client.post("/api/contacts", json={"email": "noesunemail"})
        assert r.status_code == 400

    def test_create_empty_email_returns_400(self, client):
        r = client.post("/api/contacts", json={"email": ""})
        assert r.status_code == 400

    def test_create_duplicate_returns_409(self, client, db):
        make_contact(db, email="dup@example.com")
        r = client.post("/api/contacts", json={"email": "dup@example.com"})
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# PATCH /api/contacts/{email} — update name / phone
# ---------------------------------------------------------------------------

class TestUpdateContact:
    def test_update_name(self, client, db):
        make_contact(db, email="upd@example.com", name="Old Name")
        r = client.patch("/api/contacts/upd%40example.com", json={"name": "New Name"})
        assert r.status_code == 200
        assert r.json()["name"] == "New Name"

    def test_update_phone(self, client, db):
        make_contact(db, email="phone@example.com", phone=None)
        r = client.patch("/api/contacts/phone%40example.com", json={"phone": "611222333"})
        assert r.status_code == 200
        assert r.json()["phone"] == "611222333"

    def test_update_clears_field_with_empty_string(self, client, db):
        make_contact(db, email="clear@example.com", name="Has Name")
        r = client.patch("/api/contacts/clear%40example.com", json={"name": ""})
        assert r.status_code == 200
        assert r.json()["name"] is None

    def test_update_unknown_contact_returns_404(self, client):
        r = client.patch("/api/contacts/nobody%40example.com", json={"name": "X"})
        assert r.status_code == 404

    def test_partial_update_keeps_other_fields(self, client, db):
        make_contact(db, email="partial@example.com", name="Keep", phone="999")
        r = client.patch("/api/contacts/partial%40example.com", json={"name": "Changed"})
        assert r.status_code == 200
        assert r.json()["phone"] == "999"  # unchanged


# ---------------------------------------------------------------------------
# Contact auto-upsert during sync
# ---------------------------------------------------------------------------

class TestContactUpsert:
    def test_sync_creates_contact(self, client, db, mock_classifier, mock_accounts):
        mock_accounts.fetch_emails.return_value = [{
            "gmail_id": str(uuid.uuid4()),
            "thread_id": "thread1",
            "sender": "Nina López",
            "sender_email": "nina@example.com",
            "subject": "Consulta piso",
            "body_preview": "Hola, me interesa el piso.",
            "body_full": "Hola, me interesa el piso.",
            "received_at": None,
            "raw_labels": "[]",
        }]

        with patch.object(routes_module, "_ai_classifier", mock_classifier):
            r = client.post("/api/sync")

        assert r.status_code == 200
        contact = db.query(Contact).filter(Contact.email == "nina@example.com").first()
        assert contact is not None
        assert contact.name == "Nina López"
        assert contact.pipeline_stage == "lead"

    def test_sync_updates_existing_contact_with_new_data(self, client, db, mock_classifier, mock_accounts):
        # Contact exists but without phone
        c = Contact(email="oscar@example.com", name="Oscar", phone=None)
        db.add(c)
        db.commit()

        mock_classifier.classify_email.return_value = {
            "category": "Solicitud de visita",
            "priority": "alta",
            "color": "orange",
            "summary": "Quiere visitar.",
            "lead_score": 7,
        }
        mock_accounts.fetch_emails.return_value = [{
            "gmail_id": str(uuid.uuid4()),
            "thread_id": "t2",
            "sender": "Oscar",
            "sender_email": "oscar@example.com",
            "subject": "Visita",
            "body_preview": "Quiero visitar.",
            "body_full": "Quiero visitar.",
            "received_at": None,
            "raw_labels": "[]",
        }]

        with patch("app.portal_parser.detect_source", return_value="Idealista"), \
             patch("app.portal_parser.extract_lead_data", return_value={"phone": "600123456"}), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        db.refresh(c)
        assert c.phone == "600123456"
        assert c.lead_source == "Idealista"

    def test_sync_does_not_overwrite_existing_contact_data(self, client, db, mock_classifier, mock_accounts):
        # Contact already has a phone — sync should NOT overwrite it
        c = Contact(email="paula@example.com", name="Paula", phone="611222333")
        db.add(c)
        db.commit()

        mock_accounts.fetch_emails.return_value = [{
            "gmail_id": str(uuid.uuid4()),
            "thread_id": "t3",
            "sender": "Paula",
            "sender_email": "paula@example.com",
            "subject": "Otra consulta",
            "body_preview": "Texto",
            "body_full": "Texto",
            "received_at": None,
            "raw_labels": "[]",
        }]

        with patch("app.portal_parser.detect_source", return_value="Idealista"), \
             patch("app.portal_parser.extract_lead_data", return_value={"phone": "999999999"}), \
             patch.object(routes_module, "_ai_classifier", mock_classifier):
            client.post("/api/sync")

        db.refresh(c)
        assert c.phone == "611222333"  # original preserved
