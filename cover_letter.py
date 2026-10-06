"""Cover letters: a one-page PDF with a header like a resume, written three ways (first that applies):

1. Claude (ANTHROPIC_API_KEY set): tailored to the job posting, only from the person's facts, in their voice.
2. A letter style (letter_style.json in the person's folder): their own stories, picked by keyword for each job.
3. A template (cover_template.txt): their letter with {company} {role} {name} {date} blanks filled in.
No style, template or key → no letter (the form's cover letter question is left for them).
Personal details live in the person's data folder (see paths.py), never in this code.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import paths

ROOT = paths.home()
OUT = ROOT / "cover_letters"

# the active person — set by use_identity() (profiles.activate)
NAME, CONTACT, PHONE, EMAIL = "", "", "", ""
TEMPLATE = ""   # cover_template.txt
STYLE = None    # letter_style.json: stories, opening, closing, voice notes, facts
FACTS = ""      # what letters / AI answers may say about them (resume text, or the style's facts)


def use_identity(name, contact, phone, email, out, template, facts, style=None, voice_dir=None):
    """Switch to a person: their header, their letter style or template, their facts."""
    global NAME, CONTACT, PHONE, EMAIL, OUT, TEMPLATE, FACTS, STYLE, VOICE_DIR
    style = style or {}
    NAME = style.get("name") or name
    CONTACT = style.get("contact") or contact
    PHONE, EMAIL = style.get("phone") or phone, style.get("email") or email
    OUT, TEMPLATE, STYLE, VOICE_DIR = out, template or "", style or None, voice_dir
    FACTS = style.get("facts") or facts


VOICE_DIR = None  # folder of past letters (*.txt) for Claude to match


def load_style(folder):
    try:
        return json.loads((Path(folder) / "letter_style.json").read_text())
    except (OSError, ValueError):
        return None


def fill_template(job):
    """Template → paragraphs. Blanks: {company} {title} {role} {name} {date} {phone} {email}."""
    values = {"company": job["Company"], "title": job["Title"], "role": job["Title"], "name": NAME,
              "date": datetime.now().strftime("%B %-d, %Y"), "phone": PHONE, "email": EMAIL}
    text = re.sub(r"\{(\w+)\}", lambda m: values.get(m[1].lower(), m[0]), TEMPLATE)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    # drop a greeting / sign-off if they pasted a whole letter — the PDF adds its own
    paras = [p for p in paras if not re.match(r"(dear|to whom|sincerely|best|regards|thank you,?$)", p, re.I)
             and p.strip() != NAME]
    return paras


def pick_stories(description, n=2):
    """The best-fitting 'lead' story (their strongest experience) + the best-fitting other story."""
    stories, order = STYLE["stories"], STYLE.get("order") or list(STYLE["stories"])
    text = (description or "").lower()
    scores = {k: len(re.findall(s["keywords"], text)) for k, s in stories.items()}
    rank = lambda keys: sorted(keys, key=lambda k: (-scores[k], order.index(k) if k in order else 99))
    lead = [k for k in STYLE.get("lead", []) if k in stories] or list(stories)
    first = rank(lead)[0]
    rest = [k for k in stories if k not in lead] or [k for k in stories if k != first]
    return [first, rank(rest)[0]][:n] if rest else [first]


def style_letter(job, description=""):
    company, title = job["Company"], job["Title"]
    keys = pick_stories(description)
    stories = STYLE["stories"]
    fmt = lambda s, **kw: s.format(company=company, title=title, phone=PHONE, email=EMAIL, name=NAME, **kw)
    focus = ", as well as ".join(stories[k]["focus"] for k in keys)
    text = (description or "").lower()
    extra = next((e["text"] for e in STYLE.get("extras", []) if re.search(e["keywords"], text)),
                 STYLE.get("default_extra", ""))
    opening = fmt(STYLE["opening"], focus=focus, extra=fmt(extra)).strip()
    return [opening, *[fmt(stories[k]["text"]) for k in keys], fmt(STYLE["closing"])]


# ---------- Claude (optional) ----------

SYSTEM = """You write cover letters for {name}, a student applying to new-grad roles.

FORMAT:
- Exactly four paragraphs: opening, two body paragraphs, closing. One page total (about 300-380 words).
- Opening: a strong first sentence that is not a plain statement of fact like "My name is" or "I am a senior"; then
  the position and company; how they found it (say they came across it while researching new graduate roles — never
  invent a referral, info session, or contact); why this company and role interest them, showing light research.
- Each body paragraph: a topic sentence naming one skill the job description emphasizes, then a concrete story from
  their experience proving it, ending by tying it back to this role. Do not just restate resume bullets.
- Closing: thank them, express interest again, invite contact at {phone} or {email}.

VOICE: match their past letters below if given. {voice_notes}

TRUTH: use only the facts below. Never invent projects, numbers, tools, or experiences.

