# Apply

**Fill out job applications in seconds — and still submit every one yourself.**

Apply is a Mac app for new-grad job hunting. It opens each application right inside the app, fills in everything
it knows about you (name, school, links, resume, cover letter, work-authorization answers…), and waits. You check
the form, click the site's **Submit** button, and the next job opens on its own. It never submits anything for you.

## Download

**[⬇ Download Apply for Mac](https://github.com/lcoronelr/Applying/releases/latest)** — open the `.dmg`, drag Apply
into Applications. Apple-chip Macs (M1 or newer).

First launch: macOS says the app *"can't be verified"* (it isn't from the App Store). Open
**System Settings → Privacy & Security** and click **Open Anyway**. Step-by-step guide: **[FRIENDS.md](FRIENDS.md)**.

## What it does

- **Fills applications** on Greenhouse, Lever and Ashby (and many others): text, dropdowns, checkboxes, date pickers,
  location search boxes, resume and cover-letter uploads.
- **Finds jobs** — pulls new-grad software roles from public lists
  ([SimplifyJobs](https://github.com/SimplifyJobs/New-Grad-Positions),
  [speedyapply](https://github.com/speedyapply/2027-SWE-College-Jobs),
  [ApplyGuy](https://github.com/ApplyGuy/2027-New-Grad-Jobs)), or import your own links / a CSV.
- **Matches jobs to your resume** — free and offline: every job gets a 0–100 score and a reason
  (*"Python, AWS · new grad"*, *"needs 3+ yrs"*). Senior roles, and roles that won't sponsor a visa when you need one,
  go to the bottom.
- **Learns your answers** — anything you type into a question it couldn't answer is saved and filled automatically
  next time; similar questions get your earlier answer as a suggestion to check.
- **Cover letters** — your own template with `{company}` / `{role}` blanks, or a "letter style" file with your stories
  that are picked to fit each job.
- **Profiles** — friends can share one Mac; everyone has their own resume, answers, jobs and letters.
- **Test mode** — fills everything but blocks anything from being sent, so you can see how it works first.
- **Optional Claude** — with an Anthropic API key it drafts answers to brand-new questions (never sponsorship, EEO,
  salary or legal ones) and tailors each cover letter to the posting.

Everything stays on your Mac (`~/Library/Application Support/Apply/Data`). Nothing is sent anywhere except the
applications you submit.

## Run from source

Needs Python 3.11+ and Node.js.

```bash
git clone https://github.com/lcoronelr/Applying.git && cd Applying
./setup.command                      # Python packages + the Electron app
./Apply.command                      # open the app
.venv/bin/python -m pytest -q        # tests
./build_dmg.sh                       # build build/release/Apply-<version>-arm64.dmg
```

| File | What it does |
|---|---|
| `app/` | Electron app: UI (`ui/`), the embedded job page, talks to `engine.py` |
| `engine.py` | Backend the app runs (JSON over stdin/stdout) |
| `filler.py` | Reads any application form and fills it from your answers |
| `bot.py` | Job lists → `jobs.xlsx`; also a command-line version (`bot.py fetch / match / apply`) |
| `matcher.py` | Free resume ↔ job matching |
| `learn.py` | Saves answers you type, suggests them for similar questions |
| `profiles.py` | People, their folders, starter answers, link/CSV import |
| `cover_letter.py` | One-page PDF cover letters (template, letter style, or Claude) |
| `ai.py` | Optional Claude features |
| `paths.py` | Where data lives |

### Your data folder
`profile.json`, `resume.pdf`, `jobs.xlsx` (sheets **Jobs**, **Answers**, **Unanswered**, **Submitted**),
`cover_template.txt`, optional `letter_style.json` + `cover_letter_ins/voice/*.txt` (past letters for Claude to
match), `cover_letters/`, `screenshots/`, `submitted/`, and friends under `profiles/<name>/`.

### Command line
```bash
.venv/bin/python bot.py fetch --source speedyapply     # or newgrad / applyguy / intern
.venv/bin/python bot.py match                          # score jobs against your resume
.venv/bin/python bot.py apply --dry-run --limit 10     # test fill, nothing sent
.venv/bin/python bot.py apply --ats greenhouse,lever,ashby --limit 20
```
