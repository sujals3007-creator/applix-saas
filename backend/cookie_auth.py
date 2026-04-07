"""
cookie_auth.py
==============
Handles LinkedIn session cookie authentication for the Python backend.
 
This module is ONLY used when the backend needs to make direct HTTP
requests to LinkedIn (e.g., job monitoring, HR search).
 
Your existing Chrome Extension apply flow does NOT use this file at all —
the extension already runs inside the user's logged-in Chrome session.
 
Usage in other files:
    from cookie_auth import get_linkedin_session, validate_cookies
"""
 
import os
import httpx
import logging
from typing import Optional
 
logger = logging.getLogger("cookie_auth")
 
 
# ─────────────────────────────────────────────────────────────────
# Cookie loader — reads from environment variables (.env file)
# ─────────────────────────────────────────────────────────────────
 
def get_cookies() -> dict:
    """
    Load LinkedIn session cookies from environment variables.
    
    These are set in your backend/.env file:
        LINKEDIN_LI_AT=AQEDATxxxxxx
        LINKEDIN_JSESSIONID=ajax:xxxxxxxxx
    
    Returns a dict ready to be used as httpx/requests cookies.
    """
    li_at = os.getenv("LINKEDIN_LI_AT", "").strip()
    jsessionid = os.getenv("LINKEDIN_JSESSIONID", "").strip()
    
    if not li_at:
        logger.warning("⚠️  LINKEDIN_LI_AT is not set in .env")
    if not jsessionid:
        logger.warning("⚠️  LINKEDIN_JSESSIONID is not set in .env")
    
    return {
        "li_at": li_at,
        "JSESSIONID": jsessionid,
    }
 
 
def are_cookies_configured() -> bool:
    """
    Returns True if both cookie values exist in the environment.
    Does NOT verify if they are still valid (not expired).
    """
    cookies = get_cookies()
    return bool(cookies["li_at"] and cookies["JSESSIONID"])
 
 
# ─────────────────────────────────────────────────────────────────
# Cookie validator — makes a real request to verify session is live
# ─────────────────────────────────────────────────────────────────
 
async def validate_cookies() -> dict:
    """
    Makes a lightweight request to LinkedIn to verify the cookies work.
    
    Returns:
        {
          "valid": True/False,
          "reason": "ok" | "expired" | "missing" | "rate_limited" | "error"
        }
    """
    cookies = get_cookies()
    
    if not cookies["li_at"] or not cookies["JSESSIONID"]:
        return {"valid": False, "reason": "missing"}
    
    # We hit the LinkedIn feed API — it's lightweight and reliable
    test_url = "https://www.linkedin.com/feed/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        async with httpx.AsyncClient(
            cookies=cookies,
            headers=headers,
            timeout=15,
            follow_redirects=True
        ) as client:
            response = await client.get(test_url)
            
            if response.status_code == 200:
                # If we get redirected to /login, cookies are expired
                if "/login" in str(response.url) or "/checkpoint" in str(response.url):
                    logger.warning("❌ LinkedIn redirected to login — cookies expired.")
                    return {"valid": False, "reason": "expired"}
                
                logger.info("✅ LinkedIn cookies are valid.")
                return {"valid": True, "reason": "ok"}
            
            elif response.status_code == 999:
                # LinkedIn's rate limit code
                logger.warning("⚠️ LinkedIn returned 999 — rate limited.")
                return {"valid": False, "reason": "rate_limited"}
            
            elif response.status_code in (401, 403):
                logger.warning(f"❌ LinkedIn returned {response.status_code} — cookies invalid.")
                return {"valid": False, "reason": "expired"}
            
            else:
                logger.warning(f"⚠️ Unexpected status: {response.status_code}")
                return {"valid": False, "reason": f"http_{response.status_code}"}
    
    except httpx.TimeoutException:
        logger.error("❌ LinkedIn request timed out.")
        return {"valid": False, "reason": "timeout"}
    
    except Exception as e:
        logger.error(f"❌ Cookie validation error: {e}")
        return {"valid": False, "reason": f"error: {str(e)}"}
 
 
# ─────────────────────────────────────────────────────────────────
# Session factory — returns a ready-to-use httpx client
# ─────────────────────────────────────────────────────────────────
 
def get_linkedin_session() -> httpx.AsyncClient:
    """
    Returns a configured httpx.AsyncClient with:
      - LinkedIn cookies pre-loaded from .env
      - Realistic browser headers to avoid bot detection
      - Sensible timeouts
    
    Usage:
        async with get_linkedin_session() as client:
            response = await client.get("https://www.linkedin.com/jobs/search/...")
    
    IMPORTANT: Always use as a context manager (async with).
    """
    cookies = get_cookies()
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        # LinkedIn checks this header — must match a real browser origin
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }
    
    return httpx.AsyncClient(
        cookies=cookies,
        headers=headers,
        timeout=20,
        follow_redirects=True,
    )
 
 
# ─────────────────────────────────────────────────────────────────
# Cookie updater — saves new cookie values back to .env file
# ─────────────────────────────────────────────────────────────────
 
def save_cookies_to_env(li_at: str, jsessionid: str) -> bool:
    """
    Writes new cookie values into the .env file.
    Called when the extension sends fresh cookies via the API.
    
    Preserves all existing .env variables — only updates/adds the two
    LinkedIn cookie lines.
    
    Returns True on success, False on failure.
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    
    try:
        # Read current .env content (or start fresh if file doesn't exist)
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
        
        # Remove any existing LinkedIn cookie lines
        filtered_lines = [
            line for line in lines
            if not line.strip().startswith("LINKEDIN_LI_AT=")
            and not line.strip().startswith("LINKEDIN_JSESSIONID=")
        ]
        
        # Ensure file ends with newline before appending
        if filtered_lines and not filtered_lines[-1].endswith("\n"):
            filtered_lines[-1] += "\n"
        
        # Add the new cookie values
        filtered_lines.append(f"LINKEDIN_LI_AT={li_at.strip()}\n")
        filtered_lines.append(f"LINKEDIN_JSESSIONID={jsessionid.strip()}\n")
        
        # Write back
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(filtered_lines)
        
        # Reload the environment so the running server picks up new values
        # without restarting
        os.environ["LINKEDIN_LI_AT"] = li_at.strip()
        os.environ["LINKEDIN_JSESSIONID"] = jsessionid.strip()
        
        logger.info("✅ Cookies saved to .env and loaded into memory.")
        return True
    
    except Exception as e:
        logger.error(f"❌ Failed to save cookies to .env: {e}")
        return False
 