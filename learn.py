"""Learn answers from what you type into the form, and reuse them for similar questions later.

When the app leaves a question blank and you fill it in yourself, rule_for() turns that into an Answers row
(exact question → your answer). similar_answer() reuses those answers for differently-worded versions of the
same question, as a suggestion you check (yellow), and only with an option the form really has.
"""
import re
from datetime import datetime

import filler

LEARNED = "learned"  # Notes column prefix: "learned 2026-10-06 at Acme | <the original question>"
STOP = set("a an and are as at be by can do does for from have how i if in is it of on or our please the this to "
           "we what which will with would you your yes no any currently least one per us most there".split())


def words(question):
    out = set()
    for w in re.findall(r"[a-z0-9+#]+", question.lower()):
        if w in STOP or len(w) < 2:
            continue
        if len(w) > 5:
            w = re.sub(r"(ing|ed)$", "", w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # offices → office, days → day
        out.add(w)
    return out


def similarity(a, b):
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def clean_value(f):
    """What you entered, in the Answers format. None if there's nothing worth keeping."""
    v = (f.get("value") or "").strip()
    if not v or f["type"] == "file":
        return None
    if f["type"] == "checkbox":
        return "Yes" if "checked" in v else None
    if f["type"] == "checkboxes" and f.get("options"):
        picked = [o for o in f["options"] if o and o in v]
        return " & ".join(picked) if len(picked) > 1 else (picked[0] if picked else None)
    return v[:2000]


def rule_for(f, company=""):
    """[match, answer, for, notes] for a question you answered yourself."""
    answer = clean_value(f)
    if not answer:
        return None
    q = f["question"].strip()
    match = re.escape(re.sub(r"\s+", " ", q.lower().rstrip("*: ?"))[:90]).replace(r"\ ", r"\s+")
    kind = "choice" if f["type"] in filler.CHOICE_TYPES else "text"
    note = f"{LEARNED} {datetime.now():%Y-%m-%d}{' at ' + company if company else ''} | {q}"
    return [match, answer, kind, note]


def similar_answer(f, answer_rows, threshold=0.6):
    """Answer from the most similar question you answered before, or None."""
    best, best_score = None, threshold
    for row in answer_rows:
        note = str(row[3] or "") if len(row) > 3 else ""
        if not note.startswith(LEARNED) or " | " not in note:
            continue
        past_q, kind = note.split(" | ", 1)[1], (row[2] or "")
        is_choice = f["type"] in filler.CHOICE_TYPES
        if kind and kind != ("choice" if is_choice else "text"):
            continue
        s = similarity(f["question"], past_q)
        if s >= best_score:
            best, best_score = row[1], s
    if not best:
        return None
    if f.get("options"):
        if "&" in best and f["type"] == "checkboxes":
            parts = [filler.best_option(p.strip(), f["options"]) for p in best.split("&")]
            return " & ".join(p for p in parts if p) or None
        return filler.best_option(best, f["options"])
    return best
