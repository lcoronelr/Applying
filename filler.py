"""Form filler: finds every question on an application page, answers it from the Answers sheet,
then re-checks the page and reports required questions that are still empty."""
import re
from pathlib import Path
from datetime import datetime

# Answers sheet format. Order matters: first matching row wins.
# Match = words/regex looked for in the question (case-insensitive). Answer alternatives are split by "|":
# text boxes get the first one, dropdowns/radios/buttons pick whichever option matches.
# For = blank (any field), "choice" (dropdown/radio/buttons/checkbox) or "text" (typing boxes).
# Match starting with "#2 " only applies to the 2nd copy of a question (e.g. a second education entry).
# Special answers: @resume = upload resume.pdf, @cover_letter = this job's cover letter, SKIP = leave empty.
# {company}, {title}, {today} are filled in.

def full_name(p):
    return f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()


def answers_for(p):
    """Someone's starting Answers sheet, built from their profile form. Order matters: first match wins."""
    yes = lambda v: "Yes" if v else "No"
    spons = bool(p.get("needs_sponsorship"))
    grad = p.get("graduation", "")
    month, year = (grad.split() + ["", ""])[:2] if grad else ("", "")
    rows = [
        ("autofill", "SKIP", "", "Ashby's 'autofill from resume' box"),
        ("cover letter", "@cover_letter", "", "your template (or Claude, with a key)"),
        ("resume|\\bcv\\b", "@resume", "", ""),
        ("first and last|full.?name|legal name|your name|^name$", full_name(p), "", ""),
        ("preferred.?(first.?)?name|nickname", p.get("first_name", ""), "", ""),
        ("first.?name|given.?name", p.get("first_name", ""), "", ""),
        ("last.?name|family.?name|surname", p.get("last_name", ""), "", ""),
        ("pronoun", "SKIP", "", ""),
        ("e-?mail", p.get("email", ""), "text", ""),
        ("country", "United States|United States of America|USA|US", "", ""),
        ("phone|mobile", p.get("phone", ""), "text", ""),
        ("linkedin", p.get("linkedin", ""), "text", ""),
        ("github", p.get("github", ""), "text", ""),
        ("website|portfolio|personal.?site|other.?(url|link)", p.get("website", ""), "text", ""),
        ("without.{0,30}sponsor", yes(not spons), "", ""),
        ("sponsor|visa|h-?1b|immigration", yes(spons), "choice", ""),
        ("sponsor|visa|h-?1b|immigration",
         "I will need visa sponsorship in the future." if spons else "I do not require sponsorship.", "text", ""),
        ("authori[sz]ed|eligible to work|legally|right to work|work permit",
         "Yes" + ("|I require sponsorship|require sponsorship" if spons else "|authorized to work"), "", ""),
        ("relocat", yes(p.get("relocate", True)), "", ""),
        ("hybrid|on-?site|in.?office|in-person|commut|days a week|tied to the office|office location",
         ("willing to relocate|relocate|Yes" if p.get("relocate", True) else "No"), "choice", ""),
        ("employment history|previously (been )?(employed|worked)|ever (been )?employed|worked (for|at) .{0,40}before"
         "|former employee|ever worked", "No|Never|None|have not|I have not", "", ""),
        ("text message|\\bsms\\b", "No", "", ""),
        ("18 years|age of 18|at least 18", "Yes", "", ""),
        ("were you referred|referred by|referral", "No", "", ""),
        ("read and understand|privacy|consent|acknowledge|agree|certify|attest|terms", "Yes", "", "consent boxes"),
        ("how did you (hear|find|learn)|where did you (hear|find)|^source", "LinkedIn|Job Board|Online|Other", "", ""),
        ("zip|postal", p.get("zip", ""), "", ""),
        ("state of residence|^state$", p.get("state", ""), "", ""),
        ("city|location|where are you (currently )?(located|based)", p.get("city", ""), "", ""),
        ("end (date )?year|graduat\\w* year|year .{0,25}graduat|year of graduation", year, "", ""),
        ("end (date )?month|graduation month", month, "", ""),
        ("school|university|college|institution", p.get("school", ""), "", ""),
        ("level of education|highest (level|degree|education)|degree type|^degree|education level",
         "Bachelor's|Bachelor|Undergraduate|BS|BA", "", ""),
        ("major|field of study|discipline|concentration|area of study", p.get("major", ""), "", ""),
        ("\\bgpa\\b|grade point", p.get("gpa", ""), "", ""),
        ("graduat", grad, "", ""),
        ("gender|^sex$", p.get("gender") or "Decline|don't wish|prefer not", "", "EEO"),
        ("hispanic|latin", p.get("hispanic") or "Decline|don't wish|prefer not", "", "EEO"),
        ("race|ethnic", p.get("race") or "Decline|don't wish|prefer not", "", "EEO"),
        ("veteran", p.get("veteran") or "not a protected veteran|I am not|No", "", "EEO"),
        ("disabilit", p.get("disability") or "Decline|don't wish|do not want|prefer not|not to", "", "EEO"),
        ("security clearance|clearance", "No|None", "", ""),
        ("relatives?|family member|financial or business interest|conflict of interest", "No", "", ""),
        ("essential functions|reasonable accommodation", "Yes", "", ""),
        ("if (you answered )?yes|if so|please explain", "N/A", "text", ""),
        ("^date$|today'?s date|signature date", "{today}", "", "fills today's date"),
        ("notice period|how much notice|notice (would|do) you", "Immediately|None|0|2 weeks|Two weeks", "", ""),
        ("start date|available to start|earliest .{0,20}start|when can you start", p.get("start_date") or
         (f"After graduation ({grad})" if grad else ""), "", ""),
        ("salary|compensation|pay expectation|desired pay", "Open to market rate for the role|Negotiable", "", ""),
        ("anything else|additional information|cover note", "SKIP", "", ""),
    ]
    return [r for r in rows if r[1] != ""]  # blank answers would block matching — leave those questions to them


