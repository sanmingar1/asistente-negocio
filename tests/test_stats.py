"""
Tests for /api/stats — counts must always match the actual DB state.
"""


def test_stats_empty_db(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["unread"] == 0
    assert data["archived"] == 0
    assert data["followup"] == 0
    assert data["by_category"] == []
    assert data["by_priority"] == []


def test_stats_total_excludes_archived(client, email_factory):
    email_factory()
    email_factory()
    email_factory(is_archived=True)

    data = client.get("/api/stats").json()
    assert data["total"] == 2
    assert data["archived"] == 1


def test_stats_unread_count(client, email_factory):
    email_factory(is_read=False)
    email_factory(is_read=False)
    email_factory(is_read=True)

    data = client.get("/api/stats").json()
    assert data["unread"] == 2


def test_stats_followup_count(client, email_factory):
    email_factory(priority="urgente", is_replied=False)   # ✓
    email_factory(priority="alta",    is_replied=False)   # ✓
    email_factory(priority="alta",    is_replied=True)    # ✗ replied
    email_factory(priority="media",   is_replied=False)   # ✗ priority
    email_factory(priority="urgente", is_archived=True)   # ✗ archived

    data = client.get("/api/stats").json()
    assert data["followup"] == 2


def test_stats_by_category(client, email_factory):
    email_factory(category="Oferta de compra",  color="red")
    email_factory(category="Oferta de compra",  color="red")
    email_factory(category="Spam / irrelevante", color="gray")

    by_cat = {c["category"]: c["count"] for c in client.get("/api/stats").json()["by_category"]}
    assert by_cat["Oferta de compra"] == 2
    assert by_cat["Spam / irrelevante"] == 1


def test_stats_by_priority_sorted(client, email_factory):
    email_factory(priority="baja")
    email_factory(priority="urgente")
    email_factory(priority="urgente")

    by_pri = client.get("/api/stats").json()["by_priority"]
    # urgente must come before baja
    priorities = [p["priority"] for p in by_pri]
    assert priorities.index("urgente") < priorities.index("baja")


def test_stats_by_source(client, email_factory):
    email_factory(lead_source="Idealista")
    email_factory(lead_source="Idealista")
    email_factory(lead_source="Fotocasa")
    email_factory(lead_source=None)   # should not appear in by_source

    by_src = {s["source"]: s["count"] for s in client.get("/api/stats").json()["by_source"]}
    assert by_src["Idealista"] == 2
    assert by_src["Fotocasa"] == 1
    assert None not in by_src
