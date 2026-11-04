'use strict';
/**
 * Sadness VPN — главный процесс Electron.
 *
 * Отвечает за: единственный экземпляр, окно без рамки с системным стеклом,
 * трей, управление backend-процессом и IPC для рендерера.
 */
const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, ipcMain, shell, nativeTheme, dialog } = require('electron');

const backend = require('./lib/backend');
const appearanceStore = require('./lib/appearance');
const windowState = require('./lib/window-state');
const tray = require('./lib/tray');
const { applyGlass, IS_WIN11, BUILD } = require('./lib/glass');
const startup = require('./lib/startup-event');
const { PROJECT_ROOT, resourceRoot, iconPath } = require('./lib/paths');

const RENDERER_DIR = path.join(__dirname, '..', 'renderer');

let mainWindow = null;
// quitting — пользователь действительно выходит (не сворачивание в трей).
let quitting = false;
// shuttingDown — остановка движков уже идёт, второй заход не нужен.
let shuttingDown = false;
let glassStatus = { supported: false, backend: 'css' };
let closeToTray = false;

// Прозрачное окно и аппаратное ускорение соседствуют плохо на части драйверов Win10:
// без этого флага акрил иногда рисуется чёрным прямоугольником.
app.commandLine.appendSwitch('enable-transparent-visuals');
if (process.platform === 'win32' && !IS_WIN11) {
  app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion');
}
app.setAppUserModelId('SadnessVPN.App');
// AppImage: в Ubuntu 23.10+ запрещены непривилегированные user namespaces, и
// песочница Chromium не даёт приложению запуститься. Окно показывает только
// локальную страницу бэкенда (keepLocal ниже не пускает чужие адреса), поэтому
// для AppImage песочница рендерера отключается. Пакеты deb/rpm ставят
// chrome-sandbox с нужными правами и этого не требуют.
if (process.platform === 'linux' && process.env.APPIMAGE) {
  app.commandLine.appendSwitch('no-sandbox');
}

function readRendererAsset(relative) {
  try {
    return fs.readFileSync(path.join(RENDERER_DIR, relative), 'utf8');
  } catch (error) {
    return '';
  }
}

function refreshGlass(win = mainWindow) {
  if (!win || win.isDestroyed()) return glassStatus;
  const appearance = appearanceStore.load();
  glassStatus = applyGlass(win, { mode: appearance.glassMode });
  win.webContents.send('appearance:changed', { appearance, glass: glassStatus });
  return glassStatus;
}

function createWindow({ hidden = false } = {}) {
  const saved = windowState.load();
  const win = new BrowserWindow({
    width: saved.width,
    height: saved.height,
    x: saved.x,
    y: saved.y,
    minWidth: 860,
    minHeight: 620,
    show: false,
    frame: false,
    // Настоящая alpha-прозрачность: DWM композитит окно по альфе пикселей
    // страницы. В отличие от backgroundMaterial/Mica это не зависит от
    // системной галки «Эффекты прозрачности», которая у многих выключена и
    // превращает системный акрил в сплошную заливку.
    transparent: true,
    backgroundColor: '#00000000',
    hasShadow: false,
    titleBarStyle: 'hidden',
    icon: iconPath(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
      // Приложение живёт в трее часами. Без троттлинга скрытое окно
      // продолжает крутить таймеры и композитить backdrop-filter на полной
      // частоте. Счётчик сессии считает от метки времени
      // (Date.now() - sessionStart), а не по тикам, поэтому отложенные
      // тики не дают расхождения: при показе значение сразу верное.
      backgroundThrottling: true,
    },
  });

  windowState.track(win);
  win.setMenuBarVisibility(false);

  win.once('ready-to-show', () => {
    refreshGlass(win);
    if (saved.maximized) win.maximize();
    if (!hidden) win.show();
    // Установленный лаунчер ждёт это событие до 60 секунд и без него
    // сообщает пользователю о сорванном запуске.
    startup.signalReady();
    backend.notifyReady();
  });

  // Стекло и стиль интерфейса подмешиваются в страницу, которую отдаёт backend,
  // чтобы не дублировать вёрстку на время переезда движков на Node.
  win.webContents.on('dom-ready', async () => {
    const css = readRendererAsset('css/glass-shell.css');
    if (css) await win.webContents.insertCSS(css);
    const bridge = readRendererAsset('js/shell-bridge.js');
    if (bridge) {
      try {
        await win.webContents.executeJavaScript(`${bridge}\n//# sourceURL=shell-bridge.js`, true);
      } catch (error) {
        console.error('shell-bridge:', error);
      }
    }
  });

  const notifyMaximized = () => {
    if (win.isDestroyed()) return;
    win.webContents.send('window:maximized', win.isMaximized());
  };
  win.on('maximize', notifyMaximized);
  win.on('unmaximize', notifyMaximized);

  win.on('close', (event) => {
    if (quitting || shuttingDown) return;
    if (closeToTray) {
      event.preventDefault();
      win.hide();
    }
  });

  // Страница локальная и не запрашивает камеру, микрофон, геолокацию или
  // уведомления — весь этот класс отклоняется разом. Исключение одно:
  // запись в буфер обмена, которой копируются журнал и локальный ID.
  // Без неё Chromium отказывает navigator.clipboard.writeText, и кнопка
  // «Скопировать» отвечала «Нет доступа к буферу обмена».
  const allowed = (permission, origin) =>
    permission === 'clipboard-sanitized-write' &&
    (!origin || origin.startsWith(backend.baseUrl));
  win.webContents.session.setPermissionRequestHandler(
    (wc, permission, callback) => callback(allowed(permission, wc && wc.getURL()))
  );
  win.webContents.session.setPermissionCheckHandler(
    (_wc, permission, origin) => allowed(permission, origin)
  );

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  // Окно показывает только локальный интерфейс: мост sadnessShell не должен
  // оказаться у чужой страницы. Внешние ссылки уходят в браузер.
  const keepLocal = (event, url) => {
    if (String(url).startsWith(`${backend.baseUrl}/`)) return;
    event.preventDefault();
    if (/^https?:/i.test(url)) shell.openExternal(url);
  };
  win.webContents.on('will-navigate', keepLocal);
  win.webContents.on('will-redirect', keepLocal);

  win.webContents.on('render-process-gone', (_event, details) => {
    dialog.showErrorBox(
      'Sadness VPN',
      `Графический процесс завершился (${details.reason}). Перезапустите приложение.`
    );
  });

  return win;
}

