"""
Tests for Google Calendar endpoints — Google API always mocked.
"""
from unittest.mock import patch, MagicMock


def _mock_calendar_client(slots=None, event=None):
    """Patch CalendarClient at the routes import level."""
    mock = MagicMock()
    mock.return_value.get_day_availability.return_value = slots or []
    mock.return_value.create_event.return_value = event or {
        "event_id": "evt_test",
        "html_link": "https://calendar.google.com/evt_test",
        "summary": "Visita",
        "start": "2026-04-10T10:00:00+02:00",
        "end":   "2026-04-10T11:00:00+02:00",
    }
    return mock


# ---------------------------------------------------------------------------
# GET /api/calendar/slots
# ---------------------------------------------------------------------------

def test_slots_invalid_date(client):
    r = client.get("/api/calendar/slots?date=not-a-date")
    assert r.status_code == 400


def test_slots_returns_all_statuses(client):
    sample_slots = [
        {"start": "2026-04-10T08:00:00+02:00", "end": "2026-04-10T09:00:00+02:00", "label": "08:00", "status": "free"},
        {"start": "2026-04-10T09:00:00+02:00", "end": "2026-04-10T10:00:00+02:00", "label": "09:00", "status": "partial"},
        {"start": "2026-04-10T10:00:00+02:00", "end": "2026-04-10T11:00:00+02:00", "label": "10:00", "status": "busy"},
    ]
    with patch("app.routes.CalendarClient", _mock_calendar_client(slots=sample_slots)):
        r = client.get("/api/calendar/slots?date=2026-04-10")

    assert r.status_code == 200
    data = r.json()
    assert data["date"] == "2026-04-10"
    statuses = {s["label"]: s["status"] for s in data["slots"]}
    assert statuses["08:00"] == "free"
    assert statuses["09:00"] == "partial"
    assert statuses["10:00"] == "busy"


def test_slots_passes_duration_param(client):
    with patch("app.routes.CalendarClient") as MockCal:
        MockCal.return_value.get_day_availability.return_value = []
        client.get("/api/calendar/slots?date=2026-04-10&duration=30")
        MockCal.return_value.get_day_availability.assert_called_once()
        _, kwargs = MockCal.return_value.get_day_availability.call_args
        assert kwargs.get("duration_minutes") == 30


def test_slots_empty_returns_empty_list(client):
    with patch("app.routes.CalendarClient", _mock_calendar_client(slots=[])):
        r = client.get("/api/calendar/slots?date=2026-04-10")
    assert r.status_code == 200
    assert r.json()["slots"] == []


# ---------------------------------------------------------------------------
# POST /api/emails/{id}/schedule
# ---------------------------------------------------------------------------

def test_schedule_creates_event(client, email_factory):
    e = email_factory(sender_email="cliente@example.com")
    with patch("app.routes.CalendarClient", _mock_calendar_client()):
        r = client.post(f"/api/emails/{e.id}/schedule", json={
            "start": "2026-04-10T10:00:00",
            "end":   "2026-04-10T11:00:00",
        })
    assert r.status_code == 200
    assert "html_link" in r.json()
    assert "event_id" in r.json()


def test_schedule_email_not_found(client):
    with patch("app.routes.CalendarClient", _mock_calendar_client()):
        r = client.post("/api/emails/99999/schedule", json={
            "start": "2026-04-10T10:00:00",
            "end":   "2026-04-10T11:00:00",
        })
    assert r.status_code == 404


def test_schedule_calendar_error_returns_502(client, email_factory):
    e = email_factory()
    mock = MagicMock()
    mock.return_value.create_event.side_effect = Exception("Google API down")
    with patch("app.routes.CalendarClient", mock):
        r = client.post(f"/api/emails/{e.id}/schedule", json={
            "start": "2026-04-10T10:00:00",
            "end":   "2026-04-10T11:00:00",
        })
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# Availability status logic (unit test — no HTTP)
# ---------------------------------------------------------------------------

def test_availability_partial_status():
    """Meeting 09:30–10:30 → slot 09:00–10:00 is partial, slot 10:00–11:00 is partial."""
    from datetime import date
    from unittest.mock import MagicMock, patch
    import yaml, io

    cfg = {"calendar": {
        "calendar_id": "primary", "timezone": "Europe/Madrid",
        "business_hours_start": "08:00", "business_hours_end": "21:00",
        "slot_duration_minutes": 60,
    }, "demo": {"enabled": False}}

    freebusy_response = {
        "calendars": {
            "primary": {
                "busy": [{"start": "2026-04-10T07:30:00Z", "end": "2026-04-10T08:30:00Z"}]
                # 07:30–08:30 UTC = 09:30–10:30 Europe/Madrid (UTC+2)
            }
        }
    }

    with patch("builtins.open", return_value=io.StringIO(yaml.dump(cfg))):
        from app import calendar_client as mod
        import importlib
        importlib.reload(mod)
        cc = mod.CalendarClient()

    mock_service = MagicMock()
    mock_service.freebusy.return_value.query.return_value.execute.return_value = freebusy_response
    cc._service = mock_service

    slots = cc.get_day_availability(date(2026, 4, 10))
    by_label = {s["label"]: s["status"] for s in slots}

    assert by_label.get("09:00") == "partial"   # overlaps 09:30–10:00
    assert by_label.get("10:00") == "partial"   # overlaps 10:00–10:30
    assert by_label.get("08:00") == "free"      # no overlap
    assert by_label.get("11:00") == "free"      # after meeting


def test_availability_busy_status():
    """Meeting covers full slot → status must be 'busy'."""
    from datetime import date
    import yaml, io
    from unittest.mock import MagicMock, patch

    cfg = {"calendar": {
        "calendar_id": "primary", "timezone": "Europe/Madrid",
        "business_hours_start": "08:00", "business_hours_end": "21:00",
        "slot_duration_minutes": 60,
    }, "demo": {"enabled": False}}

    freebusy_response = {
        "calendars": {
            "primary": {
                "busy": [{"start": "2026-04-10T08:00:00Z", "end": "2026-04-10T09:00:00Z"}]
                # 08:00–09:00 UTC = 10:00–11:00 Europe/Madrid (UTC+2)
            }
        }
    }

    with patch("builtins.open", return_value=io.StringIO(yaml.dump(cfg))):
        from app import calendar_client as mod
        import importlib
        importlib.reload(mod)
        cc = mod.CalendarClient()

    mock_service = MagicMock()
    mock_service.freebusy.return_value.query.return_value.execute.return_value = freebusy_response
    cc._service = mock_service

    slots = cc.get_day_availability(date(2026, 4, 10))
    by_label = {s["label"]: s["status"] for s in slots}

    assert by_label.get("10:00") == "busy"
