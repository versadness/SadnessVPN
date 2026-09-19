'use strict';
/**
 * Стекло окна.
 *
 * Основа — настоящая alpha-прозрачность окна (BrowserWindow transparent: true).
 * Она композитится самой DWM по альфе пикселей страницы, работает одинаково на
 * Windows 10 и 11 и, что важно, не зависит от системной галки «Эффекты
 * прозрачности»: именно из-за неё backgroundMaterial/Mica рисуются сплошной
 * заливкой на части машин. Поэтому тонировку целиком задаёт CSS, а не система.
 *
 * Системные эффекты остаются опцией сверху: user32!SetWindowCompositionAttribute
 * умеет размыть то, что находится ЗА окном (чего CSS backdrop-filter не может в
 * принципе — у страницы нет доступа к содержимому рабочего стола).
 */
const os = require('os');

const WCA_ACCENT_POLICY = 19;
const ACCENT_DISABLED = 0;
const ACCENT_ENABLE_BLURBEHIND = 3;
const ACCENT_ENABLE_ACRYLICBLURBEHIND = 4;
const ACCENT_FLAGS_ALL_BORDERS = 0x20 | 0x40 | 0x80 | 0x100;

const DWMWA_USE_IMMERSIVE_DARK_MODE = 20;
const DWMWA_WINDOW_CORNER_PREFERENCE = 33;
const DWMWCP_ROUND = 2;

// Тонирование целиком на стороне CSS, поэтому системному слою отдаётся
// минимальная альфа: он нужен только ради размытия, а не ради цвета.
const NATIVE_TINT = 0x10000000;

let native = null;
let nativeError = null;

function buildNumber() {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(os.release());
  return match ? Number(match[3]) : 0;
}

const BUILD = process.platform === 'win32' ? buildNumber() : 0;
const IS_WIN11 = BUILD >= 22000;

function loadNative() {
  if (native || nativeError) return native;
  if (process.platform !== 'win32') {
    nativeError = new Error('Не Windows');
    return null;
  }
  try {
    const koffi = require('koffi');
    const user32 = koffi.load('user32.dll');
    const dwmapi = koffi.load('dwmapi.dll');
    const AccentPolicy = koffi.struct('ACCENT_POLICY', {
      AccentState: 'int32',
      AccentFlags: 'int32',
      GradientColor: 'uint32',
      AnimationId: 'int32',
    });
    koffi.struct('WINDOWCOMPOSITIONATTRIBDATA', {
      Attrib: 'int32',
      pvData: 'void *',
      cbData: 'size_t',
    });
    native = {
      koffi,
      AccentPolicy,
      setComposition: user32.func(
        'int __stdcall SetWindowCompositionAttribute(void *hwnd, WINDOWCOMPOSITIONATTRIBDATA *data)'
      ),
      setDwmAttribute: dwmapi.func(
        'int __stdcall DwmSetWindowAttribute(void *hwnd, uint32 attr, const void *value, uint32 size)'
      ),
    };
  } catch (error) {
    nativeError = error;
    native = null;
  }
  return native;
}

function hwndOf(win) {
  const api = loadNative();
  if (!api) return null;
  try {
    return api.koffi.decode(win.getNativeWindowHandle(), 'void *');
  } catch (error) {
    return null;
  }
}

function applyAccent(win, accentState) {
  const api = loadNative();
  const hwnd = hwndOf(win);
  if (!api || !hwnd) return false;
  try {
    const policy = Buffer.allocUnsafe(api.koffi.sizeof(api.AccentPolicy));
    api.koffi.encode(policy, api.AccentPolicy, {
      AccentState: accentState,
      AccentFlags: accentState === ACCENT_DISABLED ? 0 : ACCENT_FLAGS_ALL_BORDERS,
      GradientColor: accentState === ACCENT_DISABLED ? 0 : NATIVE_TINT,
      AnimationId: 0,
    });
    return api.setComposition(hwnd, {
      Attrib: WCA_ACCENT_POLICY,
      pvData: policy,
      cbData: policy.length,
    }) !== 0;
  } catch (error) {
    nativeError = error;
    return false;
  }
}

function applyDwmFlags(win) {
  const api = loadNative();
  const hwnd = hwndOf(win);
  if (!api || !hwnd) return;
  const dark = Buffer.alloc(4);
  dark.writeInt32LE(1, 0);
  try {
    api.setDwmAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, dark, 4);
  } catch (error) { /* атрибута нет на старых сборках */ }
  if (!IS_WIN11) return;
  const corner = Buffer.alloc(4);
  corner.writeInt32LE(DWMWCP_ROUND, 0);
  try {
    api.setDwmAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, corner, 4);
  } catch (error) { /* Win10 скруглений не умеет — их рисует CSS */ }
}

/**
 * @param {import('electron').BrowserWindow} win
 * @param {{mode?: 'clear'|'blur'|'acrylic'|'none'}} options
 */
function applyGlass(win, options = {}) {
  const mode = options.mode || 'clear';
  const result = { mode, backend: 'alpha', supported: true, build: BUILD, win11: IS_WIN11 };

  if (process.platform !== 'win32' || win.isDestroyed()) {
    result.supported = false;
    result.reason = 'Прозрачность окна доступна только в Windows';
    return result;
  }

  applyDwmFlags(win);

  // Чистое стекло и «без стекла» системных эффектов не используют вовсе:
  // всё решает альфа страницы, поэтому результат предсказуем на любой машине.
  if (mode === 'clear' || mode === 'none') {
    applyAccent(win, ACCENT_DISABLED);
    result.backend = mode === 'none' ? 'opaque' : 'alpha';
    return result;
  }

  const state = mode === 'blur' ? ACCENT_ENABLE_BLURBEHIND : ACCENT_ENABLE_ACRYLICBLURBEHIND;
  if (applyAccent(win, state)) {
    result.backend = 'SetWindowCompositionAttribute';
    return result;
  }

  // Системный эффект не встал — окно всё равно остаётся прозрачным.
  result.backend = 'alpha';
  result.reason = nativeError
    ? `Системное размытие недоступно: ${nativeError.message}`
    : 'Системное размытие отклонено Windows';
  return result;
}

module.exports = { applyGlass, IS_WIN11, BUILD };
