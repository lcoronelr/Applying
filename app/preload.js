const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('applyApp', {
  call: (cmd, args) => ipcRenderer.invoke('engine', cmd, args),
  onEvent: (fn) => ipcRenderer.on('engine:event', (_e, name, data) => fn(name, data)),
  onUrl: (fn) => ipcRenderer.on('view:url', (_e, url) => fn(url)),
  setViewBounds: (b) => ipcRenderer.send('view:bounds', b),
  back: () => ipcRenderer.invoke('view:back'),
  reload: () => ipcRenderer.invoke('view:reload'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  showFile: (p) => ipcRenderer.invoke('show-file', p),
  openFolder: () => ipcRenderer.invoke('open-folder'),
  pickFile: (filters) => ipcRenderer.invoke('pick-file', filters),
  readText: (p) => ipcRenderer.invoke('read-text', p),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (s) => ipcRenderer.invoke('settings:set', s),
});
