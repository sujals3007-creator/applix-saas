"""
database.py — SaaS Cloud Edition (Neon.tech PostgreSQL)
"""
import os
import psycopg2
from psycopg2.extras import DictCursor
import logging
from dotenv import load_dotenv  # 🌟 ADD THIS

load_dotenv()  # 🌟 ADD THIS

logger = logging.getLogger("database")

# 1. Grab the Neon DB URL from .env
DB_URL = os.getenv("DATABASE_URL")

class PgWrapper:
    """
    A magic wrapper that automatically translates your existing SQLite 
    commands (like '?' and 'INSERT OR IGNORE') into PostgreSQL syntax 
    so you don't have to rewrite your entire backend!
    """
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=()):
        # 1. Replace SQLite '?' placeholders with Postgres '%s'
        pg_query = query.replace("?", "%s")
        
        # 2. Translate SQLite "INSERT OR IGNORE" to Postgres syntax
        pg_query = pg_query.replace("INSERT OR IGNORE INTO applied_jobs", "INSERT INTO applied_jobs")
        pg_query = pg_query.replace("INSERT OR IGNORE INTO ignored_jobs", "INSERT INTO ignored_jobs")
        pg_query = pg_query.replace("INSERT OR IGNORE INTO jobs_queue", "INSERT INTO jobs_queue")
        
        # Add ON CONFLICT DO NOTHING for the translated IGNOREs
        if "INSERT INTO applied_jobs" in pg_query and "ON CONFLICT" not in pg_query:
            pg_query += " ON CONFLICT (user_id, job_id) DO NOTHING"
        if "INSERT INTO ignored_jobs" in pg_query and "ON CONFLICT" not in pg_query:
            pg_query += " ON CONFLICT (user_id, job_id) DO NOTHING"
        if "INSERT INTO jobs_queue" in pg_query and "ON CONFLICT" not in pg_query:
            pg_query += " ON CONFLICT (user_id, job_id) DO NOTHING"
            
        # 3. Translate SQLite dates to Postgres dates
        pg_query = pg_query.replace("datetime('now')", "CURRENT_TIMESTAMP")
        pg_query = pg_query.replace(
            "date(applied_at, '+5 hours', '+30 minutes')=date('now', '+5 hours', '+30 minutes')",
            "DATE(applied_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') = CURRENT_DATE"
        )
        # 🌟 NEW FIX: Translate the 1-hour interval query!
        pg_query = pg_query.replace(
            "datetime(created_at) >= datetime('now', '-1 hour')",
            "created_at >= NOW() - INTERVAL '1 hour'"
        )

        # 4. Auto-fetch the newly created user ID for auth.py
        if "INSERT INTO users" in pg_query and "RETURNING" not in pg_query:
            pg_query += " RETURNING id"

        cur = self.conn.cursor(cursor_factory=DictCursor)
        cur.execute(pg_query, params)

        # 🌟 THE FIX: We removed the crashing cur.lastrowid line completely!
        return cur

    def executescript(self, script):
        cur = self.conn.cursor()
        cur.execute(script)

    def fetchall(self): return []
    def fetchone(self): return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()

def get_db():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return PgWrapper(conn)

def init_db():
    """Create all tables using PostgreSQL syntax."""
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            full_name     TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active     INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS candidate_profiles (
            id                   SERIAL PRIMARY KEY,
            user_id              INTEGER UNIQUE NOT NULL REFERENCES users(id),
            target_roles         TEXT,
            target_locations     TEXT,
            li_at                TEXT,
            jsessionid           TEXT,
            cookies_saved_at     TEXT,
            phone                TEXT,
            current_location     TEXT,
            notice_period_days   INTEGER DEFAULT 30,
            current_ctc_inr      INTEGER DEFAULT 0,
            expected_ctc_inr     INTEGER DEFAULT 0,
            years_experience     REAL    DEFAULT 0,
            skills               TEXT,
            education            TEXT,
            sender_email         TEXT,
            sender_phone         TEXT,
            app_password         TEXT,
            key_achievements     TEXT,
            why_good_fit         TEXT,
            resume_text          TEXT,
            updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS jobs_queue (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            job_id      TEXT    NOT NULL,
            job_url     TEXT    NOT NULL,
            title       TEXT,
            company     TEXT,
            queued_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            picked_up   INTEGER DEFAULT 0,
            UNIQUE(user_id, job_id)
        );

        CREATE TABLE IF NOT EXISTS applied_jobs (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            job_id      TEXT    NOT NULL,
            job_url     TEXT    NOT NULL,
            title       TEXT,
            company     TEXT,
            applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status      TEXT    DEFAULT 'applied',
            UNIQUE(user_id, job_id)
        );

        CREATE TABLE IF NOT EXISTS hr_contacts (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER NOT NULL REFERENCES users(id),
            job_id          TEXT,
            company         TEXT,
            recruiter_name  TEXT,
            recruiter_email TEXT,
            profile_url     TEXT,
            found_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS outreach_logs (
            id             SERIAL PRIMARY KEY,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            job_id         TEXT,
            recruiter_name TEXT,
            channel        TEXT,
            status         TEXT,
            error_msg      TEXT,
            sent_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS activity_logs (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            event_type TEXT    NOT NULL,
            message    TEXT    NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS ignored_jobs (
            user_id INTEGER,
            job_id TEXT,
            UNIQUE(user_id, job_id)
        );
        """)
        
        # 🌟 Safely injects the new ATS Match Score column
        try:
            conn.execute("ALTER TABLE applied_jobs ADD COLUMN match_score INTEGER DEFAULT 0;")
        except Exception:
            pass # Column already exists
            
        print("✅ PostgreSQL Database initialised on Neon.tech!")

# ──────────────────────────────────────────────────────────────────
# Convenience write helpers
# ──────────────────────────────────────────────────────────────────

def log_activity(user_id: int, event_type: str, message: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO activity_logs (user_id, event_type, message) VALUES (%s,%s,%s)",
            (user_id, event_type, message)
        )

def mark_job_applied(user_id: int, job_id: str, url: str,
                     title: str, company: str, status: str = "applied"):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO applied_jobs
               (user_id, job_id, job_url, title, company, status)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT(user_id, job_id) DO UPDATE SET status = EXCLUDED.status""",
            (user_id, job_id, url, title, company, status)
        )

def is_already_applied(user_id: int, job_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM applied_jobs WHERE user_id=%s AND job_id=%s",
            (user_id, job_id)
        ).fetchone()
    return row is not None

def queue_job(user_id: int, job_id: str, url: str, title: str, company: str):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs_queue
               (user_id, job_id, job_url, title, company)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (user_id, job_id, url, title, company)
        )

def get_pending_jobs_for_user(user_id: int, limit: int = 10) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM jobs_queue
               WHERE user_id=%s AND picked_up=0
               ORDER BY queued_at ASC LIMIT %s""",
            (user_id, limit)
        ).fetchall()
        if rows:
            ids = tuple(r["id"] for r in rows)
            conn.execute(
                "UPDATE jobs_queue SET picked_up=1 WHERE id IN %s",
                (ids,)
            )
    return [dict(r) for r in rows]

def get_user_profile(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM candidate_profiles WHERE user_id=%s", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_user_profile(user_id: int) -> dict:
    """Fetches the user's profile data for outreach."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM candidate_profiles WHERE user_id=%s", 
            (user_id,)
        ).fetchone()
        return dict(row) if row else {}