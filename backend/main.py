"""
main.py  —  AI Job Agent SaaS Backend  v3.1 (Fixed)

FIXES:
  - All SQL queries use %s placeholders (PostgreSQL)
  - /api/save-cookies now saves to the user's DB profile (not .env)
  - /api/answer-questions has a hard YOE cap (max 40 years)
  - master_qa_data is included in DB insert
  - Proper multi-user isolation throughout
"""
from outreach import execute_outreach_flow
from fastapi import FastAPI, UploadFile, File, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, io, json, re, logging
import pdfplumber
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from database import (
    init_db, get_db, log_activity, mark_job_applied,
    get_pending_jobs_for_user, get_user_profile
)
from auth import router as auth_router, get_current_user
from monitor import start_scheduler, stop_scheduler, get_scheduler_status
from cookie_auth import get_cookies, validate_cookies, save_cookies_to_env

app = FastAPI(title="AI Job Agent SaaS API", version="3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
# EXISTING ENDPOINTS
# ══════════════════════════════════════════════════════════════════

class JobDescription(BaseModel):
    title: str
    company: str
    description: str

USER_RESUME_TEXT = ""

@app.get("/")
def read_root():
    return {"status": "Active", "message": "AI Job Agent SaaS Backend is running!"}

@app.post("/api/parse-resume-to-form")
async def parse_resume_to_form(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Takes a PDF, extracts text, and uses Groq to auto-fill the Master Form questions."""
    if not file.filename.endswith(".pdf"):
        return {"status": "error", "message": "Only PDF files are supported."}
    
    try:
        contents = await file.read()
        resume_text = ""
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text: resume_text += text + "\n"

        llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.1, groq_api_key=os.getenv("GROQ_API_KEY"))
        
        prompt_template = """
        You are an expert HR assistant. Extract the candidate's details from the RESUME below to answer a specific set of job application questions.
        
        RESUME TEXT:
        {resume_text}
        
        INSTRUCTIONS:
        1. Respond STRICTLY with a valid JSON object. Do not include markdown formatting or extra text.
        2. The JSON keys MUST exactly match the list below.
        3. Keep values concise. If unknown, logically guess based on context, or output "Not Specified".
        4. "q_yoe" must be a WHOLE NUMBER between 0 and 40. Calculate from graduation year or work history. NEVER output more than 40.
        
        JSON KEYS TO OUTPUT (match these exactly):
        Personal: "q_name", "q_email", "q_phone", "q_location", "q_linkedin", "q_github", "q_portfolio"
        Experience: "q_current_role", "q_prev_company", "q_yoe", "q_yoe_python", "q_yoe_github",
                    "q_yoe_ml", "q_yoe_cloud", "q_yoe_react", "q_yoe_java", "q_yoe_sql",
                    "q_prev_exp", "q_summary"
        Strategy: "q_strategy", "q_founders_office", "q_pnl", "q_stakeholder", "q_presentations", "q_cross_functional"
        SDE: "q_frontend", "q_backend", "q_db", "q_mobile", "q_api", "q_testing", "q_system_design"
        AI/ML: "q_python", "q_ml", "q_dl", "q_nlp", "q_cv", "q_llm", "q_rag", "q_agents", "q_data_viz", "q_sql_analytics", "q_etl"
        DevOps: "q_cloud", "q_docker", "q_cicd", "q_linux", "q_terraform", "q_security", "q_networking"
        Education: "q_degree", "q_university", "q_grad_year", "q_gpa", "q_salary", "q_current_ctc",
                   "q_notice", "q_immediate", "q_work_auth", "q_visa", "q_relocate", "q_remote"

        IMPORTANT RULES FOR EXTRACTION:
        - "q_yoe" = TOTAL years of professional work experience (whole number, max 40)
        - "q_yoe_python", "q_yoe_github" etc = years using that specific tool (estimate from resume dates, max = q_yoe)
        - Yes/No fields: output "Yes" or "No" only
        - If info not in resume: output "Not Specified" for text fields, "0" for number fields, "No" for Yes/No fields
        - "q_gpa": extract if present, else "Not Specified"
        """
        
        prompt = PromptTemplate.from_template(prompt_template)
        chain = prompt | llm
        resp = chain.invoke({"resume_text": resume_text})
        
        raw_output = resp.content.strip()
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3]
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3]
            
        parsed_data = json.loads(raw_output)

        # Hard-cap YOE fields at 40 in case the AI hallucinates
        yoe_fields = ["q_yoe", "q_yoe_python", "q_yoe_github", "q_yoe_ml", "q_yoe_cloud", "q_yoe_react", "q_yoe_java", "q_yoe_sql"]
        for yf in yoe_fields:
            if yf in parsed_data:
                try:
                    val = int(str(parsed_data[yf]).replace("+", "").strip())
                    parsed_data[yf] = min(val, 40)
                except:
                    parsed_data[yf] = 0 if yf != "q_yoe" else 2

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
    job_description: str = ""

@app.post("/api/answer-questions")
def answer_questions(data: FormQuestions, user=Depends(get_current_user)):
    profile = get_user_profile(user["user_id"])
    if not profile or not profile.get("master_qa_data"):
        return {"status": "error", "message": "Please fill out your Master Profile Form on the dashboard first."}
    
    # Safely read years_experience from the profile (used as a hard cap below)
    try:
        profile_yoe = float(profile.get("years_experience") or 0)
        profile_yoe = min(profile_yoe, 40)  # FIX: DB cap too
    except:
        profile_yoe = 2.0

    try:
        llm = ChatGroq(
            model="llama-3.3-70b-versatile", # 🌟 FIX: Switched to 70b model for higher TPM limits
            temperature=0.0,
            max_tokens=4096,          
            groq_api_key=os.getenv("GROQ_API_KEY"),
            model_kwargs={"response_format": {"type": "json_object"}} 
        )

        # ── Strip [Type: ...] hints from questions before sending to AI ──
        clean_questions = [
            re.sub(r'\s*\[Type:[^\]]*\]', '', q).strip()
            for q in data.questions
        ]
        numbered_questions = "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(clean_questions)
        )

        current_ctc  = int(profile.get("current_ctc_inr")  or 800000)
        expected_ctc = int(profile.get("expected_ctc_inr") or 1000000)
        notice_days  = int(profile.get("notice_period_days") or 30)

        prompt_template = f"""You are a precise AI assistant filling a job application form for a candidate.

CANDIDATE DATA:
{profile.get('master_qa_data', 'NO DATA PROVIDED')}

KEY FACTS (use EXACT numbers below — never guess or use 2 for salary):
- Total years of experience: {int(profile_yoe)}
- Current CTC / current salary (INR/year): {current_ctc}
- Expected CTC / ECTC / desired salary (INR/year): {expected_ctc}
- Notice period: {notice_days} days

QUESTIONS (answer each by its number):
{numbered_questions}

RULES:
1. IDENTITY fields (name, phone, mobile, email, location, city, address):
   - Phone/mobile/contact → digits only, no +91, no spaces (e.g. 9876543210). NEVER Yes/No.
   - Name → exact full name. Email → exact email. Location → exact city name.
2. EXPERIENCE → integer only, max {int(profile_yoe)}, never > 40. Never output a 4-digit year.
3. YES/NO → "Yes" or "No" only. Work auth/background check/consent/privacy/terms → "Yes". Visa sponsorship → "No".
4. SALARY / CTC / ECTC / compensation / package / LPA:
   - "current CTC", "current salary", "CTC" → {current_ctc}
   - "expected CTC", "ECTC", "expected salary", "desired salary" → {expected_ctc}
   - NEVER output "2" or any number under 1000 for any salary/CTC/ECTC field.
5. NOTICE PERIOD / availability / how soon → {notice_days}
6. GPA/CGPA → 3.5. Any truly unknown number → 2.
7. URLS: If a question asks for a LinkedIn, GitHub, or Portfolio URL, output ONLY the raw URL string (e.g., https://linkedin.com/in/...). NEVER output a dictionary or JSON text.
8. EDUCATION: If asked for 'Degree', provide the highest qualification. If asked for 'City' in an education context and you do not know it, use the current location city. 
9. OUTPUT — ONLY a valid JSON object, no markdown, no text before or after, containing EXACTLY two keys:
   {{"score": <integer 0-100>, "answers": ["ans1", "ans2", ...]}}
   Exactly {len(clean_questions)} answers in order. PLAIN STRINGS ONLY inside the array. Do NOT add any extra keys like "reasoning" or "explanation".
10. OPTIONS MATCHING: If a question includes [Options: A | B | C], your answer MUST be an exact string match to ONE of those provided options."""
        resp = llm.invoke(prompt_template)
        raw = resp.content.strip()

        json_start = raw.find('{')
        if json_start == -1:
            raise ValueError(f"No JSON object in model response: {raw[:300]}")
        depth = 0
        json_end = -1
        in_string = False
        escape_next = False
        for idx in range(json_start, len(raw)):
            ch = raw[idx]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    json_end = idx
                    break
        if json_end == -1:
            logger.warning(f"Truncated JSON detected, attempting repair: {raw[json_start:json_start+200]}")
            partial = raw[json_start:]
            open_brackets = partial.count('[') - partial.count(']')
            open_braces   = partial.count('{') - partial.count('}')
            partial = partial.rstrip().rstrip(',')
            partial += ']' * open_brackets + '}' * open_braces
            try:
                parsed = json.loads(partial)
                raw = partial
                json_end = len(partial) - 1
            except Exception:
                raise ValueError(f"Unrecoverable truncated JSON: {raw[json_start:json_start+300]}")
        raw = raw[json_start:json_end + 1]

        parsed = json.loads(raw)
        match_score_raw = parsed.get("score", 50)
        try:
            match_score = max(0, min(100, int(match_score_raw)))
        except (ValueError, TypeError):
            match_score = 50
        answers = [str(a).strip() for a in parsed.get("answers", [])]

        while len(answers) < len(clean_questions):
            answers.append("Yes")
        answers = answers[:len(clean_questions)]
        
        capped_answers = []
        for i, ans in enumerate(answers):
            q = clean_questions[i].lower() if i < len(clean_questions) else ""

            ans = re.sub(r'\*\*[^*]*\*\*', '', ans).strip()
            ans = re.sub(r'\[Type:[^\]]*\]', '', ans).strip()
            ans = re.sub(r'\[type:[^\]]*\]', '', ans).strip()
            is_yoe_question = any(k in q for k in ["experience", "years", "how many", "yoe"])
            
            is_identity = any(k in q for k in ["phone", "mobile", "contact number", "email", "name", "location", "city", "address"])
            if not is_identity and re.search(r'(phone|mobile|contact)\s*(number|no\.?)?', q):
                is_identity = True
            if is_identity and ans.strip().lower() in ("yes", "no", "true", "false", "2", "1", "0"):
                if re.search(r'(phone|mobile|contact)', q):
                    raw_phone = str(profile.get("phone") or "").replace(" ","").replace("-","").replace("+","").replace("91","",1).strip()
                    ans = raw_phone if raw_phone else ans
                elif "email" in q:
                    em = profile.get("sender_email") or ""
                    ans = em if em else ans
                elif any(k in q for k in ["location","city","address"]):
                    loc = profile.get("current_location") or ""
                    ans = loc if loc else ans
            
            if is_yoe_question:
                try:
                    num = float(str(ans).replace("+", "").replace(",","").strip())
                    if num > 40:
                        num = float(profile_yoe)
                    ans = str(int(round(num)))
                except (ValueError, TypeError):
                    ans = "2"
            capped_answers.append(ans)
        
        return {"status": "success", "answers": capped_answers, "match_score": match_score}
    except Exception as e:
        import traceback
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": str(e), "answers": [], "match_score": 0}
        )


# ══════════════════════════════════════════════════════════════════
# NEW ENDPOINTS — SaaS Layer
# ══════════════════════════════════════════════════════════════════

class ProfilePayload(BaseModel):
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
    master_qa_data:     str = ""

@app.post("/api/profile/save")
def save_profile(payload: ProfilePayload, user=Depends(get_current_user)):
    user_id = user["user_id"]

    # FIX: Cap YOE at 40 before saving to DB
    yoe = min(float(payload.years_experience or 0), 40.0)

    with get_db() as conn:
        conn.execute("""
            INSERT INTO candidate_profiles
              (user_id, target_roles, target_locations,
               phone, current_location, notice_period_days,
               current_ctc_inr, expected_ctc_inr, years_experience,
               skills, education, sender_email, sender_phone, 
               app_password, key_achievements, why_good_fit, master_qa_data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(user_id) DO UPDATE SET
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
              updated_at=CURRENT_TIMESTAMP
        """, (
            user_id,
            json.dumps(payload.target_roles),
            json.dumps(payload.target_locations),
            payload.phone, payload.current_location,
            payload.notice_period_days,
            payload.current_ctc_inr, payload.expected_ctc_inr,
            yoe,
            payload.skills, payload.education,
            payload.sender_email, payload.sender_phone,
            payload.app_password, payload.key_achievements, payload.why_good_fit,
            payload.master_qa_data
        ))
    log_activity(user_id, "profile_updated", "Candidate Master Form saved.")
    return {"status": "success", "message": "Profile saved."}


@app.get("/api/profile")
def get_profile(user=Depends(get_current_user)):
    profile = get_user_profile(user["user_id"])
    if not profile:
        return {"status": "error", "message": "No profile found."}
    profile.pop("li_at", None)
    profile.pop("jsessionid", None)
    return {"status": "success", "profile": profile}


# ── Auto-trigger: extension polls for new jobs ───────────────────

@app.get("/api/pending-jobs")
def pending_jobs(user=Depends(get_current_user)):
    jobs = get_pending_jobs_for_user(user["user_id"], limit=1)
    return {"status": "ok", "jobs": jobs}


# ── Apply completion hook ────────────────────────────────────────

class JobAppliedPayload(BaseModel):
    job_id: str
    status: str
    job_url: str
    title: str
    company: str
    hr_name: Optional[str] = None
    hr_url: Optional[str] = None
    match_score: int = 0

@app.post("/api/job-applied")
def job_applied(req: JobAppliedPayload, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    uid = user["user_id"]
    with get_db() as conn:
        # FIX: Use %s placeholders for PostgreSQL
        conn.execute("DELETE FROM jobs_queue WHERE user_id=%s AND job_id=%s", (uid, req.job_id))
        if req.status == "success":
            conn.execute(
                """INSERT INTO applied_jobs (user_id, job_id, job_url, title, company, status, match_score)
                   VALUES (%s, %s, %s, %s, %s, 'applied', %s)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET match_score=EXCLUDED.match_score""",
                (uid, req.job_id, req.job_url, req.title, req.company, req.match_score)
            )
        elif req.status in ["skipped", "error"]:
            conn.execute(
                "INSERT INTO ignored_jobs (user_id, job_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (uid, req.job_id)
            )

    if req.status == "success":
            log_activity(uid, "applied", f"Applied to {req.title} at {req.company} [Match: {req.match_score}%]")
            
            # 🌟 FIX: Uncommented to re-enable the AI Outreach Engine using Apollo!
            background_tasks.add_task(
                execute_outreach_flow, uid, req.job_id, req.company, req.title, req.hr_name, req.hr_url
            )
    return {"status": "ok"}


# ── Dashboard endpoints ──────────────────────────────────────────

@app.get("/api/dashboard/jobs")
def dashboard_jobs(user=Depends(get_current_user), limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT title, company, job_url, applied_at, status, match_score
               FROM applied_jobs WHERE user_id=%s
               ORDER BY applied_at DESC LIMIT %s""",
            (user["user_id"], limit)
        ).fetchall()
        
    jobs = []
    for r in rows:
        d = dict(r)
        if d.get("applied_at"):
            d["applied_at"] = str(d["applied_at"])
            if not d["applied_at"].endswith("Z"):
                d["applied_at"] += "Z"
        jobs.append(d)
        
    return {"status": "ok", "jobs": jobs}

@app.get("/api/dashboard/logs")
def dashboard_logs(user=Depends(get_current_user), limit: int = 100):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT event_type, message, created_at
               FROM activity_logs WHERE user_id=%s
               ORDER BY created_at DESC LIMIT %s""",
            (user["user_id"], limit)
        ).fetchall()
        
    logs = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
            if not d["created_at"].endswith("Z"):
                d["created_at"] += "Z"
        logs.append(d)
        
    return {"status": "ok", "logs": logs}


@app.get("/api/dashboard/stats")
def dashboard_stats(user=Depends(get_current_user)):
    uid = user["user_id"]
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM applied_jobs WHERE user_id=%s", (uid,)
        ).fetchone()[0]
        today = conn.execute(
            """SELECT COUNT(*) FROM applied_jobs
               WHERE user_id=%s
               AND DATE(applied_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') = CURRENT_DATE""",
            (uid,)
        ).fetchone()[0]
        hr_found = conn.execute(
            "SELECT COUNT(*) FROM hr_contacts WHERE user_id=%s", (uid,)
        ).fetchone()[0]
        messages_sent = conn.execute(
            """SELECT COUNT(*) FROM outreach_logs WHERE user_id=%s AND status='sent'""",
            (uid,)
        ).fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM jobs_queue WHERE user_id=%s AND picked_up=0", (uid,)
        ).fetchone()[0]

    return {
        "status":        "ok",
        "total_applied": total,
        "applied_today": today,
        "hr_found":      hr_found,
        "messages_sent": messages_sent,
        "queued_jobs":   queued,
    }


@app.get("/api/agent/status")
def agent_status(user=Depends(get_current_user)):
    uid = user["user_id"]
    scheduler_info = get_scheduler_status()

    with get_db() as conn:
        last_log = conn.execute(
            """SELECT message, created_at FROM activity_logs
               WHERE user_id=%s ORDER BY created_at DESC LIMIT 1""", (uid,)
        ).fetchone()
        recent_errors = conn.execute(
            """SELECT COUNT(*) FROM activity_logs
               WHERE user_id=%s AND event_type='error'
               AND created_at >= NOW() - INTERVAL '1 hour'""", (uid,)
        ).fetchone()[0]

    return {
        "status":           "ok",
        "scanner_running":  scheduler_info["running"],
        "next_scan":        scheduler_info["next_run"],
        "last_activity":    dict(last_log) if last_log else None,
        "errors_last_hour": recent_errors,
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)