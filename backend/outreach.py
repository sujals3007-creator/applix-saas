"""
outreach.py — Automated AI SaaS Outreach (Apollo Integration)
"""
import os
import smtplib
from email.message import EmailMessage
import httpx
import logging
import re
from database import get_db, log_activity, get_user_profile
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger("outreach")

APOLLO_KEY = os.getenv("APOLLO_KEY")  

def clean_hr_name(name: str) -> str:
    return re.sub(r'[^\w\s\-\.]', '', name).strip()

def clean_company_name(name: str) -> str:
    """Strips Inc, LLC, Corp, etc. so Apollo can find the company."""
    clean = re.sub(r'(?i)\b(Inc\.?|LLC\.?|Corp\.?|Corporation|Ltd\.?|Pvt\.?|Private|Limited)\b', '', name)
    return clean.strip()

def find_specific_hr_apollo(target_name: str, company: str, person_id: str = None) -> dict:
    if not APOLLO_KEY: return {}
    try:
        url = "https://api.apollo.io/v1/people/match"
        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "X-Api-Key": APOLLO_KEY
        }
        
        # 🌟 FIX 1: If we already have their exact Apollo ID, use it for a guaranteed 100% match
        if person_id:
            payload = {"id": person_id}
        else:
            parts = target_name.split()
            first = parts[0] if parts else ""
            last = parts[-1] if len(parts) > 1 else ""
            clean_company = clean_company_name(company)
            payload = {
                "first_name": first,
                "last_name": last,
                "organization_name": clean_company
            }

        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)

        if resp.status_code == 429:
            return {"_quota_exhausted": True}

        if resp.status_code == 200:
            person = resp.json().get("person", {})
            email = person.get("email")
            if email:
                name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                return {"name": name or target_name, "email": email}
            else:
                logger.warning(f"Apollo matched person, but email was null. Free monthly credits may be exhausted.")
        else:
            logger.error(f"Apollo API rejected match: {resp.text}")
    except Exception as e:
        logger.error(f"Apollo Specific HR error: {e}")
    return {}

def find_generic_hr_apollo(company: str) -> dict:
    if not APOLLO_KEY: return {}
    try:
        clean_company = clean_company_name(company)
        url = "https://api.apollo.io/v1/mixed_people/api_search"
        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "X-Api-Key": APOLLO_KEY
        }
        payload = {
            "q_organization_name": clean_company,
            "person_titles": ["HR", "Recruiter", "Talent Acquisition", "Human Resources", "Hiring"]
        }
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)

        if resp.status_code == 429:
            return {"_quota_exhausted": True}

        if resp.status_code == 200:
            data = resp.json()
            people = data.get("people", [])
            
            for person in people:
                person_id = person.get("id")
                
                # 🌟 FIX: Apollo's new API hides last names. We now safely grab whatever is available!
                first_name = person.get("first_name") or ""
                last_name = person.get("last_name") or ""
                full_name = person.get("name") or f"{first_name} {last_name}".strip() or "Hiring Team"
                
                if person_id:
                    logger.info(f"Apollo found HR: {full_name}. Attempting to unlock email via ID {person_id}...")
                    
                    match_result = find_specific_hr_apollo(
                        full_name, 
                        clean_company, 
                        person_id=person_id
                    )
                    
                    if match_result and match_result.get("email"):
                        return match_result
            
            logger.warning(f"Apollo Search for {clean_company} returned {len(people)} people, but could not unlock any emails.")
        else:
            logger.error(f"Apollo API rejected search for {clean_company}: {resp.text}")
    except Exception as e:
        logger.error(f"Apollo Generic HR error: {e}")
    return {}

def _safe_hr_name(name: str) -> str:
    if not name or name.lower() in ["none", "none none", "null", "unknown"]:
        return "Hiring Team"
    return name


