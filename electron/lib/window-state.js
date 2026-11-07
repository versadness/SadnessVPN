'use strict';
/** Запоминает геометрию окна между запусками. */
const fs = require('fs');
const path = require('path');
const { screen } = require('electron');
const { dataDir } = require('./paths');

const FILE = 'window-state.json';
const DEFAULT = { width: 1377, height: 788, maximized: false };

function file() {
  return path.join(dataDir(), FILE);
}

function visibleOnSomeDisplay(bounds) {
  if (!Number.isFinite(bounds.x) || !Number.isFinite(bounds.y)) return false;
  return screen.getAllDisplays().some((display) => {
    const area = display.workArea;
    return bounds.x < area.x + area.width
      && bounds.x + bounds.width > area.x
      && bounds.y < area.y + area.height
      && bounds.y + bounds.height > area.y;
  });
}

function load() {
  let saved;
  try {
    saved = JSON.parse(fs.readFileSync(file(), 'utf8'));
  } catch (error) {
    return { ...DEFAULT };
  }
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return { ...DEFAULT };
  const dimension = (value, minimum, fallback) => {
    if (typeof value !== 'number' && typeof value !== 'string') return fallback;
    const number = Number(value);
    return Number.isFinite(number) && number > 0 && number <= 32768
      ? Math.max(minimum, Math.round(number)) : fallback;
  };
  const state = {
    width: dimension(saved.width, 860, DEFAULT.width),
    height: dimension(saved.height, 620, DEFAULT.height),
    maximized: saved.maximized === true,
  };
  if (visibleOnSomeDisplay({ x: saved.x, y: saved.y, width: state.width, height: state.height })) {
    state.x = saved.x;
    state.y = saved.y;
  }
  return state;
}

function track(win) {
  let timer = null;
  const persist = () => {
    if (win.isDestroyed()) return;
    const maximized = win.isMaximized();
    const bounds = maximized ? win.getNormalBounds() : win.getBounds();
    try {
      fs.writeFileSync(file(), JSON.stringify({ ...bounds, maximized }, null, 2), 'utf8');
    } catch (error) { /* не критично */ }
  };
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(persist, 400);
  };
  win.on('resize', schedule);
  win.on('move', schedule);
  win.on('maximize', schedule);
  win.on('unmaximize', schedule);
  win.on('close', () => { clearTimeout(timer); persist(); });
}

module.exports = { load, track };
