/* Apply — UI. One Jobs screen: find a job, it opens and fills, you submit. Talks to engine.py via window.applyApp. */
const A = window.applyApp;
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const EASY = new Set(['greenhouse', 'lever', 'ashby']);
const TODO = new Set(['new', 'later', 'test-filled']);
const APPLIED = new Set(['applied', 'interview', 'offer', 'rejected']);

const S = {
  state: null, jobs: [], current: null, mode: 'test', page: 'jobs', viewLoaded: false, sheet: false,
  answers: [], unanswered: [], filter: 'todo', editing: null, url: '', busyCount: 0, filling: false, nextTimer: null,
};

// ---------- helpers ----------
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const initials = (n) => (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
const reEscape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
let toastTimer;
function toast(msg, kind = '') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast ' + kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), kind === 'bad' ? 6000 : 3200);
}
function busy(text) { S.busyCount++; $('#busyText').textContent = text || 'Working…'; $('#busy').hidden = false; }
function idle() { S.busyCount = Math.max(0, S.busyCount - 1); if (!S.busyCount) $('#busy').hidden = true; }
async function call(cmd, args, label) {
  if (label) busy(label);
  try {
    return await A.call(cmd, args);
  } catch (e) {
    toast(e.message.replace(/^Error invoking remote method 'engine': (Error: )?/, ''), 'bad');
    throw e;
  } finally {
    if (label) idle();
  }
}
const jobById = (id) => S.jobs.find((j) => j.ID === id);
const me = () => S.state?.profiles.find((p) => p.id === S.state.active);

// ---------- the embedded website ----------
function updateView() {
  const show = S.page === 'jobs' && !S.sheet && S.viewLoaded;
  const r = $('#viewSlot').getBoundingClientRect();
  A.setViewBounds({ x: r.left, y: r.top, width: r.width, height: r.height, visible: show && r.width > 0 });
  $('#viewEmpty').hidden = S.viewLoaded;
}
new ResizeObserver(updateView).observe($('#viewSlot'));
window.addEventListener('resize', updateView);
A.onUrl((url) => {
  S.url = url;
  $('#urlText').textContent = url.startsWith('data:') ? 'No page open' : url.replace(/^https?:\/\//, '');
});
$('#backBtn').onclick = () => A.back();
$('#reloadBtn').onclick = () => A.reload();
$('#externalBtn').onclick = () => S.url.startsWith('http') && A.openExternal(S.url);

// ---------- pages ----------
function showPage(name) {
  S.page = name;
  $$('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + name));
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.page === name));
  if (name === 'answers') loadAnswers();
  if (name === 'profile' && S.editing !== 'new') loadProfile(S.state.active);
  updateView();
}
$$('#nav a').forEach((a) => (a.onclick = () => { S.editing = null; showPage(a.dataset.page); }));

function openSheet(html) {
  $('#sheet').innerHTML = html;
  $('#sheetBackdrop').hidden = false;
  S.sheet = true;
  updateView();
}
function closeSheet() { $('#sheetBackdrop').hidden = true; S.sheet = false; updateView(); }
$('#sheetBackdrop').addEventListener('mousedown', (e) => e.target.id === 'sheetBackdrop' && closeSheet());
document.addEventListener('keydown', (e) => e.key === 'Escape' && S.sheet && closeSheet());
function confirmSheet(title, text, yes, no = 'Cancel') {
  return new Promise((resolve) => {
    openSheet(`<h2>${esc(title)}</h2><p class="muted">${esc(text)}</p>
      <div class="sheet-actions"><button class="btn" id="sNo">${esc(no)}</button><button class="btn primary" id="sYes">${esc(yes)}</button></div>`);
    $('#sNo').onclick = () => { closeSheet(); resolve(false); };
    $('#sYes').onclick = () => { closeSheet(); resolve(true); };
  });
}