CHOICE_TYPES = {"select", "radio", "checkboxes", "checkbox", "buttons", "combobox"}

SCAN_JS = r"""
() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const CTL = 'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=search]), select, textarea, button[aria-pressed]';
  const choice = e => e && e.matches && e.matches('input[type=radio], input[type=checkbox]');
  const groupSize = e => e.name ? document.querySelectorAll(`input[name="${CSS.escape(e.name)}"]`).length : 1;

  // a checkbox is an option (not its own question) when the nearest ancestor holding several checkboxes
  // has exactly one question label — e.g. "Degree Type: [ ] Bachelor's [ ] Master's"
  const QSEL = 'label, legend, .application-label, [class*=question-title], .upload-label';
  const isQ = l => l.matches('legend, .application-label, [class*=question-title], .upload-label')
    || !choice(l.htmlFor ? document.getElementById(l.htmlFor) : l.querySelector('input'));
  const inGroup = e => { let a = e; for (let k = 0; k < 5 && a.parentElement; k++) { a = a.parentElement;
    if (a.querySelectorAll('input[type=checkbox]').length > 1)
      return [...a.querySelectorAll(QSEL)].filter(isQ).length <= 1; } return false; };
  const GENERIC = /^(attach|upload( file)?|enter manually|dropbox|google drive|choose files?|browse|replace)$/i;
  let qs = [...document.querySelectorAll('label, legend, .application-label, [class*=question-title], .upload-label')].filter(q => {
    if (!txt(q) || GENERIC.test(txt(q)) || (q.matches('.application-label') && q.closest('label'))) return false;
    const t = q.htmlFor ? document.getElementById(q.htmlFor) : q.querySelector(CTL);
    if (choice(t) && (t.type === 'radio' || groupSize(t) > 1 || inGroup(t))) return false;   // an option
    return true;
  });
  const qtextOf = q => { const c = q.cloneNode(true);
    c.querySelectorAll('select, option, input, textarea, button, ul, .application-field').forEach(x => x.remove());
    return txt(c).replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim().slice(0, 200); };
  const set = new Set(qs);
  qs = qs.filter(q => { for (let p = q.parentElement; p; p = p.parentElement) if (set.has(p)) return false; return true; });

  document.querySelectorAll('[data-bot-field]').forEach(e => e.removeAttribute('data-bot-field'));
  document.querySelectorAll('[data-bot-for]').forEach(e => e.removeAttribute('data-bot-for'));
  const fields = [], used = new Set();
  qs.forEach(q => {
    let box = q;
    while (box.parentElement && box.parentElement !== document.body
           && qs.filter(o => box.parentElement.contains(o)).length === 1) box = box.parentElement;
    let ctls = [...box.querySelectorAll(CTL)];
    const target = q.htmlFor && document.getElementById(q.htmlFor);
    if (target && target.matches(CTL) && !box.contains(target)) ctls.push(target);
    ctls = ctls.filter(c => !used.has(c) && (c.type === 'file' || choice(c) || vis(c)));
    if (!ctls.length) return;
    ctls.forEach(c => used.add(c));
    const has = s => ctls.some(c => c.matches(s));
    const type = has('input[type=file]') ? 'file' : has('button[aria-pressed]') ? 'buttons'
      : has('input[type=radio]') ? 'radio'
      : has('input[type=checkbox]') ? (ctls.filter(c => c.type === 'checkbox').length > 1 ? 'checkboxes' : 'checkbox')
      : has('select') ? 'select'
      : has('[role=combobox], [aria-autocomplete=list]') ? 'combobox'
      : ctls.some(c => /date/i.test(c.className + ' ' + c.type + ' ' + (c.placeholder || '')) || c.closest('.react-datepicker-wrapper')) ? 'date'
      : has('textarea') ? 'textarea' : 'text';
    const optLabel = c => txt((c.id && document.querySelector(`label[for="${CSS.escape(c.id)}"]`)) || c.closest('label') || c.parentElement);
    const options = type === 'select' ? [...ctls.find(c => c.tagName === 'SELECT').options].map(o => o.text.trim()).filter(Boolean)
      : ['radio', 'checkboxes'].includes(type) ? ctls.filter(choice).map(optLabel)
      : type === 'buttons' ? ctls.filter(c => c.matches('button[aria-pressed]')).map(txt) : [];
    const c0 = ctls[0];
    const filled = type === 'file' ? /\.(pdf|docx?|txt|rtf)\b/i.test(txt(box)) || ctls.some(c => c.files && c.files.length > 0)
      : ['radio', 'checkbox', 'checkboxes'].includes(type) ? ctls.some(c => c.checked)
      : type === 'buttons' ? ctls.some(c => c.getAttribute('aria-pressed') === 'true')
      : type === 'text' || type === 'textarea' || type === 'date' ? ctls.some(c => vis(c) && c.value)
      : type === 'select' ? (() => { const s = ctls.find(c => c.tagName === 'SELECT'); return s.selectedIndex > 0 || (s.selectedIndex === 0 && !!s.value && !/select|choose|^-+$/i.test(s.options[0].text)); })()
      : type === 'combobox' ? !!(c0.value || box.querySelector('[class*=single-value], [class*=singleValue], [class*=multi-value]'))
      : !!c0.value;
    const sel = ctls.find(c => c.tagName === 'SELECT');
    const file = ctls.find(c => c.files && c.files.length);
    const value = type === 'file' ? (file ? file.files[0].name : ((txt(box).match(/[\w .-]+\.(pdf|docx?)/i) || [''])[0]))
      : type === 'select' ? (filled ? sel.options[sel.selectedIndex].text.trim() : '')
      : ['radio', 'checkboxes'].includes(type) ? ctls.filter(c => choice(c) && c.checked).map(optLabel).join(', ')
      : type === 'checkbox' ? (ctls.some(c => c.checked) ? '✓ checked' : '')
      : type === 'buttons' ? ctls.filter(c => c.getAttribute('aria-pressed') === 'true').map(txt).join(', ')
      : type === 'combobox' ? txt(box.querySelector('[class*=single-value], [class*=singleValue]') || box.querySelector('[class*=multi-value]') || c0) || c0.value || ''
      : (ctls.find(c => vis(c) && c.value) || {}).value || '';
    const qtext = txt(q);
    const required = /[*✱]/.test(qtext) || ctls.some(c => c.required || c.getAttribute('aria-required') === 'true')
      || /required/i.test(q.className);
    const i = fields.length;
    box.setAttribute('data-bot-field', i);
    ctls.forEach(c => c.setAttribute('data-bot-for', i));
    const numeric = ctls.some(c => c.type === 'number');
    fields.push({ i, type, required, filled, numeric, value: String(value).slice(0, 300), options: options.slice(0, 500), question: qtextOf(q) });
  });
  return fields;
}
"""

