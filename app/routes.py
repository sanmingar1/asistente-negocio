import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Email, Contact, ContactNote, PIPELINE_STAGES
from app.gmail_client import GmailClient
from app.ai_classifier import AIClassifier
from app import notifier
from app import portal_parser
from app.calendar_client import CalendarClient

import yaml

logger = logging.getLogger(__name__)
router = APIRouter()

# Lazy singletons (initialised on first use to avoid startup failures
# when credentials are not yet configured)
_gmail_client: Optional[GmailClient] = None
_ai_classifier: Optional[AIClassifier] = None


def get_gmail_client() -> GmailClient:
    global _gmail_client
    if _gmail_client is None:
        _gmail_client = GmailClient()
    return _gmail_client


def get_ai_classifier() -> AIClassifier:
    global _ai_classifier
    if _ai_classifier is None:
        _ai_classifier = AIClassifier()
    return _ai_classifier


def _load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _upsert_contact(db: Session, email: Email) -> None:
    """Create or update a Contact record based on a newly saved email."""
    if not email.sender_email:
        return
    contact = db.query(Contact).filter(Contact.email == email.sender_email).first()
    if contact is None:
        contact = Contact(
            email=email.sender_email,
            name=email.lead_name or email.sender,
            phone=email.lead_phone,
            lead_source=email.lead_source,
        )
        db.add(contact)
    else:
        if not contact.name and (email.lead_name or email.sender):
            contact.name = email.lead_name or email.sender
        if not contact.phone and email.lead_phone:
            contact.phone = email.lead_phone
        if not contact.lead_source and email.lead_source:
            contact.lead_source = email.lead_source
    db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/emails")
def list_emails(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    source: Optional[str] = None,
    archived: bool = False,
    needs_followup: bool = False,
    db: Session = Depends(get_db),
):
    """Return emails newest first. Excludes archived by default; pass archived=true to list only archived."""
    query = db.query(Email).order_by(Email.received_at.desc())
    query = query.filter(Email.is_archived == archived)

    if needs_followup:
        query = query.filter(
            Email.priority.in_(["urgente", "alta"]),
            Email.is_replied == False,  # noqa: E712
        )
    if category:
        query = query.filter(Email.category == category)
    if priority:
        query = query.filter(Email.priority == priority)
    if source:
        query = query.filter(Email.lead_source == source)

    emails = query.all()
    return [e.to_dict() for e in emails]