// ---------- sidebar ----------
function applyState(st) {
  S.state = st;
  $('#profileName').textContent = me()?.name || 'Profile';
  $('#avatar').textContent = initials(me()?.name);
}
async function loadJobs() {
  S.jobs = await call('jobs.list');
  renderQueue();
  renderStats();
}
function renderStats() {
  $('#statApplied').textContent = S.jobs.filter((j) => APPLIED.has(j.Status)).length;
  $('#statQueue').textContent = S.jobs.filter((j) => TODO.has(j.Status)).length;
}
async function refreshAnswerCount() {
  const a = await A.call('answers.get');
  S.unanswered = a.unanswered;
  $('#answersCount').textContent = S.unanswered.length || '';
}

// ---------- the job list ----------
const score = (j) => (typeof j.Match === 'number' ? j.Match : -1);
function listJobs() {
  const q = $('#search').value.trim().toLowerCase();
  const todo = S.filter === 'todo';
  return S.jobs
    .filter((j) => (todo ? TODO.has(j.Status) : S.filter === 'applied' ? APPLIED.has(j.Status) : j.Status === 'skipped'))
    .filter((j) => !todo || !$('#easyOnly').checked || EASY.has(j.ATS))
    .filter((j) => !todo || !$('#hidePoor').checked || typeof j.Match !== 'number' || j.Match >= 35)
    .filter((j) => !q || `${j.Company} ${j.Title} ${j.Location}`.toLowerCase().includes(q))
    .sort((a, b) => todo ? score(b) - score(a) || String(b.Posted).localeCompare(String(a.Posted))
      : String(b.Updated).localeCompare(String(a.Updated)));
}
function matchBadge(j) {
  if (typeof j.Match !== 'number') return '';
  const cls = j.Match >= 70 ? 'hi' : j.Match >= 45 ? 'mid' : '';
  return `<span class="match ${cls}" title="${esc(j.Why || '')}">${j.Match}</span>`;
}
function renderQueue() {
  const list = listJobs();
  const empty = S.filter === 'todo'
    ? (S.jobs.length ? 'Nothing matches. Clear the search or untick the filters.' : 'Getting jobs…')
    : S.filter === 'applied' ? 'Nothing applied yet.' : 'Nothing skipped.';
  $('#queue').innerHTML = list.length ? list.slice(0, 300).map((j) => `
    <div class="q-item ${j.ID === S.current ? 'current' : ''}" data-id="${esc(j.ID)}">
      <div class="q-company">${esc(j.Company)}</div>${S.filter === 'todo' ? matchBadge(j) : `<span class="status ${esc(j.Status)}">${esc(j.Status)}</span>`}
      <div class="q-role">${esc(j.Title)}</div>
      <div class="q-meta">${esc((j.Location || '').slice(0, 34))}${S.filter !== 'todo' && j.Updated ? ' · ' + esc(String(j.Updated).slice(0, 10)) : ''}</div>
    </div>`).join('') : `<div class="q-empty">${empty}</div>`;
  $$('.q-item').forEach((el) => (el.onclick = () => openJob(el.dataset.id)));
  $('#nextBtn').textContent = S.current ? 'Next job' : 'Start';
}
$('#search').oninput = renderQueue;
['#easyOnly', '#hidePoor'].forEach((s) => ($(s).onchange = renderQueue));
$$('#statusSeg button').forEach((b) => (b.onclick = () => {
  S.filter = b.dataset.f;
  $$('#statusSeg button').forEach((x) => x.classList.toggle('on', x === b));
  renderQueue();
}));

