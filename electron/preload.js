'use strict';
/** Мост между главным процессом и страницей. Ничего лишнего в основной мир. */
const { contextBridge, ipcRenderer } = require('electron');

const listeners = { appearance: [], maximized: [] };

ipcRenderer.on('appearance:changed', (_event, payload) => {
  listeners.appearance.forEach((callback) => {
    try { callback(payload); } catch (error) { /* обработчик страницы */ }
  });
});

ipcRenderer.on('window:maximized', (_event, value) => {
  listeners.maximized.forEach((callback) => {
    try { callback(value); } catch (error) { /* обработчик страницы */ }
  });
});

contextBridge.exposeInMainWorld('sadnessShell', {
  isElectron: true,

  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    hide: () => ipcRenderer.invoke('window:hide'),
    isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
    setCloseToTray: (value) => ipcRenderer.invoke('window:set-close-to-tray', value),
    onMaximized: (callback) => { listeners.maximized.push(callback); },
  },

  appearance: {
    get: () => ipcRenderer.invoke('appearance:get'),
    set: (patch) => ipcRenderer.invoke('appearance:set', patch),
    onChange: (callback) => { listeners.appearance.push(callback); },
  },

  app: {
    version: () => ipcRenderer.invoke('app:version'),
    openExternal: (url) => ipcRenderer.invoke('app:open-external', url),
    openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),
    setAutostart: (enabled) => ipcRenderer.invoke('app:set-autostart', enabled),
    getAutostart: () => ipcRenderer.invoke('app:get-autostart'),
    quit: () => ipcRenderer.invoke('app:quit'),
  },

  tray: {
    setState: (connected) => ipcRenderer.invoke('tray:set-state', connected),
  },
});
