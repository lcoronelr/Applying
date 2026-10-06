// Apply — desktop app. The window shows the UI (ui/) with the real job website embedded in it;
// engine.py (same filling code as bot.py) drives that website through Electron's DevTools port.
const { app, BrowserWindow, WebContentsView, ipcMain, dialog, shell, nativeTheme } = require('electron');
const path = require('path');
const fs = require('fs');
const readline = require('readline');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const PYTHON = path.join(ROOT, '.venv', 'bin', 'python');
// Everyone's files (profile, resume, jobs, letters, screenshots, friends' profiles) live in
// ~/Library/Application Support/Apply/Data — the same place for the installed app, the project folder and bot.py.
const DATA = path.join(app.getPath('userData'), 'Data');

// Version 1.0.0 of the installed app kept files in ~/Documents/Apply: bring any real profiles over, once.
function migrateFromDocuments() {
  const old = path.join(require('os').homedir(), 'Documents', 'Apply');
  const marker = path.join(DATA, '.moved-from-documents');
  if (!app.isPackaged || fs.existsSync(marker) || !fs.existsSync(old)) return;
  try {
    const oldProfiles = path.join(old, 'profiles');
    if (fs.existsSync(oldProfiles)) {
      for (const name of fs.readdirSync(oldProfiles)) {
        const dest = path.join(DATA, 'profiles', name);
        if (!fs.existsSync(dest)) fs.cpSync(path.join(oldProfiles, name), dest, { recursive: true });
      }
    }
    const ownerOld = path.join(old, 'profile.json');
    if (!fs.existsSync(path.join(DATA, 'profile.json')) && fs.existsSync(ownerOld)) {
      const p = JSON.parse(fs.readFileSync(ownerOld, 'utf8'));
      if (!(p.first_name === 'Setup' && !p.email)) {
        for (const f of fs.readdirSync(old)) if (f !== 'profiles') fs.cpSync(path.join(old, f), path.join(DATA, f), { recursive: true });
      }
    }
    fs.writeFileSync(marker, new Date().toISOString());
  } catch (e) { console.error('Could not bring over ~/Documents/Apply:', e.message); }
}
app.setName('Apply');
app.commandLine.appendSwitch('remote-debugging-port', '0'); // random free port, local only
app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1');

let win, view, engine;
let nextId = 1;
const pending = new Map();
const settingsFile = () => path.join(app.getPath('userData'), 'settings.json');

function loadSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), 'utf8')); } catch { return {}; }
}
function saveSettings(s) {
  fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2), { mode: 0o600 }); // holds the API key
}

function devtoolsPort() {
  const f = path.join(app.getPath('userData'), 'DevToolsActivePort');
  for (let i = 0; i < 50; i++) {
    if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8').split('\n')[0].trim();
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
  }
  throw new Error('DevTools port not available');
}

function startEngine() {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const port = devtoolsPort();
  fs.mkdirSync(DATA, { recursive: true });
  migrateFromDocuments();
  env.APPLY_DATA = DATA;
  if (app.isPackaged) {
    const bin = path.join(process.resourcesPath, 'engine', 'engine');
    engine = spawn(bin, ['--cdp', port], { cwd: DATA, env });
  } else {
    engine = spawn(PYTHON, [path.join(ROOT, 'engine.py'), '--cdp', port], { cwd: ROOT, env });
  }
  readline.createInterface({ input: engine.stdout }).on('line', (line) => {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.event) return win?.webContents.send('engine:event', msg.event, msg.data);
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    msg.ok ? p.resolve(msg.result) : p.reject(new Error(msg.error));
  });
  engine.stderr.on('data', (d) => process.stderr.write(d)); // bot.py's progress prints
  engine.on('exit', (code) => {
    for (const p of pending.values()) p.reject(new Error('The engine stopped (code ' + code + ').'));
    pending.clear();
    if (!app.isQuitting) win?.webContents.send('engine:event', 'crashed', { code });
  });
}

function call(cmd, args = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    engine.stdin.write(JSON.stringify({ id, cmd, args }) + '\n');
  });
}

const BLANK = 'data:text/html;charset=utf-8,' + encodeURIComponent(
  '<title>applyview</title><body style="margin:0;background:#fff"></body>');

function createWindow() {
  win = new BrowserWindow({
    width: 1480, height: 940, minWidth: 1100, minHeight: 680,
    title: 'Apply',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 18 },
    // solid colors (no see-through sidebar): all light in light mode, all dark in dark mode
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#1e1e1f' : '#ffffff',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  win.loadFile(path.join(__dirname, 'ui', 'index.html'));

  // The job website: a real browser panel, logins kept between runs.
  view = new WebContentsView({ webPreferences: { partition: 'persist:jobs', sandbox: true } });
  view.setVisible(false);
  win.contentView.addChildView(view);
  view.webContents.loadURL(BLANK);
  view.webContents.setWindowOpenHandler(({ url }) => { view.webContents.loadURL(url); return { action: 'deny' }; });
  const sendUrl = () => win.webContents.send('view:url', view.webContents.getURL());
  view.webContents.on('did-navigate', sendUrl);
  view.webContents.on('did-navigate-in-page', sendUrl);
}

app.whenReady().then(() => {
  createWindow();
  startEngine();

  ipcMain.handle('engine', (_e, cmd, args) => call(cmd, args));
  ipcMain.on('view:bounds', (_e, b) => {
    if (!b || !b.visible) return view.setVisible(false);
    view.setBounds({ x: Math.round(b.x), y: Math.round(b.y), width: Math.round(b.width), height: Math.round(b.height) });
    view.setVisible(true);
  });
  ipcMain.handle('view:back', () => view.webContents.navigationHistory.canGoBack() && view.webContents.navigationHistory.goBack());
  ipcMain.handle('view:reload', () => view.webContents.reload());
  ipcMain.handle('open-external', (_e, url) => shell.openExternal(url));
  ipcMain.handle('show-file', (_e, p) => shell.showItemInFolder(p));
  ipcMain.handle('open-folder', () => shell.openPath(DATA));
  ipcMain.handle('pick-file', async (_e, filters) => {
    const r = await dialog.showOpenDialog(win, { properties: ['openFile'], filters });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle('read-text', (_e, p) => fs.readFileSync(p, 'utf8'));
  ipcMain.handle('settings:get', () => loadSettings());
  ipcMain.handle('settings:set', (_e, s) => { saveSettings({ ...loadSettings(), ...s }); return loadSettings(); });
});

app.on('before-quit', () => { app.isQuitting = true; engine?.kill(); });
app.on('window-all-closed', () => app.quit());
