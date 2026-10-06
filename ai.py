"""Claude helpers: rank jobs against your resume, and draft answers for questions the Answers sheet doesn't cover.

Needs ANTHROPIC_API_KEY. Model: APPLYBOT_MODEL (default claude-opus-5-5; claude-haiku-4-5 is ~4x cheaper for ranking).
Every answer is built only from the active person's facts (cover_letter.FACTS) + profile — Claude is told to skip rather than guess.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests

import cover_letter

MODEL = os.environ.get("APPLYBOT_MODEL", "claude-opus-5-5")
# Work-authorization line for the active person (friends' profiles set their own)
SITUATION = ""
_client = None


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def ask_json(system, prompt, schema, effort="low", max_tokens=2000):
    """One Claude call that must return JSON matching `schema`. None on refusal."""
    config = {"format": {"type": "json_schema", "schema": schema}}
    params = dict(model=MODEL, max_tokens=max_tokens, cache_control={"type": "ephemeral"},
                  system=system, messages=[{"role": "user", "content": prompt}], output_config=config)
    if MODEL.startswith("claude-haiku"):  # no effort setting, no server-side fallback
        resp = client().messages.create(**params)
    else:
        config["effort"] = effort
        # if a safety check wrongly declines (e.g. a defense-company posting), retry on a fallback model
        resp = client().beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if resp.stop_reason == "refusal":
        return None
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


# ---------- job descriptions (public ATS APIs, no browser) ----------

_ashby_boards = {}


def _strip_html(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "), ("&#39;", "'"), ("&quot;", '"')):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def fetch_description(job, limit=6000):
    """Plain-text job description, or "" if it can't be read without a browser."""
    url = job["URL"]
    try:
        if m := re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url):
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}", timeout=20)
            if r.ok:
                return _strip_html(_strip_html(r.json().get("content", "")))[:limit]  # content is escaped HTML
        elif m := re.search(r"jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})", url):
            r = requests.get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}", timeout=20)
            if r.ok:
                d = r.json()
                lists = " ".join(f"{x.get('text', '')}: {_strip_html(x.get('content', ''))}" for x in d.get("lists", []))
                return f"{d.get('descriptionPlain', '')} {lists} {d.get('additionalPlain', '')}"[:limit]
        elif m := re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url):
            org, jid = m[1], m[2]
            if org not in _ashby_boards:
                r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", timeout=20)
                _ashby_boards[org] = {j["id"]: j for j in r.json().get("jobs", [])} if r.ok else {}
            if j := _ashby_boards[org].get(jid):
                return (j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml", "")))[:limit]
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        return _strip_html(r.text)[:limit] if r.ok else ""
    except Exception:
        return ""


# ---------- 1. job matching ----------

RANK_SYSTEM = """You screen job postings for a new-grad candidate and score how good a fit each one is.

CANDIDATE:
{facts}
{situation}

Score 0-100:
- 80-100: entry-level / new-grad software, data, ML, cloud or infrastructure role that clearly uses their skills.
- 50-79: plausible entry-level tech role, partial skill overlap.
- 20-49: weak fit (mostly non-software work, very different stack, or unclear level).
- 0-19: not for him: needs 2+ years of experience or a senior title, needs U.S. citizenship / security clearance /
  no sponsorship ever (when they need sponsorship), internship instead of full-time, or not a technical role.
Judge from the posting text when given; otherwise from the title and company."""

RANK_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}


def rank_job(job):
    desc = fetch_description(job)
    prompt = (f"Company: {job['Company']}\nTitle: {job['Title']}\nLocation: {job.get('Location') or ''}\n\n"
              f"Posting:\n{desc or '(not available — judge from title and company)'}\n\n"
              "Return the score and a reason of at most 12 words.")
    system = RANK_SYSTEM.format(facts=cover_letter.FACTS, situation=SITUATION)
    out = ask_json(system, prompt, RANK_SCHEMA)
    if not out:
        return None, "Claude declined to score this"
    return max(0, min(100, int(out["score"]))), out["reason"].strip()[:120]


def rank_jobs(jobs, workers=8, on_result=None):
    """Score jobs in parallel; on_result(job, score, reason) is called as each one finishes."""
    def one(job):
        try:
            score, reason = rank_job(job)
        except Exception as e:
            score, reason = None, "error: " + str(e).splitlines()[0][:80]
        if on_result:
            on_result(job, score, reason)
        return job, score, reason
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, jobs))


# ---------- 2. answers for questions the Answers sheet doesn't cover ----------

# Legal / identity questions are never left to a model — you answer those yourself.
NEVER_DRAFT = re.compile(
    r"sponsor|visa|authori[sz]|citizen|clearance|veteran|disab|gender|\bsex\b|race|ethnic|hispanic|latin|"
    r"criminal|convict|felony|salary|compensation|pay\b|certify|attest|signature|social security|ssn|"
    r"date of birth|birthday|\bage\b|pronoun|password", re.I)

DRAFT_SYSTEM = """You fill in job application questions for {name}, a new-grad candidate.

FACTS (the only things you may state about them):
{facts}
{situation}
Contact and links come from his profile, given with each question.

Rules:
- Use only the FACTS and profile. Never invent employers, numbers, dates, skills or experiences.
- If the question can't be answered truthfully from them, or needs a personal decision only he can make, set skip=true.
- Short text box: a few words or one sentence. Paragraph box: 2-5 sentences, first person, specific, no clichés.
- Choice question: the answer must be copied exactly from the options list.
- Plain text only: no markdown, no quotation marks around the answer."""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "skip": {"type": "boolean"}},
    "required": ["answer", "skip"],
    "additionalProperties": False,
}


def draft_answer(question, ftype, options, job, profile, description=""):
    """An answer to paste for review, or None (sensitive question, model unsure, or not allowed)."""
    if NEVER_DRAFT.search(question) or ftype == "file":
        return None
    kind = "paragraph box" if ftype == "textarea" else "choice question" if options else "short text box"
    prompt = (f"Profile: {json.dumps({k: v for k, v in profile.items() if k != 'resume_path'})}\n\n"
              f"Job: {job.get('Title')} at {job.get('Company')}\n"
              + (f"Posting (excerpt):\n{description[:4000]}\n\n" if description else "\n")
              + f"Question ({kind}): {question}\n"
              + (f"Options: {json.dumps(options[:60])}\n" if options else ""))
    system = DRAFT_SYSTEM.format(name=cover_letter.NAME, facts=cover_letter.FACTS, situation=SITUATION)
    out = ask_json(system, prompt, DRAFT_SCHEMA, effort="medium")
    if not out or out["skip"] or not out["answer"].strip():
        return None
    answer = out["answer"].strip()
    if options and answer not in options:  # must be a real option, or nothing
        return None
    return answer
