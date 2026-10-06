"""Job application helper.

  python bot.py fetch                  pull SimplifyJobs listings into jobs.xlsx (keeps your statuses)
  python bot.py apply                  open each "new" job, autofill it, you review + submit, row gets updated
  python bot.py apply --dry-run        fill forms headless, screenshot them, never submit (for testing)

  python bot.py fetch --source speedyapply   use the speedyapply 2027 SWE new-grad list instead

apply filters: --source speedyapply  --ats greenhouse,lever  --category Software,AI/ML/Data  --limit 20
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import ai
import paths
import cover_letter
import filler

ROOT = Path(__file__).parent  # the code
# the owner's files: this folder, or ~/Documents/Apply for the installed app (APPLY_DATA)
HOME = paths.home()
HOME.mkdir(parents=True, exist_ok=True)
if not (HOME / "profile.json").exists():  # fresh install: a placeholder — everyone makes their own profile
    (HOME / "profile.json").write_text(json.dumps(
        {"first_name": "Setup", "last_name": "(use New profile)", "email": "", "phone": "", "resume_path": "resume.pdf"}))
XLSX = HOME / "jobs.xlsx"
PROFILE = json.loads((HOME / "profile.json").read_text())
DATA = HOME  # where this person's resume, screenshots, submitted/ and cover letters live (profiles/<name>/ for friends)
SOURCES = {
    "newgrad": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    "intern": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
    "speedyapply": "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md",
    # US new grad + entry level, checked against company career sites; lots of smaller companies
    "applyguy": "https://raw.githubusercontent.com/ApplyGuy/2027-New-Grad-Jobs/main/data/new-grad-jobs.json",
}
COLUMNS = ["ID", "Source", "Company", "Title", "Location", "Category", "Salary", "Posted", "ATS",
           "Sponsorship", "URL", "Status", "Match", "Why", "Updated", "Notes"]
WIDTHS = {"ID": 10, "Source": 12, "Company": 24, "Title": 44, "Location": 22, "Category": 12, "Salary": 10,
          "Posted": 11, "ATS": 12, "Sponsorship": 14, "URL": 50, "Status": 12, "Match": 8, "Why": 40,
          "Updated": 17, "Notes": 30}
STATUSES = ["new", "test-filled", "applied", "skipped", "later", "error", "interview", "rejected", "offer"]
# Roles that need U.S. citizenship or a clearance (most students on a visa can't take them).
BLOCKED_TITLE = re.compile(r"citizen|clearance|ts/sci|secret|polygraph|public trust", re.I)


def detect_ats(url):
    for key in ("greenhouse", "lever.co", "ashbyhq", "myworkdayjobs", "smartrecruiters", "icims", "workable"):
        if key in url:
            return key.replace(".co", "").replace("hq", "").replace("myworkdayjobs", "workday")
    return "other"


def job_id(url):
    return hashlib.sha1(url.split("?")[0].rstrip("/").encode()).hexdigest()[:8]


# ---------- spreadsheet ----------

def load_rows(path=None):
    path = path or XLSX
    if not path.exists():
        return {}
    wb = load_workbook(path)
    if "Jobs" not in wb.sheetnames:  # a new friend's file starts with only their Answers
        return {}
    ws = wb["Jobs"]
    it = ws.iter_rows(values_only=True)
    header = next(it)  # read by header so older files with fewer columns still load
    rows = {}
    for r in it:
        if r[0]:
            row = dict(zip(header, r))
            row.setdefault("Source", "simplify")
            rows[r[0]] = row
    return rows


HEADER_FONT, HEADER_FILL = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")


def open_wb(path):
    if path.exists():
        return load_workbook(path)
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def new_sheet(wb, name, index, header, widths):
    """Replace one sheet, leaving the others (your Answers edits) untouched."""
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name, min(index, len(wb.sheetnames)))
    ws.append(header)
    for c in ws[1]:
        c.font, c.fill = HEADER_FONT, HEADER_FILL
    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w
    ws.freeze_panes = "A2"
    return ws


def save_wb(wb, path):
    try:  # write a temp file then swap it in, so jobs.xlsx is never half-written (Ctrl+C, two runs)
        tmp = path.with_name(f".~{path.name}")
        wb.save(tmp)
        tmp.replace(path)
    except PermissionError:
        sys.exit("jobs.xlsx is open in Excel — close it and run again.")


def save_rows(rows, path=None):
    path = path or XLSX
    wb = open_wb(path)
    ws = new_sheet(wb, "Jobs", 0, COLUMNS, [WIDTHS[c] for c in COLUMNS])
    for row in sorted(rows.values(), key=lambda r: r.get("Posted") or "", reverse=True):
        ws.append([row.get(c) for c in COLUMNS])
    status_col = get_column_letter(COLUMNS.index("Status") + 1)
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"')
    ws.add_data_validation(dv)
    dv.add(f"{status_col}2:{status_col}{max(ws.max_row, 2)}")
    ws.auto_filter.ref = ws.dimensions
    save_wb(wb, path)


ANSWER_COLS = ["Match (words in the question)", "Answer (alternatives split by |)", "For (blank/choice/text)", "Notes"]
UNANSWERED_COLS = ["Question", "Field type", "Options", "Times seen", "Last company", "Last seen"]


def load_answers(path=None):
    """Your pre-list of answers from the Answers sheet. Created with sensible defaults the first time."""
    path = path or XLSX
    wb = open_wb(path)
    if "Answers" not in wb.sheetnames:
        ws = new_sheet(wb, "Answers", 1, ANSWER_COLS, [45, 70, 18, 50])
        placeholder = PROFILE.get("first_name") == "Setup" and not PROFILE.get("email")
        for row in ([] if placeholder else filler.answers_for(PROFILE)):  # built from their profile form
            ws.append(list(row))
        save_wb(wb, path)
    ws = wb["Answers"]
    return [tuple("" if v is None else str(v) for v in (list(r[:3]) + [None] * 3)[:3])
            for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]]


def record_unanswered(report, job, path=None):
    """Add required questions the bot couldn't answer (or the AI drafted) to the Unanswered sheet, counted across
    jobs — add a row to Answers for the common ones so they're filled the same way every time."""
    missing = [f for f in report if filler.is_missing(f) or f["status"] == "ai-drafted"]
    if not missing:
        return
    path = path or XLSX
    wb = open_wb(path)
    seen = {}
    if "Unanswered" in wb.sheetnames:
        for r in wb["Unanswered"].iter_rows(min_row=2, values_only=True):
            if r and r[0]:
                seen[r[0]] = list(r)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for f in missing:
        row = seen.get(f["question"]) or [f["question"], f["type"], " | ".join(f["options"])[:300], 0, "", ""]
        row[3] = (row[3] or 0) + 1
        row[4], row[5] = job["Company"], now
        seen[f["question"]] = row
    ws = new_sheet(wb, "Unanswered", 2, UNANSWERED_COLS, [70, 12, 60, 11, 22, 17])
    for row in sorted(seen.values(), key=lambda r: -(r[3] or 0)):
        ws.append(row)
    save_wb(wb, path)


