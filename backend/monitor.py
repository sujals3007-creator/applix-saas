"""
monitor.py  —  Background job scanner (Feature: Auto-trigger)

FIXES v3.1:
  - Cookies are read from each user's DB profile (not .env)
    → This is what was causing "no jobs found" — the scanner was using
      empty .env cookies instead of the per-user cookies saved by the extension.
  - Target-role filtering is exact-match against the user's target_roles list
  - Also checks ignored_jobs before queuing
  - All DB queries use %s placeholders
  - Polite per-user delays to avoid hammering LinkedIn
"""
from datetime import datetime
import asyncio
import httpx
import json
import re
import logging
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_db, queue_job, is_already_applied, is_ignored, log_activity

logger = logging.getLogger("monitor")

SCAN_INTERVAL_SECONDS = 300   # 5 minutes
MAX_JOB_AGE_HOURS     = 168   # 1 week

scheduler = AsyncIOScheduler()


# ── Age parser ───────────────────────────────────────────────────

def parse_age_hours(text: str) -> float:
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

async def scrape_jobs_for_role(role: str, location: str, cookies: dict) -> list[dict]:
    import urllib.parse

    exact_role       = f'%22{urllib.parse.quote(role)}%22'
    encoded_location = urllib.parse.quote(location)

    url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={exact_role}"
        f"&location={encoded_location}"
        "&f_AL=true&f_TPR=r604800&sortBy=DD"
        "&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Upgrade-Insecure-Requests": "1",
    }
    jobs = []

    try:
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=20, follow_redirects=False) as client:
            resp = await client.get(url)

            if resp.status_code in (301, 302):
                logger.error(
                    f"🚨 LinkedIn blocked the request ({resp.status_code}). "
                    f"Cookies expired/flagged for '{role}'."
                )
                return []
            if resp.status_code != 200:
                logger.warning(f"LinkedIn returned {resp.status_code} for '{role}'")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")

            for card in soup.select(
                "li.jobs-search-results__list-item, "
                "div.job-card-container, "
                ".base-card"
            ):
                job_id = (
                    card.get("data-job-id")
                    or card.get("data-entity-urn", "").split(":")[-1]
                )
                if not job_id:
                    a = card.select_one("a[href*='/jobs/view/']")
                    if a:
                        m = re.search(r"/jobs/view/(\d+)", a["href"])
                        job_id = m.group(1) if m else None

                if not job_id or not str(job_id).isdigit():
                    continue

                title_el   = card.select_one(".base-search-card__title, .job-card-list__title")
                title      = title_el.get_text(strip=True) if title_el else ""
                company_el = card.select_one(".base-search-card__subtitle, .job-card-container__company-name")
                company    = company_el.get_text(strip=True) if company_el else "LinkedIn Network"

                # FUZZY MATCH: all words in the role must appear in the title
                # "AI Engineer" matches "Senior AI Engineer", "AI/ML Engineer", etc.
                role_words = role.lower().split()
                title_lower = title.lower()
                if not all(word in title_lower for word in role_words):
                    logger.debug(f"Skipping '{title}' — doesn't match role '{role}'")
                    continue

                if not any(j["job_id"] == str(job_id) for j in jobs):
                    jobs.append({
                        "job_id":   str(job_id),
                        "url":      f"https://www.linkedin.com/jobs/view/{job_id}/",
                        "title":    title,
                        "company":  company,
                        "age_text": "",
                    })

    except Exception as e:
        logger.error(f"Scrape error for '{role}' in '{location}': {e}")

    logger.info(f"Scraped {len(jobs)} matching jobs for role='{role}' location='{location}'")
    return jobs


# ── Per-user scan ────────────────────────────────────────────────

