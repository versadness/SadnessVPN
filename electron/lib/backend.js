'use strict';
/**
 * Управление backend-процессом.
 *
 * Пока движки (sing-box, mihomo, AmneziaWG, zapret) живут в Python,
 * Electron запускает их сервер дочерним процессом и ждёт /api/health.
 * Переезд на Node идёт помодульно — контракт HTTP остаётся тем же, поэтому
 * этот файл меняется в одном месте, когда Python перестанет быть нужен.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');
const { app } = require('electron');
const { PROJECT_ROOT } = require('./paths');

const HOST = '127.0.0.1';
const PORT = 45678;

let child = null;
let stopping = false;

/**
 * Где живёт бэкенд.
 *
 * В установленном виде это тот же PyInstaller-пакет, что и раньше
 * (INSTALLDIR/runtime/SadnessVPN.exe), запущенный с --headless: окно рисует
 * Electron, а Python остаётся только сервером API. Так в MSI не появляется
 * второй Python и не трогаются уже зарегистрированные компоненты.
 */
function backendCommand() {
  if (app.isPackaged) {
    // process.resourcesPath = INSTALLDIR/electron/resources
    const executable = path.resolve(process.resourcesPath, '..', '..', 'runtime', 'SadnessVPN.exe');
    return { executable, args: ['--headless'], cwd: path.dirname(executable) };
  }
  const candidates = [
    path.join(PROJECT_ROOT, 'venv311', 'Scripts', 'pythonw.exe'),
    path.join(PROJECT_ROOT, 'venv311', 'Scripts', 'python.exe'),
  ];
  const executable = candidates.find((candidate) => fs.existsSync(candidate)) || 'python';
  return {
    executable,
    args: [path.join(PROJECT_ROOT, 'backend_main.py')],
    cwd: PROJECT_ROOT,
  };
}

