import sys, os, threading, time, ctypes, ctypes.wintypes, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui.server import SERVER_INSTANCE_ID, run as run_server
from engine.paths import data_dir
import webview
import urllib.request

# Переопределяем иконку процесса в таскбаре
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SadnessVPN.App")

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(BASE_DIR, "app.ico")

W, H = 920, 620


def load_startup_preferences() -> dict:
    try:
        with open(os.path.join(data_dir(), "settings.json"), "r", encoding="utf-8") as file:
            settings = json.load(file)
        if not isinstance(settings, dict):
            raise ValueError("Invalid settings")
    except Exception:
        settings = {}
    return {
        "silent": settings.get("silent") is True,
    }

def start_server():
    run_server(host="127.0.0.1", port=45678)


def show_startup_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Sadness VPN", 0x10)
    except Exception:
        print(message)

def wait_for_server(
    host="127.0.0.1",
    port=45678,
    timeout=10.0,
    expected_instance=SERVER_INSTANCE_ID,
) -> bool:
    deadline = time.perf_counter() + timeout
    url = f"http://{host}:{port}/api/health"
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.3) as response:
                payload = json.load(response)
            if (
                payload.get("app") == "SadnessVPN"
                and payload.get("instance") == expected_instance
            ):
                return True
        except Exception:
            pass
        time.sleep(0.05)
    return False

def get_work_area():
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    return rect

def find_hwnd(title="Sadness VPN", attempts=60, delay=0.1):
    user32 = ctypes.windll.user32
    for _ in range(attempts):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(delay)
    return None

def fix_window(minimize_after=False):
    hwnd = find_hwnd()
    if not hwnd:
        return

    user32 = ctypes.windll.user32
    wa = get_work_area()
    x  = wa.left + (wa.right  - wa.left - W) // 2
    y  = wa.top  + (wa.bottom - wa.top  - H) // 2

    FLAGS = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE

    for delay in [0, 0.1, 0.3, 0.6, 1.0]:
        time.sleep(delay)
        buf = ctypes.create_string_buffer(44)
        ctypes.memmove(buf, (44).to_bytes(4, 'little'), 4)
        user32.GetWindowPlacement(hwnd, buf)
        show_cmd = int.from_bytes(buf.raw[8:12], 'little')
        if show_cmd == 3:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, 0, x, y, W, H, FLAGS)
    if minimize_after:
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE

def set_icon():
    if not os.path.exists(ICON_PATH):
        print(f"[icon] Файл не найден: {ICON_PATH}")
        return

    hwnd = find_hwnd()
    if not hwnd:
        print("[icon] hwnd не найден")
        return

    try:
        user32 = ctypes.windll.user32

        # Задаём argtypes явно для корректной передачи 64-битных HANDLE на x64
        HANDLE  = ctypes.c_void_p
        HWND    = ctypes.wintypes.HWND
        UINT    = ctypes.wintypes.UINT
        WPARAM  = ctypes.c_size_t   # 64-bit на x64
        LPARAM  = ctypes.c_ssize_t  # 64-bit на x64

        user32.LoadImageW.restype  = HANDLE
        user32.LoadImageW.argtypes = [
            HANDLE, ctypes.c_wchar_p, UINT, ctypes.c_int, ctypes.c_int, UINT
        ]
        user32.SendMessageW.restype  = LPARAM
        user32.SendMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]

        user32.SetClassLongPtrW.restype  = ctypes.c_size_t
        user32.SetClassLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]

        path_w = ctypes.c_wchar_p(ICON_PATH)
        LR_LOADFROMFILE = 0x0010

        hbig   = user32.LoadImageW(None, path_w, 1,  0,  0, LR_LOADFROMFILE)
        hsmall = user32.LoadImageW(None, path_w, 1, 16, 16, LR_LOADFROMFILE)

        # Иконка окна (заголовок)
        if hbig:   user32.SendMessageW(hwnd, 0x0080, 1, hbig)
        if hsmall: user32.SendMessageW(hwnd, 0x0080, 0, hsmall)

        # Иконка класса окна (таскбар)
        if hbig:   user32.SetClassLongPtrW(hwnd, -14, hbig)   # GCLP_HICON
        if hsmall: user32.SetClassLongPtrW(hwnd, -34, hsmall) # GCLP_HICONSM

        print(f"[icon] big={hbig} small={hsmall} — готово")
    except Exception as e:
        print(f"[icon] Ошибка: {e}")

def on_loaded():
    # Ждём пока EdgeChromium закончит инициализацию и перестанет сбрасывать иконку
    time.sleep(1.5)
    set_icon()

if __name__ == "__main__":
    print(f"[icon] Путь: {ICON_PATH}")
    print(f"[icon] Существует: {os.path.exists(ICON_PATH)}")

    threading.Thread(target=start_server, daemon=True).start()
    if not wait_for_server():
        message = "Не удалось запустить локальный сервер SadnessVPN. Возможно, порт 45678 уже занят."
        show_startup_error(message)
        raise SystemExit(message)

    startup_preferences = load_startup_preferences()
    threading.Thread(
        target=fix_window,
        kwargs={"minimize_after": startup_preferences["silent"]},
        daemon=True,
    ).start()

    window = webview.create_window(
        "Sadness VPN",
        "http://127.0.0.1:45678",
        width=W,
        height=H,
        min_size=(760, 500),
        background_color="#0D0810",
        frameless=True,
        easy_drag=False,
        resizable=True,
    )

    # Устанавливаем иконку ПОСЛЕ того как Edge полностью загрузился
    window.events.loaded += lambda: threading.Thread(target=on_loaded, daemon=True).start()

    webview.start(icon=ICON_PATH)
