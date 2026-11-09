"""
answer_postprocess.py - turns the model's raw answer into something the
Easy Apply form will actually accept, for every question type:

  1. Dropdown / radio with [Options: A | B | C]  -> exact option string
  2. Multi-select ([Type: ...checkbox/multi...]) -> several options joined by " | "
  3. Yes/No questions without options             -> "Yes" / "No"
  4. "How many years..." numeric questions        -> whole number (capped)
  5. Identity fields (phone/email/city/name)      -> real profile values
  6. URLs, free text, salary, notice period       -> cleaned, otherwise untouched
"""
import re
import difflib
from datetime import date, datetime, timedelta

PLACEHOLDERS = {"", "select an option", "select", "choose", "please select",
                "-- select --", "--", "select one", "choose an option"}
YES_WORDS = {"yes", "y", "true"}
NO_WORDS = {"no", "n", "false"}

BOOL_LEAD = re.compile(
    r"^\s*(do|does|did|are|is|am|have|has|had|can|could|will|would|should|were|was)\b", re.I)
NUMERIC_LEAD = re.compile(r"^\s*(how many|how much|how long|number of)\b", re.I)
NUMERIC_HINTS = ("years of", "year of", "in years", "yoe", "years' experience", "years experience")
NOT_YOE = ("ctc", "salary", "compensation", "lpa", "notice", "gpa", "cgpa", "stipend", "package")


# ── parsing helpers ──────────────────────────────────────────────

def parse_options(raw_q: str) -> list:
    m = re.search(r"\[Options:\s*(.*?)\]", raw_q or "", re.I | re.S)
    if not m:
        return []
    opts = [o.strip() for o in m.group(1).split("|")]
    return [o for o in opts if o.lower() not in PLACEHOLDERS]


def parse_type_hint(raw_q: str) -> str:
    m = re.search(r"\[Type:\s*([^\]]*)\]", raw_q or "", re.I)
    return m.group(1).strip().lower() if m else ""


def first_number(text: str):
    m = re.search(r"\d+(?:\.\d+)?", str(text).replace(",", ""))
    return float(m.group(0)) if m else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+ ]", "", str(s).lower()).strip()


def _number_fits_option(num: float, option: str) -> bool:
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", option.replace(",", ""))]
    low = option.lower()
    if not nums:
        return False
    if len(nums) >= 2 and re.search(r"\d\s*(-|–|to)\s*\d", low):
        return nums[0] <= num <= nums[1]
    n = nums[0]
    if "+" in low or any(w in low for w in ("more than", "above", "over", "at least", "plus")):
        return num >= n
    if any(w in low for w in ("less than", "under", "below", "<")):
        return num < n
    return abs(num - n) < 0.5


STOP = {"the", "a", "an", "of", "in", "and", "or", "i", "is", "are", "am", "would", "say", "so", "yes", "no",
        "have", "has", "my", "to", "with", "for", "on", "at", "it", "that", "this", "degree", "level", "completed"}


def _canon(text: str) -> str:
    """Map degree / level spellings to one word so 'B.E. Computer Engineering' ~ "Bachelor's Degree"."""
    t = str(text).lower().replace("\u2019", "'")
    t = re.sub(r"\bph\.?\s?d\b|\bdoctor\w*", " doctorate ", t)
    t = re.sub(r"\bm\.?\s?tech\b|\bm\.?\s?e\b|\bm\.?\s?sc\b|\bmca\b|\bmba\b|\bmaster\w*|\bpost\s?graduate\b", " master ", t)
    t = re.sub(r"\bb\.?\s?tech\b|\bb\.?\s?e\b|\bb\.?\s?sc\b|\bbca\b|\bbachelor\w*|\bunder\s?graduate\b", " bachelor ", t)
    return t


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]+", _canon(text)) if w not in STOP and len(w) > 1}


def _overlap_option(ans: str, options: list):
    """Option sharing the most meaningful words with the answer (None if nothing in common)."""
    a = _tokens(ans)
    if not a:
        return None
    best, best_score = None, 0.0
    for o in options:
        ot = _tokens(o)
        if not ot:
            continue
        score = len(a & ot) / len(a | ot)
        if score > best_score:
            best, best_score = o, score
    return best if best_score >= 0.2 else None