MARK_MISSING_JS = """(ids) => ids.forEach(i => { const b = document.querySelector(`[data-bot-field="${i}"]`);
  if (b) { b.style.outline = '3px solid #e5484d'; b.style.outlineOffset = '4px'; } })"""


MARK_DRAFTED_JS = """(ids) => ids.forEach(i => { const b = document.querySelector(`[data-bot-field="${i}"]`);
  if (b) { b.style.outline = '3px solid #f5a524'; b.style.outlineOffset = '4px'; } })"""  # yellow = AI wrote it, check it


# A resume file name shown anywhere on the form ("resume.pdf", "Alex Rivera Resume.pdf") means one is attached.
RESUME_ON_PAGE_JS = r"""() => [...document.querySelectorAll('body *')].some(e => e.children.length === 0
  && e.offsetParent !== null && e.textContent.length < 150
  && /[\w()-]\.(pdf|docx?)\b/i.test(e.textContent) && !/cover/i.test(e.textContent))"""


# ---------- answer lookup ----------

def compile_answers(rows):
    """rows: [(match, answer, for)] → [(regex, answer, for)]. Bad regexes are treated as plain text."""
    out = []
    for match, answer, *rest in rows:
        if not match:
            continue
        match = str(match)
        occ = 0
        if re.match(r"#\d+ ", match):  # "#2 school|#2 degree" → only the 2nd copy of those questions
            occ = int(match[1:match.index(" ")])
            match = re.sub(r"#\d+ ", "", match)
        try:
            rx = re.compile(match, re.I)
        except re.error:
            rx = re.compile(re.escape(match), re.I)
        out.append((rx, "" if answer is None else str(answer), (rest[0] or "").strip().lower() if rest else "", occ))
    return out