def send_email(user_id: int, to_email: str, hr_name: str, job_title: str, company: str) -> bool:
    profile = get_user_profile(user_id)
    if not profile or not profile.get("sender_email") or not profile.get("app_password"):
        log_activity(
            user_id, "error",
            f"Cannot send email to {company}. Missing Gmail App Password in Dashboard."
        )
        return False

    sender_email = profile["sender_email"]
    app_password  = profile["app_password"]
    qa_data = profile.get("master_qa_data", "")
    
    # Extract Full Name
    name_match = re.search(r'- Full Name \[TYPE:IDENTITY\]:\s*(.+)', qa_data, re.IGNORECASE)
    full_name = name_match.group(1).strip() if name_match else (profile.get("full_name") or sender_email.split("@")[0])

    phone = profile.get("phone", "")
    achievements = profile.get("key_achievements") or "Strong, relevant technical background."
    fit = profile.get("why_good_fit") or "Highly aligned with the role requirements."
    safe_name = _safe_hr_name(hr_name)

    # 🌟 NEW: Extract custom URLs from the master QA blueprint
    def extract_url(label: str) -> str:
        match = re.search(fr'- {label} \[TYPE:IDENTITY\]:\s*(.+)', qa_data, re.IGNORECASE)
        return match.group(1).strip() if match else None

    linkedin_url = extract_url("LinkedIn URL")
    github_url   = extract_url("GitHub URL")
    portfolio    = extract_url("Portfolio URL")
    resume_url   = extract_url("Resume Link")
    projects_url = extract_url("Projects Link")
    video_url    = extract_url("Video Explanation URL")

    try:
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.4,
            groq_api_key=os.getenv("GROQ_API_KEY")
        )
        prompt = PromptTemplate.from_template("""
        You are an expert copywriter writing a cold outreach email for a candidate to a recruiter.

        RECRUITER NAME: {hr_name}
        COMPANY: {company}
        ROLE APPLIED FOR: {job_title}

        CANDIDATE'S KEY ACHIEVEMENTS: {achievements}
        WHY THEY ARE A GOOD FIT: {fit}

        Write ONLY the body paragraphs of the email (no greeting, no sign-off).
        Keep it under 5 sentences. Be professional, confident, and specific.
        Do NOT use placeholders like [Your Name].
        """)
        chain = prompt | llm
        ai_body = chain.invoke({
            "hr_name": safe_name,
            "company": company,
            "job_title": job_title,
            "achievements": achievements,
            "fit": fit
        }).content.strip()

        # Build the dynamic contact info block
        contact_info = full_name
        if phone:
            contact_info += f"\nPhone: {phone}"
        contact_info += f"\nEmail: {sender_email}"

        # Build the dynamic links block
        links_block = []
        if resume_url:   links_block.append(f"Resume: {resume_url}")
        if video_url:    links_block.append(f"Video Intro: {video_url}")
        if portfolio:    links_block.append(f"Portfolio: {portfolio}")
        if projects_url: links_block.append(f"Projects: {projects_url}")
        if github_url:   links_block.append(f"GitHub: {github_url}")
        if linkedin_url: links_block.append(f"LinkedIn: {linkedin_url}")

        if links_block:
            contact_info += "\n\nRelevant Links:\n" + "\n".join(links_block)

        body = (
            f"Dear {safe_name},\n\n"
            f"{ai_body}\n\n"
            f"I would appreciate the opportunity for a brief conversation about the {job_title} "
            f"role at {company}. Please let me know if you have a convenient time.\n\n"
            f"Best regards,\n{contact_info}"
        )

        subject = f"Application follow-up: {job_title} at {company}"

        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"]    = sender_email
        msg["To"]      = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        server.ehlo()
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()

        logger.info(f"📧 SaaS Email sent successfully to {to_email} on behalf of {sender_email}")
        log_activity(user_id, "message_sent", f"Sent AI-crafted email to {safe_name} at {company}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        log_activity(
            user_id, "error",
            f"Email to {company} failed: {str(e)[:120]}"
        )
        return False


def execute_outreach_flow(
    user_id: int,
    job_id: str,
    company: str,
    job_title: str,
    target_hr_name: str = None,
    target_hr_url: str = None
):
    logger.info(f"Starting SaaS outreach flow for job: {job_id} at {company}")

    # 🌟 Safety check: Skip if Apollo Key isn't set in Google Cloud
    if not APOLLO_KEY:
        log_activity(user_id, "error", "Apollo API key missing. Outreach skipped.")
        return

    # 1. Try specific HR by name, fall back to domain search using APOLLO
    hr_data = {}
    if target_hr_name and target_hr_name.lower() not in ["unknown", "none", "hiring team", "hr"]:
        hr_data = find_specific_hr_apollo(target_hr_name, company)

    if not hr_data or not hr_data.get("email"):
        hr_data = find_generic_hr_apollo(company)

    # 2. Handle Quota limits or Missing Emails
    if hr_data and hr_data.get("_quota_exhausted"):
        log_activity(user_id, "hr_found", f"Apollo API quota exhausted. Outreach skipped for {company}.")
        return

    if not hr_data or not hr_data.get("email"):
        log_activity(
            user_id, "hr_found",
            f"No verified HR email found in Apollo for {company}. Skipped outreach."
        )
        return

    # 3. Save the found contact
    hr_name  = _safe_hr_name(hr_data["name"])
    hr_email = hr_data["email"]

    with get_db() as conn:
        conn.execute(
            """INSERT INTO hr_contacts
               (user_id, job_id, company, recruiter_name, recruiter_email, profile_url)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (user_id, job_id, company, hr_name, hr_email, target_hr_url or "")
        )

    log_activity(user_id, "hr_found", f"Found HR via Apollo: {hr_name} ({hr_email})")

    # 4. Send the Email
    email_success = send_email(user_id, hr_email, hr_name, job_title, company)

    with get_db() as conn:
        conn.execute(
            """INSERT INTO outreach_logs
               (user_id, job_id, recruiter_name, channel, status)
               VALUES (%s, %s, %s, 'email', %s)""",
            (user_id, job_id, hr_name, "sent" if email_success else "failed")
        )

    if email_success:
        log_activity(
            user_id, "message_sent",
            f"Sent AI-generated email to {hr_name} ({hr_email})"
        )