// ---------- applying ----------
function setFilling(on) {
  S.filling = on;
  $('#stopBtn').hidden = !on;
  ['#refillBtn', '#skipBtn'].forEach((s) => ($(s).disabled = on || !S.current));
  $('#nextBtn').disabled = on;
}
function cancelAutoNext() { clearTimeout(S.nextTimer); S.nextTimer = null; }
function header(j) {
  $('#curCompany').textContent = j.Company;
  $('#curRole').textContent = `${j.Title}${j.Location ? ' · ' + j.Location : ''}`;
}
async function openJob(id) {
  const j = jobById(id);
  if (!j || S.filling) return;
  cancelAutoNext();
  if (me()?.placeholder) return startNewProfile('Create your profile first.');
  if (S.current && S.current !== id) await learnFromPage();
  if (APPLIED.has(j.Status)) { // never fill (or send) an application twice
    const ok = await confirmSheet(`You already applied to ${j.Company}`,
      `Applied ${String(j.Updated || '').slice(0, 10)}. Open the posting just to look? Nothing will be filled or sent.`, 'Open posting');
    if (!ok) return;
    S.current = id; header(j); renderQueue();
    S.viewLoaded = true; updateView(); setBanner('', '');
    await call('apply.view', { id }, 'Opening…');
    $('#summary').textContent = 'Already applied';
    $('#inspBody').innerHTML = '<p class="muted">You already applied here — this is just the posting.</p>';
    return;
  }
  S.current = id;
  header(j);
  renderQueue();
  setBanner('', '');
  $('#summary').textContent = 'Filling…';
  $('#inspBody').innerHTML = '<p class="muted">Opening the application and filling in what I know…</p>';
  S.viewLoaded = true;
  updateView();
  setFilling(true);
  try {
    const res = await call('apply.open', { id, test: S.mode === 'test' }, `Filling ${j.Company}…`);
    if (S.current === id) afterFill(res);
  } catch {
    $('#summary').textContent = 'Something went wrong';
    $('#inspBody').innerHTML = '<p class="muted">Couldn\'t fill this one. Fill it by hand, or Skip.</p>';
  } finally {
    setFilling(false);
  }
}
function afterFill(res) {
  if (res.stopped) {
    $('#summary').textContent = 'Stopped';
    $('#inspBody').innerHTML = '<p class="muted">Stopped — nothing more will be filled. Press <b>Fill again</b> or <b>Next job</b> when you\'re ready.</p>';
    return setBanner('test', 'Stopped. The form stays as it is.');
  }
  const j = jobById(res.job.ID);
  if (j) j.Status = res.job.Status;
  renderReport(res);
  renderQueue();
  renderStats();
  if (res.test) setBanner('test', `Test mode — nothing can be sent from this page (file uploads look empty). Switch to Live to apply.`);
  else setBanner('live', res.missing
    ? `Fill the ${res.missing} question${res.missing > 1 ? 's' : ''} in red, check the rest, then click the site's Submit.`
    : 'All filled. Give it a quick look, then click the site\'s Submit button.');
}
function setBanner(kind, text, actionLabel, action) {
  const b = $('#banner');
  b.hidden = !kind;
  b.className = 'banner ' + kind;
  b.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>${actionLabel ? `<button class="link" id="bannerAction">${esc(actionLabel)}</button>` : ''}`;
  if (actionLabel) $('#bannerAction').onclick = action;
  requestAnimationFrame(updateView);
}
function renderReport(res) {
  const g = { miss: [], ai: [], ok: [] };
  for (const f of res.report) {
    if (['filled', 'already'].includes(f.status)) g.ok.push(f);
    else if (f.status === 'ai-drafted') g.ai.push(f);
    else if (f.required) g.miss.push(f);
  }
  $('#summary').textContent = g.miss.length ? `${g.miss.length} need you · ${g.ok.length + g.ai.length} filled`
    : `All ${g.ok.length + g.ai.length} filled`;
  const row = (f, k, v) => `<div class="qa ${k}"><span class="ic"></span><span class="q">${esc(f.question)}</span>${v ? `<span class="a" title="${esc(v)}">${esc(v)}</span>` : ''}</div>`;
  let html = '';
  if (g.miss.length) html += `<div class="group-title">Needs you</div><p class="hint">Answer these on the page — they're saved for next time.</p>` + g.miss.map((f) => row(f, 'miss', '')).join('');
  if (g.ai.length) html += `<div class="group-title">Suggested — check these</div>` + g.ai.map((f) => row(f, 'ai', f.value)).join('');
  if (!g.miss.length && !g.ai.length && res.report.length) html += '<p class="all-good">✓ Nothing needs you. Check the page and submit.</p>';
  if (g.ok.length) html += `<details class="filled"><summary>Filled (${g.ok.length})</summary>${g.ok.map((f) => row(f, 'ok', f.value || '✓')).join('')}</details>`;
  if (!res.report.length) html = '<p class="muted">No form on this page. If it\'s a job description, click its Apply button, then <b>Fill again</b>.</p>';
  if (res.letter) html += `<a class="insp-link" data-file="${esc(res.letter)}">Cover letter used</a>`;
  $('#inspBody').innerHTML = html;
  $$('.insp-link').forEach((a) => (a.onclick = () => A.showFile(a.dataset.file)));
}
function nextJob() {
  cancelAutoNext();
  if (S.filter !== 'todo') $$('#statusSeg button')[0].click();
  const list = listJobs();
  const i = list.findIndex((j) => j.ID === S.current);
  const nxt = list[i + 1] || list.find((j) => j.ID !== S.current);
  if (!nxt) return toast('That\'s every job in your list for now.');
  openJob(nxt.ID);
}
async function setStatus(id, status) {
  await call('jobs.status', { id, status });
  const j = jobById(id);
  if (j) j.Status = status;
  renderStats();
}
async function learnFromPage() {
  if (!S.current || !S.viewLoaded) return;
  try {
    const r = await A.call('apply.learn', {});
    if (r.learned) { toast(`Saved ${r.learned} new answer${r.learned > 1 ? 's' : ''} for next time`, 'good'); refreshAnswerCount(); }
  } catch { /* never block moving on */ }
}
$('#nextBtn').onclick = nextJob;
$('#skipBtn').onclick = async () => { await learnFromPage(); await setStatus(S.current, 'skipped'); nextJob(); };
$('#refillBtn').onclick = async () => {
  setFilling(true);
  try { afterFill(await call('apply.refill', {}, 'Filling again…')); } finally { setFilling(false); }
};
$('#stopBtn').onclick = async () => { cancelAutoNext(); await A.call('apply.stop', {}); toast('Stopped'); };
$$('#modeSeg button').forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
async function setMode(mode) {
  if (mode === S.mode) return;
  if (mode === 'live' && !(await confirmSheet('Switch to Live?',
    'In Live mode, clicking Submit on the website sends a real application. The app fills the form but never clicks Submit for you.', 'Go Live', 'Stay in Test'))) return;
  S.mode = mode;
  $$('#modeSeg button').forEach((x) => x.classList.toggle('on', x.dataset.mode === mode));
  if (S.current && !S.filling && TODO.has(jobById(S.current)?.Status)) openJob(S.current);
}