def find_answers(question, answers, job, ftype="text", occurrence=1):
    """All answers whose Match fits the question and whose For fits the field type, in sheet order.
    A matching row with a blank answer stops the search (it means "I'll answer this myself")."""
    kind = "choice" if ftype in CHOICE_TYPES else "text"
    out = []
    for rx, answer, applies, occ in answers:
        if applies in ("choice", "text") and applies != kind and ftype not in ("file", "combobox"):
            continue
        if occ and occ != occurrence:
            continue
        if rx.search(question):
            if not answer:
                break
            out.append(answer.replace("{company}", job.get("Company") or "").replace("{title}", job.get("Title") or "")
                       .replace("{today}", datetime.now().strftime("%m/%d/%Y")))
    return out


def find_answer(question, answers, job, ftype="text", occurrence=1):
    found = find_answers(question, answers, job, ftype, occurrence)
    return found[0] if found else ""


def norm(s):
    s = s.lower().replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^\w+'/ ]", " ", s)).strip()


def best_option(answer, options):
    """Pick the option that matches the first answer alternative possible; shortest wins within a tier."""
    opts = [(o, norm(o)) for o in options if o.strip()]
    for alt in [norm(a) for a in answer.split("|") if a.strip()]:
        tiers = [
            [o for o, n in opts if n == alt],
            [o for o, n in opts if re.match(rf"{re.escape(alt)}(\b|$|\W)", n)],
            [o for o, n in opts if re.search(rf"(^|\W)(?<!not )(?<!non ){re.escape(alt)}(\b|$|\W)", n)],
        ]
        for tier in tiers:
            if tier:
                return min(tier, key=len)
    return None


def as_date(answer):
    for alt in answer.split("|"):
        if re.match(r"\d{1,2}/\d{1,2}/\d{4}$", alt.strip()):
            return alt.strip()
    try:
        return datetime.strptime(answer.split("|")[0].strip(), "%B %Y").strftime("%m/15/%Y")
    except ValueError:
        return answer.split("|")[0]


# ---------- filling ----------

def _pick_from_listbox(frame, answer, seen=None):
    opts = frame.locator("[role=option]:visible")
    texts = [t.strip() for t in opts.all_inner_texts()]
    if seen is not None and texts:
        seen[:] = texts[:500]
    choice = best_option(answer, texts)
    if choice is None:
        return False
    opts.nth(texts.index(choice)).click()
    return True


