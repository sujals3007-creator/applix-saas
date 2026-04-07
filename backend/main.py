"""
main.py  —  AI Job Agent SaaS Backend  v3.0

EXISTING endpoints (100% UNCHANGED — DO NOT MODIFY):
  GET  /
  POST /api/upload-resume
  POST /api/match-job
  POST /api/answer-questions
  GET  /api/check-cookies
  GET  /api/validate-cookies
  POST /api/save-cookies

NEW endpoints (additive):
  POST /api/auth/signup
  POST /api/auth/login
  POST /api/profile/save          — save biodata + LinkedIn cookies + job prefs
  GET  /api/profile               — get current user's profile
  POST /api/job-applied           — extension calls this after success → triggers outreach
  GET  /api/pending-jobs          — extension polls this for auto-detected jobs
  GET  /api/dashboard/jobs        — applied jobs list
  GET  /api/dashboard/logs        — activity log feed
  GET  /api/dashboard/stats       — counts for the stats bar
  GET  /api/agent/status          — is the background scanner running?
"""
from outreach import execute_outreach_flow
from fastapi import FastAPI, UploadFile, File, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, io, json, logging
import pdfplumber
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

load_dotenv()
logging.basicConfig(level=logging.INFO)

# ── New module imports ───────────────────────────────────────────
from database import (
    init_db, get_db, log_activity, mark_job_applied,
    get_pending_jobs_for_user, get_user_profile
)
from auth import router as auth_router, get_current_user
from monitor import start_scheduler, stop_scheduler, get_scheduler_status
from outreach import execute_outreach_flow
from cookie_auth import get_cookies, validate_cookies, save_cookies_to_env