// ---------- engine events ----------
A.onEvent((name, data) => {
  if (name === 'progress') $('#busyText').textContent = data.text;
  if (name === 'submitted') {
    const j = jobById(data.id);
    if (j) j.Status = 'applied';
    renderStats();
    if (data.learned) refreshAnswerCount();
    toast(`Applied to ${data.company} ✓`, 'good');
    let n = 4;
    const tick = () => {
      if (S.current !== data.id) return;
      if (--n <= 0) return nextJob();
      setBanner('done', `Applied to ${data.company} ✓ — next job in ${n}…`, 'Stay here', () => { cancelAutoNext(); setBanner('done', `Applied to ${data.company} ✓`); });
      S.nextTimer = setTimeout(tick, 1000);
    };
    tick();
  }
  if (name === 'crashed') toast('Something stopped working. Quit (⌘Q) and reopen the app.', 'bad');
});

// ---------- job lists: always up to date, software only ----------
async function refreshJobs(force = false) {
  $('#refreshInfo').textContent = 'Checking for new jobs…';
  try {
    const r = await A.call('jobs.refresh', { force });
    await loadJobs();
    await matchNewJobs();
    $('#refreshInfo').textContent = r.added ? `${r.added} new jobs added` : 'Up to date';
  } catch {
    $('#refreshInfo').textContent = 'Couldn\'t reach the job lists';
  }
}
async function matchNewJobs() {
  if (!S.jobs.some((j) => TODO.has(j.Status) && typeof j.Match !== 'number')) return;
  $('#refreshInfo').textContent = 'Matching jobs to your resume…';
  try { await A.call('match', { only_new: true }); await loadJobs(); } catch { /* list still works */ }
}
$('#refreshBtn').onclick = () => refreshJobs(true);

