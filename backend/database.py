"""
database.py — SaaS Cloud Edition (Neon.tech PostgreSQL)

FIXES v3.1:
  - master_qa_data column added to schema
  - get_pending_jobs_for_user is now atomic (FOR UPDATE SKIP LOCKED)
  - All helpers use %s placeholders
  - YOE capped at 40 on insert
"""
import os   #operating system
import psycopg2   #used for making tuples data to dictioaries 
from psycopg2.extras import DictCursor  #same as above
import logging  #console ogs of warnings and logs 
from dotenv import load_dotenv  #.env 

load_dotenv() #loading .env

logger = logging.getLogger("database")  #from console 

DB_URL = os.getenv("DATABASE_URL")  #db url from .env (neon)

class PgWrapper:  ##thin wrapper that keeps the code running with postgresql
    """
    Thin wrapper that keeps existing code working with PostgreSQL.
    Translates ? → %s, SQLite date functions → Postgres equivalents,
    and handles RETURNING id for INSERTs into users.
    """
    def __init__(self, conn):  #initialise connection
        self.conn = conn  #conn

    def execute(self, query, params=()):  #executes the self , query and params tuples
        pg_query = query.replace("?", "%s")  #replace 

        # Translate INSERT OR IGNORE patterns
        pg_query = pg_query.replace("INSERT OR IGNORE INTO applied_jobs", "INSERT INTO applied_jobs") #replace
        pg_query = pg_query.replace("INSERT OR IGNORE INTO ignored_jobs", "INSERT INTO ignored_jobs")  #replace 
        pg_query = pg_query.replace("INSERT OR IGNORE INTO jobs_queue",   "INSERT INTO jobs_queue")  #replace 

        if "INSERT INTO applied_jobs" in pg_query and "ON CONFLICT" not in pg_query:  #checks between conditions 
            pg_query += " ON CONFLICT (user_id, job_id) DO NOTHING"   #part of above function
        if "INSERT INTO ignored_jobs" in pg_query and "ON CONFLICT" not in pg_query:  #checks between conditions 
            pg_query += " ON CONFLICT (user_id, job_id) DO NOTHING"  ##-
        if "INSERT INTO jobs_queue" in pg_query and "ON CONFLICT" not in pg_query: ##-
            pg_query += " ON CONFLICT (user_id, job_id) DO NOTHING"   ##-

        # Translate SQLite date helpers
        pg_query = pg_query.replace("datetime('now')", "CURRENT_TIMESTAMP") #time stamp 
        pg_query = pg_query.replace(  
            "date(applied_at, '+5 hours', '+30 minutes')=date('now', '+5 hours', '+30 minutes')",
            "DATE(applied_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') = CURRENT_DATE"  ##replace
        )
        pg_query = pg_query.replace( ##replace 
            "datetime(created_at) >= datetime('now', '-1 hour')", #replace datetime to -1 hour
            "created_at >= NOW() - INTERVAL '1 hour'" ##
        )

        # Auto-return id on INSERT INTO users
        if "INSERT INTO users" in pg_query and "RETURNING" not in pg_query: #user id is created and asked for user if 
            pg_query += " RETURNING id"  ###add the user id and sends back 

        cur = self.conn.cursor(cursor_factory=DictCursor) #cursor used for converting the query values as dictionary
        cur.execute(pg_query, params if params else None) #sends the query and parameter and actually sends it to database
        return cur

    def executescript(self, script):  #executing the script entirely of main database table 
        cur = self.conn.cursor()  #making changes in script
        cur.execute(script)   #executing the script

    def fetchall(self): return []  #fetch single row or column
    def fetchone(self): return None  #fetch all 

    def __enter__(self): #making it ready 
        return self  #return self

    def __exit__(self, exc_type, exc_val, exc_tb): #handling cleanup tasks 
        self.conn.close()  #conn


def get_db():  #get database
    conn = psycopg2.connect(DB_URL)   #making the data to dictionary
    conn.autocommit = True  #conn autocommit
    return PgWrapper(conn) # thin layer of wrapping the actual code 