# ---------- fetch ----------

def parse_simplify(listings, source):
    for j in listings:
        if not (j.get("active") and j.get("is_visible")):
            continue
        yield {
            "ID": j["id"][:8], "Source": source, "Company": j["company_name"], "Title": j["title"],
            "Location": ", ".join(j.get("locations", []))[:80], "Category": j.get("category", ""),
            "Posted": datetime.fromtimestamp(j["date_posted"]).strftime("%Y-%m-%d"),
            "Sponsorship": j.get("sponsorship", ""), "URL": j["url"],
        }


def parse_speedyapply(md, today=None):
    """Rows look like: | <a><strong>Co</strong></a> | Title | Loc | [Salary |] <a href=URL><img alt="Apply"></a> | 3d |"""
    today = today or datetime.now()
    section = ""
    for line in md.splitlines():
        if line.startswith("### "):
            section = re.sub(r":\w+:", "", line[4:]).strip()
        if not line.startswith("|") or 'alt="Apply"' not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        url = re.search(r'href="([^"]+)"', cells[-2]).group(1)
        age = re.match(r"(\d+)", cells[-1])
        posted = today - timedelta(days=int(age.group(1))) if age else today
        yield {
            "ID": job_id(url), "Source": "speedyapply", "Category": section,
            "Company": re.sub(r"<[^>]+>", "", cells[0]).strip(), "Title": cells[1], "Location": cells[2],
            "Salary": cells[3] if len(cells) == 6 else "", "Posted": posted.strftime("%Y-%m-%d"),
            "Sponsorship": "", "URL": url,
        }


