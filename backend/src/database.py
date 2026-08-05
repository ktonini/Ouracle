import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .models import Base

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Database")

from .paths import get_user_data_dir
import sys
import traceback

# --- Configuration ---

try:
    # Use user data directory for database
    BASE_DIR = get_user_data_dir()
    DB_PATH = os.path.join(BASE_DIR, "oura_database.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"

    # Verify we can write to this directory
    test_file = os.path.join(BASE_DIR, "write_test.tmp")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("test")
    os.remove(test_file)

except Exception as e:
    # CRITICAL: always log to stderr (containers/headless), then try to leave
    # a crash report in Documents for desktop users. The report is best-effort;
    # a failure to write it must not mask the original error.
    logger.critical("Database Config CRASH: %s\n%s", e, traceback.format_exc())
    try:
        crash_file = os.path.expanduser("~/Documents/cracked_oura_backend_crash.txt")
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write(f"Database Config CRASH: {e}\n")
            f.write(traceback.format_exc())
    except OSError:
        pass
    sys.exit(1)

# --- SQLAlchemy Setup ---

# Create the SQLAlchemy engine
# echo=False disables raw SQL logging to keep console output clean
# Enable WAL mode and longer timeout for concurrent mobile sync access
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30.0},
)

# Enable WAL mode for better concurrent read/write performance
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# Session factory for creating new database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Utilities ---

def init_db():
    """
    Initializes the database schema.
    Creates all tables defined in `models.py` if they do not already exist.
    """
    try:
        Base.metadata.create_all(bind=engine)
        from backend.src.ingestion.key_migration import normalize_keys_if_needed

        db = SessionLocal()
        try:
            normalize_keys_if_needed(db)
        finally:
            db.close()
        logger.info(f"Database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

def get_db():
    """
    FastAPI Dependency for database sessions.
    Ensures that a session is created for each request and closed afterwards.
    
    Yields:
        Session: The SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
