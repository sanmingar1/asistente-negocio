from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float
from sqlalchemy.sql import func
from app.database import Base


PIPELINE_STAGES = ["lead", "visita", "oferta", "cerrado", "descartado"]


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    lead_source = Column(String(100), nullable=True)
    pipeline_stage = Column(String(50), default="lead", nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self):
        return {
            "email": self.email,
            "name": self.name,
            "phone": self.phone,
            "lead_source": self.lead_source,
            "pipeline_stage": self.pipeline_stage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ContactNote(Base):
    __tablename__ = "contact_notes"

    id = Column(Integer, primary_key=True, index=True)
    contact_email = Column(String(255), nullable=False, index=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "contact_email": self.contact_email,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    gmail_id = Column(String(255), unique=True, index=True, nullable=False)
    sender = Column(String(255), nullable=True)
    sender_email = Column(String(255), nullable=True, index=True)
    subject = Column(String(500), nullable=True)
    body_preview = Column(Text, nullable=True)  # First 500 chars
    received_at = Column(DateTime, nullable=True, index=True)
    category = Column(String(100), nullable=True, index=True)
    priority = Column(String(50), nullable=True, index=True)
    color = Column(String(50), nullable=True)
    summary = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    is_replied = Column(Boolean, default=False, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    thread_id = Column(String(255), nullable=True)
    raw_labels = Column(Text, nullable=True)  # JSON string of Gmail labels
    lead_score = Column(Integer, nullable=True)       # AI lead quality score 0-10
    lead_source = Column(String(100), nullable=True)  # Portal: Idealista, Fotocasa…
    lead_name = Column(String(255), nullable=True)    # Extracted contact name
    lead_phone = Column(String(50), nullable=True)    # Extracted phone number
    lead_property_ref = Column(String(100), nullable=True)  # Extracted property ref
    is_demo = Column(Boolean, default=False, nullable=False)
    account_email = Column(String(255), nullable=True, index=True)  # Gmail account that owns this email
    snoozed_until = Column(DateTime, nullable=True)  # If set, hide email until this datetime
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "gmail_id": self.gmail_id,
            "sender": self.sender,
            "sender_email": self.sender_email,
            "subject": self.subject,
            "body_preview": self.body_preview,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "category": self.category,
            "priority": self.priority,
            "color": self.color,
            "summary": self.summary,
            "is_read": self.is_read,
            "is_replied": self.is_replied,
            "is_archived": self.is_archived,
            "thread_id": self.thread_id,
            "raw_labels": self.raw_labels,
            "lead_score": self.lead_score,
            "lead_source": self.lead_source,
            "lead_name": self.lead_name,
            "lead_phone": self.lead_phone,
            "lead_property_ref": self.lead_property_ref,
            "is_demo": self.is_demo,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "account_email": self.account_email,
            "snoozed_until": self.snoozed_until.isoformat() if self.snoozed_until else None,
            "needs_followup": (
                self.priority in ("urgente", "alta")
                and not self.is_replied
                and not self.is_archived
            ),
        }
