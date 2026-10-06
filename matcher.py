"""Free, offline resume ↔ job matching (no AI key). Scores each job 0-100 with a short reason.

score = skills the posting asks for that the resume has (45%)
      + how much the role's field fits the resume (25%)
      + level: new grad / entry vs senior / years required (30%)
      × blockers: no sponsorship (when needed), PhD/Master's only.
Job descriptions come from Greenhouse/Lever/Ashby's public APIs and are cached in .cache/descriptions.json.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import ai

# canonical skill → pattern (case-insensitive unless noted)
SKILLS = {
    "Python": r"\bpython\b", "Java": r"\bjava\b(?!\s*script)", "C++": r"c\+\+", "C#": r"c#|\.net\b|dotnet",
    "JavaScript": r"javascript|\bjs\b|ecmascript", "TypeScript": r"typescript", "Go": r"\bgolang\b|\bgo\s*\(|\bin go\b",
    "Rust": r"\brust\b", "Kotlin": r"\bkotlin\b", "Swift": r"\bswift\b", "Ruby": r"\bruby\b", "PHP": r"\bphp\b",
    "Scala": r"\bscala\b", "SQL": r"\bsql\b", "Bash": r"\bbash\b|shell script", "PowerShell": r"powershell",
    "MATLAB": r"\bmatlab\b", "C": r"\bC/C\+\+|\bC,\s*C\+\+|\bin C\b|\bC programming",
    "React": r"\breact(\.js)?\b(?!\s*native)", "Angular": r"\bangular", "Vue": r"\bvue(\.js)?\b", "Node.js": r"node\.?js|\bnode\b",
    "HTML": r"\bhtml", "CSS": r"\bcss\b", "Django": r"\bdjango\b", "Flask": r"\bflask\b", "FastAPI": r"fastapi",
    "Spring": r"\bspring( boot)?\b", "GraphQL": r"graphql", "REST APIs": r"\brest(ful)?\b|\bapis?\b",
    "AWS": r"\baws\b|amazon web services|\blambda\b|\bec2\b|\bs3\b", "Azure": r"\bazure\b", "GCP": r"\bgcp\b|google cloud",
    "Docker": r"\bdocker", "Kubernetes": r"kubernetes|\bk8s\b", "Terraform": r"terraform", "AWS CDK": r"\bcdk\b",
    "CI/CD": r"ci/cd|continuous integration|\bjenkins\b|github actions|gitlab ci", "Jenkins": r"\bjenkins\b",
    "Linux": r"\blinux|\bunix\b", "Git": r"\bgit\b|github|gitlab",
    "Machine learning": r"machine learning|\bml\b", "Deep learning": r"deep learning|neural net",
    "PyTorch": r"pytorch", "TensorFlow": r"tensorflow|keras", "scikit-learn": r"scikit|sklearn",
    "NLP": r"\bnlp\b|natural language", "LLMs": r"\bllms?\b|large language model|generative ai|\bgenai\b",
    "Computer vision": r"computer vision|\bopencv\b", "Pandas": r"\bpandas\b", "NumPy": r"\bnumpy\b",
    "Spark": r"\bspark\b|pyspark", "Kafka": r"\bkafka\b", "Airflow": r"\bairflow\b", "Snowflake": r"snowflake",
    "Tableau": r"tableau", "Power BI": r"power\s?bi", "Excel": r"\bexcel\b", "Statistics": r"statistic",
    "PostgreSQL": r"postgres", "MySQL": r"mysql", "MongoDB": r"mongo", "Redis": r"\bredis\b", "DynamoDB": r"dynamo",
    "iOS": r"\bios\b", "Android": r"\bandroid\b", "React Native": r"react native", "Flutter": r"flutter",
    "Embedded": r"embedded|firmware|\brtos\b|microcontroller", "FPGA": r"\bfpga|verilog|vhdl",
    "Networking": r"tcp/ip|networking|\bdns\b",
    "Security": r"cyber|penetration test|vulnerabilit|\bctf\b|security engineer|application security|information security"
                r"|appsec|threat model|reverse engineer",
    "Distributed systems": r"distributed systems|microservice", "Robotics": r"robotic|\bros\b",
    "RPA": r"\brpa\b|uipath|automation anywhere", "Salesforce": r"salesforce", "Unity": r"\bunity\b|unreal",
    "Agile": r"\bagile\b|scrum", "Data structures": r"data structures|algorithms",
}
_SKILL_RX = {k: re.compile(v, re.I if not k == "C" else 0) for k, v in SKILLS.items()}

# role families: what the title looks like, and what in a resume shows affinity for it
FAMILIES = {
    "software": (r"software|developer|\bswe\b|engineer(ing)?\b.*(backend|frontend|full.?stack|platform|cloud|infra|devops|"
                 r"site reliability|mobile|ios|android|web|api|product|systems|tools|application)|backend|front.?end|"
                 r"full.?stack|devops|\bsre\b|platform engineer|cloud engineer|member of technical staff|programmer",
                 ["Python", "Java", "C++", "JavaScript", "TypeScript", "Go", "React", "Node.js", "AWS", "Git", "SQL",
                  "Docker", "Linux", "REST APIs", "Data structures"]),
    "data": (r"\bdata\b|analytics|analyst|business intelligence|\bbi\b",
             ["SQL", "Python", "Pandas", "Tableau", "Power BI", "Excel", "Statistics", "Spark", "Snowflake"]),
    "ml": (r"machine learning|\bml\b|\bai\b|artificial intelligence|research engineer|applied scientist|deep learning|"
           r"computer vision|\bnlp\b|llm",
           ["Machine learning", "Deep learning", "PyTorch", "TensorFlow", "NLP", "LLMs", "Python", "scikit-learn"]),
    "embedded": (r"embedded|firmware|hardware|electrical|fpga|asic|silicon|circuit|rf\b|power electronics|physical design"
                 r"|\bgpu\b.*design|chip|soc design|verification engineer|analog|mixed.?signal|layout",
                 ["Embedded", "C", "C++", "FPGA", "MATLAB"]),
    "it": (r"\bit\b|support|help ?desk|technician|systems administrator|sysadmin|network|desktop",
           ["PowerShell", "Linux", "Networking", "Bash"]),
    "security": (r"security|cyber|soc\b|threat|penetration", ["Security", "Linux", "Networking", "Python"]),
    "quant": (r"quant|trader|trading", ["Python", "C++", "Statistics"]),
    "other_eng": (r"mechanical|civil|chemical|manufacturing|process engineer|test engineer|quality engineer|"
                  r"field engineer|structural|aerospace engineer|propulsion", []),
    "non_tech": (r"sales|marketing|recruit|account (executive|manager)|nurse|teacher|designer|artist|technical art|"
                 r"customer success|operations associate|legal|paralegal|hr\b|human resources|writer", []),
}

SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|architect|vp)\b", re.I)
MID = re.compile(r"\b(ii|iii|iv|2|3|level 2|mid)\b(?!\d)", re.I)
INTERN = re.compile(r"\b(intern(ship)?|co-?op)\b", re.I)
JUNIOR = re.compile(r"new grad|graduate|entry|junior|\bjr\b|associate|early career|university|campus|"
                    r"\b(i|1)\b(?!\d)|apprentice|rotational", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*(\d{1,2})?\s*\+?\s*years?(?:'|’)?\s*(?:of\s+)?(?:\w+\s+){0,4}experience",
                   re.I)
NO_SPONSOR = re.compile(  # hard blockers for someone who needs a visa
    r"(not|unable to|will not|won'?t|cannot|can'?t|does not|do not|is not able to)\s+(?:\w+\s+){0,4}sponsor"
    r"(?!\w*\s+(?:\w+\s+){0,2}(?:for )?an? export)"
    r"|without (?:the need for |needing |requiring )?(?:\w+\s+){0,2}sponsorship(?! for an export)|no (?:visa )?sponsorship"
    r"|u\.?s\.? citizen(?:ship)?\s+(?:is\s+)?required|must be (?:a )?u\.?s\.? citizen|only u\.?s\.? citizens"
    r"|clearance[^.\n]{0,60}\b(required|must|eligib|obtain)|\b(required|must|eligib\w*|obtain|ability to obtain)\b[^.\n]{0,60}"
    r"\bclearance|ts/sci", re.I)
EXPORT = re.compile(r"\bitar\b|export control|u\.?s\.? persons?\b", re.I)  # usually U.S. persons only — strong penalty
ADVANCED = re.compile(r"(ph\.?d|doctorate|master'?s)[^.\n]{0,50}(required|must|minimum)|(required|must have|minimum)"
                      r"[^.\n]{0,40}(ph\.?d|doctorate|master'?s)", re.I)


def skills_in(text):
    return {k for k, rx in _SKILL_RX.items() if rx.search(text or "")}


def family_of(title):
    t = (title or "").lower()
    if re.search(r"software (engineer|developer|development)|\bswe\b|full.?stack|backend|front.?end", t) \
            and not re.search(r"machine learning engineer|ml engineer|data engineer", t):
        return "software"
    for fam in ("non_tech", "ml", "security", "embedded", "quant", "data", "it", "other_eng", "software"):
        if re.search(FAMILIES[fam][0], t, re.I):
            return fam
    return "software" if "engineer" in t else "other"


def level(title, desc):
    """1.0 entry/new grad … 0.05 senior. Returns (score, label)."""
    if SENIOR.search(title):
        return 0.05, "senior role"
    if INTERN.search(title):
        return 0.1, "internship"
    years = [int(a) for a, b in YEARS.findall(desc or "") if int(a) <= 15]
    need = min(years) if years else None
    title_level = (1.0, "new grad") if JUNIOR.search(title) else (0.4, "mid-level") if MID.search(title) else (0.75, "")
    if need is not None and need >= 3:
        return min(title_level[0], 0.2), f"needs {need}+ yrs"
    if need == 2:
        return min(title_level[0], 0.55), "needs 2+ yrs"
    return title_level


def score_job(job, desc, resume_skills, affinity, needs_sponsorship):
    title = job.get("Title") or ""
    text = f"{title}\n{desc}"
    want = skills_in(text)
    have = want & resume_skills
    skill = (len(have) + 0.5) / (len(want) + 1.5) if want else 0.45
    fam = family_of(title)
    role = 0.05 if fam == "non_tech" else 0.25 + 0.75 * affinity.get(fam, 0.15)
    lvl, lvl_label = level(title, desc)
    score = 100 * (0.45 * skill + 0.25 * role + 0.30 * lvl)
    # wrong level or wrong field sinks the whole score, however good the skill overlap
    score *= {"senior role": 0.45, "internship": 0.5}.get(lvl_label, 0.7 if lvl_label.startswith("needs") and lvl < 0.5 else 1)
    score *= {"non_tech": 0.4, "other_eng": 0.6}.get(fam, 1)
    flags = []
    if needs_sponsorship and NO_SPONSOR.search(desc or ""):
        score, flags = min(score, 5), ["no sponsorship"]
    elif needs_sponsorship and EXPORT.search(desc or ""):
        score, flags = score * 0.4, ["export-controlled (U.S. persons)"]
    if ADVANCED.search(desc or "") or re.search(r"ph\.?d|master", title, re.I):
        score *= 0.5
        flags.append("grad degree")
    if not desc:  # couldn't read the posting: sponsorship and years unchecked — rank below verified matches
        score *= 0.85
    top = sorted(have, key=lambda k: list(SKILLS).index(k))[:3]
    why = " · ".join(x for x in [", ".join(top) or ("no skill overlap" if want else ""), lvl_label, *flags,
                                 "" if desc else "title only"] if x)
    return round(max(0, min(100, score))), why


def resume_profile(resume_text):
    """Skills on the resume + how strongly it points at each role family (0..1)."""
    have = skills_in(resume_text)
    affinity = {}
    for fam, (_, fam_skills) in FAMILIES.items():
        affinity[fam] = min(1.0, len(have & set(fam_skills)) / 4) if fam_skills else 0.0
    return have, affinity


def load_cache(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def match_jobs(jobs, resume_text, needs_sponsorship, cache_path, on_progress=None, workers=12):
    """Set Match/Why on each job. Descriptions are fetched once and cached."""
    cache = load_cache(cache_path)
    todo = [j for j in jobs if j["ID"] not in cache]
    done = 0

    def fetch(job):
        return job["ID"], ai.fetch_description(job)
    with ThreadPoolExecutor(workers) as pool:
        for jid, desc in pool.map(fetch, todo):
            cache[jid] = desc
            done += 1
            if on_progress and (done % 10 == 0 or done == len(todo)):
                on_progress(f"Reading job posts {done}/{len(todo)}…")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    have, affinity = resume_profile(resume_text)
    for j in jobs:
        j["Match"], j["Why"] = score_job(j, cache.get(j["ID"], ""), have, affinity, needs_sponsorship)
    return jobs