@router.get("/api/emails/{email_id}")
def get_email(email_id: int, db: Session = Depends(get_db)):
    """Return a single email by its DB id and mark it as read."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    if not email.is_read:
        email.is_read = True
        db.commit()
        db.refresh(email)

    return email.to_dict()


@router.post("/api/sync")
def sync_emails(db: Session = Depends(get_db)):
    """
    Fetch new emails from Gmail, classify them with AI, and persist to DB.
    Returns the number of newly added emails.
    """
    gmail = get_gmail_client()
    classifier = get_ai_classifier()

    # Detect the active Gmail account and purge data from any previous account
    try:
        active_account = gmail.get_account_email()
    except Exception as exc:
        logger.error("Could not determine Gmail account: %s", exc)
        raise HTTPException(status_code=502, detail=f"Gmail auth failed: {exc}")

    # Detect an explicit account switch (only when a known different account exists)
    foreign = (
        db.query(Email)
        .filter(
            Email.is_demo == False,  # noqa: E712
            Email.account_email.isnot(None),
            Email.account_email != active_account,
        )
        .first()
    )
    if foreign:
        # Purge ALL non-demo emails that don't belong to the active account,
        # including legacy rows with account_email=NULL (pre-isolation emails).
        deleted_count = (
            db.query(Email)
            .filter(
                Email.is_demo == False,  # noqa: E712
                or_(Email.account_email.is_(None), Email.account_email != active_account),
            )
            .delete(synchronize_session=False)
        )
        logger.warning(
            "Account changed to %s — purged %d emails from previous account.",
            active_account, deleted_count,
        )
        db.commit()

    # Collect existing gmail IDs for this account to avoid duplicates
    existing_ids = {row[0] for row in db.query(Email.gmail_id).all()}

    try:
        raw_emails = gmail.fetch_emails(existing_ids=existing_ids)
    except Exception as exc:
        logger.error("Gmail fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Gmail fetch failed: {exc}")

    new_count = 0
    errors = []

    for email_data in raw_emails:
        try:
            classification = classifier.classify_email(
                subject=email_data["subject"],
                body=email_data.get("body_full", email_data["body_preview"]),
                sender=f"{email_data['sender']} <{email_data['sender_email']}>",
            )

            source = portal_parser.detect_source(email_data["sender_email"])
            portal_data = portal_parser.extract_lead_data(
                email_data.get("body_full", email_data["body_preview"])
            ) if source else {}

            db_email = Email(
                gmail_id=email_data["gmail_id"],
                thread_id=email_data.get("thread_id"),
                sender=email_data["sender"],
                sender_email=email_data["sender_email"],
                subject=email_data["subject"],
                body_preview=email_data["body_preview"],
                received_at=email_data["received_at"],
                category=classification["category"],
                priority=classification["priority"],
                color=classification["color"],
                summary=classification["summary"],
                lead_score=classification.get("lead_score"),
                lead_source=source,
                lead_name=portal_data.get("name"),
                lead_phone=portal_data.get("phone"),
                lead_property_ref=portal_data.get("property_ref"),
                is_read=False,
                is_replied=False,
                raw_labels=email_data["raw_labels"],
                account_email=active_account,
            )
            db.add(db_email)
            db.commit()
            _upsert_contact(db, db_email)
            new_count += 1
            notifier.notify(email_data, classification)
        except IntegrityError:
            db.rollback()
            logger.debug("Skipping duplicate email %s", email_data.get("gmail_id"))
        except Exception as exc:
            db.rollback()
            logger.error("Failed to process email %s: %s", email_data.get("gmail_id"), exc)
            errors.append(str(exc))

    response = {"new_emails": new_count, "total_fetched": len(raw_emails)}
    if errors:
        response["errors"] = errors[:5]  # Cap error list size
    return response


@router.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Return email counts grouped by category and by priority."""
    by_category = (
        db.query(Email.category, Email.color, func.count(Email.id).label("count"))
        .filter(Email.is_archived == False)  # noqa: E712
        .group_by(Email.category, Email.color)
        .order_by(func.count(Email.id).desc())
        .all()
    )

    by_priority = (
        db.query(Email.priority, func.count(Email.id).label("count"))
        .filter(Email.is_archived == False)  # noqa: E712
        .group_by(Email.priority)
        .all()
    )

    by_source = (
        db.query(Email.lead_source, func.count(Email.id).label("count"))
        .filter(Email.is_archived == False, Email.lead_source.isnot(None))  # noqa: E712
        .group_by(Email.lead_source)
        .order_by(func.count(Email.id).desc())
        .all()
    )

    unread_count = db.query(func.count(Email.id)).filter(Email.is_read == False, Email.is_archived == False).scalar()  # noqa: E712
    total_count = db.query(func.count(Email.id)).filter(Email.is_archived == False).scalar()
    archived_count = db.query(func.count(Email.id)).filter(Email.is_archived == True).scalar()  # noqa: E712
    followup_count = db.query(func.count(Email.id)).filter(
        Email.priority.in_(["urgente", "alta"]),
        Email.is_replied == False,  # noqa: E712
        Email.is_archived == False,  # noqa: E712
    ).scalar()

    priority_order = {"urgente": 0, "alta": 1, "media": 2, "baja": 3}

    return {
        "total": total_count,
        "unread": unread_count,
        "archived": archived_count,
        "followup": followup_count,
        "by_category": [
            {"category": row.category, "color": row.color, "count": row.count}
            for row in by_category
        ],
        "by_priority": sorted(
            [{"priority": row.priority, "count": row.count} for row in by_priority],
            key=lambda x: priority_order.get(x["priority"], 99),
        ),
        "by_source": [
            {"source": row.lead_source, "count": row.count}
            for row in by_source
        ],
    }


class NoteBody(BaseModel):
    body: str


class StageBody(BaseModel):
    stage: str


class ScheduleBody(BaseModel):
    start: str        # ISO datetime string, e.g. "2024-05-10T10:00:00"
    end: str
    summary: Optional[str] = None
    description: str = ""


class ManualClassification(BaseModel):
    category: str
    priority: str


class ReplyBody(BaseModel):
    body: str


