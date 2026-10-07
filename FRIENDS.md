# Apply — fill out job applications in seconds

Apply opens each job application inside the app, fills in everything it knows about you (name, school, links, resume,
cover letter, sponsorship answers…), and waits. You look it over, click the site's **Submit** button yourself, and the
next job opens on its own. It never submits anything for you.

Works on Macs with Apple chips (M1 or newer — Apple menu → About This Mac → "Chip").

---

## 1. Install

1. **[Download Apply.dmg](https://github.com/lcoronelr/Applying/releases/latest/download/Apply.dmg)**, open it, and drag
   **Apply** into **Applications**.
2. Open **Apply** from Applications. macOS will say it *"can't be verified"* — that's because the app isn't from the
   App Store, not because anything is wrong. Click **Done**.
3. Open **System Settings → Privacy & Security**, scroll down to *"Apply was blocked…"* and click **Open Anyway**,
   then confirm with your password or Touch ID.
4. Open Apply again. You only do this once.

Your files (profile, job list, answers, letters, screenshots) stay on your Mac — **Settings → Show in Finder** opens them.

> **Intel Mac?** The download is for Apple chips only — you can run it from source instead (see the README).

## 2. Create your profile

The first time you open Apply it takes you straight to **New profile**.
(To add another person later: click the name at the top left → **New profile…**)

1. Fill in your info, school, links, and the two switches under **Work authorization**
   (*do you need visa sponsorship?* and *willing to relocate?*). These are used on every application, so double-check them.
2. **Voluntary questions** (gender, race, veteran, disability) are optional — leave them on *Decline to answer* if you like.
3. **Resume** → *Choose PDF…*
4. **Cover letter template** → write your letter once. Use these blanks and they're filled in for each job:

   | Write | Becomes |
   |---|---|
   | `{company}` | the company's name |
   | `{role}` | the job title |
   | `{name}` | your name |
   | `{date}` | today's date |

   Leave out *"Dear…"* and *"Sincerely"* — those are added for you, with your name and contact info at the top.
   Example: *"I'm excited to apply for the {role} position at {company}. Last summer I…"*
5. Click **Save**.

Each person gets their own folder (`profiles/your-name/`) with their own resume, answers, job list and letters —
several friends can share one computer without mixing anything up. Switch people from the name at the top left.

## 3. Apply

Everything happens on the **Jobs** screen:

- **Your job list** (left) — new-grad software engineering jobs, updated by themselves from public GitHub lists
  (SimplifyJobs, speedyapply, ApplyGuy) and **matched to your resume**: best fits first, with a score. Senior roles and
  roles that won't sponsor a visa (if you need one) are hidden while *Good matches* is on. **Search** at the top.
- **Start** (or click any job) — the application opens in the middle and fills itself in. Short dropdowns are picked
  from their real options; nothing is ever typed into them.
- **Test / Live** (top right): **Test** fills everything but nothing can be sent (uploads look empty) — try it first.
  **Live** is for real: fix anything in **red**, check it, and click the site's **Submit** button.
  The app **never submits for you** — while it's filling, the form can't be sent at all.
- After you submit, it says *"Applied ✓ — next job in 3…"* — click **Stay here** to cancel.
- **Stop** halts filling right away. **Skip** hides a job. **Applied** / **Skipped** tabs show your history;
  opening a job you already applied to only shows the posting.
- The right side shows only what **needs you**; everything filled is folded under *Filled*.

## 4. It learns your answers

When a question has no saved answer it's outlined in **red** — just answer it on the page like normal.
When you submit (or move to another job), whatever you entered is **saved and filled automatically next time**
the same question shows up — dropdowns, checkboxes and text boxes. You'll see *"Saved 1 new answer"*.

Questions that are worded differently but mean the same thing (*"Can you work in-office 3 days a week?"* vs
*"Are you able to work in person 3 days per week?"*) get your earlier answer as a **suggestion**, outlined in
**yellow** — check it before you submit. Dropdowns only ever get an option that's really on the form.

The **Answers** page shows everything it has learned (you can edit or delete any of it), plus a
**Needs your answer** list of questions you haven't answered yet.

## Optional: Claude (AI)

In **Settings** you can paste an Anthropic API key (from <https://console.anthropic.com>). Then Claude:
drafts answers to questions you haven't answered (outlined in **yellow** — always check those), rewrites your cover
letter for each job, and can score how well each job matches your resume. It never answers sponsorship,
citizenship, EEO, salary or signature questions.
API use is billed separately from a Claude or ChatGPT subscription (roughly 2–5¢ per application).
Without a key, everything else works the same.

## Tips

- Always glance at the form before you submit — it's your name on it.
- Some sites show a CAPTCHA; just solve it on the page.
- Your logins to job sites are remembered inside the app.
- Everything stays on your computer (Settings → Show in Finder). Don't share your `profiles/` folder — it has your info.

## Something's wrong?

| Problem | Fix |
|---|---|
| "Apply can't be verified" / "can't be opened" | System Settings → Privacy & Security → **Open Anyway** (step 1). |
| "Apply is damaged and can't be opened" | In Terminal run `xattr -cr /Applications/Apply.app`, then open it again. |
| A job opens a description, not a form | Click the site's *Apply* button, then **Fill again**. |
| The app froze or says "The engine stopped" | Quit (⌘Q) and open it again. |
| A field filled wrong | Fix it on the page, then fix or add the answer on the **Answers** page so it's right next time. |