async function bootstrap() {
  const result = await backend.start((level, message) => {
    if (level === 'error') console.error('[backend]', message);
    else console.log('[backend]', message);
  });

  if (!result.ok) {
    dialog.showErrorBox('Sadness VPN', result.error || 'Не удалось запустить backend.');
    app.quit();
    return;
  }

  // Автозапуск Windows прячет окно в трей только при включённом «Тихом запуске».
  const hidden = startup.startedByAutostart() && (await backend.startupPreferences()).silent;
  mainWindow = createWindow({ hidden });
  registerIpc();
  // Лаунчер активирует уже запущенное окно через бэкенд. Второй экземпляр
  // Electron (app.on('second-instance')) остаётся запасным путём.
  backend.watchShowRequests(showWindow, () => { quitting = true; app.quit(); });
  await backend.attachToSession(mainWindow.webContents.session);
  await mainWindow.loadURL(`${backend.baseUrl}/?desktop=1&shell=electron`);

  tray.create({
    onShow: showWindow,
    onQuit: () => { quitting = true; app.quit(); },
    onToggleConnect: () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.executeJavaScript(
          'window.toggleConnect && window.toggleConnect()'
        ).catch(() => {});
      }
    },
  });
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showWindow);

  app.whenReady().then(() => {
    nativeTheme.themeSource = 'dark';
    bootstrap();
  });

  app.on('window-all-closed', () => {
    if (!closeToTray) app.quit();
  });

  // Единственная точка выхода: движки останавливаются до того, как процесс умрёт,
  // иначе в системе остаются TUN-интерфейс и правила маршрутизации.
  app.on('before-quit', (event) => {
    if (shuttingDown) return;
    shuttingDown = true;
    quitting = true;
    event.preventDefault();
    tray.destroy();
    backend.stop()
      .catch((error) => console.error('backend.stop:', error))
      .finally(() => app.exit(0));
  });
}

/* ------------------------------- IPC ------------------------------- */

// Обработчики регистрируются из bootstrap(), когда окно уже существует.
// Раньше они висели на уровне модуля при mainWindow === null, и, например,
// window:close уводил приложение в app.quit() ещё до появления окна.
function registerIpc() {
  ipcMain.handle('window:minimize', () => mainWindow && mainWindow.minimize());
  ipcMain.handle('window:toggle-maximize', () => {
    if (!mainWindow) return false;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
    return mainWindow.isMaximized();
  });
  ipcMain.handle('window:close', () => {
    if (!mainWindow) return;
    if (closeToTray) mainWindow.hide();
    else app.quit();
  });
  ipcMain.handle('window:hide', () => mainWindow && mainWindow.hide());
  ipcMain.handle('window:is-maximized', () => Boolean(mainWindow && mainWindow.isMaximized()));
  ipcMain.handle('window:set-close-to-tray', (_event, value) => {
    closeToTray = value === true;
    return closeToTray;
  });
  // Полный выход по запросу страницы: нужен перед установкой обновления —
  // установщик ждёт, пока освободятся файлы в каталоге установки, а сворачивание
  // в трей его не устраивает.
  ipcMain.handle('app:quit', () => { quitting = true; app.quit(); });

  ipcMain.handle('appearance:get', () => ({
    appearance: appearanceStore.load(),
    glass: glassStatus,
    platform: { win11: IS_WIN11, build: BUILD },
  }));

  ipcMain.handle('appearance:set', (_event, patch) => {
    const appearance = appearanceStore.save(patch);
    const glass = refreshGlass();
    return { appearance, glass };
  });

  ipcMain.handle('app:version', () => app.getVersion());
  ipcMain.handle('app:open-external', (_event, url) => {
    if (/^https?:/i.test(String(url))) shell.openExternal(url);
  });
  ipcMain.handle('app:open-data-dir', () => shell.openPath(require('./lib/paths').dataDir()));
  ipcMain.handle('tray:set-state', (_event, connected) => tray.setState(connected === true));
}
