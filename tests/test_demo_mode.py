"""
Tests for demo mode restrictions:
- Email replies must be blocked (HTTP 403)
- Calendar invitations must NOT be sent (sendUpdates="none")
"""
from unittest.mock import patch, MagicMock


DEMO_CONFIG = {
    "demo": {"enabled": True},
    "categories": [
        {"name": "Consulta general", "priority": "media", "color": "green", "description": ""},
    ],
    "business": {"name": "Test"},
    "email_provider": {"sync_interval_minutes": 5},
}

LIVE_CONFIG = {**DEMO_CONFIG, "demo": {"enabled": False}}


# ---------------------------------------------------------------------------
# Reply blocking
# ---------------------------------------------------------------------------

def test_reply_blocked_in_demo_mode(client, email_factory, monkeypatch):
    monkeypatch.setattr("app.routes._load_config", lambda: DEMO_CONFIG)
    e = email_factory()
    r = client.post(f"/api/emails/{e.id}/reply", json={"body": "Hola, gracias."})
    assert r.status_code == 403
    assert "demo" in r.json()["detail"].lower()


def test_reply_allowed_when_demo_off(client, email_factory, mock_gmail, monkeypatch):
    monkeypatch.setattr("app.routes._load_config", lambda: LIVE_CONFIG)
    monkeypatch.setattr("app.routes.get_gmail_client", lambda: mock_gmail)
    e = email_factory()
    r = client.post(f"/api/emails/{e.id}/reply", json={"body": "Hola, gracias."})
    assert r.status_code == 200
    assert r.json()["is_replied"] is True


def test_reply_with_empty_body_blocked_regardless_of_demo(client, email_factory, monkeypatch):
    monkeypatch.setattr("app.routes._load_config", lambda: LIVE_CONFIG)
    e = email_factory()
    r = client.post(f"/api/emails/{e.id}/reply", json={"body": "  "})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Calendar invitation suppression
# ---------------------------------------------------------------------------

def test_calendar_no_invitations_in_demo_mode():
    """CalendarClient must use sendUpdates='none' when demo is enabled."""
    with patch("app.calendar_client.CalendarClient._get_service") as mock_svc:
        mock_events = MagicMock()
        mock_svc.return_value.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt_001",
            "htmlLink": "https://calendar.google.com/evt_001",
            "summary": "Visita",
            "start": {"dateTime": "2026-04-10T10:00:00+02:00"},
            "end":   {"dateTime": "2026-04-10T11:00:00+02:00"},
        }

        import yaml, io
        demo_config = {"demo": {"enabled": True}, "calendar": {
            "calendar_id": "primary", "timezone": "Europe/Madrid",
            "business_hours_start": "08:00", "business_hours_end": "21:00",
            "slot_duration_minutes": 60,
        }}

        with patch("builtins.open", return_value=io.StringIO(yaml.dump(demo_config))):
            from app import calendar_client as mod
            import importlib
            importlib.reload(mod)
            client_instance = mod.CalendarClient()
            client_instance._service = mock_svc.return_value

        client_instance.create_event(
            summary="Visita",
            attendee_email="cliente@example.com",
            start_iso="2026-04-10T10:00:00+02:00",
            end_iso="2026-04-10T11:00:00+02:00",
        )

        call_kwargs = mock_svc.return_value.events.return_value.insert.call_args.kwargs
        assert call_kwargs.get("sendUpdates") == "none"


def test_calendar_sends_invitations_in_live_mode():
    """In live mode, sendUpdates must be 'all'."""
    with patch("app.calendar_client.CalendarClient._get_service") as mock_svc:
        mock_svc.return_value.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt_002",
            "htmlLink": "https://calendar.google.com/evt_002",
            "summary": "Visita",
            "start": {"dateTime": "2026-04-10T10:00:00+02:00"},
            "end":   {"dateTime": "2026-04-10T11:00:00+02:00"},
        }

        import yaml, io
        live_config = {"demo": {"enabled": False}, "calendar": {
            "calendar_id": "primary", "timezone": "Europe/Madrid",
            "business_hours_start": "08:00", "business_hours_end": "21:00",
            "slot_duration_minutes": 60,
        }}

        with patch("builtins.open", return_value=io.StringIO(yaml.dump(live_config))):
            from app import calendar_client as mod
            import importlib
            importlib.reload(mod)
            client_instance = mod.CalendarClient()
            client_instance._service = mock_svc.return_value

        client_instance.create_event(
            summary="Visita",
            attendee_email="cliente@example.com",
            start_iso="2026-04-10T10:00:00+02:00",
            end_iso="2026-04-10T11:00:00+02:00",
        )

        call_kwargs = mock_svc.return_value.events.return_value.insert.call_args.kwargs
        assert call_kwargs.get("sendUpdates") == "all"
