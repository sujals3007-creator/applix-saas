"""
main.py  —  AI Job Agent SaaS Backend  v3.1 (Fixed)

FIXES:
  - All SQL queries use %s placeholders (PostgreSQL)
  - /api/save-cookies now saves to the user's DB profile (not .env)
  - /api/answer-questions has a hard YOE cap (max 40 years)
  - master_qa_data is included in DB insert
  - Proper multi-user isolation throughout
"""
from outreach import execute_outreach_flow   #from outrech file it importrs the execute outreach flow 
from fastapi import FastAPI, UploadFile, File, Depends, BackgroundTasks #from fastapi library we import Fastapi, and uploadfile users can upload files, and files comes from upload file, depends is used to verify users, backgroundTasks are used to do to things in background like sending mail to hr or find mail of hr 
from fastapi.middleware.cors import CORSMiddleware #helps our frontend and backend server to be accepted and run on browser
from pydantic import BaseModel #checks the json data is correct or not 
from typing import Optional #using optional as if we can allow two values in which one can be the real value and second can be optional
import os, io, json, re, logging  #importing operating system, Io used for handling in memory files, json, regular expression used for searching text, logging
import pdfplumber #used to extract text from pdf files
from dotenv import load_dotenv # load secret keys and variables from .env file
from langchain_groq import ChatGroq #to communicate with groq model
from langchain_core.prompts import PromptTemplate #it used for long prompts

load_dotenv() # calls for environment variables (.env)
logging.basicConfig(level=logging.INFO) #logs in console 
logger = logging.getLogger(__name__) #saas api console 

from database import (  #importing database
    init_db, get_db, log_activity, mark_job_applied, #initialise database like setting up environment, get db means opening and closing of databse, log activity records activity of users doing in website, marking to jobs that have been applied 
    get_pending_jobs_for_user, get_user_profile #jobs thatare in queue, store the details of users skils from databse
)
from auth import router as auth_router, get_current_user # seccurity guard like wrong login details 
from monitor import start_scheduler, stop_scheduler, get_scheduler_status # starts checking for new jobs every 5 min, stops auto scans, checks whether the agent is active or not
from cookie_auth import get_cookies, validate_cookies, save_cookies_to_env #check cookies 

app = FastAPI(title="AI Job Agent SaaS API", version="3.1") #title of the fastapi and the verson

app.add_middleware(
    CORSMiddleware, #helps our acts a bridge between frontend and backend just like a middleware
    allow_origins=["*"], # allow clients to communicate to servers
    allow_credentials=True, #allow cookies and auth coming from frontend
    allow_methods=["*"], # allows get, post,put, delete
    allow_headers=["*"], #specify which request should be permitted and using * means every request is allowed
)

app.include_router(auth_router) # make user login and registration work on your website


# ── Startup / shutdown ───────────────────────────────────────────

@app.on_event("startup") #preparing database by running scheduler functions 
async def startup(): #triggers task to be done in background
    init_db() #triggers databse 
    start_scheduler() # starts the schedule of finding new jobs on linkedin


@app.on_event("shutdown")# runs to stop the server 
async def shutdown(): #calls for stutdown for closing tasks
    stop_scheduler() #stops the scheduler 


# ══════════════════════════════════════════════════════════════════
# EXISTING ENDPOINTS
# ══════════════════════════════════════════════════════════════════

class JobDescription(BaseModel): # funtion which is using basemodel for ensuring the data extracted should be in correct data and type
    title: str #title should be in string 
    company: str #company name should be in a string 
    description: str #description should be in string 

USER_RESUME_TEXT = "" #stroring the data extracted from resume and calculates the ats 

@app.get("/") # get request made by fastapi to check if the backend is running perfectly
def read_root(): #function ask for health check of backend
    return {"status": "Active", "message": "AI Job Agent SaaS Backend is running!"} # ask for the specific details listed in the code