// ---------- answers ----------
async function loadAnswers() {
  const r = await call('answers.get');
  S.answers = r.answers.map((x) => [x[0], x[1], x[2] || '']);
  S.unanswered = r.unanswered;
  renderAnswers();
}
function renderAnswers() {
  $('#answersCount').textContent = S.unanswered.length || '';
  $('#unansweredCard').hidden = !S.unanswered.length;
  $('#unansweredList').innerHTML = S.unanswered.map((u, i) => {
    const opts = u[2] ? String(u[2]).split(' | ').filter(Boolean) : [];
    const input = opts.length
      ? `<select data-i="${i}"><option value="">Choose…</option>${opts.map((o) => `<option>${esc(o)}</option>`).join('')}</select>`
      : `<input type="text" data-i="${i}" placeholder="Your answer">`;
    return `<div class="una"><div><div class="q">${esc(u[0])}</div><div class="meta">seen ${esc(u[3])}× · last at ${esc(u[4])}</div></div>${input}<button class="btn" data-save="${i}">Save</button></div>`;
  }).join('');
  $$('[data-save]').forEach((b) => (b.onclick = async () => {
    const i = +b.dataset.save;
    const v = $(`#unansweredList [data-i="${i}"]`).value.trim();
    if (!v) return toast('Type or pick an answer first');
    const q = S.unanswered[i][0];
    S.answers.unshift([reEscape(q.toLowerCase().replace(/[*?:]+$/, '').trim().slice(0, 80)), v, '']);
    await saveAnswers([q]);
    toast('Saved — it fills itself from now on');
  }));
  const q = $('#answerSearch').value.trim().toLowerCase();
  $('#answersBody').innerHTML = S.answers.map((r, i) => ({ r, i }))
    .filter(({ r }) => !q || `${r[0]} ${r[1]}`.toLowerCase().includes(q)).map(({ r, i }) => `
    <tr data-i="${i}">
      <td><input type="text" value="${esc(r[0])}" data-k="0" spellcheck="false"></td>
      <td><input type="text" value="${esc(r[1])}" data-k="1"></td>
      <td><select data-k="2">${['', 'choice', 'text'].map((v) => `<option value="${v}" ${v === r[2] ? 'selected' : ''}>${v || 'any'}</option>`).join('')}</select></td>
      <td><button class="icon-btn" title="Delete" data-del="${i}"><svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg></button></td>
    </tr>`).join('');
  $$('#answersBody [data-k]').forEach((el) => (el.onchange = () => { S.answers[+el.closest('tr').dataset.i][+el.dataset.k] = el.value; }));
  $$('[data-del]').forEach((b) => (b.onclick = () => { S.answers.splice(+b.dataset.del, 1); renderAnswers(); }));
}
$('#answerSearch').oninput = renderAnswers;
async function saveAnswers(resolved = []) {
  const r = await call('answers.save', { rows: S.answers.filter((x) => x[0]), resolved }, 'Saving…');
  S.answers = r.answers.map((x) => [x[0], x[1], x[2] || '']);
  S.unanswered = r.unanswered;
  renderAnswers();
}
$('#addAnswerBtn').onclick = () => { $('#answerSearch').value = ''; S.answers.unshift(['', '', '']); renderAnswers(); $('#answersBody input').focus(); };
$('#saveAnswersBtn').onclick = async () => { await saveAnswers(); toast('Answers saved'); };

// ---------- profile ----------
const EEO = {
  gender: ['', 'Male', 'Female', 'Non-binary'],
  hispanic: ['', 'Yes', 'No'],
  race: ['', 'Asian', 'Black or African American', 'Hispanic or Latino', 'White', 'Two or more races', 'Native American or Alaska Native', 'Native Hawaiian or Pacific Islander'],
  veteran: ['', 'I am not a protected veteran', 'I identify as a protected veteran'],
  disability: ['', 'No, I do not have a disability', 'Yes, I have a disability'],
};
let pendingResume = null;
async function loadProfile(id) {
  S.editing = id;
  renderProfileForm(await call('profile.get', { id }));
}
const field = (name, label, value, type = 'text', wide = false, ph = '') =>
  `<label class="field ${wide ? 'wide' : ''}"><span>${label}</span><input type="${type}" name="${name}" value="${esc(value)}" placeholder="${esc(ph)}" spellcheck="false"></label>`;
