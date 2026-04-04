"""
Tests for email CRUD endpoints, filters and business logic.
"""


# ---------------------------------------------------------------------------
# List / filters
# ---------------------------------------------------------------------------

def test_list_emails_empty(client):
    r = client.get("/api/emails")
    assert r.status_code == 200
    assert r.json() == []


def test_list_excludes_archived_by_default(client, email_factory):
    email_factory(subject="Activo")
    email_factory(subject="Archivado", is_archived=True)
    data = client.get("/api/emails").json()
    assert len(data) == 1
    assert data[0]["subject"] == "Activo"


def test_list_archived_filter(client, email_factory):
    email_factory(subject="Activo")
    email_factory(subject="Archivado", is_archived=True)
    data = client.get("/api/emails?archived=true").json()
    assert len(data) == 1
    assert data[0]["subject"] == "Archivado"


def test_list_filter_by_priority(client, email_factory):
    email_factory(priority="urgente")
    email_factory(priority="baja")
    data = client.get("/api/emails?priority=urgente").json()
    assert len(data) == 1
    assert data[0]["priority"] == "urgente"


def test_list_filter_by_category(client, email_factory):
    email_factory(category="Oferta de compra")
    email_factory(category="Spam / irrelevante")
    data = client.get("/api/emails?category=Oferta de compra").json()
    assert len(data) == 1
    assert data[0]["category"] == "Oferta de compra"


def test_list_filter_by_source(client, email_factory):
    email_factory(lead_source="Idealista")
    email_factory(lead_source="Fotocasa")
    email_factory(lead_source=None)
    data = client.get("/api/emails?source=Idealista").json()
    assert len(data) == 1
    assert data[0]["lead_source"] == "Idealista"


def test_list_filter_needs_followup(client, email_factory):
    email_factory(priority="urgente", is_replied=False)   # ✓ followup
    email_factory(priority="alta",    is_replied=False)   # ✓ followup
    email_factory(priority="alta",    is_replied=True)    # ✗ already replied
    email_factory(priority="media",   is_replied=False)   # ✗ priority too low
    data = client.get("/api/emails?needs_followup=true").json()
    assert len(data) == 2
    assert all(e["priority"] in ("urgente", "alta") for e in data)
    assert all(not e["is_replied"] for e in data)


# ---------------------------------------------------------------------------
# needs_followup computed field
# ---------------------------------------------------------------------------

def test_needs_followup_true_for_high_priority_unreplied(client, email_factory):
    for priority in ("urgente", "alta"):
        e = email_factory(priority=priority, is_replied=False, is_archived=False)
        r = client.get(f"/api/emails/{e.id}")
        assert r.json()["needs_followup"] is True, f"Expected True for priority={priority}"


def test_needs_followup_false_when_replied(client, email_factory):
    e = email_factory(priority="urgente", is_replied=True)
    assert client.get(f"/api/emails/{e.id}").json()["needs_followup"] is False


def test_needs_followup_false_for_low_priority(client, email_factory):
    for priority in ("media", "baja"):
        e = email_factory(priority=priority, is_replied=False)
        assert client.get(f"/api/emails/{e.id}").json()["needs_followup"] is False


def test_needs_followup_false_when_archived(client, email_factory):
    # Archived emails are fetched with ?archived=true
    e = email_factory(priority="urgente", is_archived=True)
    r = client.get(f"/api/emails/{e.id}")
    assert r.json()["needs_followup"] is False


# ---------------------------------------------------------------------------
# Detail / read tracking
# ---------------------------------------------------------------------------

def test_get_email_marks_as_read(client, email_factory):
    e = email_factory(is_read=False)
    r = client.get(f"/api/emails/{e.id}")
    assert r.status_code == 200
    assert r.json()["is_read"] is True


def test_get_email_not_found(client):
    assert client.get("/api/emails/99999").status_code == 404


