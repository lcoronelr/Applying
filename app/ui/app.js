/* Apply — UI. Talks to engine.py through window.applyApp (preload.js). */
const A = window.applyApp;
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const EASY = new Set(['greenhouse', 'lever', 'ashby']);
const TODO = new Set(['new', 'later', 'test-filled']);
const STATUSES = ['new', 'test-filled', 'applied', 'skipped', 'later', 'error', 'interview', 'rejected', 'offer'];

const S = {
  state: null, jobs: [], current: null, mode: 'test', page: 'apply', viewLoaded: false, sheet: false,
  answers: [], unanswered: [], statusFilter: 'todo', editing: null, url: '', busyCount: 0,
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
function busy(text) {
  S.busyCount++;
  $('#busyText').textContent = text || 'Working…';
  $('#busy').hidden = false;
}
function idle() {
  S.busyCount = Math.max(0, S.busyCount - 1);
  if (!S.busyCount) $('#busy').hidden = true;
}
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

// ---------- the embedded website ----------
function updateView() {
  const show = S.page === 'apply' && !S.sheet && S.viewLoaded;
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

// ---------- navigation ----------
function showPage(name) {
  S.page = name;
  $$('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + name));
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.page === name));
  if (name === 'jobs') renderJobs();
  if (name === 'answers') loadAnswers();
  if (name === 'profile' && S.editing !== 'new') loadProfile(S.state.active);
  updateView();
}
$$('#nav a').forEach((a) => (a.onclick = () => showPage(a.dataset.page)));

// ---------- sheets ----------
function openSheet(html, wide = false) {
  $('#sheet').innerHTML = html;
  $('#sheet').className = 'sheet' + (wide ? ' wide' : '');
  $('#sheetBackdrop').hidden = false;
  S.sheet = true;
  updateView();
}
function closeSheet() {
  $('#sheetBackdrop').hidden = true;
  S.sheet = false;
  updateView();
}
$('#sheetBackdrop').addEventListener('mousedown', (e) => e.target.id === 'sheetBackdrop' && closeSheet());
document.addEventListener('keydown', (e) => e.key === 'Escape' && S.sheet && closeSheet());

// ---------- state / sidebar ----------
function applyState(st) {
  S.state = st;
  const me = st.profiles.find((p) => p.id === st.active);
  $('#profileName').textContent = me?.name || 'Profile';
  $('#avatar').textContent = initials(me?.name);
  $('#aiPill').textContent = st.ai ? 'AI on' : 'AI off';
  $('#aiPill').classList.toggle('on', st.ai);
  $('#rankBtn').hidden = !st.ai;
}
async function loadJobs() {
  S.jobs = await call('jobs.list');
  renderQueue();
  renderStats();
  if (S.page === 'jobs') renderJobs();
}
function renderStats() {
  $('#statApplied').textContent = S.jobs.filter((j) => j.Status === 'applied').length;
  const todo = queueJobs(false).length;
  $('#statQueue').textContent = todo;
  $('#jobsCount').textContent = todo || '';
}

// ---------- queue ----------
function score(j) { return typeof j.Match === 'number' ? j.Match : -1; }
function queueJobs(withSearch = true) {
  const easy = $('#easyOnly').checked;
  const q = withSearch ? $('#queueSearch').value.trim().toLowerCase() : '';
  return S.jobs
    .filter((j) => TODO.has(j.Status) && (!easy || EASY.has(j.ATS)))
    .filter((j) => !$('#hidePoor').checked || typeof j.Match !== 'number' || j.Match >= 35)
    .filter((j) => !q || `${j.Company} ${j.Title}`.toLowerCase().includes(q))
    .sort((a, b) => score(b) - score(a) || String(b.Posted).localeCompare(String(a.Posted)));
}
function matchBadge(j) {
  if (typeof j.Match !== 'number') return '';
  const cls = j.Match >= 70 ? 'hi' : j.Match >= 45 ? 'mid' : '';
  return `<span class="match ${cls}" title="${esc(j.Why || '')}">${j.Match}</span>`;
}
function renderQueue() {
  const list = queueJobs();
  const cur = S.current && jobById(S.current);
  const items = cur && !list.includes(cur) ? [cur, ...list] : list;
  $('#queue').innerHTML = items.length ? items.slice(0, 300).map((j) => `
    <div class="q-item ${j.ID === S.current ? 'current' : ''}" data-id="${esc(j.ID)}">
      <div class="q-company">${esc(j.Company)}</div>${matchBadge(j)}
      <div class="q-role">${esc(j.Title)}</div>
      <div class="q-meta"><span>${esc(j.ATS)}</span><span>·</span><span>${esc(j.Location || '').slice(0, 30)}</span>${j.Status !== 'new' ? `<span>·</span><span>${esc(j.Status)}</span>` : ''}</div>
    </div>`).join('') : `<div class="q-empty">Nothing to do here.<br>Get new jobs or import links on the Jobs page.</div>`;
  $$('.q-item').forEach((el) => (el.onclick = () => openJob(el.dataset.id)));
  $('#nextBtn').textContent = S.current ? 'Next job' : 'Start';
}
$('#queueSearch').oninput = renderQueue;
$('#easyOnly').onchange = () => { renderQueue(); renderStats(); };
$('#hidePoor').onchange = () => { renderQueue(); renderStats(); };

// ---------- apply flow ----------
function setActionsEnabled(on) {
  ['#refillBtn', '#laterBtn', '#skipBtn'].forEach((s) => ($(s).disabled = !on));
}
async function openJob(id) {
  const j = jobById(id);
  if (!j) return;
  if (S.current && S.current !== id) await learnFromPage(); // picked another job from the queue
  if (S.state.profiles.find((p) => p.id === S.state.active)?.placeholder) { // never apply as the placeholder
    toast('Create your profile first — click the name at the top left → New profile', 'bad');
    S.editing = 'new';
    showPage('profile');
    renderProfileForm({ id: 'new', profile: { relocate: true }, template: '', owner: false, resume: false });
    return;
  }
  S.current = id;
  showPage('apply');
  $('#curCompany').textContent = j.Company;
  $('#curRole').textContent = `${j.Title}${j.Location ? ' · ' + j.Location : ''}`;
  setActionsEnabled(false);
  renderQueue();
  setBanner('', '');
  $('#summary').textContent = 'Filling…';
  $('#inspBody').innerHTML = '<p class="muted">Opening the application and filling in what I know…</p>';
  S.viewLoaded = true;
  updateView();
  try {
    const res = await call('apply.open', { id, test: S.mode === 'test' }, `Applying to ${j.Company}…`);
    if (S.current !== id) return; // you moved on meanwhile
    afterFill(res);
  } catch {
    $('#summary').textContent = 'Something went wrong';
    $('#inspBody').innerHTML = '<p class="muted">Couldn\'t fill this one. You can fill it by hand, or Skip.</p>';
  } finally {
    setActionsEnabled(true);
  }
}
function afterFill(res) {
  const j = jobById(res.job.ID);
  if (j) Object.assign(j, { Status: res.job.Status });
  renderReport(res);
  renderQueue();
  renderStats();
  if (res.test) setBanner('test', `Test mode: ${res.summary.split(';')[0].replace('/', ' of ')} — nothing can be sent from this page, and file uploads show empty. Screenshot saved.`);
  else setBanner('live', res.missing
    ? `Fill the ${res.missing} question${res.missing > 1 ? 's' : ''} outlined in red, check the rest, then click Submit on the page. The next job opens by itself.`
    : 'Everything is filled. Give it a quick look, then click Submit on the page — the next job opens by itself.');
}
function setBanner(kind, text) {
  const b = $('#banner');
  b.hidden = !kind;
  b.className = 'banner ' + kind;
  b.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>`;
  requestAnimationFrame(updateView);
}
function renderReport(res) {
  const groups = { miss: [], ai: [], ok: [], opt: [] };
  for (const f of res.report) {
    if (['filled', 'already'].includes(f.status)) groups.ok.push(f);
    else if (f.status === 'ai-drafted') groups.ai.push(f);
    else if (f.required) groups.miss.push(f);
    else groups.opt.push(f);
  }
  const titles = { miss: 'Needs you — what you enter is saved for next time', ai: 'Suggested — check it', ok: 'Filled', opt: 'Optional, left blank' };
  const val = (f, kind) => kind === 'miss' ? (f.status === 'no answer' ? 'No saved answer' : f.status)
    : kind === 'opt' ? 'Optional' : f.value || '✓';
  $('#summary').textContent = `${groups.ok.length + groups.ai.length} of ${res.report.length} filled`
    + (groups.miss.length ? ` · ${groups.miss.length} need you` : '');
  let html = '';
  for (const k of ['miss', 'ai', 'ok', 'opt']) {
    if (!groups[k].length) continue;
    html += `<div class="group-title">${titles[k]}</div>` + groups[k].map((f) => `
      <div class="qa ${k}"><span class="ic"></span><span class="q">${esc(f.question)}</span><span class="a" title="${esc(val(f, k))}">${esc(val(f, k))}</span></div>`).join('');
  }
  if (!res.report.length) html = '<p class="muted">No form found on this page. If it\'s a job description, click its Apply button, then press Fill again.</p>';
  if (res.letter) html += `<a class="insp-link" data-file="${esc(res.letter)}">Show cover letter in Finder</a>`;
  if (res.screenshot) html += `<a class="insp-link" data-file="${esc(res.screenshot)}">Show screenshot in Finder</a>`;
  $('#inspBody').innerHTML = html;
  $$('.insp-link').forEach((a) => (a.onclick = () => A.showFile(a.dataset.file)));
}
function nextJob() {
  const list = queueJobs();
  const i = list.findIndex((j) => j.ID === S.current);
  const nxt = list[i + 1] || list.find((j) => j.ID !== S.current);
  if (!nxt) return toast('Queue finished. Get new jobs on the Jobs page.');
  openJob(nxt.ID);
}
async function setStatus(id, status) {
  await call('jobs.status', { id, status });
  const j = jobById(id);
  if (j) j.Status = status;
  renderStats();
}
// before leaving a job: keep whatever you typed into questions the app couldn't answer
async function learnFromPage() {
  if (!S.current || !S.viewLoaded) return;
  try {
    const r = await A.call('apply.learn', {});
    if (r.learned) {
      toast(`Saved ${r.learned} new answer${r.learned > 1 ? 's' : ''} — filled automatically from now on`, 'good');
      refreshAnswerCount();
    }
  } catch { /* never block moving on */ }
}
async function refreshAnswerCount() {
  const a = await A.call('answers.get');
  S.unanswered = a.unanswered;
  $('#answersCount').textContent = S.unanswered.length || '';
}
$('#nextBtn').onclick = nextJob; // openJob saves what you typed before switching
$('#skipBtn').onclick = async () => { await learnFromPage(); await setStatus(S.current, 'skipped'); nextJob(); };
$('#laterBtn').onclick = async () => { await learnFromPage(); await setStatus(S.current, 'later'); nextJob(); };
$('#refillBtn').onclick = async () => {
  setActionsEnabled(false);
  try { afterFill(await call('apply.refill', {}, 'Filling again…')); } finally { setActionsEnabled(true); }
};
$$('#modeSeg button').forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
function setMode(mode) {
  if (mode === S.mode) return;
  if (mode === 'live') {
    openSheet(`<h2>Switch to Live?</h2>
      <p class="muted">In Live mode, clicking Submit on the website sends a real application. The app never clicks Submit for you — you always review first.</p>
      <div class="sheet-actions"><button class="btn" id="cancelLive">Stay in Test</button><button class="btn primary" id="goLive">Go Live</button></div>`);
    $('#cancelLive').onclick = closeSheet;
    $('#goLive').onclick = () => { closeSheet(); applyMode('live'); };
  } else applyMode('test');
}
function applyMode(mode) {
  S.mode = mode;
  $$('#modeSeg button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
  if (S.current) openJob(S.current); // reopen so sending is blocked/allowed for this page
}

// ---------- engine events ----------
A.onEvent((name, data) => {
  if (name === 'progress') $('#busyText').textContent = data.text;
  if (name === 'submitted') {
    const j = jobById(data.id);
    if (j) j.Status = 'applied';
    toast(`Applied to ${data.company} ✓` + (data.learned ? ` · saved ${data.learned} new answer${data.learned > 1 ? 's' : ''}` : ''), 'good');
    if (data.learned) refreshAnswerCount();
    setBanner('done', `Submitted to ${data.company}. Saved a copy of what you sent. Opening the next job…`);
    renderStats();
    setTimeout(() => { if (S.current === data.id) nextJob(); }, 1800);
  }
  if (name === 'crashed') toast('The engine stopped. Quit and reopen the app.', 'bad');
});

// jobs nobody has scored yet (first run, a new profile) get matched in the background
async function matchNewJobs() {
  if (!S.jobs.some((j) => TODO.has(j.Status) && typeof j.Match !== 'number')) return;
  busy('Matching jobs to your resume…');
  try {
    await A.call('match', { only_new: true });
    await loadJobs();
  } catch { /* the queue still works unsorted */ } finally { idle(); }
}

// ---------- jobs page ----------
$$('#statusSeg button').forEach((b) => (b.onclick = () => {
  S.statusFilter = b.dataset.f;
  $$('#statusSeg button').forEach((x) => x.classList.toggle('on', x === b));
  renderJobs();
}));
$('#jobSearch').oninput = renderJobs;
$('#siteFilter').onchange = renderJobs;
$('#matchFilter').onchange = renderJobs;
function renderJobs() {
  const q = $('#jobSearch').value.trim().toLowerCase();
  const site = $('#siteFilter').value;
  const f = S.statusFilter;
  const rows = S.jobs.filter((j) =>
    (f === 'all' || (f === 'todo' && TODO.has(j.Status)) || (f === 'applied' && ['applied', 'interview', 'offer', 'rejected'].includes(j.Status))
      || (f === 'skipped' && j.Status === 'skipped'))
    && (!site || (site === 'easy' ? EASY.has(j.ATS) : site === 'workday' ? j.ATS === 'workday' : !EASY.has(j.ATS) && j.ATS !== 'workday'))
    && (!q || `${j.Company} ${j.Title} ${j.Location}`.toLowerCase().includes(q))
    && (+$('#matchFilter').value === 0 || score(j) >= +$('#matchFilter').value))
    .sort((a, b) => score(b) - score(a) || String(b.Posted).localeCompare(String(a.Posted)));
  $('#jobsSub').textContent = `${rows.length} job${rows.length === 1 ? '' : 's'} · ${S.jobs.length} total`;
  const shown = rows.slice(0, 400);
  $('#jobsBody').innerHTML = shown.map((j) => `
    <tr data-id="${esc(j.ID)}">
      <td class="num">${matchBadge(j)}</td>
      <td class="company">${esc(j.Company)}</td>
      <td title="${esc(j.Why || j.Title)}">${esc(j.Title)}</td>
      <td class="muted">${esc(j.Location || '')}</td>
      <td><span class="site">${esc(j.ATS)}</span></td>
      <td class="muted">${esc(j.Posted || '')}</td>
      <td><select class="status-sel">${STATUSES.map((s) => `<option ${s === j.Status ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
    </tr>`).join('');
  $('#jobsMore').textContent = rows.length > shown.length ? `Showing the first ${shown.length} — search to narrow it down.` : '';
  $$('#jobsBody tr').forEach((tr) => {
    tr.onclick = (e) => { if (e.target.tagName !== 'SELECT') openJob(tr.dataset.id); };
    tr.querySelector('select').onchange = (e) => setStatus(tr.dataset.id, e.target.value).then(() => renderQueue());
  });
}
$('#fetchBtn').onclick = async () => {
  const r = await call('jobs.fetch', {}, 'Getting new jobs…');
  toast(r.added ? `Added ${r.added} new jobs — matched to your resume` : 'No new jobs since last time');
  loadJobs();
};
$('#matchBtn').onclick = async () => {
  const r = await call('match', {}, 'Matching jobs to your resume…');
  toast(`Matched ${r.scored} jobs — ${r.good} good fits` + (r.blocked ? `, ${r.blocked} don't sponsor visas` : ''));
  $('#matchFilter').value = '0';
  await loadJobs();
};
$('#rankBtn').onclick = async () => {
  const r = await call('rank', {}, 'Scoring matches…');
  toast(`Scored ${r.scored} jobs`);
  loadJobs();
};
$('#importBtn').onclick = () => {
  openSheet(`<h2>Import links</h2>
    <p class="muted">Paste job application links, one per line — or a CSV with a <code>url</code> column (optional: <code>company</code>, <code>title</code>, <code>location</code>).</p>
    <textarea id="importText" placeholder="https://job-boards.greenhouse.io/company/jobs/123&#10;https://jobs.lever.co/company/abc…"></textarea>
    <div class="sheet-actions"><button class="btn left" id="csvBtn">Choose CSV…</button><button class="btn" id="cancelImport">Cancel</button><button class="btn primary" id="doImport">Import</button></div>`);
  $('#cancelImport').onclick = closeSheet;
  $('#csvBtn').onclick = async () => {
    const p = await A.pickFile([{ name: 'CSV or text', extensions: ['csv', 'txt'] }]);
    if (p) $('#importText').value = await A.readText(p);
  };
  $('#doImport').onclick = async () => {
    const text = $('#importText').value;
    if (!text.trim()) return;
    closeSheet();
    const r = await call('jobs.import', { text }, 'Importing links…');
    toast(`Added ${r.added} job${r.added === 1 ? '' : 's'}` + (r.duplicates ? ` (${r.duplicates} already there)` : ''));
    await loadJobs();
    if (r.added) { S.statusFilter = 'all'; $('#siteFilter').value = ''; showPage('jobs'); }
  };
};

// ---------- answers page ----------
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
    return `<div class="una"><div><div class="q">${esc(u[0])}</div><div class="meta">${esc(u[1])} · seen ${esc(u[3])}× · last at ${esc(u[4])}</div></div>${input}<button class="btn" data-save="${i}">Save</button></div>`;
  }).join('');
  $$('[data-save]').forEach((b) => (b.onclick = async () => {
    const i = +b.dataset.save;
    const v = $(`#unansweredList [data-i="${i}"]`).value.trim();
    if (!v) return toast('Type or pick an answer first');
    const q = S.unanswered[i][0];
    const match = reEscape(q.toLowerCase().replace(/[*?]+$/, '').trim().slice(0, 80));
    S.answers.unshift([match, v, '']); // specific answers go first — first match wins
    await saveAnswers([q]);
    toast('Saved. It will be filled from now on.');
  }));
  $('#answersBody').innerHTML = S.answers.map((r, i) => `
    <tr data-i="${i}">
      <td><input type="text" value="${esc(r[0])}" data-k="0" spellcheck="false"></td>
      <td><input type="text" value="${esc(r[1])}" data-k="1"></td>
      <td><select data-k="2">${['', 'choice', 'text'].map((v) => `<option value="${v}" ${v === r[2] ? 'selected' : ''}>${v || 'any'}</option>`).join('')}</select></td>
      <td><button class="icon-btn" title="Delete" data-del="${i}"><svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg></button></td>
    </tr>`).join('');
  $$('#answersBody [data-k]').forEach((el) => (el.onchange = () => {
    S.answers[+el.closest('tr').dataset.i][+el.dataset.k] = el.value;
  }));
  $$('[data-del]').forEach((b) => (b.onclick = () => { S.answers.splice(+b.dataset.del, 1); renderAnswers(); }));
}
async function saveAnswers(resolved = []) {
  const r = await call('answers.save', { rows: S.answers.filter((x) => x[0]), resolved }, 'Saving answers…');
  S.answers = r.answers.map((x) => [x[0], x[1], x[2] || '']);
  S.unanswered = r.unanswered;
  renderAnswers();
}
$('#addAnswerBtn').onclick = () => { S.answers.unshift(['', '', '']); renderAnswers(); $('#answersBody input').focus(); };
$('#saveAnswersBtn').onclick = async () => { await saveAnswers(); toast('Answers saved'); };

