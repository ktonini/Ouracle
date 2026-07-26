"""Shared pytest fixtures for the insights unit tests.

The production database module touches the user data directory at import time;
these tests sidestep it by binding an in-memory SQLite engine to the same
``Base.metadata`` declared in ``backend.src.models``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure the project root is on sys.path so ``backend.src...`` imports work
# regardless of where pytest is invoked from.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.src.models import Base  # noqa: E402  (path injection above)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    from backend.src.ingestion.key_migration import normalize_keys_if_needed

    normalize_keys_if_needed(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
