import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

DATABASE_URL = "sqlite:///data/emails.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite with FastAPI
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they don't exist, and add any missing columns."""
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Lightweight migration: add columns introduced after the initial schema
    _add_column_if_missing("emails", "is_replied", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing("emails", "thread_id", "VARCHAR(255)")
    _add_column_if_missing("emails", "is_archived", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing("emails", "lead_score", "INTEGER")
    _add_column_if_missing("emails", "lead_source", "VARCHAR(100)")
    _add_column_if_missing("emails", "lead_name", "VARCHAR(255)")
    _add_column_if_missing("emails", "lead_phone", "VARCHAR(50)")
    _add_column_if_missing("emails", "lead_property_ref", "VARCHAR(100)")
    _add_column_if_missing("emails", "is_demo", "BOOLEAN NOT NULL DEFAULT 0")


def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    """Add a column to a SQLite table only if it does not already exist."""
    with engine.connect() as conn:
        result = conn.execute(
            __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
        )
        existing = {row[1] for row in result}
        if column not in existing:
            conn.execute(
                __import__("sqlalchemy").text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
            )
            conn.commit()
