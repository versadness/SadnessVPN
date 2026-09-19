'use strict';
/**
 * Подтверждение готовности интерфейса установленному лаунчеру.
 *
 * SadnessVPN.exe (C#) создаёт одноразовое событие Local\SadnessVPN.Startup.<guid>,
 * передаёт его имя через --startup-event= и ждёт до 60 секунд. Раньше событие
 * выставлял Python из notify_ready(); теперь окно рисует Electron, поэтому
 * подтверждать готовность должен он — иначе лаунчер решит, что запуск сорвался.
 */
const PREFIX = '--startup-event=';
const EVENT_MODIFY_STATE = 0x0002;

let signalled = false;

function eventName() {
  const argument = process.argv.find((value) => value.startsWith(PREFIX));
  if (!argument) return '';
  const name = argument.slice(PREFIX.length);
  // Те же границы, что и в engine/startup_diagnostics.notify_ready.
  if (!name.startsWith('Local\\SadnessVPN.Startup.') || name.length > 100) return '';
  return name;
}

/** Выставляет событие ровно один раз; повторные вызовы безвредны. */
function signalReady() {
  if (signalled || process.platform !== 'win32') return false;
  const name = eventName();
  if (!name) return false;
  try {
    const koffi = require('koffi');
    const kernel32 = koffi.load('kernel32.dll');
    const openEvent = kernel32.func('void *__stdcall OpenEventW(uint32 access, int inherit, const char16_t *name)');
    const setEvent = kernel32.func('int __stdcall SetEvent(void *handle)');
    const closeHandle = kernel32.func('int __stdcall CloseHandle(void *handle)');
    const handle = openEvent(EVENT_MODIFY_STATE, 0, name);
    if (!handle) return false;
    try {
      setEvent(handle);
      signalled = true;
      return true;
    } finally {
      closeHandle(handle);
    }
  } catch (error) {
    return false;
  }
}

/** Автозапуск Windows: окно не поднимается, приложение живёт в трее. */
function startedByAutostart() {
  return process.argv.includes('--autostart');
}

module.exports = { signalReady, startedByAutostart };
