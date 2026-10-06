"""People who use the app. The owner = the top data folder (paths.py). Friends = profiles/<id>/ with their own
profile.json, resume.pdf, cover_template.txt, jobs.xlsx (Jobs/Answers/Unanswered), screenshots/, submitted/, cover_letters/.
Also: turning a pasted list of links / a CSV into jobs."""
import csv
import io
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

import ai
import bot
import cover_letter
import filler

ROOT = bot.HOME  # data, not code
DIR = ROOT / "profiles"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "friend"


full_name = filler.full_name


def list_profiles():
    owner = json.loads((ROOT / "profile.json").read_text())
    out = [{"id": "me", "name": full_name(owner), "owner": True,
            "placeholder": owner.get("first_name") == "Setup" and not owner.get("email")}]
    for d in sorted(DIR.glob("*/profile.json")) if DIR.exists() else []:
        out.append({"id": d.parent.name, "name": full_name(json.loads(d.read_text())), "owner": False})
    return out


def profile_dir(pid):
    return ROOT if pid == "me" else DIR / pid


def resume_text(path):
    try:
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)[:8000]
    except Exception:
        return ""


def match_context(pid, p):
    """What the free matcher needs: resume text (+ their letter-style facts) and whether they need sponsorship."""
    d = profile_dir(pid)
    style = cover_letter.load_style(d) or {}
    text = resume_text(d / p.get("resume_path", "resume.pdf")) + "\n" + style.get("facts", "")
    return text, bool(p.get("needs_sponsorship"))


def activate(pid):
    """Point the bot, cover letters and AI at this person's folder. Returns their profile.
    Everyone works the same way; the owner ("me") is just the one in the top folder."""
    d = profile_dir(pid)
    p = json.loads((d / "profile.json").read_text())
    bot.XLSX, bot.PROFILE, bot.DATA = d / "jobs.xlsx", p, d
    contact = "  ●  ".join(x for x in (p.get("city"), p.get("phone"), p.get("email"),
                                       re.sub(r"^https?://(www\.)?", "", p.get("website") or "")) if x)
    template = (d / "cover_template.txt").read_text() if (d / "cover_template.txt").exists() else ""
    cover_letter.use_identity(full_name(p), contact, p.get("phone", ""), p.get("email", ""), d / "cover_letters",
                              template, resume_text(d / p.get("resume_path", "resume.pdf")) or full_name(p),
                              style=cover_letter.load_style(d), voice_dir=d / "cover_letter_ins" / "voice")
    ai.SITUATION = (f"Graduates {p.get('graduation', '')}. "
                    + ("Will need visa sponsorship in the future." if p.get("needs_sponsorship")
                       else "Authorized to work in the U.S. without sponsorship."))
    return p


def save_profile(pid, data, resume_src=None, template=None):
    """Create or update a person. data = the profile form. Returns the profile id."""
    if pid in (None, "", "new"):
        pid = slug(f"{data.get('first_name', '')}-{data.get('last_name', '')}")
        base, n = pid, 2
        while (DIR / pid).exists():
            pid, n = f"{base}-{n}", n + 1
    d = profile_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    old = json.loads((d / "profile.json").read_text()) if (d / "profile.json").exists() else {}
    p = {**old, **data, "resume_path": old.get("resume_path", "resume.pdf")}
    (d / "profile.json").write_text(json.dumps(p, indent=2))
    if resume_src:
        shutil.copyfile(resume_src, d / p["resume_path"])
    if template is not None:
        (d / "cover_template.txt").write_text(template)
    if pid != "me" and not old:  # first time: their own Answers sheet, built from the form
        _seed_answers(d / "jobs.xlsx", answers_for(p))
    return pid


def _seed_answers(xlsx, rows):
    wb = bot.open_wb(xlsx)
    ws = bot.new_sheet(wb, "Answers", 1, bot.ANSWER_COLS, [45, 70, 18, 50])
    for r in rows:
        ws.append(list(r))
    bot.save_wb(wb, xlsx)


answers_for = filler.answers_for


# ---------- importing links ----------