app = FastAPI(title="AI Job Agent SaaS API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register auth routes (/api/auth/signup, /api/auth/login)
app.include_router(auth_router)


# ── Startup / shutdown ───────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


# ══════════════════════════════════════════════════════════════════
# EXISTING ENDPOINTS — 100% UNCHANGED
# ══════════════════════════════════════════════════════════════════

class JobDescription(BaseModel):
    title: str
    company: str
    description: str

class FormQuestions(BaseModel):
    questions: list[str]

USER_RESUME_TEXT = ""   # kept for backward compat with single-user flow

@app.get("/")
def read_root():
    return {"status": "Active", "message": "AI Job Agent SaaS Backend is running!"}

@app.post("/api/parse-resume-to-form")
async def parse_resume_to_form(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Takes a PDF, extracts text, and uses Groq to auto-fill the Master Form questions."""
    if not file.filename.endswith(".pdf"):
        return {"status": "error", "message": "Only PDF files are supported."}
    
    try:
        # 1. Read PDF
        contents = await file.read()
        resume_text = ""
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text: resume_text += text + "\n"

        # 2. Ask Groq to extract structured answers
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.1, groq_api_key=os.getenv("GROQ_API_KEY"))
        
        prompt_template = """
        You are an expert HR assistant. Extract the candidate's details from the RESUME below to answer a specific set of job application questions.
        
        RESUME TEXT:
        {resume_text}
        
        INSTRUCTIONS:
        1. Respond STRICTLY with a valid JSON object. Do not include markdown formatting or extra text.
        2. The JSON keys MUST exactly match the list below.
        3. Keep values concise. If unknown, logically guess based on context, or output "Not Specified". Default to "Yes" for skills if their title strongly implies it.
        4. "q_yoe" must be a pure number (e.g., 3).
        
        JSON KEYS TO OUTPUT:
        "q_name", "q_email", "q_phone", "q_location", "q_relocate",
        "q_yoe", "q_summary", "q_current_role", "q_prev_company",
        "q_langs", "q_python", "q_ml", "q_dl", "q_nlp", "q_cv", "q_llm", "q_frameworks", "q_api", "q_cloud", "q_devops",
        "q_project", "q_deployed", "q_github", "q_portfolio",
        "q_degree", "q_university", "q_grad_year",
        "q_salary", "q_notice", "q_immediate",
        "q_work_auth", "q_visa"
        """
        
        prompt = PromptTemplate.from_template(prompt_template)
        chain = prompt | llm
        resp = chain.invoke({"resume_text": resume_text})
        
        # 3. Clean and parse JSON
        raw_output = resp.content.strip()
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3]
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3]
            
        parsed_data = json.loads(raw_output)
        return {"status": "success", "data": parsed_data}

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
    
@app.post("/api/match-job")
def match_job(job: JobDescription):
    global USER_RESUME_TEXT
    if not USER_RESUME_TEXT:
        return {"status": "error", "message": "Please upload a resume first."}
    try:
        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.7,
                       groq_api_key=os.getenv("GROQ_API_KEY"))
        prompt_template = f"""
        USER'S RESUME CONTEXT: {USER_RESUME_TEXT}
        JOB TITLE: {{title}} | COMPANY: {{company}} | DESCRIPTION: {{description}}
        Write a highly tailored 3-sentence cover letter introduction.
        Return ONLY the cover letter text.
        """
        prompt = PromptTemplate.from_template(prompt_template)
        chain  = prompt | llm
        resp   = chain.invoke({"title": job.title, "company": job.company,
                               "description": job.description[:3000]})
        return {"status": "success", "ai_cover_letter": resp.content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class FormQuestions(BaseModel):
    questions: list[str]
    job_description: str = ""  # 🌟 NEW: Extension will send the JD text here!

@app.post("/api/answer-questions")
def answer_questions(data: FormQuestions, user=Depends(get_current_user)):
    profile = get_user_profile(user["user_id"])
    if not profile or not profile.get("master_qa_data"):
        return {"status": "error", "message": "Please fill out your Master Profile Form on the dashboard first."}
        
    try:
        # We upgraded to Llama-3-8b for speed, but you can change back to 70b if you have credits
        llm = ChatGroq(model="llama3-8b-8192", temperature=0.2, groq_api_key=os.getenv("GROQ_API_KEY"))
        
        prompt_template = f"""
        You are an elite AI recruiting agent filling out an application.
        
        CANDIDATE'S VERIFIED MASTER DATA:
        {profile.get('master_qa_data')}
        
        JOB DESCRIPTION (For ATS Targeting):
        {{job_description}}
        
        QUESTIONS TO ANSWER:
        {{questions}}
        
        INSTRUCTIONS:
        1. Calculate a MATCH SCORE (0-100) based on how well the candidate's data fits the Job Description. 
        2. Identify 3 ATS Keywords from the Job Description and subtly inject them into any text-based answers.
        3. Keep answers extremely short. Numbers must be pure digits (e.g. "2").
        4. You MUST output EXACTLY in this format: MatchScore|Answer1|Answer2|...
           Example: 85|Yes|2|Python, AWS|Data Not Found
        """
        
        prompt = PromptTemplate.from_template(prompt_template)
        chain  = prompt | llm
        resp   = chain.invoke({"questions": str(data.questions), "job_description": data.job_description[:3000]})
        
        parts = [p.strip() for p in resp.content.split("|")]
        match_score = int(parts[0]) if parts[0].isdigit() else 85
        answers = parts[1:]
        
        return {"status": "success", "answers": answers, "match_score": match_score}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class CookiePayload(BaseModel):
    li_at: str
    jsessionid: str

@app.get("/api/check-cookies")
def check_cookies():
    cookies = get_cookies()
    li_ok = bool(cookies.get("li_at"))
    js_ok = bool(cookies.get("JSESSIONID"))
    return {"status": "ok" if (li_ok and js_ok) else "missing",
            "li_at_present": li_ok, "jsessionid_present": js_ok}

@app.get("/api/validate-cookies")
async def validate_cookies_endpoint():
    result = await validate_cookies()
    return {"status": "valid" if result["valid"] else "invalid",
            "reason": result["reason"]}

@app.post("/api/save-cookies")
async def save_cookies_endpoint(payload: CookiePayload):
    if not payload.li_at.strip() or not payload.jsessionid.strip():
        return {"status": "error", "message": "Both values required."}
    if len(payload.li_at) < 50:
        return {"status": "error", "message": "li_at looks too short."}
    success = save_cookies_to_env(payload.li_at, payload.jsessionid)
    return {"status": "success" if success else "error"}


# ══════════════════════════════════════════════════════════════════
# NEW ENDPOINTS — SaaS Layer
# ══════════════════════════════════════════════════════════════════

# ── Profile management ───────────────────────────────────────────

class ProfilePayload(BaseModel):
    li_at:              str = ""
    jsessionid:         str = ""
    target_roles:       list[str] = ["AI Engineer", "AIML", "Agentic AI"]
    target_locations:   list[str] = ["Mumbai", "Remote", "Noida"]
    phone:              str = ""
    current_location:   str = ""
    notice_period_days: int = 30
    current_ctc_inr:    int = 0
    expected_ctc_inr:   int = 0
    years_experience:   float = 0
    skills:             str = ""
    education:          str = ""
    sender_email:       str = ""
    sender_phone:       str = ""
    app_password:       str = ""
    key_achievements:   str = ""
    why_good_fit:       str = ""
    master_qa_data:     str = "" # 🌟 NEW: The Master Form Data!

@app.post("/api/profile/save")
def save_profile(payload: ProfilePayload,
                 user=Depends(get_current_user)):
    user_id = user["user_id"]
    with get_db() as conn:
        conn.execute("""
            INSERT INTO candidate_profiles
              (user_id, li_at, jsessionid, target_roles, target_locations,
               phone, current_location, notice_period_days,
               current_ctc_inr, expected_ctc_inr, years_experience,
               skills, education, sender_email, sender_phone, 
               app_password, key_achievements, why_good_fit, master_qa_data, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
              li_at=excluded.li_at,
              jsessionid=excluded.jsessionid,
              target_roles=excluded.target_roles,
              target_locations=excluded.target_locations,
              phone=excluded.phone,
              current_location=excluded.current_location,
              notice_period_days=excluded.notice_period_days,
              current_ctc_inr=excluded.current_ctc_inr,
              expected_ctc_inr=excluded.expected_ctc_inr,
              years_experience=excluded.years_experience,
              skills=excluded.skills,
              education=excluded.education,
              sender_email=excluded.sender_email,
              sender_phone=excluded.sender_phone,
              app_password=excluded.app_password,
              key_achievements=excluded.key_achievements,
              why_good_fit=excluded.why_good_fit,
              master_qa_data=excluded.master_qa_data,
              updated_at=datetime('now')
        """, (
            user_id,
            payload.li_at.strip(), payload.jsessionid.strip(),
            json.dumps(payload.target_roles),
            json.dumps(payload.target_locations),
            payload.phone, payload.current_location,
            payload.notice_period_days,
            payload.current_ctc_inr, payload.expected_ctc_inr,
            payload.years_experience,
            payload.skills, payload.education,
            payload.sender_email, payload.sender_phone,
            payload.app_password, payload.key_achievements, payload.why_good_fit, payload.master_qa_data
        ))
    log_activity(user_id, "profile_updated", "Candidate Master Form saved.")
    return {"status": "success", "message": "Profile saved."}


@app.get("/api/profile")
def get_profile(user=Depends(get_current_user)):
    profile = get_user_profile(user["user_id"])
    if not profile:
        return {"status": "error", "message": "No profile found."}
    # Don't expose raw cookie values in GET response
    profile.pop("li_at", None)
    profile.pop("jsessionid", None)
    return {"status": "success", "profile": profile}


# ── Auto-trigger: extension polls for new jobs ───────────────────

@app.get("/api/pending-jobs")
def pending_jobs(user=Depends(get_current_user)):
    # FORCE the limit to 1 so the extension doesn't get overwhelmed!
    jobs = get_pending_jobs_for_user(user["user_id"], limit=1)
    return {"status": "ok", "jobs": jobs}


# ── Apply completion hook ────────────────────────────────────────
# ── Apply completion hook ────────────────────────────────────────
from typing import Optional

class FormQuestions(BaseModel):
    questions: list[str]
    job_description: str = ""  # 🌟 NEW: Extension will send the JD text here!

@app.post("/api/answer-questions")
def answer_questions(data: FormQuestions, user=Depends(get_current_user)):
    profile = get_user_profile(user["user_id"])
    if not profile or not profile.get("master_qa_data"):
        return {"status": "error", "message": "Please fill out your Master Profile Form on the dashboard first."}
        
    try:
        # We upgraded to Llama-3-8b for speed, but you can change back to 70b if you have credits
        llm = ChatGroq(model="llama3-8b-8192", temperature=0.2, groq_api_key=os.getenv("GROQ_API_KEY"))
        
        prompt_template = f"""
        You are an elite AI recruiting agent filling out an application.
        
        CANDIDATE'S VERIFIED MASTER DATA:
        {profile.get('master_qa_data')}
        
        JOB DESCRIPTION (For ATS Targeting):
        {{job_description}}
        
        QUESTIONS TO ANSWER:
        {{questions}}
        
        INSTRUCTIONS:
        1. Calculate a MATCH SCORE (0-100) based on how well the candidate's data fits the Job Description. 
        2. Identify 3 ATS Keywords from the Job Description and subtly inject them into any text-based answers.
        3. Keep answers extremely short. Numbers must be pure digits (e.g. "2").
        4. You MUST output EXACTLY in this format: MatchScore|Answer1|Answer2|...
           Example: 85|Yes|2|Python, AWS|Data Not Found
        """
        
        prompt = PromptTemplate.from_template(prompt_template)
        chain  = prompt | llm
        resp   = chain.invoke({"questions": str(data.questions), "job_description": data.job_description[:3000]})
        
        parts = [p.strip() for p in resp.content.split("|")]
        match_score = int(parts[0]) if parts[0].isdigit() else 85
        answers = parts[1:]
        
        return {"status": "success", "answers": answers, "match_score": match_score}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Update Job Applied Hook to save the Match Score ---
class FormQuestions(BaseModel):
    questions: list[str]
    job_description: str = ""  # 🌟 NEW: Extension will send the JD text here!

@app.post("/api/answer-questions")
def answer_questions(data: FormQuestions, user=Depends(get_current_user)):
    profile = get_user_profile(user["user_id"])
    if not profile or not profile.get("master_qa_data"):
        return {"status": "error", "message": "Please fill out your Master Profile Form on the dashboard first."}
        
    try:
        # 🌟 THE FIX: Using the smaller 8B model to save your API credits!
        llm = ChatGroq(model="llama3-8b-8192", temperature=0.2, groq_api_key=os.getenv("GROQ_API_KEY"))
        
        prompt_template = f"""
        You are an elite AI recruiting agent filling out an application.
        
        CANDIDATE'S VERIFIED MASTER DATA:
        {profile.get('master_qa_data')}
        
        JOB DESCRIPTION (For ATS Targeting):
        {{job_description}}
        
        QUESTIONS TO ANSWER:
        {{questions}}
        
        INSTRUCTIONS:
        1. Calculate a MATCH SCORE (0-100) based on how well the candidate's data fits the Job Description. 
        2. Identify 3 ATS Keywords from the Job Description and subtly inject them into any text-based answers.
        3. Keep answers extremely short. Numbers must be pure digits (e.g. "2").
        4. You MUST output EXACTLY in this format: MatchScore|Answer1|Answer2|...
           Example: 85|Yes|2|Python, AWS|Data Not Found
        """
        
        prompt = PromptTemplate.from_template(prompt_template)
        chain  = prompt | llm
        resp   = chain.invoke({"questions": str(data.questions), "job_description": data.job_description[:3000]})
        
        parts = [p.strip() for p in resp.content.split("|")]
        match_score = int(parts[0]) if parts[0].isdigit() else 85
        answers = parts[1:]
        
        return {"status": "success", "answers": answers, "match_score": match_score}
    except Exception as e:
        return {"status": "error", "message": str(e)}
# --- Update Job Applied Hook to save the Match Score ---
class JobAppliedPayload(BaseModel):
    job_id: str
    status: str
    job_url: str
    title: str
    company: str
    hr_name: str | None = None 
    hr_url: str | None = None  
    match_score: int = 0  # 🌟 NEW

@app.post("/api/job-applied")
def mark_job_applied(req: JobAppliedPayload, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    uid = user["user_id"]
    with get_db() as conn:
        conn.execute("DELETE FROM jobs_queue WHERE user_id=? AND job_id=?", (uid, req.job_id))
        if req.status == "success":
            conn.execute(
                """INSERT INTO applied_jobs (user_id, job_id, job_url, title, company, status, match_score)
                   VALUES (%s, %s, %s, %s, %s, 'applied', %s)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET match_score=EXCLUDED.match_score""",
                (uid, req.job_id, req.job_url, req.title, req.company, req.match_score) 
            )
        elif req.status in ["skipped", "error"]:
            conn.execute("INSERT INTO ignored_jobs (user_id, job_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (uid, req.job_id))

    if req.status == "success":
        log_activity(uid, "applied", f"Applied to {req.title} at {req.company} [Match: {req.match_score}%]")
        background_tasks.add_task(execute_outreach_flow, uid, req.job_id, req.company, req.title, req.hr_name, req.hr_url)
    return {"status": "ok"}
# ── Dashboard endpoints ──────────────────────────────────────────

@app.get("/api/dashboard/jobs")
def dashboard_jobs(user=Depends(get_current_user), limit: int = 50):
    """Returns the user's applied jobs list for the dashboard table."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT title, company, job_url, applied_at, status
               FROM applied_jobs WHERE user_id=?
               ORDER BY applied_at DESC LIMIT ?""",
            (user["user_id"], limit)
        ).fetchall()
        
    jobs = []
    for r in rows:
        d = dict(r)
        if d["applied_at"]:
            d["applied_at"] = str(d["applied_at"]) # FIX: Convert datetime to string first
            if not d["applied_at"].endswith("Z"):
                d["applied_at"] += "Z"
        jobs.append(d)
        
    return {"status": "ok", "jobs": jobs}

@app.get("/api/dashboard/logs")
def dashboard_logs(user=Depends(get_current_user), limit: int = 100):
    """Returns the activity log feed."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT event_type, message, created_at
               FROM activity_logs WHERE user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (user["user_id"], limit)
        ).fetchall()
        
    logs = []
    for r in rows:
        d = dict(r)
        if d["created_at"]:
            d["created_at"] = str(d["created_at"]) # FIX: Convert datetime to string first
            if not d["created_at"].endswith("Z"):
                d["created_at"] += "Z"
        logs.append(d)
        
    return {"status": "ok", "logs": logs}


@app.get("/api/dashboard/stats")
def dashboard_stats(user=Depends(get_current_user)):
    """Returns counts for the stats cards at the top of the dashboard."""
    uid = user["user_id"]
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM applied_jobs WHERE user_id=?", (uid,)
        ).fetchone()[0]
        today = conn.execute(
            """SELECT COUNT(*) FROM applied_jobs
               WHERE user_id=? AND date(applied_at, '+5 hours', '+30 minutes')=date('now', '+5 hours', '+30 minutes')""", (uid,)
        ).fetchone()[0]
        hr_found = conn.execute(
            "SELECT COUNT(*) FROM hr_contacts WHERE user_id=?", (uid,)
        ).fetchone()[0]
        messages_sent = conn.execute(
            """SELECT COUNT(*) FROM outreach_logs
               WHERE user_id=? AND status='sent'""", (uid,)
        ).fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM jobs_queue WHERE user_id=? AND picked_up=0", (uid,)
        ).fetchone()[0]
    return {
        "status":        "ok",
        "total_applied": total,
        "applied_today": today,
        "hr_found":      hr_found,
        "messages_sent": messages_sent,
        "queued_jobs":   queued,
    }