def fill_field(frame, f, answer, resume_path, cover_letter=None):
    ctl = lambda sel: frame.locator(f'[data-bot-for="{f["i"]}"]:is({sel})')
    t = f["type"]
    first = answer.split("|")[0]
    if answer == "@cover_letter":
        if not cover_letter:
            return False
        made = cover_letter()
        if not made:  # no template / no AI for this person — leave it for them
            return False
        pdf, text = made
        if t == "file":
            ctl("input[type=file]").first.set_input_files(str(pdf))
            frame.page.wait_for_timeout(2000)
            return True
        if t in ("text", "textarea"):
            ctl("input:visible, textarea:visible").first.fill(text)
            return True
        return False
    if t == "file":
        if answer != "@resume":
            return False
        if not Path(resume_path).is_file():
            raise ValueError("no resume in your profile — add it on the Profile page")
        inp = ctl("input[type=file]").first
        if inp.evaluate("e => e.files && e.files.length > 0") or frame.evaluate(RESUME_ON_PAGE_JS):
            return True  # Simplify (or you) already attached one
        inp.set_input_files(resume_path)
        frame.page.wait_for_timeout(2000)
        return True
    if t in ("text", "textarea"):
        if f.get("numeric") and not re.fullmatch(r"[\d.]+", first):
            return False
        el = ctl("input:visible, textarea:visible").first
        if el.evaluate("e => e.classList.contains('location-input')"):  # Lever: only a picked suggestion counts
            el.fill("")
            el.press_sequentially(first, delay=30)
            sugg = frame.locator(".dropdown-results .dropdown-location").first
            try:
                sugg.wait_for(timeout=4000)
            except Exception:
                return False
            sugg.click()
            return True
        el.fill(first)
    elif t == "date":
        el = ctl("input:visible").first
        el.fill(as_date(answer))
        frame.page.keyboard.press("Escape")  # never Enter: it can submit the form
    elif t == "select":
        choice = best_option(answer, f["options"])
        if not choice:
            return False
        ctl("select").first.select_option(label=choice)
    elif t == "checkboxes" and (answer == "@all" or "&" in answer):  # tick several: "A|a2 & B|b2", or @all
        picks = f["options"] if answer == "@all" else [best_option(a, f["options"]) for a in answer.split("&")]
        picks = [o for o in dict.fromkeys(picks) if o]
        if not picks:
            return False
        for choice in picks:
            inp = ctl("input[type=checkbox]").nth(f["options"].index(choice))
            try:
                inp.check(force=True)
            except Exception:
                inp.evaluate("e => (e.closest('label') || e).click()")
    elif t in ("radio", "checkboxes", "buttons"):
        choice = best_option(answer, f["options"])
        if not choice:
            return False
        idx = f["options"].index(choice)
        if t == "buttons":
            ctl("button[aria-pressed]").nth(idx).click()
        else:
            inp = ctl("input[type=radio], input[type=checkbox]").nth(idx)
            try:
                inp.check(force=True)
            except Exception:  # styled radios (Lever) only react to a real click on their label
                inp.evaluate("e => (e.closest('label') || e).click()")
    elif t == "checkbox":
        if norm(first) not in ("yes", "true", "agree", "i agree", "x"):
            return False
        ctl("input[type=checkbox]").first.check(force=True)
    elif t == "combobox":
        el = ctl("[role=combobox], [aria-autocomplete=list]").first
        el.click()
        frame.page.wait_for_timeout(500)
        if _pick_from_listbox(frame, answer, f["options"]):  # short static list (Yes/No, EEO, country)
            return True
        for alt in [a for a in answer.split("|") if a.strip()][:3]:  # searchable list (location, school)
            el.fill("")
            el.press_sequentially(alt, delay=30)
            for _ in range(10):  # suggestions load from the network — give them up to 5s
                frame.page.wait_for_timeout(500)
                if _pick_from_listbox(frame, alt):
                    return True
        el.fill("")
        frame.page.keyboard.press("Escape")
        return False
    return True


