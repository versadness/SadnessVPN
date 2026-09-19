'use strict';
const path = require('path');
const { Tray, Menu, nativeImage } = require('electron');
const { resourceRoot } = require('./paths');

let tray = null;

/**
 * Ищет иконку трея.
 *
 * Раньше путь был один — resources/app.ico, — а файл туда не попадал:
 * в сборку Electron он не входил вовсе. nativeImage молча отдавал пустое
 * изображение, и значок в трее оказывался невидимым. Теперь перебираем
 * известные места и явно сообщаем, если не нашли.
 */
function findIcon() {
  const candidates = [
    path.join(resourceRoot(), 'app.ico'),
    path.join(__dirname, '..', '..', 'app.ico'),
    // Установленная раскладка: рядом с Electron лежит пакет Python.
    path.join(resourceRoot(), '..', '..', 'runtime', '_internal', 'app.ico'),
  ];
  for (const candidate of candidates) {
    const image = nativeImage.createFromPath(candidate);
    if (!image.isEmpty()) return image;
  }
  return null;
}

function create({ onShow, onQuit, onToggleConnect }) {
  if (tray) return tray;
  const icon = findIcon();
  if (!icon) {
    console.error('Tray: иконка app.ico не найдена, значок будет невидимым');
  }
  try {
    tray = new Tray(icon || nativeImage.createEmpty());
  } catch (error) {
    return null;
  }
  tray.setToolTip('Sadness VPN');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Открыть Sadness VPN', click: onShow },
    { type: 'separator' },
    { label: 'Подключить / отключить', click: onToggleConnect },
    { type: 'separator' },
    { label: 'Выход', click: onQuit },
  ]));
  tray.on('click', onShow);
  tray.on('double-click', onShow);
  return tray;
}

function setState(connected) {
  if (!tray) return;
  tray.setToolTip(connected ? 'Sadness VPN — подключено' : 'Sadness VPN — отключено');
}

function destroy() {
  if (tray && !tray.isDestroyed()) tray.destroy();
  tray = null;
}

module.exports = { create, setState, destroy };