def parse_applyguy(data):
    for j in data["jobs"]:
        url = j.get("listingUrl") or j["url"]  # listingUrl = the company's own posting
        yield {
            "ID": job_id(url), "Source": "applyguy", "Company": re.sub(r"\s*-\s*(External|Internal)$", "", j["company"]),
            "Title": j["title"], "Location": j["location"][:80], "Category": j.get("eligibility", ""),
            "Salary": "", "Posted": j["posted"], "Sponsorship": "", "URL": url,
        }


def match(args):
    """Free resume matching (no AI): score every job still to do 0-100; `apply` goes best match first."""
    import matcher
    import profiles
    rows = load_rows()
    todo = [r for r in rows.values() if r["Status"] in ("new", "later", "test-filled")]
    text, needs = profiles.match_context("me", PROFILE)
    print(f"Matching {len(todo)} jobs to your resume…")
    matcher.match_jobs(todo, text, needs, DATA / ".cache" / "descriptions.json", on_progress=print)
    save_rows(rows)
    for r in sorted(todo, key=lambda r: -r["Match"])[:20]:
        print(f"  {r['Match']:>3}  {r['Company'][:26]:26} {r['Title'][:48]:48} {r['Why']}")


def rank(args):
    """Score jobs 0-100 against your resume with Claude; `apply` then goes best match first."""
    if not ai.available():
        sys.exit("Set ANTHROPIC_API_KEY first (console.anthropic.com → API keys), then run rank again.")
    rows = load_rows()
    wanted_ats = set(args.ats.split(",")) if args.ats else None
    todo = [r for r in rows.values()
            if r["Status"] in ("new", "later") and (args.rerank or r.get("Match") is None)
            and (not wanted_ats or r["ATS"] in wanted_ats)
            and (not args.source or r["Source"] == args.source)][: args.limit]
    if not todo:
        sys.exit("Nothing to rank (use --rerank to score again).")
    print(f"Scoring {len(todo)} jobs with {ai.MODEL}…")
    done = []

    def on_result(job, score, reason):
        job["Match"], job["Why"] = score, reason
        done.append(job)
        print(f"  [{len(done)}/{len(todo)}] {score if score is not None else '--':>3}  {job['Company'][:28]:28} {job['Title'][:50]}")
        if len(done) % 25 == 0:
            save_rows(rows)  # progress survives Ctrl+C
    ai.rank_jobs(todo, on_result=on_result)
    save_rows(rows)
    best = sorted((r for r in todo if r.get("Match") is not None), key=lambda r: -r["Match"])
    print("\nTop matches:")
    for r in best[:15]:
        print(f"  {r['Match']:>3}  {r['Company'][:28]:28} {r['Title'][:50]:50} {r['Why']}")
    print(f"\nSaved to the Match/Why columns. `apply` now goes best match first (--min-match 60 to skip weak ones).")


def fetch(args):
    rows = load_rows()
    resp = requests.get(SOURCES[args.source], timeout=60)
    resp.raise_for_status()
    listings = (parse_speedyapply(resp.text) if args.source == "speedyapply"
                else parse_applyguy(resp.json()) if args.source == "applyguy"
                else parse_simplify(resp.json(), args.source))
    cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    known_urls = {job_id(r["URL"]) for r in rows.values() if r.get("URL")}  # same job listed in two sources
    added = 0
    for j in listings:
        if j["Posted"] < cutoff or j["ID"] in rows or job_id(j["URL"]) in known_urls:
            continue
        if j["Sponsorship"] in ("U.S. Citizenship is Required", "Does Not Offer Sponsorship") \
                or BLOCKED_TITLE.search(j["Title"]):
            continue
        rows[j["ID"]] = dict(j, ATS=detect_ats(j["URL"]), Status="new", Updated="", Notes="")
        known_urls.add(job_id(j["URL"]))
        added += 1
    save_rows(rows)
    print(f"Added {added} new jobs from {args.source}. {len(rows)} total in {XLSX.name}.")


# ---------- autofill ----------

def application_url(url, ats):
    base = url.split("?")[0].rstrip("/")
    if ats == "lever" and not base.endswith("/apply"):
        return base + "/apply"
    if ats == "ashby" and not base.endswith("/application"):
        return base + "/application"
    return url


