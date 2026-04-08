"""
monitor.py  —  Background job scanner (Feature: Auto-trigger)

Runs on a schedule using APScheduler (no Redis needed).
Every 2 minutes, for each active user who has LinkedIn cookies set:
  1. Scrapes LinkedIn for jobs matching their target_roles
  2. Deduplicates against applied_jobs table
  3. Inserts new jobs into jobs_queue
  4. The Chrome extension polls /api/pending-jobs and picks them up

This is purely a TRIGGER layer — it does NOT touch content.js or
background.js at all. The existing apply logic fires unchanged.
"""
from datetime import datetime
import asyncio
import httpx
import json
import re
import logging
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_db, queue_job, is_already_applied, log_activity

logger = logging.getLogger("monitor")

# Poll interval in seconds
SCAN_INTERVAL_SECONDS = 300  # 🌟 Changed from 120 to 600 (10 minutes)

# Only apply to jobs posted within this many hours
MAX_JOB_AGE_HOURS = 168

scheduler = AsyncIOScheduler()


# ── Age parser ───────────────────────────────────────────────────

def parse_age_hours(text: str) -> float:
    """
    Converts LinkedIn's "Just posted", "2 hours ago", "1 day ago" etc.
    into a float number of hours. Returns 999 if unparseable.
    """
    t = (text or "").lower().strip()
    if "just" in t or "moment" in t or "second" in t:
        return 0.1
    m = re.search(r"(\d+)\s*(minute|hour|day|week)", t)
    if not m:
        return 999
    n, unit = int(m.group(1)), m.group(2)
    if unit.startswith("minute"): return n / 60
    if unit.startswith("hour"):   return float(n)
    if unit.startswith("day"):    return n * 24
    if unit.startswith("week"):   return n * 168
    return 999


# ── LinkedIn scraper ─────────────────────────────────────────────

async def scrape_jobs_for_role(role: str, cookies: dict) -> list[dict]:
    url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={role.replace(' ', '%20')}"
        "&f_AL=true&f_TPR=r604800&sortBy=DD"       
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate",
    }
    jobs = []
    
    try:
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=20) as client:
            resp = await client.get(url)
            if resp.status_code == 302:
                logger.error(f"🚨 LinkedIn blocked the request (302). Cookies expired/flagged for '{role}'.")
                return []
            if resp.status_code != 200: return []

            soup = BeautifulSoup(resp.text, "html.parser")
            
            # --- STRICT DOM PARSING ONLY ---
            for card in soup.select("li.jobs-search-results__list-item, div.job-card-container, .base-card"):
                job_id = card.get("data-job-id") or card.get("data-entity-urn", "").split(":")[-1]
                if not job_id:
                    a = card.select_one("a[href*='/jobs/view/']")
                    job_id = re.search(r"/jobs/view/(\d+)", a["href"]).group(1) if a else None
                
                if not job_id or not job_id.isdigit(): continue

                title_el = card.select_one(".base-search-card__title, .job-card-list__title")
                title = title_el.get_text(strip=True) if title_el else ""

                company_el = card.select_one(".base-search-card__subtitle, .job-card-container__company-name")
                company = company_el.get_text(strip=True) if company_el else "LinkedIn Network"

                # 🌟 THE FIX: STRICT ROLE FILTERING!
                # Break the target role into words (e.g., "AI Engineer" -> "AI", "Engineer")
                # 🌟 THE FIX: STRICT ROLE FILTERING!
                title_lower = title.lower()
                role_lower = role.lower().strip()
                
                # The job title MUST contain the exact target role phrase (e.g., "ai engineer")
                if role_lower not in title_lower:
                    logger.info(f"Skipping irrelevant role: {title}")
                    continue 

                if not any(j["job_id"] == job_id for j in jobs):
                    jobs.append({
                        "job_id": job_id,
                        "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                        "title": title,
                        "company": company,
                        "age_text": "",
                    })
    except Exception as e:
        logger.error(f"Scrape error for '{role}': {e}")
        
    return jobs
# ── Per-user scan ────────────────────────────────────────────────

async def scan_for_user(user_id: int, profile: dict):
    """
    Runs the full scan cycle for one user.
    Called by the scheduler every SCAN_INTERVAL_SECONDS seconds.
    """
    li_at      = (profile.get("li_at") or "").strip()
    jsessionid = (profile.get("jsessionid") or "").strip()

    if not li_at or not jsessionid:
        logger.debug(f"User {user_id}: no LinkedIn cookies — skipping scan.")
        return

    roles_raw = profile.get("target_roles") or '["AI Engineer"]'
    try:
        roles = json.loads(roles_raw)
    except Exception:
        roles = ["AI Engineer"]

    cookies = {"li_at": li_at, "JSESSIONID": jsessionid}
    new_jobs_found = 0

    for role in roles:
        jobs = await scrape_jobs_for_role(role, cookies)
        for job in jobs:
            age_h = parse_age_hours(job["age_text"])
            if age_h > MAX_JOB_AGE_HOURS:
                continue
            if is_already_applied(user_id, job["job_id"]):
                continue
            queue_job(user_id, job["job_id"], job["url"],
                      job["title"], job["company"])
            new_jobs_found += 1

        # Polite delay between role searches
        await asyncio.sleep(5)

    if new_jobs_found > 0:
        msg = f"Auto-scanner found {new_jobs_found} new jobs and added them to your queue."
        log_activity(user_id, "scan", msg)
        logger.info(f"User {user_id}: {msg}")
    else:
        logger.debug(f"User {user_id}: scan complete, no new jobs.")


# ── Scheduler job: scan ALL active users ─────────────────────────

async def run_all_user_scans():
    """
    Called by APScheduler every SCAN_INTERVAL_SECONDS.
    Fetches all users who have LinkedIn cookies configured,
    then runs scan_for_user for each.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT u.id, cp.li_at, cp.jsessionid, cp.target_roles
            FROM users u
            JOIN candidate_profiles cp ON cp.user_id = u.id
            WHERE u.is_active = 1
              AND cp.li_at IS NOT NULL
              AND cp.li_at != ''
        """).fetchall()

    if not rows:
        logger.debug("Scanner: no active users with cookies configured.")
        return

    logger.info(f"Scanner: running scans for {len(rows)} user(s)...")
    for row in rows:
        try:
            await scan_for_user(row["id"], dict(row))
        except Exception as e:
            logger.error(f"Scan failed for user {row['id']}: {e}")


# ── Start / stop scheduler ───────────────────────────────────────

def start_scheduler():
    """Call this once at FastAPI startup."""
    scheduler.add_job(
        run_all_user_scans,
        trigger="interval",
        seconds=SCAN_INTERVAL_SECONDS,
        id="job_scanner",
        replace_existing=True,
        misfire_grace_time=30,
        next_run_time=datetime.now()  # 🌟 FIX: Forces the very first scan to run instantly!
    )
    scheduler.start()
    logger.info(f"✅ Job scanner started. Interval: {SCAN_INTERVAL_SECONDS}s.")


def stop_scheduler():
    """Call this at FastAPI shutdown."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Job scanner stopped.")


def get_scheduler_status() -> dict:
    """Returns current scheduler state for the agent monitor dashboard."""
    if not scheduler.running:
        return {"running": False, "next_run": None, "job_count": 0}
    jobs = scheduler.get_jobs()
    job_scanner = next((j for j in jobs if j.id == "job_scanner"), None)
    return {
        "running":   True,
        "next_run":  str(job_scanner.next_run_time) if job_scanner else None,
        "job_count": len(jobs),
    }