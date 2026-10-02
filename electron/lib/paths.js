'use strict';
const path = require('path');
const fs = require('fs');
const { app } = require('electron');

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');

/**
 * Папка данных: та же, что использует Python-слой (engine/paths.app_root_dir).
 * dev — ./data; Windows — %LOCALAPPDATA%\SadnessVPN; Linux — $XDG_DATA_HOME/SadnessVPN
 * (по умолчанию ~/.local/share/SadnessVPN).
 */
function installedRoot() {
  if (process.platform === 'win32') {
    return path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'SadnessVPN');
  }
  const xdg = process.env.XDG_DATA_HOME || path.join(require('os').homedir(), '.local', 'share');
  return path.join(xdg, 'SadnessVPN');
}

function dataDir() {
  const dir = app.isPackaged ? installedRoot() : path.join(PROJECT_ROOT, 'data');
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

/** Значок приложения: ICO на Windows, PNG на Linux (ICO там не читается). */
function iconPath() {
  return path.join(resourceRoot(), process.platform === 'win32' ? 'app.ico' : 'app.png');
}

function resourceRoot() {
  return app.isPackaged ? process.resourcesPath : PROJECT_ROOT;
}

module.exports = { PROJECT_ROOT, dataDir, resourceRoot, iconPath };