def find_extension():
    """Copy Simplify Copilot out of your regular Chrome so the bot browser can use it."""
    dest = HOME / "simplify_ext"
    if (dest / "manifest.json").exists():
        return dest
    exts = Path.home() / "Library/Application Support/Google/Chrome/Default/Extensions"
    for manifest in exts.glob("*/*/manifest.json"):
        if "simplify" in manifest.read_text(errors="ignore").lower():
            shutil.copytree(manifest.parent, dest, ignore=shutil.ignore_patterns("_metadata"))
            return dest
    return None


ICONS = {"filled": "✅", "already": "✅", "skipped": "⏭️ ", "ai-drafted": "🤖"}


def print_report(report):
    """Every question on the form and exactly what was put in it."""
    for f in report:
        icon = ICONS.get(f["status"], "❌" if filler.is_missing(f) else "⚪")
        value = f["value"] if f["status"] in ("filled", "already", "ai-drafted") else f"({f['status']})"
        value = " ".join(str(value).split())
        print(f"   {icon} {f['question'][:58]:58} → {value[:70]}{'…' if len(value) > 70 else ''}")


SUBMITTED = re.compile(
    r"thank(s| you) for (applying|your application|submitting)|application (has been |was )?(submitted|received)"
    r"|we('ve| have) received your application|successfully (submitted|applied)|you('ve| have) (successfully )?applied"
    r"|application complete", re.I)


def looks_submitted(page):
    if re.search(r"confirmation|thank|/submitted|success", page.url, re.I):
        return True
    for frame in page.frames:
        try:
            if SUBMITTED.search(frame.evaluate("document.body ? document.body.innerText.slice(0, 6000) : ''")):
                return True
        except Exception:
            pass
    return False


def start_key_reader():
    """Read terminal lines in the background so the browser can be watched at the same time."""
    import queue
    import threading
    keys = queue.Queue()

    def read():
        for line in sys.stdin:
            keys.put(line.strip().lower()[:1])
    threading.Thread(target=read, daemon=True).start()
    return keys


def job_description(ctx, job):
    """Text of the job posting (opened in a separate tab, read-only) for tailoring the cover letter."""
    tab = ctx.new_page()
    try:
        tab.goto(job["URL"].split("?")[0].removesuffix("/apply").removesuffix("/application"),
                 wait_until="domcontentloaded", timeout=30000)
        tab.wait_for_timeout(2500)
        return tab.inner_text("body")[:15000]
    except Exception:
        return ""
    finally:
        tab.close()


def wait_for_user(page, keys):
    """Wait until you submit (confirmation page appears) or type s/l/q/a. Never clicks anything itself.
    Keeps the last snapshot of the filled form, so we can save exactly what you submitted."""
    import queue
    already = looks_submitted(page)  # some job pages say "thank you for your interest" before you apply
    start_url = page.url
    last, last_values, last_check = None, None, 0
    while True:
        try:
            if (not already or page.url != start_url) and looks_submitted(page):
                page.wait_for_timeout(1500)
                return "a", last, page.screenshot(full_page=True)
            now = datetime.now().timestamp()
            if now - last_check > 3:  # re-snapshot the form whenever its answers change
                last_check = now
                vals = [(q, v) for fr in page.frames for q, v in _scan(fr)]
                if vals and vals != last_values:
                    last_values = vals
                    last = (vals, page.screenshot(full_page=True))
            page.wait_for_timeout(700)
        except Exception:  # browser window closed
            return "q", last, None
        try:
            k = keys.get_nowait()
            if k in ("a", "s", "l", "q"):
                return k, last, None
        except queue.Empty:
            pass


def simplify_logged_in(ctx):
    # before login simplify.jobs only sets analytics/consent cookies (_ga, _fbp, posthog, consent)
    return any(re.search(r"auth|token|session|jwt", c["name"], re.I) for c in ctx.cookies("https://simplify.jobs"))


