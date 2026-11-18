"""
Shared fixtures for all tests.
Uses an in-memory SQLite DB and a minimal FastAPI app (no lifespan / demo data).
External APIs (Gmail, Calendar, NVIDIA NIM) are always mocked.
"""
import os
import uuid
import pytest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# The LLM client is created at import time; tests never call it, but it needs a key.
os.environ.setdefault("NVIDIA_API_KEY", "test-key")

from app.database import Base, get_db
from app.routes import router
from app.models import Email
import app.routes as routes_module
from app import account_manager

# ---------------------------------------------------------------------------
# Minimal test app — no lifespan, no static files, no demo data loading
# ---------------------------------------------------------------------------
test_app = FastAPI()
test_app.include_router(router)

TEST_DB_URL = "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # single connection ensures in-memory DB is shared
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    test_app.dependency_overrides[get_db] = override_get_db
    # Reset cached singletons so each test starts clean
    routes_module._gmail_client = None
    routes_module._ai_classifier = None

    with TestClient(test_app, raise_server_exceptions=True) as c:
        yield c

    test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_classifier():
    """AIClassifier that returns safe, predictable results."""
    m = MagicMock()
    m.classify_email.return_value = {
        "category": "Consulta general",
        "priority": "media",
        "color": "green",
        "summary": "Resumen de prueba.",
        "lead_score": 3,
    }
    m.draft_reply.return_value = "Estimado cliente, gracias por su consulta."
    m.summarize_thread.return_value = "El cliente consultó y la agencia respondió."
    return m


@pytest.fixture()
def mock_gmail():
    """GmailClient with empty inbox by default."""
    m = MagicMock()
    m.fetch_emails.return_value = []
    m.send_reply.return_value = "sent_msg_id"
    m.get_account_email.return_value = "test@gmail.com"
    return m


@pytest.fixture()
def mock_accounts(mock_gmail):
    """
    Patch account_manager.list_accounts to return one test account and
    patch GmailClient constructor to return mock_gmail.
    Use this fixture in any test that calls POST /api/sync.
    """
    with patch.object(account_manager, "list_accounts", return_value=["test@gmail.com"]), \
         patch.object(account_manager, "get_token_path", return_value="token.json"), \
         patch("app.routes.GmailClient", return_value=mock_gmail):
        yield mock_gmail


# ---------------------------------------------------------------------------
# Email factory
# ---------------------------------------------------------------------------

@pytest.fixture()
def email_factory(db):
    """Create and persist Email instances with sensible defaults."""
    def make(
        gmail_id=None,
        sender="Test User",
        sender_email="test@example.com",
        subject="Correo de prueba",
        body_preview="Contenido del correo.",
        category="Consulta general",
        priority="media",
        color="green",
        summary="Resumen.",
        is_read=False,
        is_replied=False,
        is_archived=False,
        thread_id=None,
        lead_score=None,
        lead_source=None,
        lead_name=None,
        lead_phone=None,
        lead_property_ref=None,
        is_demo=False,
        **kwargs,
    ):
        email = Email(
            gmail_id=gmail_id or str(uuid.uuid4()),
            sender=sender,
            sender_email=sender_email,
            subject=subject,
            body_preview=body_preview,
            category=category,
            priority=priority,
            color=color,
            summary=summary,
            is_read=is_read,
            is_replied=is_replied,
            is_archived=is_archived,
            thread_id=thread_id,
            lead_score=lead_score,
            lead_source=lead_source,
            lead_name=lead_name,
            lead_phone=lead_phone,
            lead_property_ref=lead_property_ref,
            is_demo=is_demo,
            **kwargs,
        )
        db.add(email)
        db.commit()
        db.refresh(email)
        return email

    return make