# ---------------------------------------------------------------------------
# Archive / restore
# ---------------------------------------------------------------------------

def test_archive_toggles_status(client, email_factory):
    e = email_factory(is_archived=False)
    r = client.post(f"/api/emails/{e.id}/archive")
    assert r.status_code == 200
    assert r.json()["is_archived"] is True

    r = client.post(f"/api/emails/{e.id}/archive")
    assert r.json()["is_archived"] is False


def test_archive_not_found(client):
    assert client.post("/api/emails/99999/archive").status_code == 404


# ---------------------------------------------------------------------------
# Manual classification
# ---------------------------------------------------------------------------

def test_manual_classify_updates_email(client, email_factory):
    e = email_factory(category="Consulta general", priority="media")
    r = client.put(
        f"/api/emails/{e.id}/classify",
        json={"category": "Oferta de compra", "priority": "urgente"},
    )
    assert r.status_code == 200
    assert r.json()["category"] == "Oferta de compra"
    assert r.json()["priority"] == "urgente"


def test_manual_classify_rejects_unknown_category(client, email_factory):
    e = email_factory()
    r = client.put(
        f"/api/emails/{e.id}/classify",
        json={"category": "Categoria Inventada", "priority": "media"},
    )
    assert r.status_code == 400


def test_manual_classify_rejects_invalid_priority(client, email_factory):
    e = email_factory()
    r = client.put(
        f"/api/emails/{e.id}/classify",
        json={"category": "Consulta general", "priority": "super_urgente"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Thread
# ---------------------------------------------------------------------------

def test_thread_no_thread_id_returns_empty(client, email_factory):
    e = email_factory(thread_id=None)
    r = client.get(f"/api/emails/{e.id}/thread")
    assert r.status_code == 200
    assert r.json() == []


def test_thread_returns_others_in_same_thread(client, email_factory):
    e1 = email_factory(thread_id="thread_abc", subject="Mensaje 1")
    e2 = email_factory(thread_id="thread_abc", subject="Respuesta")
    email_factory(thread_id="thread_xyz", subject="Otro hilo")

    r = client.get(f"/api/emails/{e1.id}/thread")
    assert r.status_code == 200
    subjects = [e["subject"] for e in r.json()]
    assert "Respuesta" in subjects
    assert "Mensaje 1" not in subjects     # self excluded
    assert "Otro hilo" not in subjects     # different thread


def test_thread_summary_single_email_returns_none(client, email_factory):
    e = email_factory(thread_id=None)
    r = client.post(f"/api/emails/{e.id}/thread-summary")
    assert r.status_code == 200
    assert r.json()["summary"] is None


# ---------------------------------------------------------------------------
# AI endpoints (mocked)
# ---------------------------------------------------------------------------

def test_reclassify_updates_fields(client, email_factory, mock_classifier, monkeypatch):
    monkeypatch.setattr("app.routes.get_ai_classifier", lambda: mock_classifier)
    e = email_factory(category="Spam / irrelevante", priority="baja")
    r = client.post(f"/api/emails/{e.id}/reclassify")
    assert r.status_code == 200
    assert r.json()["category"] == "Consulta general"
    assert r.json()["priority"] == "media"


def test_draft_reply_returns_text(client, email_factory, mock_classifier, monkeypatch):
    monkeypatch.setattr("app.routes.get_ai_classifier", lambda: mock_classifier)
    e = email_factory()
    r = client.post(f"/api/emails/{e.id}/draft")
    assert r.status_code == 200
    assert "draft" in r.json()
    assert len(r.json()["draft"]) > 0


# ---------------------------------------------------------------------------
# Settings / categories
# ---------------------------------------------------------------------------

def test_get_categories_returns_list(client):
    r = client.get("/api/categories")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) > 0


def test_get_settings_returns_required_keys(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "sync_interval_minutes" in data
    assert "business_name" in data
    assert "demo_mode" in data