def match_option(ans: str, options: list):
    """Best option for ans, or None."""
    a = str(ans).strip()
    if not options:
        return None
    by_lower = {o.lower(): o for o in options}
    if a.lower() in by_lower:
        return by_lower[a.lower()]
    by_norm = {_norm(o): o for o in options}
    if _norm(a) in by_norm:
        return by_norm[_norm(a)]
    if a.lower() in YES_WORDS | NO_WORDS:
        want = "yes" if a.lower() in YES_WORDS else "no"
        for o in options:
            if _norm(o).startswith(want):
                return o
    num = first_number(a)
    if num is not None:
        for o in options:
            if _number_fits_option(num, o):
                return o
    na = _norm(a)
    if na:
        for o in options:
            no = _norm(o)
            if na in no or (no and no in na):
                return o
    hit = _overlap_option(a, options)
    if hit:
        return hit
    close = difflib.get_close_matches(a, options, n=1, cutoff=0.4)
    return close[0] if close else None


def _best_effort_option(ans, options, boolean_q):
    hit = match_option(ans, options)
    if hit:
        return hit
    if boolean_q:                                   # unsure on a yes/no style dropdown -> "Yes" option
        for o in options:
            if _norm(o).startswith("yes"):
                return o
    close = difflib.get_close_matches(str(ans), options, n=1, cutoff=0.0)
    return close[0] if close else options[0]