@app.post("/api/parse-resume-to-form") #post request made by frontend when the user upload a resume it parse the resume and then fill the master form automatically
async def parse_resume_to_form(file: UploadFile = File(...), user=Depends(get_current_user)): #check for vali authentitcaton user befor parsing the resume 
    """Takes a PDF, extracts text, and uses Groq to auto-fill the Master Form questions.""" #
    if not file.filename.endswith(".pdf"): #checks if the file uploaded is pdf
        return {"status": "error", "message": "Only PDF files are supported."} #if not file than gives this
    
    try: # 
        contents = await file.read() #  reads the file uploads 
        resume_text = "" #save the data in string in resume_text
        with pdfplumber.open(io.BytesIO(contents)) as pdf: #converts the text into bytes and then usinf pdyplumber extracts the resume content 
            for page in pdf.pages: # goes page by page in sequence to extract the text from resume 
                text = page.extract_text() #extract text from the specific page we are on 
                if text: resume_text += text + "\n" #added text to the variable if the text wa extracted 

        llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.1, groq_api_key=os.getenv("GROQ_API_KEY")) #creates a json format of the text extrated from the resume 
        
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
        
        prompt = PromptTemplate.from_template(prompt_template) # PromptTemplate is taken from the template's langchain library tell me the 
        chain = prompt | llm # this is a pipeline of linking the prompt and the groq model
        resp = chain.invoke({"resume_text": resume_text}) # the model has now processed the the prompt 
        
        raw_output = resp.content.strip() #takes the raw text respomse from the model and remove the leading and trailing spaces from the text using strip()
        if raw_output.startswith("```json"): # raw output that also give some starting given my model
            raw_output = raw_output[7:-3] #this if statement removes that staring text and keeping it fully json 
        elif raw_output.startswith("```"): #if the if statement is not true 
            raw_output = raw_output[3:-3] # we will remove the raw output 
            
        parsed_data = json.loads(raw_output) # uses loads() to take the json and convert it into dictionary

        # Hard-cap YOE fields at 40 in case the AI hallucinates
        yoe_fields = ["q_yoe", "q_yoe_python", "q_yoe_github", "q_yoe_ml", "q_yoe_cloud", "q_yoe_react", "q_yoe_java", "q_yoe_sql"] #contains different skills years of experience
        for yf in yoe_fields:  # yf means each variable from the list above 
            if yf in parsed_data: #if the elements in the field are parsed each element from the list
                try: #try 
                    val = int(str(parsed_data[yf]).replace("+", "").strip()) #when we have the years of experience we take that value in string and then remove any character and keep it a number of yoe and then remove the lending and trailing part using strip() and in the end converting the string into the integer value 
                    parsed_data[yf] = min(val, 40) #it shows the minimum and maximum number of experience 
                except: #expext is used when try is useless
                    parsed_data[yf] = 0 if yf != "q_yoe" else 2 # it give default value as 0 yoe or 2 yoe if the skills is prior

        return {"status": "success", "data": parsed_data} # give the success message to web dasboard by filling the form directly 

    except Exception as e:
        return {"status": "error", "message": str(e)}  # if the process fails it sends the error message 
    
    
@app.post("/api/match-job") # post request for matching jobs 
def match_job(job: JobDescription): # matching job or generatingb a cover letter 
    global USER_RESUME_TEXT #text extracted from users resume
    if not USER_RESUME_TEXT: # if he does not getv any resume text
        return {"status": "error", "message": "Please upload a resume first."} #it returns an error message 
    try: #using try function 
        llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.7, groq_api_key=os.getenv("GROQ_API_KEY"))#using llama model of groq with a 0.7 temperature creating more randomness and creating text using groq api from the environment variables
        prompt_template = f""" 
        USER'S RESUME CONTEXT: {USER_RESUME_TEXT}
        JOB TITLE: {{title}} | COMPANY: {{company}} | DESCRIPTION: {{description}}
        Write a highly tailored 3-sentence cover letter introduction.
        Return ONLY the cover letter text.
        """    #writing a prompt that wll be send to groq
        prompt = PromptTemplate.from_template(prompt_template) #taking the prompt template from the langchain library and the prompt we have craeted just now 
        chain  = prompt | llm  #creating a pipeline 
        resp   = chain.invoke({"title": job.title, "company": job.company,
                               "description": job.description[:3000]}) #executing the pipeline
        return {"status": "success", "ai_cover_letter": resp.content} #if this process succeed then it sends an success message 
    except Exception as e: #or we use except statment if fails 
        return {"status": "error", "message": str(e)} #sends fail message 