// ---------- profile page ----------
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
  const r = await call('profile.get', { id });
  renderProfileForm(r);
}
function field(name, label, value, type = 'text', wide = false, ph = '') {
  return `<label class="field ${wide ? 'wide' : ''}"><span>${label}</span><input type="${type}" name="${name}" value="${esc(value)}" placeholder="${esc(ph)}" spellcheck="false"></label>`;
}
function renderProfileForm(r) {
  const p = r.profile || {};
  const isNew = r.id === 'new';
  const owner = r.owner;
  pendingResume = null;
  $('#profileTitle').textContent = isNew ? 'New profile' : `${p.first_name || ''} ${p.last_name || ''}`.trim() || 'Profile';
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
    <div class="card"><h3>Voluntary questions</h3><p class="muted">Equal-opportunity questions. Leave as "Decline to answer" if you prefer.</p><div class="grid">
      ${sel('gender', 'Gender')}${sel('hispanic', 'Hispanic or Latino')}${sel('race', 'Race')}${sel('veteran', 'Veteran status')}${sel('disability', 'Disability')}
    </div>${owner ? '<p class="muted">Changes here only fill in new answers — edit existing ones on the Answers page.</p>' : ''}</div>
    <div class="card"><h3>Resume</h3><p class="muted">Uploaded to every application. PDF works best.</p>
      <div class="file-row"><button type="button" class="btn" id="pickResume">Choose PDF…</button><span class="file-name" id="resumeName">${r.resume ? 'resume.pdf ✓' : 'No resume yet'}</span></div></div>
    <div class="card"><h3>Cover letter template</h3>
      ${r.style ? '<p class="muted"><b>You have a custom letter style</b> (letter_style.json in your folder): your stories are picked to fit each job, so this template isn\'t used.</p>' : ''}
      <p class="muted">Write your letter once. Blanks get filled for each job: <code>{company}</code> <code>{role}</code> <code>{name}</code> <code>{date}</code>. Leave out "Dear…" and "Sincerely" — they're added for you. With a Claude key in Settings, each letter is rewritten for the job in your voice instead.</p>
      <label class="field wide"><textarea name="__template" placeholder="I'm excited to apply for the {role} position at {company}…">${esc(r.template || '')}</textarea></label></div>
  `;
  $('#pickResume').onclick = async () => {
    const f = await A.pickFile([{ name: 'Resume', extensions: ['pdf'] }]);
    if (f) { pendingResume = f; $('#resumeName').textContent = f.split('/').pop() + ' (will be saved)'; }
  };
}
$('#saveProfileBtn').onclick = async () => {
  const form = $('#profileForm');
  const data = {};
  form.querySelectorAll('input[name], select[name]').forEach((el) => {
    data[el.name] = el.type === 'checkbox' ? el.checked : el.value.trim();
  });
  if (!data.first_name || !data.email) return toast('First name and email are required', 'bad');
  const tpl = form.querySelector('[name="__template"]');
  if (S.editing === 'new' && !pendingResume) return toast('Add a resume first', 'bad');
  const st = await call('profile.save', { id: S.editing, data, resume: pendingResume, template: tpl ? tpl.value : null }, 'Saving profile…');
  applyState(st);
  S.editing = st.active;
  toast('Profile saved');
  await afterProfileSwitch();
  loadProfile(st.active);
};
async function afterProfileSwitch() {
  A.setSettings({ lastProfile: S.state.active });
  S.current = null;
  S.viewLoaded = false;
  $('#curCompany').textContent = 'Pick a job to start';
  $('#curRole').textContent = 'Your queue is on the left, best matches first.';
  $('#inspBody').innerHTML = '<p class="muted">Questions and what was filled in will show up here.</p>';
  $('#summary').textContent = '';
  setBanner('', '');
  await loadJobs();
  await matchNewJobs();
  const a = await call('answers.get');
  S.unanswered = a.unanswered;
  $('#answersCount').textContent = S.unanswered.length || '';
  updateView();
}

// ---------- profile switcher ----------
$('#profileBtn').onclick = () => {
  const st = S.state;
  openSheet(`<h2>Who's applying?</h2><p class="muted">Each person has their own resume, answers, job list and letters.</p>
    <div class="plist">${st.profiles.filter((p) => !p.placeholder).map((p) => `
      <div class="pitem ${p.id === st.active ? 'on' : ''}" data-id="${esc(p.id)}"><span class="avatar">${esc(initials(p.name))}</span><span>${esc(p.name)}</span>${p.owner ? '<span class="tag">Owner</span>' : ''}</div>`).join('')}
    </div>
    <div class="sheet-actions"><button class="btn left" id="newProfile">New profile…</button><button class="btn" id="closeP">Done</button></div>`);
  $$('.pitem').forEach((el) => (el.onclick = async () => {
    closeSheet();
    if (el.dataset.id === S.state.active) return;
    applyState(await call('profile.activate', { id: el.dataset.id }, 'Switching profile…'));
    await afterProfileSwitch();
    toast(`Now applying as ${S.state.profiles.find((p) => p.id === S.state.active).name}`);
  }));
  $('#closeP').onclick = closeSheet;
  $('#newProfile').onclick = () => {
    closeSheet();
    S.editing = 'new';
    showPage('profile');
    renderProfileForm({ id: 'new', profile: { relocate: true }, template: '', owner: false, resume: false });
  };
};

// ---------- settings ----------
$('#saveSettingsBtn').onclick = async () => {
  const s = await A.setSettings({ apiKey: $('#apiKey').value.trim(), model: $('#model').value });
  applyState(await call('settings', { api_key: s.apiKey || '', model: s.model }, 'Saving…'));
  toast(S.state.ai ? 'Claude is on' : 'Claude is off');
};
$('#openFolderBtn').onclick = () => A.openFolder();

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
      applyState(await A.call('profile.activate', { id: s.lastProfile })); // reopen whoever used it last
    }
    if (S.state.profiles.find((p) => p.id === S.state.active)?.placeholder) {
      const real = S.state.profiles.filter((p) => !p.placeholder);
      if (real.length) applyState(await A.call('profile.activate', { id: real[0].id }));
      else { // first launch: straight to "create your profile"
        S.editing = 'new';
        showPage('profile');
        renderProfileForm({ id: 'new', profile: { relocate: true }, template: '', owner: false, resume: false });
        toast('Welcome! Start by creating your profile.');
        return;
      }
    }
    await loadJobs();
    const a = await A.call('answers.get');
    S.unanswered = a.unanswered;
    $('#answersCount').textContent = S.unanswered.length || '';
    await matchNewJobs();
  } catch (e) {
    toast('Could not start: ' + e.message, 'bad');
  } finally {
    idle();
  }
})();