function renderProfileForm(r) {
  const p = r.profile || {};
  pendingResume = null;
  $('#profileTitle').textContent = r.id === 'new' ? 'New person' : 'My profile';
  const sel = (name, label) => `<label class="field"><span>${label}</span><select name="${name}">${EEO[name].map((o) => `<option value="${esc(o)}" ${o === (p[name] || '') ? 'selected' : ''}>${o || 'Decline to answer'}</option>`).join('')}</select></label>`;
  $('#profileForm').innerHTML = `
    <div class="card"><h3>About you</h3><div class="grid">
      ${field('first_name', 'First name', p.first_name)}${field('last_name', 'Last name', p.last_name)}
      ${field('email', 'Email', p.email, 'email')}${field('phone', 'Phone', p.phone, 'tel', false, '555-123-4567')}
      ${field('city', 'City', p.city, 'text', false, 'Springfield, IL')}${field('state', 'State', p.state, 'text', false, 'Illinois')}
      ${field('zip', 'ZIP code', p.zip)}${field('linkedin', 'LinkedIn', p.linkedin, 'url')}
      ${field('github', 'GitHub', p.github, 'url')}${field('website', 'Website', p.website, 'url')}
    </div></div>
    <div class="card"><h3>Education</h3><div class="grid">
      ${field('school', 'School', p.school, 'text', true)}
      ${field('degree', 'Degree', p.degree, 'text', false, 'Bachelor of Science')}${field('major', 'Major', p.major, 'text', false, 'Computer Science')}
      ${field('gpa', 'GPA', p.gpa)}${field('graduation', 'Graduation', p.graduation, 'text', false, 'May 2027')}
    </div></div>
    <div class="card"><h3>Work authorization</h3>
      <div class="switch-row"><span>I will need visa sponsorship (now or in the future)</span><input type="checkbox" class="toggle" name="needs_sponsorship" ${p.needs_sponsorship ? 'checked' : ''}></div>
      <div class="switch-row"><span>I'm willing to relocate</span><input type="checkbox" class="toggle" name="relocate" ${p.relocate !== false ? 'checked' : ''}></div>
    </div>
    <div class="card"><h3>Voluntary questions</h3><p class="muted">Equal-opportunity questions. "Decline to answer" is always fine.</p><div class="grid">
      ${sel('gender', 'Gender')}${sel('hispanic', 'Hispanic or Latino')}${sel('race', 'Race')}${sel('veteran', 'Veteran status')}${sel('disability', 'Disability')}
    </div></div>
    <div class="card"><h3>Resume</h3><p class="muted">Uploaded to every application, and used to match jobs to you.</p>
      <div class="file-row"><button type="button" class="btn" id="pickResume">Choose PDF…</button><span class="file-name" id="resumeName">${r.resume ? 'resume.pdf ✓' : 'No resume yet'}</span></div></div>
    <div class="card"><h3>Cover letter</h3>
      ${r.style ? '<p class="muted"><b>You have a custom letter style</b> — your own stories are picked to fit each job, so the template below isn\'t used.</p>'
        : '<p class="muted">Write it once. These get filled in for each job: <code>{company}</code> <code>{role}</code> <code>{name}</code> <code>{date}</code>. Leave out "Dear…" and "Sincerely" — they\'re added for you.</p>'}
      <label class="field wide"><textarea name="__template" placeholder="I'm excited to apply for the {role} position at {company}…">${esc(r.template || '')}</textarea></label></div>`;
  $('#pickResume').onclick = async () => {
    const f = await A.pickFile([{ name: 'Resume', extensions: ['pdf'] }]);
    if (f) { pendingResume = f; $('#resumeName').textContent = f.split('/').pop() + ' (will be saved)'; }
  };
}
function startNewProfile(msg) {
  S.editing = 'new';
  showPage('profile');
  renderProfileForm({ id: 'new', profile: { relocate: true }, template: '', resume: false });
  if (msg) toast(msg);
}
$('#saveProfileBtn').onclick = async () => {
  const form = $('#profileForm');
  const data = {};
  form.querySelectorAll('input[name], select[name]').forEach((el) => { data[el.name] = el.type === 'checkbox' ? el.checked : el.value.trim(); });
  if (!data.first_name || !data.email) return toast('First name and email are required', 'bad');
  if (S.editing === 'new' && !pendingResume) return toast('Add a resume first', 'bad');
  const tpl = form.querySelector('[name="__template"]');
  const st = await call('profile.save', { id: S.editing, data, resume: pendingResume, template: tpl ? tpl.value : null }, 'Saving…');
  applyState(st);
  toast('Saved');
  await afterProfileSwitch();
  S.editing = null;
  showPage('jobs');
};
async function afterProfileSwitch() {
  A.setSettings({ lastProfile: S.state.active });
  S.current = null;
  S.viewLoaded = false;
  $('#curCompany').textContent = 'Software engineering jobs';
  $('#curRole').textContent = 'Pick a job on the left — best matches first.';
  $('#inspBody').innerHTML = '<p class="muted">What needs you will show up here.</p>';
  $('#summary').textContent = '';
  setBanner('', '');
  await loadJobs();
  refreshAnswerCount();
  updateView();
  refreshJobs();
}
$('#profileBtn').onclick = () => {
  const people = S.state.profiles.filter((p) => !p.placeholder);
  openSheet(`<h2>Who's applying?</h2>
    <div class="plist">${people.map((p) => `
      <div class="pitem ${p.id === S.state.active ? 'on' : ''}" data-id="${esc(p.id)}"><span class="avatar">${esc(initials(p.name))}</span><span>${esc(p.name)}</span>${p.id === S.state.active ? '<span class="tag">You\'re here</span>' : ''}</div>`).join('')}
    </div>
    <div class="sheet-actions"><button class="btn left" id="newProfile">Add a person…</button><button class="btn" id="closeP">Done</button></div>`);
  $$('.pitem').forEach((el) => (el.onclick = async () => {
    closeSheet();
    if (el.dataset.id === S.state.active) return;
    applyState(await call('profile.activate', { id: el.dataset.id }, 'Switching…'));
    await afterProfileSwitch();
    toast(`Now applying as ${me().name}`);
  }));
  $('#closeP').onclick = closeSheet;
  $('#newProfile').onclick = () => { closeSheet(); startNewProfile(); };
};

