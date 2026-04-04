import logging
from datetime import datetime, date, timedelta, time as time_type
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

import yaml
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

DEFAULT_SLOT_MINUTES = 60
DEFAULT_START = "09:00"
DEFAULT_END = "19:00"
DEFAULT_CAL_ID = "primary"


class CalendarClient:
    def __init__(self):
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self._cfg = config.get("calendar", {})
        self._demo = config.get("demo", {}).get("enabled", False)
        self._service = None

    def _get_service(self):
        if self._service is None:
            # Reuse Gmail OAuth flow (same credentials, token now includes calendar scope)
            from app.gmail_client import GmailClient
            creds = GmailClient().authenticate()
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def get_day_availability(self, target_date: date, duration_minutes: Optional[int] = None) -> List[Dict]:
        """
        Return all hourly slots from business_hours_start to business_hours_end,
        each annotated with an availability status:
          - "free"    → no overlap with any existing event
          - "partial" → overlaps partially with an existing event
          - "busy"    → the entire slot is covered by existing events
        All slots are returned so the frontend can render a full time picker.
        """
        duration = duration_minutes if duration_minutes is not None else self._cfg.get("slot_duration_minutes", DEFAULT_SLOT_MINUTES)
        start_str = self._cfg.get("business_hours_start", DEFAULT_START)
        end_str = self._cfg.get("business_hours_end", DEFAULT_END)
        cal_id = self._cfg.get("calendar_id", DEFAULT_CAL_ID)
        tz = ZoneInfo(self._cfg.get("timezone", "Europe/Madrid"))

        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))

        # Build timezone-aware datetimes so Google receives correct UTC offsets
        day_start = datetime.combine(target_date, time_type(sh, sm), tzinfo=tz)
        day_end   = datetime.combine(target_date, time_type(eh, em), tzinfo=tz)

        freebusy_result = self._get_service().freebusy().query(body={
            "timeMin": day_start.isoformat(),   # includes +HH:MM offset — no fake "Z"
            "timeMax": day_end.isoformat(),
            "items": [{"id": cal_id}],
        }).execute()

        busy_raw = freebusy_result.get("calendars", {}).get(cal_id, {}).get("busy", [])
        # Google returns RFC3339 strings; replace trailing Z with +00:00 for fromisoformat
        busy = [
            (
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
            )
            for b in busy_raw
        ]

        slots = []
        slot_delta = timedelta(minutes=max(duration, 1))  # guard against 0-min loops
        current = day_start
        while current + slot_delta <= day_end:
            slot_end = current + slot_delta

            overlap = timedelta(0)
            for bs, be in busy:
                ov_start = max(current, bs)
                ov_end   = min(slot_end, be)
                if ov_end > ov_start:
                    overlap += ov_end - ov_start

            if overlap == timedelta(0):
                status = "free"
            elif overlap >= slot_delta:
                status = "busy"
            else:
                status = "partial"

            slots.append({
                "start": current.isoformat(),
                "end": slot_end.isoformat(),
                "label": current.strftime("%H:%M"),
                "status": status,
            })
            current += slot_delta

        return slots

    def create_event(
        self,
        summary: str,
        attendee_email: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        location: str = "",
    ) -> Dict:
        """
        Create a Google Calendar event and send an email invite to the attendee.
        Returns basic event info including the Calendar link.
        """
        cal_id = self._cfg.get("calendar_id", DEFAULT_CAL_ID)
        tz_name = self._cfg.get("timezone", "Europe/Madrid")

        # 0-duration (reminder): Google requires end > start, add 1 min
        if start_iso == end_iso:
            dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_iso = (dt + timedelta(minutes=1)).isoformat()

        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": tz_name},
            "end": {"dateTime": end_iso, "timeZone": tz_name},
            "attendees": [{"email": attendee_email}],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 30},
                ],
            },
        }
        if location:
            event_body["location"] = location

        # In demo mode, create the event but don't send invitations
        send_updates = "none" if self._demo else "all"
        created = self._get_service().events().insert(
            calendarId=cal_id,
            body=event_body,
            sendUpdates=send_updates,
        ).execute()

        return {
            "event_id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "summary": created.get("summary"),
            "start": created.get("start", {}).get("dateTime"),
            "end": created.get("end", {}).get("dateTime"),
        }