async def scan_for_user(user_id: int, profile: dict):
    """
    v4.0: LinkedIn scraping moved to Chrome extension.
    Cloud-side scraping is permanently blocked by LinkedIn (302 on GCP IPs).
    The extension opens a silent background tab in the user's real browser
    session, scrapes job IDs safely, and adds them to the queue via the backend.
    This function is intentionally a no-op now.
    """
    logger.debug(
        f"User {user_id}: server-side LinkedIn scan skipped — "
        "scanning is now handled by the Chrome extension."
    )
    return

    # ── DISABLED CODE BELOW (kept for reference) ──────────────────
    li_at      = (profile.get("li_at")      or "").strip()
    jsessionid = (profile.get("jsessionid") or "").strip()

    if not li_at or not jsessionid:
        logger.debug(f"User {user_id}: no LinkedIn cookies in DB profile — skipping scan.")
        return

    # Parse target roles
    roles_raw = profile.get("target_roles") or '["AI Engineer"]'
    try:
        roles = json.loads(roles_raw)
        if not isinstance(roles, list) or not roles:
            roles = ["AI Engineer"]
    except Exception:
        roles = ["AI Engineer"]

    # Parse target locations
    locs_raw = profile.get("target_locations") or '["India"]'
    try:
        locations = json.loads(locs_raw)
        if not isinstance(locations, list) or not locations:
            locations = ["India"]
    except Exception:
        locations = ["India"]

    cookies       = {"li_at": li_at, "JSESSIONID": jsessionid}
    new_jobs_found = 0
    cookies_blocked = False  # Track if LinkedIn is blocking — stop early to save quota

    for role in roles:
        if cookies_blocked:
            break
        for location in locations:
            if cookies_blocked:
                break
            jobs = await scrape_jobs_for_role(role, location, cookies)

            # If we get 0 jobs AND the scraper logged a 302, cookies are expired
            # scrape_jobs_for_role returns [] on 302 — detect by checking logs isn't feasible
            # Instead: if 3 consecutive roles return 0, assume blocked
            if jobs == [] and len(roles) > 1:
                # Will naturally skip — no jobs queued
                pass

            for job in jobs:
                age_h = parse_age_hours(job["age_text"])
                if age_h > MAX_JOB_AGE_HOURS:
                    continue
                # Skip jobs already applied to OR explicitly ignored
                if is_already_applied(user_id, job["job_id"]):
                    continue
                if is_ignored(user_id, job["job_id"]):
                    continue

                queue_job(
                    user_id,
                    job["job_id"],
                    job["url"],
                    job["title"],
                    job["company"]
                )
                new_jobs_found += 1

            # Polite delay between searches to avoid bot detection
            await asyncio.sleep(12)

    if new_jobs_found > 0:
        msg = f"Auto-scanner found {new_jobs_found} new jobs and added them to your queue."
        log_activity(user_id, "scan", msg)
        logger.info(f"User {user_id}: {msg}")
    else:
        logger.debug(f"User {user_id}: scan complete, no new qualifying jobs.")


# ── Scheduler job: scan ALL active users ─────────────────────────

async def run_all_user_scans():
    """
    Called by APScheduler every SCAN_INTERVAL_SECONDS.
    Fetches all users who have LinkedIn cookies configured in their profile,
    then runs scan_for_user for each.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT u.id, cp.target_roles, cp.target_locations
            FROM users u
            JOIN candidate_profiles cp ON cp.user_id = u.id
            WHERE u.is_active = 1
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

        # Small delay between users to be polite
        await asyncio.sleep(5)


# ── Start / stop scheduler ───────────────────────────────────────

def start_scheduler():
    scheduler.add_job(
        run_all_user_scans,
        trigger="interval",
        seconds=SCAN_INTERVAL_SECONDS,
        id="job_scanner",
        replace_existing=True,
        misfire_grace_time=30,
        next_run_time=datetime.now()   # Run immediately on startup
    )
    scheduler.start()
    logger.info(f"✅ Job scanner started. Interval: {SCAN_INTERVAL_SECONDS}s.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Job scanner stopped.")


def get_scheduler_status() -> dict:
    if not scheduler.running:
        return {"running": False, "next_run": None, "job_count": 0}
    jobs         = scheduler.get_jobs()
    job_scanner  = next((j for j in jobs if j.id == "job_scanner"), None)
    return {
        "running":   True,
        "next_run":  str(job_scanner.next_run_time) if job_scanner else None,
        "job_count": len(jobs),
    }