def _clean_phone(raw) -> str:
    """Digits only; drop a leading +91/91 country code only when the number is longer than 10 digits."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    return digits[-10:] if len(digits) > 10 else digits


def _as_int(x, default=0) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


SALARY_WORDS = ("ctc", "salary", "compensation", "package", "remuneration", "stipend", "lpa", "lakh")


JUNK_ANSWERS = {"", "yes", "no", "n/a", "na", "none", "null", "unknown", "data not found", "not found", "not available"}
_FACT_STOP = STOP | {"what", "which", "your", "you", "please", "enter", "provide", "current", "do", "does", "how", "many", "much",
                     "are", "can", "will", "highest", "type", "text"}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def lookup_fact(q: str, master_qa: str):
    """Find the saved Master-Profile line ("- Label [TYPE:x]: value") whose label best matches the question."""
    qt = {_stem(w) for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in _FACT_STOP and len(w) > 1}
    best, best_score = None, 0.0
    for line in (master_qa or "").splitlines():
        m = re.match(r"\s*[-*]?\s*(.+?)\s*(?:\[[^\]]*\])?\s*:\s*(.+)$", line)
        if not m:
            continue
        label, value = m.group(1), m.group(2).strip()
        lt = {_stem(w) for w in re.findall(r"[a-z0-9]+", label.lower()) if w not in _FACT_STOP and len(w) > 1}
        if not lt or not value or value.lower() in JUNK_ANSWERS:
            continue
        score = len(lt & qt) / len(lt)
        if score > best_score or (score == best_score and best is not None and len(lt) > best[2]):
            best, best_score = (label, value, len(lt)), score
    return best[1] if best and best_score >= 0.99 else None


def _boolean_rule(q: str, profile: dict):
    """Questions where a blind 'Yes' is almost always wrong. Returns 'No' or None.
    Skipped when the saved master profile talks about the topic (then the model's own answer is trusted)."""
    master = (profile.get("master_qa_data") or "").lower()
    if re.search(r"sponsor", q) and re.search(r"requir|need|will you|now or in the future|support", q) and "sponsor" not in master:
        return "No"
    if re.search(r"\b(convicted|felony|misdemeanou?r|criminal (record|offen[cs]e)|background check.*(fail|reject))", q) and "convict" not in master and "criminal" not in master:
        return "No"
    if re.search(r"non[- ]?compete|restrictive covenant|service (bond|agreement)|currently (employed|working) (at|by|for) (this|the) company", q):
        return "No"
    return None


def profile_backed_option(q: str, ans: str, options: list, profile: dict, profile_yoe: float):
    """For dropdown/radio questions whose options are numeric ranges (notice period, years of experience)
    pick the option that fits the numbers saved on the profile - unless the model already picked a real option."""
    exact = {o.lower() for o in options}
    if str(ans).strip().lower() in exact:
        return None
    asks_notice = "notice" in q or "how soon" in q or ("join" in q and "day" in q) or "availab" in q
    asks_yoe = ("year" in q and ("experience" in q or "exp" in q)) and not asks_notice
    if asks_notice and not _is_yes_no_opts(options):
        days = _as_int(profile.get("notice_period_days"), 30)
        if days <= 0:
            for o in options:
                if "immediate" in o.lower():
                    return o
        for o in options:
            if _number_fits_option(float(days), o):
                return o
    if asks_yoe and not _is_yes_no_opts(options):
        for o in options:
            if _number_fits_option(float(profile_yoe), o):
                return o
    return None


def _is_yes_no_opts(options: list) -> bool:
    return {_norm(o) for o in options} <= {"yes", "no"}


def _fmt_lpa(rupees: int) -> str:
    v = rupees / 100000.0
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def to_date_text(ans: str, fmt_hint: str, profile: dict) -> str:
    """Date answer in the format the field wants. Falls back to today + notice period."""
    d = None
    a = str(ans).strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            d = datetime.strptime(a, f).date(); break
        except ValueError:
            pass
    if d is None:
        d = date.today() + timedelta(days=_as_int(profile.get("notice_period_days"), 30))
    h = (fmt_hint or "").lower()
    if h.startswith("dd"):
        return d.strftime("%d/%m/%Y")
    if h.startswith("mm"):
        return d.strftime("%m/%d/%Y")
    return d.isoformat()


def profile_backed_override(q: str, ans: str, profile: dict):
    """
    Deterministic fixes for fields the model keeps getting wrong ("Yes" in a salary box...).
    Returns a replacement answer, or None to keep the model's answer.
    Only fires when the model's answer is clearly unusable for that kind of field.
    """
    num = first_number(ans)

    # Salary / CTC -> exact numbers saved on the profile (rupees, or lakhs when the field says LPA / lakh)
    if any(w in q for w in SALARY_WORDS):
        asks_current = ("current" in q or "present" in q or "last drawn" in q) and "expect" not in q
        want = _as_int(profile.get("current_ctc_inr") if asks_current else profile.get("expected_ctc_inr"))
        in_lakhs = "lpa" in q or "lakh" in q or "lac" in q
        if in_lakhs:
            if num is not None and num >= 1000:                 # model answered in rupees -> convert
                return _fmt_lpa(int(num))
            if (num is None or num <= 0) and want:
                return _fmt_lpa(want)
            return None
        if want and (num is None or num < 1000):
            return str(want)
        return None

    # Notice period / "in how many days can you join" -> notice_period_days
    asks_days = ("how many days" in q or "how soon" in q or "notice period" in q
                 or ("join" in q and "day" in q) or "days to join" in q)
    if asks_days and num is None:
        days = profile.get("notice_period_days")
        if days is not None:
            return str(_as_int(days, 30))

    # "Rate your X skills on a scale of 1-10" -> a number inside the range (never "Yes")
    m = re.search(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", q)
    if m and ("rate" in q or "rating" in q or "scale" in q):
        lo, hi = float(m.group(1)), float(m.group(2))
        if hi > lo and (num is None or not (lo <= num <= hi)):
            return str(int(round(lo + (hi - lo) * 0.7)))      # 1-10 -> 7
    return None


# ── main entry ───────────────────────────────────────────────────

def postprocess_answer(raw_q: str, clean_q: str, ans: str, profile: dict, profile_yoe: float) -> str:
    q = re.sub(r"\[(?:options|format|type):[^\]]*\]", " ", (clean_q or ""), flags=re.I).lower().strip()
    q = re.sub(r"\s+", " ", q)
    ans = str(ans or "")
    ans = re.sub(r"\*\*[^*]*\*\*", "", ans)
    ans = re.sub(r"\[type:[^\]]*\]", "", ans, flags=re.I).strip()

    options = parse_options(raw_q)
    hint = parse_type_hint(raw_q)
    boolean_q = bool(BOOL_LEAD.match(q)) and not NUMERIC_LEAD.match(q)

    # 0. The model gave a non-answer ("Yes", "Data Not Found"...) to a question that is NOT yes/no:
    #    look the real value up in the saved profile instead of typing "Yes" into a text box / dropdown.
    yn_q = _is_yes_no_opts(options) if options else boolean_q
    if not yn_q and (_norm(ans) in JUNK_ANSWERS or re.match(r"^(yes|no)\b", ans.strip().lower())):
        fact = lookup_fact(q, profile.get("master_qa_data") or "")
        if fact:
            ans = fact
        elif re.search(r"\b(why|fit|motivat|describe|tell us|cover letter|about yourself|summar)", q) and not options:
            ans = (profile.get("why_good_fit") or profile.get("key_achievements") or ans)

    rule = _boolean_rule(q, profile)
    if rule and yn_q:
        return (match_option(rule, options) or rule) if options else rule

    # 1/2. Choice questions: answer MUST be one of the offered options
    if options:
        forced = profile_backed_option(q, ans, options, profile, profile_yoe)
        if forced:
            return forced
        if any(k in hint for k in ("check", "multi")):
            parts = [p for p in re.split(r"\s*(?:\||;|,)\s*", ans) if p]
            picked = []
            for p in parts:
                hit = match_option(p, options)
                if hit and hit not in picked:
                    picked.append(hit)
            return " | ".join(picked) if picked else options[0]
        return _best_effort_option(ans, options, boolean_q)

    low = ans.lower().strip(" .")

    # 3. Yes/No question without options
    if boolean_q:
        if low.startswith("yes") or low in YES_WORDS:
            return "Yes"
        if low.startswith("no") or low in NO_WORDS:
            return "No"
        num = first_number(ans)
        if num is not None and len(ans.split()) <= 2:       # model answered a yes/no with a number
            return "Yes" if num > 0 else "No"
        return ans

    # 4b. Profile-backed numeric fields (salary, notice period, 1-10 ratings)
    fixed = profile_backed_override(q, ans, profile)
    if fixed is not None:
        return fixed

    # 5. Identity fields: never let a placeholder answer through
    is_identity = any(k in q for k in ["phone", "mobile", "contact number", "email", "name",
                                       "location", "city", "address"])
    if is_identity and low in ("yes", "no", "true", "false", "2", "1", "0"):
        if re.search(r"(phone|mobile|contact)", q):
            ans = _clean_phone(profile.get("phone")) or ans
        elif "email" in q:
            ans = profile.get("sender_email") or ans
        elif any(k in q for k in ["location", "city", "address"]):
            ans = profile.get("current_location") or ans

    # 4. Numeric "years of experience" style questions
    is_numeric = bool(NUMERIC_LEAD.match(q)) or (
        any(h in q for h in NUMERIC_HINTS) or ("experience" in q and "years" in q))
    if is_numeric and not any(k in q for k in NOT_YOE):
        num = first_number(ans)
        if num is None:
            ans = "0" if low in NO_WORDS or low in ("none", "nil", "n/a") else str(int(profile_yoe))
        else:
            if num > 40:
                num = float(profile_yoe)
            ans = str(int(round(num)))
        return ans

    # 5b. Date fields ([Type: date] or a [Format: mm/dd/yyyy] hint added by the extension)
    fmt = re.search(r"\[format:\s*([^\]]*)\]", raw_q or "", re.I)
    if hint == "date" or fmt:
        return to_date_text(ans, fmt.group(1) if fmt else "", profile)

    # 6. URLs: model sometimes returns {"url": "..."} text
    if ans.startswith("{") and "http" in ans:
        m = re.search(r"https?://[^\s\"'}\]]+", ans)
        if m:
            ans = m.group(0)

    return ans