def fill_page(page, answers, job, resume_path, passes=3, cover_letter=None, drafter=None):
    """Fill every frame, re-scanning so follow-up questions that appear get answered too.
    drafter(field) -> answer or None: asked for required questions the Answers sheet doesn't cover (AI).
    Returns one dict per question on the final page: question/type/required/options/status."""
    report = []
    page.set_default_timeout(8000)  # one stubborn field shouldn't stall the whole run
    for frame in page.frames:
        add_education = True
        tried, seen_options = {}, {}  # question -> status of our attempt / options it offered
        refilled = set()  # filled once but the page wiped it (re-render) → one more try
        uploaded = set()  # @resume / @cover_letter already sent on this form — never upload a file twice
        try:
            for _ in range(passes):
                todo = [f for f in number_repeats(frame.evaluate(SCAN_JS)) if not f["filled"]
                        and (key(f) not in tried or (tried[key(f)] == "filled" and key(f) not in refilled
                                                     and f["type"] != "file"))]
                refilled |= {key(f) for f in todo if key(f) in tried}
                if not todo:
                    break
                for f in todo:
                    found = find_answers(f["question"], answers, job, f["type"], f["occ"])
                    if f["type"] == "file" and found and found[0] in uploaded:
                        tried[key(f)] = "filled"
                        continue
                    tried[key(f)] = attempt(frame, f, found, resume_path, cover_letter)
                    if f["type"] == "file" and tried[key(f)] == "filled":
                        uploaded.add(found[0])
                    seen_options[key(f)] = f["options"]
                if add_education and has_second_education(answers) and frame.evaluate(ADD_EDUCATION_JS):
                    add_education = False  # second degree: click "Add another" once, next pass fills it
                    page.wait_for_timeout(800)
                    continue
                page.wait_for_timeout(800)
            if drafter:
                for f in number_repeats(frame.evaluate(SCAN_JS)):
                    if f["required"] and not f["filled"] and tried.get(key(f)) in (None, "no answer", "no matching option"):
                        answer = drafter(f)
                        if answer and attempt(frame, f, [answer], resume_path) == "filled":
                            tried[key(f)] = "ai-drafted"
            final = number_repeats(frame.evaluate(SCAN_JS))
        except Exception:
            continue  # detached / cross-origin frame
        for f in final:
            st = tried.get(key(f))
            f["options"] = f["options"] or seen_options.get(key(f), [])
            if f["filled"]:
                f["status"] = st if st in ("filled", "ai-drafted") else "already"
            else:
                f["status"] = "didn't stick" if st == "filled" else (st or "no answer")
        try:
            frame.evaluate(MARK_MISSING_JS, [f["i"] for f in final if is_missing(f)])
            frame.evaluate(MARK_DRAFTED_JS, [f["i"] for f in final if f["status"] == "ai-drafted"])
        except Exception:
            pass
        report += final
    return report


def key(f):
    return f"{f['type']}:{f['question'][:60]}#{f.get('occ', 1)}"


def number_repeats(fields):
    """Same question twice (School, School) → occ 1, 2 so '#2' answers can target the second."""
    seen = {}
    for f in fields:
        k = f["type"] + f["question"]
        seen[k] = seen.get(k, 0) + 1
        f["occ"] = seen[k]
    return fields


ADD_EDUCATION_JS = r"""
() => {
  if (document.querySelector('[id$="--1"][id^=school], [name*="school"][name*="1"]')) return false;
  const btn = [...document.querySelectorAll('button, a[role=button]')].find(b => {
    if (!/^\+?\s*add (another|more|education)/i.test((b.innerText || '').trim())) return false;
    let a = b; for (let k = 0; k < 5 && a.parentElement; k++) { a = a.parentElement;
      if ([...a.querySelectorAll('label')].some(l => /^(school|university|institution)/i.test(l.innerText.trim()))) return true; }
    return false;
  });
  if (!btn) return false;
  btn.click();
  return true;
}
"""


def attempt(frame, f, candidates, resume_path, cover_letter=None):
    """Try each matching answer until one fits the field (e.g. a radio needs 'Yes', not a paragraph)."""
    if not candidates:
        return "no answer"
    if candidates[0] == "SKIP":
        return "skipped"
    status = "no matching option"
    for answer in candidates:
        if answer == "SKIP":
            break
        try:
            if fill_field(frame, f, answer, resume_path, cover_letter):
                return "filled"
        except Exception as e:
            status = "error: " + str(e).splitlines()[0][:60]
    return status


def has_second_education(answers):
    return any(occ == 2 and re.search("school|discipline|major|degree", rx.pattern) for rx, _, _, occ in answers)


def is_missing(f):
    return f["required"] and f["status"] not in ("filled", "already", "ai-drafted")