/** Возвращает ответ /api/health живого бэкенда или null, если его нет. */
function health(timeoutMs = 400) {
  return new Promise((resolve) => {
    const request = http.get(
      { host: HOST, port: PORT, path: '/api/health', timeout: timeoutMs },
      (response) => {
        let body = '';
        response.on('data', (chunk) => { body += chunk; });
        response.on('end', () => {
          try {
            const payload = JSON.parse(body);
            resolve(payload.app === 'SadnessVPN' ? payload : null);
          } catch (error) {
            resolve(null);
          }
        });
      }
    );
    request.on('timeout', () => { request.destroy(); resolve(null); });
    request.on('error', () => resolve(null));
  });
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealth(timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  // Холодный старт PyInstaller занимает секунды, поэтому опрос замедляется:
  // фиксированные 150 мс давали до 166 запросов на один запуск.
  let delay = 150;
  while (Date.now() < deadline) {
    if (await health()) return true;
    await wait(delay);
    delay = Math.min(delay * 2, 600);
  }
  return false;
}

/** @returns {Promise<{ok: boolean, reused?: boolean, error?: string}>} */
async function start(onLog) {
  // Порт 45678 один на всю систему. Если на нём уже кто-то отвечает, это
  // может быть другая установленная версия — переиспользовать её нельзя:
  // окно покажет чужую вёрстку, и это выглядит как «собралась старая сборка».
  const running = await health();
  if (running) {
    const expected = app.getVersion();
    if (running.version && running.version !== expected) {
      return {
        ok: false,
        error: `На порту ${PORT} уже работает Sadness VPN ${running.version}, `
          + `а запускается ${expected}. Закройте запущенную версию полностью, `
          + `включая значок в области уведомлений, и повторите запуск.`,
      };
    }
    return { ok: true, reused: true };
  }

  const command = backendCommand();
  if (command.executable !== 'python' && !fs.existsSync(command.executable)) {
    return { ok: false, error: `Не найден бэкенд: ${command.executable}` };
  }

  try {
    child = spawn(command.executable, command.args, {
      cwd: command.cwd,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
    });
  } catch (error) {
    return { ok: false, error: `Не удалось запустить backend (${command.executable}): ${error.message}` };
  }

  const relay = (stream, level) => {
    if (!stream) return;
    stream.setEncoding('utf8');
    stream.on('data', (chunk) => {
      if (typeof onLog === 'function') onLog(level, chunk.trimEnd());
    });
  };
  relay(child.stdout, 'info');
  relay(child.stderr, 'error');

  let exitInfo = null;
  child.on('exit', (code, signal) => {
    exitInfo = { code, signal };
    child = null;
    if (!stopping && typeof onLog === 'function') {
      onLog('error', `Backend завершился (code=${code}, signal=${signal})`);
    }
  });

  if (await waitForHealth()) return { ok: true };

  return {
    ok: false,
    error: exitInfo
      ? `Backend завершился с кодом ${exitInfo.code}. Проверьте, что установлены зависимости из requirements.txt.`
      : 'Backend не ответил на 127.0.0.1:45678 за 25 секунд. Возможно, порт занят предыдущей версией Sadness VPN.',
  };
}

/**
 * Держит один длинный запрос к бэкенду и поднимает окно, когда лаунчер
 * попросил активировать уже запущенный экземпляр. Так повторный клик по
 * ярлыку не поднимает второй процесс Electron и не просит прав администратора.
 */
function watchShowRequests(onShow) {
  let stopped = false;

  const ask = () => new Promise((resolve) => {
    const request = http.get(
      { host: HOST, port: PORT, path: '/api/shell/show-wait', timeout: 40000 },
      (response) => {
        let body = '';
        response.on('data', (chunk) => { body += chunk; });
        response.on('end', () => {
          try {
            resolve(JSON.parse(body).show === true);
          } catch (error) {
            resolve(null);
          }
        });
      }
    );
    request.on('timeout', () => { request.destroy(); resolve(null); });
    request.on('error', () => resolve(null));
  });

  (async () => {
    while (!stopped && !stopping) {
      const show = await ask();
      if (stopped || stopping) return;
      if (show === null) {
        // Бэкенд перезапускается или ещё не поднялся — не долбим его в цикле.
        await wait(2000);
        continue;
      }
      if (show) {
        try { onShow(); } catch (error) { console.error('show-request:', error); }
      }
    }
  })();

  return () => { stopped = true; };
}

/** Корректная остановка: сначала движки, потом сам процесс. */
function requestShutdown(timeoutMs = 8000) {
  return new Promise((resolve) => {
    const request = http.request(
      { host: HOST, port: PORT, path: '/api/shell/shutdown', method: 'POST', timeout: timeoutMs },
      (response) => {
        response.resume();
        response.on('end', () => resolve(response.statusCode === 200));
      }
    );
    request.on('timeout', () => { request.destroy(); resolve(false); });
    request.on('error', () => resolve(false));
    request.end();
  });
}

async function stop() {
  stopping = true;
  // Убить процесс сразу нельзя: в системе останутся поднятый TUN-интерфейс
  // и правила маршрутизации, а пользователь потеряет сеть до перезагрузки.
  const graceful = await requestShutdown();
  const deadline = Date.now() + (graceful ? 10000 : 2000);
  while (Date.now() < deadline) {
    if (!(await health(300))) break;
    await wait(200);
  }

  if (!child) return;
  const pid = child.pid;
  try { child.kill(); } catch (error) { /* уже завершился */ }
  await wait(600);
  // Ждём taskkill до конца: раньше его запускали и тут же выходили из
  // Electron через app.exit(0), так что дерево процессов могло пережить
  // выход — а вместе с ним поднятый TUN и правила маршрутизации.
  if (child && process.platform === 'win32') {
    await new Promise((resolve) => {
      let killer;
      try {
        killer = spawn('taskkill', ['/pid', String(pid), '/f', '/t'], { windowsHide: true });
      } catch (error) {
        resolve();
        return;
      }
      const done = setTimeout(resolve, 4000);
      const finish = () => { clearTimeout(done); resolve(); };
      killer.on('exit', finish);
      killer.on('error', finish);
    });
  }
  child = null;
}

module.exports = { start, stop, requestShutdown, watchShowRequests, health, HOST, PORT, baseUrl: `http://${HOST}:${PORT}` };