def login(args):
    """Open the bot browser (with Simplify) so you can log into Simplify once; it stays logged in after."""
    from playwright.sync_api import sync_playwright
    ext = find_extension()
    if not ext:
        sys.exit("Simplify Copilot isn't installed in your regular Chrome — install it there first.")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(HOME / ".browser-profile"), headless=False, channel="chromium", viewport={"width": 1280, "height": 900},
            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"])
        if simplify_logged_in(ctx):
            print("Simplify is already logged in ✔")
            return ctx.close()
        page = ctx.new_page()
        page.goto("https://simplify.jobs/auth/login")
        print("Log into Simplify in the browser window that opened (email + password works best).\n"
              "It closes by itself once you're in — up to 10 minutes.")
        for _ in range(300):
            if simplify_logged_in(ctx):
                page.wait_for_timeout(3000)  # let the extension pick up the login
                print("Simplify logged in ✔")
                break
            try:
                page.wait_for_timeout(2000)
            except Exception:
                print("Window closed before logging in — run `bot.py login` again.")
                return
        else:
            print("Timed out — run `bot.py login` again.")
        ctx.close()


def _filled_values(page):
    return [(q, v) for fr in page.frames for q, v in _scan(fr) if v]


def wait_for_simplify(page, quiet=4, longest=25):
    """Let Simplify Copilot go first: wait until it stops changing the form (or it never starts).
    Returns how many fields it filled; the bot then only touches what is still empty."""
    import time
    start = changed = time.time()
    first = last = _filled_values(page)
    while time.time() - start < longest:
        page.wait_for_timeout(1000)
        vals = _filled_values(page)
        if vals != last:
            last, changed = vals, time.time()
        idle = time.time() - changed
        if idle >= quiet and (last != first or time.time() - start >= 10):
            break
    return max(0, len(last) - len(first))


def _scan(frame):
    try:
        return [(f["question"], f["value"]) for f in frame.evaluate(filler.SCAN_JS)]
    except Exception:
        return []


SUBMITTED_COLS = ["Submitted at", "Job ID", "Company", "Title", "Question", "Answer", "Form screenshot",
                  "Confirmation screenshot"]


def slug(text, limit=50):
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")[:limit].strip("-")


def shot_name(job):
    """screenshots/Harvey_Software-Engineer-New-Grad-2027_2829bdb3.png — company + role, id keeps it unique."""
    return f"{slug(job['Company'])}_{slug(job['Title'])}_{job['ID']}.png"


def record_submission(job, snapshot, confirmation_png):
    """Save what you submitted: form + confirmation screenshots, and every answer to the Submitted sheet."""
    folder = DATA / "submitted"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    base = f"{stamp}_{slug(job['Company'])}_{job['ID']}"
    form_png = conf_png = ""
    values = []
    if snapshot:
        values, png = snapshot
        form_png = f"{base}_1-form.png"
        (folder / form_png).write_bytes(png)
    if confirmation_png:
        conf_png = f"{base}_2-confirmation.png"
        (folder / conf_png).write_bytes(confirmation_png)
    wb = open_wb(XLSX)
    old = [list(r) for r in wb["Submitted"].iter_rows(min_row=2, values_only=True)] if "Submitted" in wb.sheetnames else []
    ws = new_sheet(wb, "Submitted", 3, SUBMITTED_COLS, [17, 10, 22, 36, 55, 60, 40, 40])
    for r in old:
        ws.append(r)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for q, v in values or [("(no snapshot)", "")]:
        ws.append([now, job["ID"], job["Company"], job["Title"], q, v, f"submitted/{form_png}" if form_png else "",
                   f"submitted/{conf_png}" if conf_png else ""])
    save_wb(wb, XLSX)
    return form_png, conf_png


