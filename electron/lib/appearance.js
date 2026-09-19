'use strict';
/** Настройки оформления окна: режим стекла и уровни прозрачности. */
const fs = require('fs');
const path = require('path');
const { dataDir } = require('./paths');

const FILE = 'window-appearance.json';

const MODES = ['clear', 'blur', 'acrylic', 'none'];

const HEX = /^#[0-9a-f]{6}$/i;

const DEFAULTS = {
  // clear   — чистая alpha-прозрачность окна (работает везде, не зависит от Windows)
  // blur    — плюс системное размытие того, что за окном
  // acrylic — плюс системный акрил с шумом
  // none    — непрозрачное окно
  glassMode: 'clear',
  // 0 — сквозь окно полностью виден рабочий стол, 100 — плотная подложка
  windowAlpha: 100,
  // плотность карточек и боковой панели поверх прозрачного окна
  panelAlpha: 0,
  // дополнительное затемнение ради читаемости текста на пёстрых обоях
  veil: 0,
  // акцент интерфейса: активный пункт меню, кнопки, фокус, графики
  accent: '#49258e',
  // база фона: из неё выводится тон окна и плотных панелей
  background: '#170a1c',
};

function file() {
  return path.join(dataDir(), FILE);
}

function clamp(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

function normalize(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  return {
    glassMode: MODES.includes(source.glassMode) ? source.glassMode : DEFAULTS.glassMode,
    windowAlpha: clamp(source.windowAlpha, 0, 100, DEFAULTS.windowAlpha),
    panelAlpha: clamp(source.panelAlpha, 0, 100, DEFAULTS.panelAlpha),
    veil: clamp(source.veil, 0, 90, DEFAULTS.veil),
    accent: HEX.test(source.accent || '') ? source.accent.toLowerCase() : DEFAULTS.accent,
    background: HEX.test(source.background || '') ? source.background.toLowerCase() : DEFAULTS.background,
  };
}

function load() {
  try {
    return normalize(JSON.parse(fs.readFileSync(file(), 'utf8')));
  } catch (error) {
    return { ...DEFAULTS };
  }
}

function save(patch) {
  const next = normalize({ ...load(), ...(patch || {}) });
  try {
    fs.writeFileSync(file(), JSON.stringify(next, null, 2), 'utf8');
  } catch (error) { /* диск только для чтения — работаем с тем, что в памяти */ }
  return next;
}

module.exports = { load, save, normalize, DEFAULTS, MODES };