def _company_from_url(url):
    for pat in (r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)", r"jobs\.lever\.co/([\w.-]+)",
                r"jobs\.ashbyhq\.com/([^/?#]+)", r"https?://([\w-]+)\.wd\d+\.myworkdayjobs", r"([\w-]+)\.bamboohr",
                r"apply\.workable\.com/([\w-]+)", r"jobs\.smartrecruiters\.com/([\w-]+)"):
        if m := re.search(pat, url, re.I):
            return m[1].replace("-", " ").title()
    host = re.sub(r"^www\.|^careers?\.|^jobs\.", "", re.sub(r"https?://", "", url).split("/")[0])
    return host.split(".")[0].title()


def _title_from_api(url):
    """Real job title + company from Greenhouse / Lever / Ashby's public job APIs."""
    if m := re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url):
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}", timeout=12)
        if r.ok:
            d = r.json()
            return d.get("title", ""), d.get("company_name", ""), (d.get("location") or {}).get("name", "")
    elif m := re.search(r"jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})", url):
        r = requests.get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}", timeout=12)
        if r.ok:
            d = r.json()
            return d.get("text", ""), "", (d.get("categories") or {}).get("location", "")
    elif m := re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url):
        ai.fetch_description({"URL": url})  # loads + caches that company's board
        if j := ai._ashby_boards.get(m[1], {}).get(m[2]):
            return j.get("title", ""), "", j.get("location", "")
    return "", "", ""


def _title_from_page(url):
    try:
        html = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"}).text
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        t = ai._strip_html(m[1]) if m else ""
        t = re.split(r"\s+[|–—-]\s+(?:Careers|Jobs|Job Application|Greenhouse|Lever|Ashby)", t)[0]
        return t[:100]
    except Exception:
        return ""


def parse_links(text):
    """Links pasted one per line, or a CSV with a url/link column (+ optional company, title, location)."""
    text = text.strip()
    rows = []
    first = text.splitlines()[0].lower() if text else ""
    if "," in first and re.search(r"url|link", first):
        for r in csv.DictReader(io.StringIO(text)):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            url = r.get("url") or r.get("link") or r.get("apply url") or r.get("application link") or ""
            if url.startswith("http"):
                rows.append({"URL": url, "Company": r.get("company", ""), "Title": r.get("title") or r.get("role", ""),
                             "Location": r.get("location", "")})
    else:
        for url in re.findall(r"https?://[^\s,;\"'<>]+", text):
            rows.append({"URL": url.rstrip(").]"), "Company": "", "Title": "", "Location": ""})
    need_title = [r for r in rows if not r["Title"]]
    def lookup(r):
        try:
            title, company, loc = _title_from_api(r["URL"])
        except Exception:
            title = company = loc = ""
        return title or _title_from_page(r["URL"]), company, loc
    with ThreadPoolExecutor(8) as pool:
        for r, (t, c, loc) in zip(need_title, pool.map(lookup, need_title)):
            if re.search(r"not found|404|page doesn.t exist|^jobs at|careers$", t, re.I):
                t = ""
            r["Title"] = t or "Job (title unknown)"
            r["Company"] = r["Company"] or c
            r["Location"] = r["Location"] or loc
    for r in rows:
        r["Company"] = r["Company"] or _company_from_url(r["URL"])
    return rows


def import_links(text):
    """Add pasted links / CSV rows to the active person's jobs. Returns (added, skipped_duplicates)."""
    from datetime import datetime
    rows = bot.load_rows()
    known = {bot.job_id(r["URL"]) for r in rows.values() if r.get("URL")}
    added = dup = 0
    for j in parse_links(text):
        jid = bot.job_id(j["URL"])
        if jid in rows or jid in known:
            dup += 1
            continue
        rows[jid] = dict(j, ID=jid, Source="imported", Category="", Salary="", Sponsorship="",
                         Posted=datetime.now().strftime("%Y-%m-%d"), ATS=bot.detect_ats(j["URL"]),
                         Status="new", Updated="", Notes="")
        known.add(jid)
        added += 1
    bot.save_rows(rows)
    return added, dup
