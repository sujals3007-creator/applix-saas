"""
outreach.py — Automated AI SaaS Outreach
Uses Groq to generate highly personalized emails based on User Profiles.
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

HUNTER_KEY = "3b370da32c7ee857d34199edc71768381070b040"

def clean_hr_name(name: str) -> str:
    return re.sub(r'[^\w\s\-\.]', '', name).strip()

def find_specific_hr_hunter(target_name: str, company: str) -> dict:
    if not HUNTER_KEY: return None
    url = "https://api.hunter.io/v2/email-finder"
    try:
        resp = httpx.get(url, params={"company": company, "full_name": clean_hr_name(target_name), "api_key": HUNTER_KEY}, timeout=15)
        if resp.status_code == 200 and resp.json().get("data", {}).get("email"):
            return {"name": clean_hr_name(target_name), "email": resp.json()["data"]["email"]}
    except Exception: pass
    return None

def find_generic_hr_hunter(company: str) -> dict:
    if not HUNTER_KEY: return None
    url = "https://api.hunter.io/v2/domain-search"
    try:
        resp = httpx.get(url, params={"company": company, "api_key": HUNTER_KEY, "limit": 10, "type": "personal"}, timeout=15)
        if resp.status_code == 200 and resp.json().get("data", {}).get("emails"):
            emails = resp.json()["data"]["emails"]
            best = next((e for e in emails if any(k in (e.get("position") or "").lower() for k in ["hr", "recruiter", "talent", "founder", "ceo"])), emails[0])
            name = f"{best.get('first_name', 'Hiring')} {best.get('last_name', 'Team')}".strip()
            return {"name": name, "email": best["value"]}
    except Exception: pass
    return None

def generate_ai_email_body(profile: dict, full_name: str, hr_name: str, job_title: str, company: str) -> str:
    """Uses Groq to write the core paragraphs, while Python enforces a flawless professional structure."""
    # Lowered temperature to 0.4 so the AI is more professional and less "fluffy"
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.4, groq_api_key=os.getenv("GROQ_API_KEY"))
    
    prompt_template = """
    Write the BODY ONLY of a cold outreach email from a candidate to a hiring manager.
    
    CANDIDATE INFO:
    Skills: {skills}
    Key Achievements: {achievements}
    Why they are a good fit: {fit}
    
    JOB INFO:
    Role: {job_title}
    Company: {company}
    
    INSTRUCTIONS:
    1. Write exactly 2 short, punchy paragraphs.
    2. Paragraph 1: State you recently applied for the {job_title} role at {company} via LinkedIn.
    3. Paragraph 2: Briefly highlight 1 or 2 specific skills or achievements from the CANDIDATE INFO that prove you are a great fit.
    4. TONE: Highly professional, direct, and confident. DO NOT use cliches like "highly motivated individual" or "I wanted to take a moment".
    5. STRICT RULE: DO NOT include greetings (e.g., "Hi Name") or sign-offs (e.g., "Thanks"). DO NOT include a subject line. Output ONLY the core text.
    """
    prompt = PromptTemplate.from_template(prompt_template)
    chain = prompt | llm
    
    try:
        resp = chain.invoke({
            "skills": profile.get("skills", ""),
            "achievements": profile.get("key_achievements", "Strong relevant background."),
            "fit": profile.get("why_good_fit", "Highly aligned with the role requirements."),
            "job_title": job_title, "company": company
        })
        ai_core_text = resp.content.strip()
    except Exception as e:
        logger.error(f"Groq Email Generation Failed: {e}")
        ai_core_text = f"I recently submitted my application for the {job_title} position at {company} via LinkedIn. Given my background and technical skills, I believe I align closely with the requirements of your team and am very interested in the opportunity."

    # ... (Keep the Groq AI part above exactly the same) ...

    # 🌟 THE FIX: Sanitize the HR Name to prevent "Dear None None"
    safe_hr_name = str(hr_name).strip()
    bad_names = ["none", "none none", "null", "unknown", "undefined", "", "none none."]
    if safe_hr_name.lower() in bad_names:
        safe_hr_name = "Hiring Team" # Safe, professional fallback

    # 🌟 PYTHON ENFORCES THE PERFECT STRUCTURE
    phone = profile.get("phone", "")
    email = profile.get("sender_email", "")
    
    # Safely format phone/email only if they exist
    contact_info = f"{full_name}"
    if phone: contact_info += f"\n{phone}"
    if email: contact_info += f"\n{email}"

    final_email = (
        f"Dear {safe_hr_name},\n\n"
        f"{ai_core_text}\n\n"
        f"I would greatly appreciate the opportunity for a brief chat to discuss how I can add value to the team at {company}. "
        f"Please let me know if there is a convenient time for a quick conversation..\n\n"
        f"Best regards,\n"
        f"{contact_info}"
    )
    
    return final_email.strip()

def send_email(user_id: int, to_email: str, hr_name: str, job_title: str, company: str) -> bool:
    profile = get_user_profile(user_id)
    if not profile: return False
    
    with get_db() as conn:
        user_row = conn.execute("SELECT full_name FROM users WHERE id=?", (user_id,)).fetchone()
        full_name = user_row["full_name"] if user_row else "Candidate"
        
    sender = profile.get("sender_email")
    password = profile.get("app_password")  # 🌟 SaaS: Pulls secure password from DB!
    
    if not sender or not password or not to_email or "@" not in to_email:
        logger.error("Missing sender credentials or invalid HR email.")
        return False

    body = generate_ai_email_body(profile, full_name, hr_name, job_title, company)

    try:
        msg = EmailMessage()
        msg['From'] = sender
        msg['To'] = to_email
        msg['Subject'] = f"Application follow-up: {job_title} role at {company}" 
        msg.set_content(body)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        logger.info(f"📧 SaaS Email sent successfully to {to_email} on behalf of {sender}")
        return True
    except Exception as e:
        logger.error(f"Email Sending Error: {e}")
        return False

def execute_outreach_flow(user_id: int, job_id: str, company: str, job_title: str, target_hr_name: str = None, target_hr_url: str = None):
    logger.info(f"Starting SaaS outreach flow for job: {job_id} at {company}")
    
    hr_data = find_specific_hr_hunter(target_hr_name, company) if target_hr_name else None
    if not hr_data:
        hr_data = find_generic_hr_hunter(company)

    if not hr_data or not hr_data.get("email"):
        log_activity(user_id, "hr_found", f"No verified HR email found in Hunter.io for {company}. Skipped outreach.")
        return
        
    hr_name, hr_email = hr_data["name"], hr_data["email"]
    
    with get_db() as conn:
        conn.execute(
            """INSERT INTO hr_contacts (user_id, job_id, company, recruiter_name, recruiter_email, profile_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, job_id, company, hr_name, hr_email, target_hr_url or "")
        )
        
    log_activity(user_id, "hr_found", f"Found HR via Hunter.io: {hr_name} ({hr_email})")
    
    # 🌟 Passes user_id to pull correct credentials
    email_success = send_email(user_id, hr_email, hr_name, job_title, company)
    
    with get_db() as conn:
        conn.execute(
            """INSERT INTO outreach_logs (user_id, job_id, recruiter_name, channel, status)
               VALUES (?, ?, ?, 'email', ?)""",
            (user_id, job_id, hr_name, "sent" if email_success else "failed")
        )
        
    if email_success:
        log_activity(user_id, "message_sent", f"Sent AI-generated email to {hr_name} ({hr_email})")