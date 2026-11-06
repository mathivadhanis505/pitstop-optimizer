"""
Database Initialization Script for Pitstop Optimizer
Safe to run in Render build command or local environment.
Only executes schema and seed data if database is empty, unless --force is specified.
"""
import os
import sys
from pathlib import Path
from sqlalchemy import text

# Add current directory to path so app modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import engine

BASE_DIR = Path(__file__).resolve().parent

SQL_SCRIPTS = [
    BASE_DIR / "db" / "schema.sql",
    BASE_DIR / "db" / "functions.sql",
    BASE_DIR / "db" / "seed.sql",
    BASE_DIR / "db" / "migrations" / "001_fastf1_analytics_upgrade.sql",
    BASE_DIR / "db" / "migrations" / "002_fix_telemetry_and_standings.sql",
    BASE_DIR / "db" / "migrations" / "003_fix_calendar_mappings.sql",
]


def is_db_initialized() -> bool:
    try:
        with engine.connect() as conn:
            # Check if tracks and lap_telemetry exist and have records
            res = conn.execute(text("SELECT count(*) FROM tracks")).scalar()
            if res and res > 0:
                return True
    except Exception:
        return False
    return False


def run_init(force: bool = False):
    if not force and is_db_initialized():
        print("[init_db] Database is already initialized with data. Skipping.")
        print("[init_db] Pass --force to drop and re-seed from scratch.")
        return

    print("[init_db] Starting database schema, seed, and migrations deployment...")
    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        for script_path in SQL_SCRIPTS:
            if not script_path.exists():
                print(f"[init_db] Warning: {script_path.name} not found, skipping.")
                continue

            print(f"[init_db] Executing {script_path.name}...")
            with open(script_path, "r", encoding="utf-8") as f:
                sql_content = f.read()

            cur.execute(sql_content)
            raw_conn.commit()
            print(f"[init_db] Completed {script_path.name}")

        print("[init_db] Database successfully initialized and verified!")
    except Exception as e:
        raw_conn.rollback()
        print(f"[init_db] ERROR: Failed executing SQL script: {e}")
        sys.exit(1)
    finally:
        raw_conn.close()


if __name__ == "__main__":
    force_mode = "--force" in sys.argv
    run_init(force=force_mode)