class FormQuestions(BaseModel): # checks the data is correct or not in the master form 
    questions: list[str] #questions should be in string
    job_description: str = ""  #if no job description is provided it store it into the empty string 

@app.post("/api/answer-questions") ##post request to answer questions 
def answer_questions(data: FormQuestions, user=Depends(get_current_user)):#gets the users data from the databse and use it to answer questions of the master form
    profile = get_user_profile(user["user_id"]) # ask for data from the dataset for the specific user
    if not profile or not profile.get("master_qa_data"): # if does not found any users data from the dataset
        return {"status": "error", "message": "Please fill out your Master Profile Form on the dashboard first."} #gives error message 
    
    # Safely read years_experience from the profile (used as a hard cap below)
    try: #then try 
        profile_yoe = float(profile.get("years_experience") or 0) # profile years of experince in float 
        profile_yoe = min(profile_yoe, 40)  # FIX: DB cap too #set the max and min yoe
    except: #use another yoe
        profile_yoe = 2.0 #sets 2 yoe as default in exxceptional case

    try: # then we try
        llm = ChatGroq( #groq model
            model="openai/gpt-oss-120b", # 🌟 FIX: Switched to 70b model for higher TPM limits #mode; version
            temperature=0.0, #dead temperrature
            max_tokens=4096,           #tokens limit of answering questions is set to 4096
            groq_api_key=os.getenv("GROQ_API_KEY"),   #takes the api key from .env
            model_kwargs={"response_format": {"type": "json_object"}}   #takes the output in jason format so it can answer to the specific questions and correct answer
        )

        # ── Strip [Type: ...] hints from questions before sending to AI ──
        clean_questions = [
            re.sub(r'\s*\[Type:[^\]]*\]', '', q).strip() #clean the answer by remove the lending and trailing part 
            for q in data.questions  # loop that goes to each question one ny one 
        ]
        numbered_questions = "\n".join(  # joins all the questions with numbers 
            f"{i+1}. {q}" for i, q in enumerate(clean_questions)  # gives index for every question and fill it one by one
        )

        current_ctc  = int(profile.get("current_ctc_inr")  or 800000) # for currect ctc questions or default fils 80000
        expected_ctc = int(profile.get("expected_ctc_inr") or 1000000) # for expected ctc
        notice_days  = int(profile.get("notice_period_days") or 30) #notice period

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
        resp = llm.invoke(prompt_template) # sends the formatted prompt to the groq model so that it can generate a response 
        raw = resp.content.strip()  # removes the lending and triling part fom the response from the model's output 

        json_start = raw.find('{') # search for the curly braces that is the start of the json response given by model
        if json_start == -1: #if the response does not have any curly braces 
            raise ValueError(f"No JSON object in model response: {raw[:300]}") #raise error that no json object 
        depth = 0  # this means the they have found the exact end of that JSON object
        json_end = -1 # means the code does not found proper Json OBJECT
        in_string = False # MEANS IT HAS not STARTED inside the string 
        escape_next = False # meas the json is not treating the character as a special character
        for idx in range(json_start, len(raw)): # starts from the json start which is the curly braces and ends till len of the string response
            ch = raw[idx] # determines the text stored in raw variable 
            if escape_next: # it is used for checking if the statement started inside the string 
                escape_next = False  #means not in the string 
                continue  # continue to next statement
            if ch == '\\' and in_string:   # its shows the special chracter is inside the string 
                escape_next = True #as it is true
                continue  #continue to nect 
            if ch == '"':   #this tells the characters are not in strng
                in_string = not in_string  #as this shows its not in string 
                continue   #continue to nect statements
            if in_string:  #it shows its in strinng
                continue ##c
            if ch == '{':  #starts the json response from here
                depth += 1 #and now it will start reading the response from here
            elif ch == '}':  #this is the closing indicates the json response ends here
                depth -= 1 #so we should not look for more from now on
                if depth == 0:  #when all the curly braces has ended 
                    json_end = idx  #when the ed of all response
                    break # the loop ends here 
        if json_end == -1: # it does not find any closing curly braces
            logger.warning(f"Truncated JSON detected, attempting repair: {raw[json_start:json_start+200]}") #gives an error and try to repair or add any closing braces 
            partial = raw[json_start:] #starts from the raw json response and ends with the end of response 
            open_brackets = partial.count('[') - partial.count(']') #to get the number of all the opeing and closing brackets in the response by subtracting the opening and clsoing brackets 
            open_braces   = partial.count('{') - partial.count('}') #same for curly braces
            partial = partial.rstrip().rstrip(',') #removing the trailing and , from the response 
            partial += ']' * open_brackets + '}' * open_braces #counts the total [] and {} so that i cant be used for form filling process 
            try: #try statements 
                parsed = json.loads(partial) #loads the new updated json from partial and converts to dictionary
                raw = partial #upated the raw json with partial
                json_end = len(partial) - 1  #to match the lenght of new partial data 
            except Exception:  #except
                raise ValueError(f"Unrecoverable truncated JSON: {raw[json_start:json_start+300]}") #give erroe
        raw = raw[json_start:json_end + 1] # includes the ending character is also added to our string 

        parsed = json.loads(raw) #updated the final and clean will be used for the rest of the program 
        match_score_raw = parsed.get("score", 50) #default value of 50 if no value in the response
        try: # try
            match_score = max(0, min(100, int(match_score_raw)))  #value stays in int and the range is 0 to 100
        except (ValueError, TypeError): #give error
            match_score = 50 # match score a default value as 50
        answers = [str(a).strip() for a in parsed.get("answers", [])] #convert each part of the answers to string and strip it and give the answers

        while len(answers) < len(clean_questions): #as the answers less than the questions 
            answers.append("Yes")  #append answers 
        answers = answers[:len(clean_questions)]  #finds the answer from the loop of json
        
        capped_answers = []  #it will be used to store and format processed answers 
        for i, ans in enumerate(answers):  #gives the indiex of iteams list and also the ans 
            q = clean_questions[i].lower() if i < len(clean_questions) else ""  #lowercase the clean questions 

            ans = re.sub(r'\*\*[^*]*\*\*', '', ans).strip() #removes the specific character 
            ans = re.sub(r'\[Type:[^\]]*\]', '', ans).strip()  #removes
            ans = re.sub(r'\[type:[^\]]*\]', '', ans).strip()  #removes 
            is_yoe_question = any(k in q for k in ["experience", "years", "how many", "yoe"])  #for specific questions it find for words like the l=elements in the list 
            
            is_identity = any(k in q for k in ["phone", "mobile", "contact number", "email", "name", "location", "city", "address"]) #same 
            if not is_identity and re.search(r'(phone|mobile|contact)\s*(number|no\.?)?', q): #search
                is_identity = True   #the identity is true
            if is_identity and ans.strip().lower() in ("yes", "no", "true", "false", "2", "1", "0"):  #checks the data fits or not
                if re.search(r'(phone|mobile|contact)', q):  #search for specific domain
                    raw_phone = str(profile.get("phone") or "").replace(" ","").replace("-","").replace("+","").replace("91","",1).strip()  #for phone 
                    ans = raw_phone if raw_phone else ans  #phone
                elif "email" in q:   #email
                    em = profile.get("sender_email") or ""  #email 
                    ans = em if em else ans   #email
                elif any(k in q for k in ["location","city","address"]):    #address search
                    loc = profile.get("current_location") or ""   #loc
                    ans = loc if loc else ans   #loc
            
            if is_yoe_question:   #experience questions
                try:  #try
                    num = float(str(ans).replace("+", "").replace(",","").strip())  #replaces + to "" to empty strings in experince answers 
                    if num > 40:  #if exp is more than 40
                        num = float(profile_yoe) #years of exp in flaot
                    ans = str(int(round(num)))  #ans in int and then convert to string 
                except (ValueError, TypeError): #or error 
                    ans = "2"   #default 2
            capped_answers.append(ans)  #final and formatted answer that will be return in the dashboard
        
        return {"status": "success", "answers": capped_answers, "match_score": match_score} #if succeed sends a success message 
    except Exception as e:  # otherwise 
        import traceback  #handling errors
        from fastapi.responses import JSONResponse  #importing jsonresponse from fastapi responses
        return JSONResponse( #response 
            status_code=200,  #status of scceful request
            content={"status": "error", "message": str(e), "answers": [], "match_score": 0}  #gets the specific data responses 
        )