// ---------- settings ----------
$('#saveSettingsBtn').onclick = async () => {
  const s = await A.setSettings({ apiKey: $('#apiKey').value.trim(), model: $('#model').value });
  applyState(await call('settings', { api_key: s.apiKey || '', model: s.model }, 'Saving…'));
  toast(S.state.ai ? 'Claude is on' : 'Claude is off');
};
$('#openFolderBtn').onclick = () => A.openFolder();
$('#newProfileBtn').onclick = () => startNewProfile();

// ---------- start ----------
(async function init() {
  busy('Starting…');
  try {
    const s = await A.getSettings();
    $('#apiKey').value = s.apiKey || '';
    if (s.model) $('#model').value = s.model;
    applyState(await A.call('init'));
    if (s.apiKey || s.model) applyState(await A.call('settings', { api_key: s.apiKey || '', model: s.model }));
    if (s.lastProfile && s.lastProfile !== S.state.active && S.state.profiles.some((p) => p.id === s.lastProfile)) {
      applyState(await A.call('profile.activate', { id: s.lastProfile }));
    }
    if (me()?.placeholder) {
      const real = S.state.profiles.filter((p) => !p.placeholder);
      if (real.length) applyState(await A.call('profile.activate', { id: real[0].id }));
      else { idle(); return startNewProfile('Welcome! Start by creating your profile.'); }
    }
    await loadJobs();
    refreshAnswerCount();
  } catch (e) {
    toast('Could not start: ' + e.message, 'bad');
  } finally {
    idle();
  }
  refreshJobs(); // new jobs + matching, in the background
})();