@router.put("/api/emails/{email_id}/classify")
def manual_classify(email_id: int, data: ManualClassification, db: Session = Depends(get_db)):
    """Manually override the category and priority of an email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    config = _load_config()
    cat_meta = {c["name"]: c for c in config.get("categories", [])}

    if data.category not in cat_meta:
        raise HTTPException(status_code=400, detail=f"Unknown category: {data.category}")

    valid_priorities = {"urgente", "alta", "media", "baja"}
    if data.priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {data.priority}")

    email.category = data.category
    email.priority = data.priority
    email.color = cat_meta[data.category]["color"]
    db.commit()
    db.refresh(email)
    return email.to_dict()


@router.post("/api/emails/{email_id}/reclassify")
def reclassify_email(email_id: int, db: Session = Depends(get_db)):
    """Re-run AI classification on an existing email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    classifier = get_ai_classifier()
    try:
        classification = classifier.classify_email(
            subject=email.subject or "",
            body=email.body_preview or "",
            sender=f"{email.sender} <{email.sender_email}>",
        )
    except Exception as exc:
        logger.error("Reclassification failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail=f"AI classification failed: {exc}")

    email.category = classification["category"]
    email.priority = classification["priority"]
    email.color = classification["color"]
    email.summary = classification["summary"]
    email.lead_score = classification.get("lead_score")
    db.commit()
    db.refresh(email)
    return email.to_dict()


@router.post("/api/emails/{email_id}/draft")
def draft_reply_endpoint(email_id: int, db: Session = Depends(get_db)):
    """Generate an AI draft reply for an email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    classifier = get_ai_classifier()
    try:
        draft = classifier.draft_reply(
            subject=email.subject or "",
            body=email.body_preview or "",
            sender=f"{email.sender} <{email.sender_email}>",
            category=email.category or "",
        )
    except Exception as exc:
        logger.error("Draft generation failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail=f"Draft generation failed: {exc}")

    return {"draft": draft}


@router.get("/api/calendar/slots")
def get_calendar_slots(date: str, duration: int = 60):
    """
    Return all time slots for a given date with availability status.
    duration: slot size in minutes (0 = reminder, handled client-side).
    """
    import datetime as dt
    try:
        target = dt.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date. Use YYYY-MM-DD.")

    try:
        slots = CalendarClient().get_day_availability(target, duration_minutes=max(duration, 15))
        return {"date": date, "slots": slots, "duration": duration}
    except Exception as exc:
        logger.error("Calendar slots failed for %s: %s", date, exc)
        raise HTTPException(status_code=502, detail=f"Calendar error: {exc}")


@router.post("/api/emails/{email_id}/schedule")
def schedule_visit(email_id: int, data: ScheduleBody, db: Session = Depends(get_db)):
    """Create a Google Calendar event for a visit and send invite to the lead."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    summary = data.summary or f"Visita – {email.subject or 'Propiedad'}"
    description = data.description or f"Cita con {email.sender} | {email.subject}"

    try:
        event = CalendarClient().create_event(
            summary=summary,
            attendee_email=email.sender_email or "",
            start_iso=data.start,
            end_iso=data.end,
            description=description,
        )
    except Exception as exc:
        logger.error("Calendar event creation failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail=f"Calendar error: {exc}")

    return event


@router.get("/api/emails/{email_id}/thread")
def get_thread(email_id: int, db: Session = Depends(get_db)):
    """Return all other emails in the same Gmail thread, ordered by date."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if not email.thread_id:
        return []
    others = (
        db.query(Email)
        .filter(Email.thread_id == email.thread_id, Email.id != email_id)
        .order_by(Email.received_at.asc())
        .all()
    )
    return [e.to_dict() for e in others]


@router.post("/api/emails/{email_id}/thread-summary")
def thread_summary(email_id: int, db: Session = Depends(get_db)):
    """Generate an AI summary of the full email thread."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if not email.thread_id:
        return {"summary": None, "count": 1}

    thread = (
        db.query(Email)
        .filter(Email.thread_id == email.thread_id)
        .order_by(Email.received_at.asc())
        .all()
    )
    if len(thread) <= 1:
        return {"summary": None, "count": 1}

    classifier = get_ai_classifier()
    try:
        summary = classifier.summarize_thread([e.to_dict() for e in thread])
    except Exception as exc:
        logger.error("Thread summary failed for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail=f"Thread summary failed: {exc}")

    return {"summary": summary, "count": len(thread)}


@router.get("/api/categories")
def get_categories():
    """Return the list of categories from config."""
    config = _load_config()
    return config.get("categories", [])


@router.post("/api/emails/{email_id}/archive")
def archive_email(email_id: int, db: Session = Depends(get_db)):
    """Toggle archived status on an email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email.is_archived = not email.is_archived
    db.commit()
    db.refresh(email)
    return email.to_dict()


@router.post("/api/emails/{email_id}/reply")
def reply_email(email_id: int, data: ReplyBody, db: Session = Depends(get_db)):
    """Send a reply to an email and mark it as replied."""
    if not data.body or not data.body.strip():
        raise HTTPException(status_code=400, detail="Reply body cannot be empty")

    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    if _load_config().get("demo", {}).get("enabled", False):
        raise HTTPException(status_code=403, detail="Email sending is disabled in demo mode.")

    gmail = get_gmail_client()
    try:
        gmail.send_reply(
            gmail_id=email.gmail_id,
            to_email=email.sender_email,
            subject=email.subject or "",
            body=data.body.strip(),
            thread_id=email.thread_id,
        )
    except Exception as exc:
        logger.error("Failed to send reply for email %s: %s", email_id, exc)
        raise HTTPException(status_code=502, detail=f"Failed to send reply: {exc}")

    email.is_replied = True
    if not email.is_read:
        email.is_read = True
    db.commit()
    db.refresh(email)
    return email.to_dict()


# ---------------------------------------------------------------------------
# CRM — Contacts
# ---------------------------------------------------------------------------

@router.get("/api/contacts")
def list_contacts(db: Session = Depends(get_db)):
    """Return all contacts with their email count and last contact date."""
    contacts = db.query(Contact).order_by(Contact.updated_at.desc()).all()
    result = []
    for c in contacts:
        email_count = (
            db.query(func.count(Email.id))
            .filter(Email.sender_email == c.email)
            .scalar()
        )
        last_row = (
            db.query(Email.received_at)
            .filter(Email.sender_email == c.email)
            .order_by(Email.received_at.desc())
            .first()
        )
        row = c.to_dict()
        row["email_count"] = email_count or 0
        row["last_contact"] = last_row[0].isoformat() if last_row and last_row[0] else None
        result.append(row)
    return result


@router.get("/api/contacts/{contact_email:path}")
def get_contact(contact_email: str, db: Session = Depends(get_db)):
    """Return a contact profile with all their emails and notes."""
    contact = db.query(Contact).filter(Contact.email == contact_email).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    emails = (
        db.query(Email)
        .filter(Email.sender_email == contact_email)
        .order_by(Email.received_at.desc())
        .all()
    )
    notes = (
        db.query(ContactNote)
        .filter(ContactNote.contact_email == contact_email)
        .order_by(ContactNote.created_at.desc())
        .all()
    )

    data = contact.to_dict()
    data["emails"] = [e.to_dict() for e in emails]
    data["notes"] = [n.to_dict() for n in notes]
    return data


@router.put("/api/contacts/{contact_email:path}/stage")
def update_contact_stage(contact_email: str, data: StageBody, db: Session = Depends(get_db)):
    """Update the pipeline stage of a contact."""
    if data.stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Valid: {PIPELINE_STAGES}")
    contact = db.query(Contact).filter(Contact.email == contact_email).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact.pipeline_stage = data.stage
    db.commit()
    db.refresh(contact)
    return contact.to_dict()


@router.post("/api/contacts/{contact_email:path}/notes")
def add_contact_note(contact_email: str, data: NoteBody, db: Session = Depends(get_db)):
    """Add a note to a contact."""
    if not data.body or not data.body.strip():
        raise HTTPException(status_code=400, detail="Note body cannot be empty")
    contact = db.query(Contact).filter(Contact.email == contact_email).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    note = ContactNote(contact_email=contact_email, body=data.body.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note.to_dict()


@router.delete("/api/contacts/{contact_email:path}/notes/{note_id}")
def delete_contact_note(contact_email: str, note_id: int, db: Session = Depends(get_db)):
    """Delete a note from a contact."""
    note = (
        db.query(ContactNote)
        .filter(ContactNote.id == note_id, ContactNote.contact_email == contact_email)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return {"deleted": note_id}


@router.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    """Return public app settings (sync interval, business name, active account)."""
    config = _load_config()
    # Derive active account from the most recently synced email
    row = (
        db.query(Email.account_email)
        .filter(Email.account_email.isnot(None), Email.is_demo == False)  # noqa: E712
        .order_by(Email.created_at.desc())
        .first()
    )
    return {
        "sync_interval_minutes": config.get("email_provider", {}).get("sync_interval_minutes", 5),
        "business_name": config.get("business", {}).get("name", ""),
        "demo_mode": config.get("demo", {}).get("enabled", False),
        "active_account": row[0] if row else None,
    }