def init_db():   #initial db
    """Create all tables using PostgreSQL syntax."""
    with get_db() as conn:  #making changes in database
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
            master_qa_data       TEXT,
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
            match_score INTEGER DEFAULT 0,
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
            id      SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            job_id  TEXT    NOT NULL,
            UNIQUE(user_id, job_id)
        );
        """)

        # Safely add columns that might not exist yet on existing deployments
        safe_alters = [  ## Safely add columns that might not exist yet on existing deployments
            "ALTER TABLE applied_jobs ADD COLUMN IF NOT EXISTS match_score INTEGER DEFAULT 0;",# Safely add columns that might not exist yet on existing deployments
            "ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS master_qa_data TEXT;",# Safely add columns that might not exist yet on existing deployments
            "ALTER TABLE candidate_profiles ADD COLUMN IF NOT EXISTS cookies_saved_at TEXT;",# Safely add columns that might not exist yet on existing deployments
        ]
        for stmt in safe_alters: #update the database schema and keep runinng ithout crashing
            try:  #try function
                conn.execute(stmt)  #connect
            except Exception:  #expect 
                pass #pass to further statment

    print("✅ PostgreSQL Database initialised on Neon.tech!")  ##neon database


# ──────────────────────────────────────────────────────────────────
# Convenience write helpers  (all use %s — no translation needed)
# ──────────────────────────────────────────────────────────────────

def log_activity(user_id: int, event_type: str, message: str):#function
    with get_db() as conn: #goes to dataset
        conn.execute( #conn
            "INSERT INTO activity_logs (user_id, event_type, message) VALUES (%s,%s,%s)", #user if, event_type_str 
            (user_id, event_type, message) 
        )


def mark_job_applied(user_id: int, job_id: str, url: str,
                     title: str, company: str, status: str = "applied"): #after the job has been applied it is marked as applied 
    with get_db() as conn:  #get database as conn 
        conn.execute( ##conn
            """INSERT INTO applied_jobs
               (user_id, job_id, job_url, title, company, status)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT(user_id, job_id) DO UPDATE SET status = EXCLUDED.status""",
            (user_id, job_id, url, title, company, status) # mark the jobs has been applied ater filling the details 
        )


def is_already_applied(user_id: int, job_id: str) -> bool:  #already applied jobs 
    with get_db() as conn: ##con
        row = conn.execute(  ##conn
            "SELECT id FROM applied_jobs WHERE user_id=%s AND job_id=%s",  #se;ect the id stored in applied jobs setion
            (user_id, job_id) ##
        ).fetchone() #fect only one specific row and column 
    return row is not None  #the row in not none 


def is_ignored(user_id: int, job_id: str) -> bool: #to ignore the jobs that has been skipped 
    with get_db() as conn:   ##conn
        row = conn.execute(  #conn
            "SELECT id FROM ignored_j bs WHERE user_id=%s AND job_id=%s", #slect from ignore jobs 
            (user_id, job_id) ##
        ).fetchone()  ##fetch only one row
    return row is not None  #no none value


def queue_job(user_id: int, job_id: str, url: str, title: str, company: str):  #queue jobs 
    with get_db() as conn: #conn
        conn.execute(  #conn
            """INSERT INTO jobs_queue
               (user_id, job_id, job_url, title, company)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (user_id, job_id, url, title, company)  ##queue jobs dataset
        )


def get_pending_jobs_for_user(user_id: int, limit: int = 1) -> list[dict]:  ##pending jos that are not applied yet 
    """
    FIX: Atomically fetches AND marks jobs as picked_up in one transaction.
    Uses FOR UPDATE SKIP LOCKED to be safe with multiple concurrent users.
    """
    conn_raw = psycopg2.connect(DB_URL)  #from neon database making into python dictionaries
    conn_raw.autocommit = False  ##cahnges made to dataset are not directly changed they have to go through the autocommit for saving the changes 
    try:  #try function
        with conn_raw.cursor(cursor_factory=DictCursor) as cur:  ###conn with the dictionary changes of data 
            cur.execute(   #cursor 
                """SELECT id, job_id, job_url, title, company
                   FROM jobs_queue
                   WHERE user_id=%s AND picked_up=0
                   ORDER BY queued_at ASC
                   LIMIT %s
                   FOR UPDATE SKIP LOCKED""",
                (user_id, limit)  #user id to limit 
            )
            rows = cur.fetchall()  #cursor to fetch all the rows of dataset
            if rows:   # if rows
                ids = tuple(r["id"] for r in rows) #tuples values stored 
                if len(ids) == 1:  #to check when only job id was picked 
                    cur.execute("UPDATE jobs_queue SET picked_up=1 WHERE id=%s", (ids[0],)) #updates the job id to 1 
                else:  #else
                    cur.execute("UPDATE jobs_queue SET picked_up=1 WHERE id=ANY(%s)", (list(ids),))  #handle multiple jobs ids with any operator in postgresql
        conn_raw.commit() #save all the changes made above 
        return [dict(r) for r in rows] #making database to python dicionaries 
    except Exception as e:  ##handles any error and save them as e and log the error message 
        conn_raw.rollback()  #if somethings goes wrong this line acts as a undo button 
        logger.error(f"get_pending_jobs_for_user error: {e}") #makes it easier to debugg by giving details of logs 
        return [] #return an empty list
    finally: #wether any exception occurs or not 
        conn_raw.close() #closes the database so it ensure no data will leak 


def get_user_profile(user_id: int) -> dict:   #calls for specific user profile from the database and sends in dictionary 
    """Fetches the user's full profile data."""
    with get_db() as conn: #feteches full profile data 
        row = conn.execute(  # conn
            "SELECT * FROM candidate_profiles WHERE user_id=%s",  #sql command for selecting specific candidate profile 
            (user_id,)  #user id
        ).fetchone()   #fetch a specific row 
        return dict(row) if row else {}  #return dict value if user was found otherwise an empty dictionary is send 