# ══════════════════════════════════════════════════════════════════
# NEW ENDPOINTS — SaaS Layer
# ══════════════════════════════════════════════════════════════════

class ProfilePayload(BaseModel):  #checks the json data correct or not 
    target_roles:       list[str] = ["AI Engineer", "AIML", "Agentic AI"]  #role
    target_locations:   list[str] = ["Mumbai", "Remote", "Noida"]  #loc
    phone:              str = "" ##
    current_location:   str = ""#
    notice_period_days: int = 30#
    current_ctc_inr:    int = 0     #
    expected_ctc_inr:   int = 0    #
    years_experience:   float = 0   #
    skills:             str = ""   #
    education:          str = ""   #
    sender_email:       str = ""   #
    sender_phone:       str = ""    #
    app_password:       str = ""    #
    key_achievements:   str = ""   #
    why_good_fit:       str = ""    #
    master_qa_data:     str = ""    #

@app.post("/api/profile/save")   #post request for saving profile 
def save_profile(payload: ProfilePayload, user=Depends(get_current_user)):   #after the data is set it saves it from get current user 
    user_id = user["user_id"]  #user id from databse

    # FIX: Cap YOE at 40 before saving to DB
    yoe = min(float(payload.years_experience or 0), 40.0)   #the minimum is 0 or the the real exp or max is 40

    with get_db() as conn:   #conn-connection  this helps insert or update values from the dataset 
        conn.execute("""    #tell to execute the following changes in the dataset 
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
            user_id, #user id means user info
            json.dumps(payload.target_roles),  #to store it properly in database the target roles
            json.dumps(payload.target_locations), #dumps location in dataset as json 
            payload.phone, payload.current_location, # database storing ways 
            payload.notice_period_days,  #database storing 
            payload.current_ctc_inr, payload.expected_ctc_inr, #database 
            yoe, #database
            payload.skills, payload.education, #data
            payload.sender_email, payload.sender_phone,  #data
            payload.app_password, payload.key_achievements, payload.why_good_fit,   #data
            payload.master_qa_data   #data
        ))
    log_activity(user_id, "profile_updated", "Candidate Master Form saved.") #saving c=master form and the actvity 
    return {"status": "success", "message": "Profile saved."}   #sends success message 


@app.get("/api/profile")   #get request to profile 
def get_profile(user=Depends(get_current_user)):  #looks for only authenticate profles from the dataset
    profile = get_user_profile(user["user_id"]) ## gets user if from datset
    if not profile:  #if not auth
        return {"status": "error", "message": "No profile found."}  ##error
    profile.pop("li_at", None) #li at cookie
    profile.pop("jsessionid", None)  #jsession cookie
    return {"status": "success", "profile": profile}  #sucess


# ── Auto-trigger: extension polls for new jobs ───────────────────

@app.get("/api/pending-jobs")   #queue jobs 
def pending_jobs(user=Depends(get_current_user)):  #from dataset 
    jobs = get_pending_jobs_for_user(user["user_id"], limit=1)  #one at a time
    return {"status": "ok", "jobs": jobs}  #feeback of th task 


# ── Apply completion hook ────────────────────────────────────────

class JobAppliedPayload(BaseModel):  #authenticate job applies
    job_id: str  #
    status: str    #
    job_url: str   #
    title: str    #
    company: str    #
    hr_name: Optional[str] = None    #
    hr_url: Optional[str] = None    #
    match_score: int = 0     #

@app.post("/api/job-applied") #post request with job info which are done applying 
def job_applied(req: JobAppliedPayload, background_tasks: BackgroundTasks, user=Depends(get_current_user)): #gets the job details an save to dataset
    uid = user["user_id"]  #to user id 
    with get_db() as conn:  #connects to dataset to make or update changes 
        # FIX: Use %s placeholders for PostgreSQL
        conn.execute("DELETE FROM jobs_queue WHERE user_id=%s AND job_id=%s", (uid, req.job_id))  #delete the queue jobs 
        if req.status == "success":  #if successs
            conn.execute( #execute following changes in the dataset
                """INSERT INTO applied_jobs (user_id, job_id, job_url, title, company, status, match_score)
                   VALUES (%s, %s, %s, %s, %s, 'applied', %s)
                   ON CONFLICT(user_id, job_id) DO UPDATE SET match_score=EXCLUDED.match_score""",
                (uid, req.job_id, req.job_url, req.title, req.company, req.match_score) ##adds job id, job url, title, comapny and match score to dataset
            )
        elif req.status in ["skipped", "error"]:  #if the job is skipped it does not add it to the dataset with the applied jobs and adds to ignore job list so our agent dosent apply to it again
            conn.execute(    #conn execute changes 
                "INSERT INTO ignored_jobs (user_id, job_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (uid, req.job_id) #Req job id
            )

    if req.status == "success":  #if sucesss
            log_activity(uid, "applied", f"Applied to {req.title} at {req.company} [Match: {req.match_score}%]") #saves the data 
            
            # 🌟 FIX: Uncommented to re-enable the AI Outreach Engine using Apollo!
            background_tasks.add_task( #for outreach
                execute_outreach_flow, uid, req.job_id, req.company, req.title, req.hr_name, req.hr_url # saces the detail of hr 
            )
    return {"status": "ok"}  #give status as ok 


# ── Dashboard endpoints ──────────────────────────────────────────

@app.get("/api/dashboard/jobs") #dashboard update
def dashboard_jobs(user=Depends(get_current_user), limit: int = 50): #add daya to dashboard
    with get_db() as conn: #make changes to dataset
        rows = conn.execute( #execute 
            """SELECT title, company, job_url, applied_at, status, match_score
               FROM applied_jobs WHERE user_id=%s
               ORDER BY applied_at DESC LIMIT %s""",
            (user["user_id"], limit)  #user id is updates 
        ).fetchall() #fetch all the rws and colums 
        
    jobs = []  # craete a empty list
    for r in rows: #rows staore in r
        d = dict(r)  # stores in dictionary
        if d.get("applied_at"):  # applied at this job 
            d["applied_at"] = str(d["applied_at"])  #appplied at means the time of applying to job 
            if not d["applied_at"].endswith("Z"):  #give the time with adding z to make ot utctime 
                d["applied_at"] += "Z"  #same 
        jobs.append(d)  #then appends this data 
        
    return {"status": "ok", "jobs": jobs} #returns an status

@app.get("/api/dashboard/logs") #recent acivity happended and add the dataset
def dashboard_logs(user=Depends(get_current_user), limit: int = 100): #gets the user data 
    with get_db() as conn: #making changes to dataset
        rows = conn.execute(   #connects the data 
            """SELECT event_type, message, created_at
               FROM activity_logs WHERE user_id=%s
               ORDER BY created_at DESC LIMIT %s""",
            (user["user_id"], limit) #user id
        ).fetchall() #fetch all the data 
        
    logs = []  #craete a empty list
    for r in rows: #happen in rows 
        d = dict(r)   #convert to dictionary
        if d.get("created_at"):   #created at that time 
            d["created_at"] = str(d["created_at"])  #time 
            if not d["created_at"].endswith("Z"):  #adds the z to make it utc
                d["created_at"] += "Z"   #same
        logs.append(d)   #adds the changes to dataset
        
    return {"status": "ok", "logs": logs}  #return status 


@app.get("/api/dashboard/stats")  #dashboard status
def dashboard_stats(user=Depends(get_current_user)):   #gets the user dataset from dashboard status 
    uid = user["user_id"]  #user if
    with get_db() as conn: #conn
        total = conn.execute(  #conn
            "SELECT COUNT(*) FROM applied_jobs WHERE user_id=%s", (uid,)
        ).fetchone()[0]  #calling the very first row 
        today = conn.execute(   #conn
            """SELECT COUNT(*) FROM applied_jobs
               WHERE user_id=%s
               AND DATE(applied_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata') = CURRENT_DATE""",
            (uid,)  #user id
        ).fetchone()[0] #calling the very first row 
        hr_found = conn.execute(
            "SELECT COUNT(*) FROM hr_contacts WHERE user_id=%s", (uid,) #details from dataset
        ).fetchone()[0]#calling the very first row 
        messages_sent = conn.execute( #user log
            """SELECT COUNT(*) FROM outreach_logs WHERE user_id=%s AND status='sent'""", #activity log
            (uid,) #
        ).fetchone()[0] #calling the very first row 
        queued = conn.execute( #activity log
            "SELECT COUNT(*) FROM jobs_queue WHERE user_id=%s AND picked_up=0", (uid,) ####
        ).fetchone()[0] #calling the very first row 

    return {
        "status":        "ok",  #
        "total_applied": total,   #
        "applied_today": today,   #
        "hr_found":      hr_found,   #
        "messages_sent": messages_sent,   #
        "queued_jobs":   queued,    #
    }


@app.get("/api/agent/status")   #retrieve the agent status 
def agent_status(user=Depends(get_current_user)):  #fom dataset
    uid = user["user_id"]    #user id
    scheduler_info = get_scheduler_status()   #scheduling the time 

    with get_db() as conn:  #conn
        last_log = conn.execute(  #conn
            """SELECT message, created_at FROM activity_logs   
               WHERE user_id=%s ORDER BY created_at DESC LIMIT 1""", (uid,)
        ).fetchone()  #select the specific row from the dataset
        recent_errors = conn.execute(   #conn
            """SELECT COUNT(*) FROM activity_logs
               WHERE user_id=%s AND event_type='error'
               AND created_at >= NOW() - INTERVAL '1 hour'""", (uid,)
        ).fetchone()[0]  #calling the very first row 

    return {  #return 
        "status":           "ok",     #staus 
        "scanner_running":  scheduler_info["running"],   ##
        "next_scan":        scheduler_info["next_run"],  ##
        "last_activity":    dict(last_log) if last_log else None,   #
        "errors_last_hour": recent_errors,   ##
    }

if __name__ == "__main__":  #main calling 
    import uvicorn   #fastapi server
    port = int(os.environ.get("PORT", 8080))   ##server 
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)   #function calling 