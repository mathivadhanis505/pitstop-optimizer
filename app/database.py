import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/f1_pitstop"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

# Normalize postgres:// to postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Ensure proper driver prefix
if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+"):
    try:
        import psycopg2  # type: ignore
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    except ImportError:
        try:
            import psycopg  # type: ignore
            DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            pass

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