def apply(args):
    from playwright.sync_api import sync_playwright

    rows = load_rows()
    wanted_ats = set(args.ats.split(",")) if args.ats else None
    wanted_cat = set(args.category.split(",")) if args.category else None
    queue = [r for r in rows.values()
             if r["Status"] in ("new", "test-filled", "later")
             and (not args.source or r["Source"] == args.source)
             and (not args.company or args.company.lower() in (r["Company"] or "").lower())
             and (not wanted_ats or r["ATS"] in wanted_ats)
             # speedyapply/applyguy are SWE-only lists; their categories mean something else
             and (not wanted_cat or r["Source"] in ("speedyapply", "applyguy") or r["Category"] in wanted_cat)
             and (r.get("Match") is None or r["Match"] >= args.min_match)]
    # best match first once `rank` has scored them (unscored jobs keep their order, after scored ones)
    queue.sort(key=lambda r: -(r["Match"] if isinstance(r.get("Match"), (int, float)) else -1))
    queue = queue[: args.limit]
    if not queue:
        sys.exit("Nothing to do — run `fetch` first or loosen filters.")
    print(f"{len(queue)} jobs queued.")
    use_ai = ai.available() and not args.no_ai
    print("AI:", f"on ({ai.MODEL}) — drafts missing answers (yellow outline) and tailors cover letters" if use_ai
          else "off" + ("" if args.no_ai else " — set ANTHROPIC_API_KEY to turn it on"))

    answers = filler.compile_answers(load_answers())
    resume = str(DATA / PROFILE["resume_path"])
    shots = DATA / "screenshots"
    shots.mkdir(exist_ok=True)
    use_simplify = args.simplify  # off by default: the bot fills everything itself
    ext = find_extension() if use_simplify else None
    launch_args = [f"--disable-extensions-except={ext}", f"--load-extension={ext}"] if ext else []
    if use_simplify:
        print("Simplify extension:", "loaded" if ext else "not found (built-in autofill only)")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            # tests get a throwaway profile, so they never clash with a real session's open browser
            # --watch shares the real profile so Simplify stays logged in
            str(HOME / ".browser-profile") if use_simplify else tempfile.mkdtemp(prefix="applybot-"),
            headless=args.dry_run and not args.watch, channel="chromium",
            args=launch_args, viewport={"width": 1280, "height": 900})
        # our own tab: Simplify opens/redirects its own tabs at startup, and filling one of those makes the
        # form "refresh" under us
        page = ctx.new_page()
        blocked = []
        if args.dry_run:
            # Hard guarantee for tests: the browser may load pages but never send data anywhere
            # (no POST/PUT/PATCH/DELETE), so nothing can be submitted even by accident.
            def guard(route):
                req = route.request
                read_only_query = "graphql" in req.url and re.search(r"op=Api(JobPosting|Organization|Application(Form)?\b|Brand|Location|AutocompleteGeoLocation)", req.url) \
                    and not re.search(r"submit|apply|create|upload|parse", req.url, re.I)
                simplify = "simplify.jobs" in req.url  # Simplify's own account/autofill data, not the job site
                if req.method in ("GET", "HEAD", "OPTIONS") or read_only_query or simplify:
                    return route.continue_()
                blocked.append(f"{route.request.method} {route.request.url[:80]}")
                return route.abort()
            ctx.route("**/*", guard)
        if ext and not simplify_logged_in(ctx):
            print("  ⚠️  Simplify isn't logged in in the bot browser, so it won't autofill. Run once:\n"
                  "     .venv/bin/python bot.py login")
        keys = None if args.dry_run else start_key_reader()

        for n, job in enumerate(queue, 1):
            print(f"\n[{n}/{len(queue)}] {job['Company']} — {job['Title']} ({job['ATS']})")
            if page.is_closed():  # tab closed (by you or an extension) → keep going in a fresh one
                try:
                    page = ctx.new_page()
                except Exception:
                    print("  browser window was closed — stopping. Progress is saved.")
                    break
            try:
                page.goto(application_url(job["URL"], job["ATS"]), wait_until="domcontentloaded", timeout=45000)
                try:  # wait for the form itself, not a fixed delay (some sites render it late)
                    page.wait_for_selector("input[type=email], input[type=file], textarea", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                if ext:
                    n = wait_for_simplify(page)
                    print(f"  Simplify filled {n} field(s); checking the rest myself")
                letter, posting = {}, {}

                def description(job=job):  # fetched once per job, only if something needs it
                    if "text" not in posting:
                        posting["text"] = ai.fetch_description(job) or job_description(ctx, job)
                    return posting["text"]

                def cover(job=job):  # only written when a form actually asks for a cover letter
                    if "pdf" not in letter:
                        made = cover_letter.make_cover_letter(job, description())
                        if not made:
                            return None
                        letter["pdf"], letter["text"] = made
                        print("  ✉️  cover letter →", letter["pdf"].relative_to(DATA))
                    return letter["pdf"], letter["text"]

                def drafter(f, job=job):
                    try:
                        return ai.draft_answer(f["question"], f["type"], f["options"], job, PROFILE, description())
                    except Exception as e:
                        print("  (AI draft failed:", str(e).splitlines()[0][:80], ")")
                        return None
                report = filler.fill_page(page, answers, job, resume, cover_letter=cover,
                                          drafter=drafter if use_ai else None)
            except Exception as e:
                if "has been closed" in str(e):  # not the job's fault — leave its status alone
                    print("  browser tab was closed — this job stays queued for next time")
                    continue
                job.update(Status="error", Notes=str(e).splitlines()[0][:120])
                print("  error:", job["Notes"])
                save_rows(rows)
                continue
            print_report(report)
            filled = [f for f in report if f["status"] in ("filled", "already")]
            missing = [f for f in report if filler.is_missing(f)]
            print(f"  {len(filled)}/{len(report)} questions filled", "— all required done" if not missing else "")
            for f in missing:
                print(f"  ✗ MISSING ({f['status']}): {f['question'][:90]}")
            if not report:
                print("  no form found (login page?) — Simplify / you")
            record_unanswered(report, job)
            summary = f"{len(filled)}/{len(report)} filled" + (
                "; missing: " + "; ".join(f["question"][:40] for f in missing) if missing else "")

            if args.dry_run:
                shot = shots / shot_name(job)
                page.screenshot(path=str(shot), full_page=True)
                job.update(Status="test-filled", Notes=f"{summary}; {shot.name}"
                           + (f"; {letter['pdf'].relative_to(DATA)}" if "pdf" in letter else ""))
                if args.watch and input("  Look at the browser. Enter = next job, q = quit > ").strip().lower() == "q":
                    job["Updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    save_rows(rows)
                    break
            else:
                print("  👉 Fill anything outlined in red, check the form, then click Submit in the browser.")
                print("     I'll see the confirmation and open the next job. Or type s=skip, l=later, q=quit + Enter.")
                choice, snapshot, confirmation = wait_for_user(page, keys)
                if choice == "q":
                    break
                job["Status"] = {"a": "applied", "s": "skipped"}.get(choice, "later")
                job["Notes"] = summary
                if choice == "a":
                    form_png, conf_png = record_submission(job, snapshot, confirmation)
                    job["Notes"] = f"{summary}; submitted/{form_png or '-'}"
                    print(f"  📸 saved submitted/{form_png} and {conf_png or '(no confirmation page)'}")
                print("  ✔ marked", job["Status"])
            job["Updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_rows(rows)  # saved after every job, so quitting never loses progress
        ctx.close()

    if args.dry_run:
        print(f"\nDry run: blocked {len(blocked)} outgoing requests — nothing was sent or submitted.")
        for b in sorted(set(blocked))[:15]:
            print("  blocked:", b)
    applied = sum(r["Status"] == "applied" for r in rows.values())
    print(f"\nDone. {applied} applied total. Spreadsheet: {XLSX}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--source", choices=SOURCES, default="newgrad")
    f.add_argument("--days", type=int, default=30, help="only jobs posted in the last N days")
    sub.add_parser("login", help="log into Simplify once in the bot browser")
    sub.add_parser("match", help="score jobs against your resume (free, no AI)")
    r = sub.add_parser("rank", help="score jobs against your resume with Claude (needs ANTHROPIC_API_KEY)")
    r.add_argument("--ats", default="greenhouse,lever,ashby", help='comma list, or "" for every site')
    r.add_argument("--source", choices=SOURCES, help="only jobs from this list")
    r.add_argument("--limit", type=int, default=500)
    r.add_argument("--rerank", action="store_true", help="score jobs that already have a Match again")
    a = sub.add_parser("apply")
    a.add_argument("--dry-run", action="store_true", help="headless, screenshot, never submit")
    a.add_argument("--watch", action="store_true", help="test mode in a visible browser, pausing on each job")
    a.add_argument("--ats", help="e.g. greenhouse,lever,ashby")
    a.add_argument("--category", default="Software,AI/ML/Data", help="comma list, or \"\" for all")
    a.add_argument("--source", choices=SOURCES, help="only jobs from this list")
    a.add_argument("--company", help="only this company, e.g. --company apex")
    a.add_argument("--limit", type=int, default=25)
    a.add_argument("--min-match", type=int, default=0, help="skip jobs `rank` scored below this")
    a.add_argument("--no-ai", action="store_true", help="don't use Claude even if ANTHROPIC_API_KEY is set")
    a.add_argument("--simplify", action="store_true", help="let the Simplify extension fill first (needs `login`)")
    args = ap.parse_args()
    if getattr(args, "watch", False):
        args.dry_run = True  # watching is always a safe test run
    {"fetch": fetch, "match": match, "rank": rank, "apply": apply, "login": login}[args.cmd](args)


if __name__ == "__main__":
    main()