FACTS:
{facts}

OUTPUT: only the four paragraphs, separated by one blank line. No header, date, greeting, or sign-off."""


def _past_letters():
    out = [p.read_text() for p in sorted(Path(VOICE_DIR).glob("*.txt"))] if VOICE_DIR and Path(VOICE_DIR).is_dir() else []
    if TEMPLATE.strip():
        out.append(TEMPLATE)
    return "\n\n---\n\n".join(out)


def claude_letter(job, description):
    import anthropic

    client = anthropic.Anthropic()
    voice = _past_letters()
    prompt = (
        (f"{NAME}'s past cover letters (match this voice):\n\n{voice}\n\n" if voice else "")
        + f"Company: {job['Company']}\nPosition: {job['Title']}\nLocation: {job.get('Location') or ''}\n\n"
        f"Job description:\n{description}"
    )
    response = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        system=SYSTEM.format(name=NAME, phone=PHONE, email=EMAIL, facts=FACTS,
                             voice_notes=(STYLE or {}).get("voice_notes", "Warm, direct, plain professional English.")),
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs if 3 <= len(paragraphs) <= 5 else None


# ---------- PDF ----------

def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    supp = Path("/System/Library/Fonts/Supplemental")
    try:
        pdfmetrics.registerFont(TTFont("TNR", str(supp / "Times New Roman.ttf")))
        pdfmetrics.registerFont(TTFont("TNR-Bold", str(supp / "Times New Roman Bold.ttf")))
        body, bold = "TNR", "TNR-Bold"
    except Exception:
        body, bold = "Times-Roman", "Times-Bold"
    try:
        pdfmetrics.registerFont(TTFont("Signature", str(supp / "Apple Chancery.ttf")))
        sig = "Signature"
    except Exception:
        sig = "Times-Italic"
    return body, bold, sig


def render_pdf(job, paragraphs, path):
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    body, bold, sig = _fonts()
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    size = 11.5
    normal = ParagraphStyle("n", fontName=body, fontSize=size, leading=size * 1.25)
    para = ParagraphStyle("p", parent=normal, spaceAfter=size * 0.9)
    name = ParagraphStyle("h", fontName=bold, fontSize=24, leading=28)
    contact = ParagraphStyle("c", fontName=body, fontSize=10.5, leading=13, alignment=TA_CENTER)
    signature = ParagraphStyle("s", fontName=sig, fontSize=18, leading=24)

    story = [
        Paragraph(NAME, name),
        HRFlowable(width="100%", thickness=0.8, color="black", spaceBefore=2, spaceAfter=3),
        Paragraph(esc(CONTACT), contact),
        Spacer(1, 18),
        Paragraph(datetime.now().strftime("%B %-d, %Y"), normal),
        Spacer(1, 12),
        Paragraph(esc(job["Company"]), normal),
        Paragraph(esc(job["Title"]), normal),
        Spacer(1, 12),
        Paragraph(f"Dear {esc(job['Company'])} Hiring Committee,", para),
        *[Paragraph(esc(p), para) for p in paragraphs],
        Paragraph("Sincerely,", normal),
        Spacer(1, 4),
        Paragraph(NAME, signature),
    ]
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title=f"{NAME} - Cover Letter - {job['Company']}", author=NAME)
    doc.build(story)


def letter_path(job):
    """cover_letters/TerraClear_Jr-Software-Development/Alex-Rivera-Cover-Letter-TerraClear.pdf —
    the file the company sees has a clean name; the folder keeps different roles apart."""
    slug = lambda t, n=50: re.sub(r"[^A-Za-z0-9]+", "-", t or "").strip("-")[:n].strip("-")
    return OUT / f"{slug(job['Company'])}_{slug(job['Title'])}" / f"{slug(NAME)}-Cover-Letter-{slug(job['Company'])}.pdf"


def make_cover_letter(job, description=""):
    """Returns (pdf_path, plain_text), or None when there's no style, template or AI to write one.
    Reuses a letter already written for this job."""
    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY")) and description
    if not STYLE and not TEMPLATE.strip() and not use_ai:
        return None
    pdf = letter_path(job)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    txt = pdf.with_suffix(".txt")
    if pdf.exists() and txt.exists():
        return pdf, txt.read_text()
    paragraphs = None
    if use_ai:
        try:
            paragraphs = claude_letter(job, description)
        except Exception as e:  # no credits / network: fall back to the template
            print("  (Claude cover letter failed, using template:", str(e).splitlines()[0][:80], ")")
    paragraphs = paragraphs or (style_letter(job, description) if STYLE else fill_template(job))
    render_pdf(job, paragraphs, pdf)
    text = f"Dear {job['Company']} Hiring Committee,\n\n" + "\n\n".join(paragraphs) + f"\n\nSincerely,\n{NAME}"
    txt.write_text(text)
    return pdf, text
