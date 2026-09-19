'use strict';
const path = require('path');
const fs = require('fs');
const { app } = require('electron');

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');

/** Папка данных: та же, что использует Python-слой (dev — ./data, релиз — LOCALAPPDATA). */
function dataDir() {
  const dir = app.isPackaged
    ? path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'SadnessVPN')
    : path.join(PROJECT_ROOT, 'data');
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function resourceRoot() {
  return app.isPackaged ? process.resourcesPath : PROJECT_ROOT;
}

module.exports = { PROJECT_ROOT, dataDir, resourceRoot };
