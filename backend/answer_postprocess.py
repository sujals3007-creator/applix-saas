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


# ── main entry ───────────────────────────────────────────────────

def postprocess_answer(raw_q: str, clean_q: str, ans: str, profile: dict, profile_yoe: float) -> str:
    q = (clean_q or "").lower().strip()
    ans = str(ans or "")
    ans = re.sub(r"\*\*[^*]*\*\*", "", ans)
    ans = re.sub(r"\[type:[^\]]*\]", "", ans, flags=re.I).strip()

    options = parse_options(raw_q)
    hint = parse_type_hint(raw_q)
    boolean_q = bool(BOOL_LEAD.match(q)) and not NUMERIC_LEAD.match(q)

    # 1/2. Choice questions: answer MUST be one of the offered options
    if options:
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

    # 5. Identity fields: never let a placeholder answer through
    is_identity = any(k in q for k in ["phone", "mobile", "contact number", "email", "name",
                                       "location", "city", "address"])
    if is_identity and low in ("yes", "no", "true", "false", "2", "1", "0"):
        if re.search(r"(phone|mobile|contact)", q):
            raw_phone = (str(profile.get("phone") or "").replace(" ", "").replace("-", "")
                         .replace("+", "").replace("91", "", 1).strip())
            ans = raw_phone or ans
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

    # 6. URLs: model sometimes returns {"url": "..."} text
    if ans.startswith("{") and "http" in ans:
        m = re.search(r"https?://[^\s\"'}\]]+", ans)
        if m:
            ans = m.group(0)

    return ans