# ── Agent monitor ────────────────────────────────────────────────

@app.get("/api/agent/status")
def agent_status(user=Depends(get_current_user)):
    """
    Returns whether the background scanner is running,
    last activity time, and any recent errors.
    """
    uid = user["user_id"]
    scheduler_info = get_scheduler_status()

    with get_db() as conn:
        last_log = conn.execute(
            """SELECT message, created_at FROM activity_logs
               WHERE user_id=? ORDER BY created_at DESC LIMIT 1""", (uid,)
        ).fetchone()
        recent_errors = conn.execute(
            """SELECT COUNT(*) FROM activity_logs
               WHERE user_id=? AND event_type='error'
               AND datetime(created_at) >= datetime('now', '-1 hour')""", (uid,)
        ).fetchone()[0]

    return {
        "status":          "ok",
        "scanner_running": scheduler_info["running"],
        "next_scan":       scheduler_info["next_run"],
        "last_activity":   dict(last_log) if last_log else None,
        "errors_last_hour": recent_errors,
    }

from pydantic import BaseModel

class CookiePayload(BaseModel):
    li_at: str
    jsessionid: str

@app.post("/api/save-cookies")
def save_cookies(payload: CookiePayload):
    """Receives fresh LinkedIn cookies from the candidate's Chrome Extension."""
    try:
        # Phase 1: Update the environment variables in memory so the monitor works immediately
        os.environ["LINKEDIN_LI_AT"] = payload.li_at
        os.environ["LINKEDIN_JSESSIONID"] = payload.jsessionid
        
        # NOTE: For a multi-tenant SaaS, you wouldn't save these to the global .env or memory. 
        # You would save them directly to the `users` table in PostgreSQL so each user 
        # has their own dedicated scraper session. We will migrate to that in Phase 4.
        
        return {"status": "success", "message": "Cookies synchronized successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}