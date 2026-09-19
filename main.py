"""Desktop entry point. Native window operations run on the WinForms UI thread."""
import ctypes
import json
import os
import sys
import threading
import time
import urllib.request

from engine.paths import data_dir
from engine.diagnostics import journal
from engine.webview_runtime import prepare_webview_runtime
from ui.server import SERVER_INSTANCE_ID, run as run_server, shutdown_engines, close_to_tray_enabled
from ui import window_control
from ui.tray import WindowsTray
from engine.startup_diagnostics import notify_ready
import webview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(BASE_DIR, "app.ico")
W, H = 980, 700


def load_startup_preferences():
    try:
        with open(os.path.join(data_dir(), "settings.json"), encoding="utf-8") as file:
            settings = json.load(file)
        return {"silent": settings.get("silent") is True}
    except (OSError, ValueError, AttributeError):
        return {"silent": False}


def show_startup_error(message):
    journal.error(message)
    ctypes.windll.user32.MessageBoxW(None, message, "Sadness VPN", 0x10)


def wait_for_server(host="127.0.0.1", port=45678, timeout=10.0,
                    expected_instance=SERVER_INSTANCE_ID):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=.3) as response:
                payload = json.load(response)
            if payload.get("app") == "SadnessVPN" and payload.get("instance") == expected_instance:
                return True
        except Exception:
            pass
        time.sleep(.05)
    return False


class SingleInstance:
    """OS-owned mutex and activation event; released automatically on a crash."""
    def __init__(self):
        import ctypes.wintypes as wt
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
        self.kernel.CreateMutexW.restype = wt.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        self.kernel.CreateEventW.restype = wt.HANDLE
        self.kernel.SetEvent.argtypes = [wt.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        self.event = self.kernel.CreateEventW(None, False, False, "Local\\SadnessVPN.Activate.v1")
        self.mutex = self.kernel.CreateMutexW(None, False, "Local\\SadnessVPN.Instance.v1")
        self.existing = ctypes.get_last_error() == 183
        if not self.event or not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())

    def notify(self):
        self.kernel.SetEvent(self.event)

    def listen(self):
        while True:
            result = self.kernel.WaitForSingleObject(self.event, 1000)
            if result == 0:
                window_control.controller.show()
            elif result != 258:
                return


def main():
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SadnessVPN.App")
    instance = SingleInstance()
    if instance.existing:
        instance.notify()
        notify_ready()
        return
    journal.info("Sadness VPN: запуск")
    try:
        runtime = prepare_webview_runtime(BASE_DIR, webview.settings)
        journal.info("WebView2: %s", runtime or "системный (режим разработки)")
    except Exception as exc:
        show_startup_error(str(exc))
        return
    threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": 45678}, daemon=True).start()
    if not wait_for_server():
        show_startup_error("Не удалось открыть локальный порт 45678. Закройте предыдущую версию Sadness VPN или приложение, занимающее этот порт.")
        return
    window = webview.create_window(
        "Sadness VPN", "http://127.0.0.1:45678?desktop=1", width=W, height=H,
        min_size=(780, 600), background_color="#0D1018", frameless=False,
        easy_drag=False, resizable=True, shadow=False,
    )
    controller = window_control.WindowController(window, shutdown_engines, ICON_PATH)
    window_control.controller = controller
    tray = WindowsTray(ICON_PATH, controller.show, controller.close)
    tray_ok = tray.start(wait=True)
    controller.close_to_tray = lambda: tray_ok and close_to_tray_enabled()
    if not tray_ok:
        journal.warning("Трей недоступен: %s", tray.error)
    # Explicit launcher/desktop activation must open an actual window even if
    # background startup is configured. Autostart retains the saved preference.
    controller.silent = load_startup_preferences()["silent"] and tray_ok and "--show" not in sys.argv
    window.events.before_show += controller.before_show
    window.events.loaded += controller.loaded
    window.events.loaded += notify_ready
    window.events.closing += controller.on_closing
    threading.Thread(target=instance.listen, daemon=True).start()
    webview.start(controller.watch_startup, gui="edgechromium", private_mode=False,
                  storage_path=os.path.join(data_dir(), "webview"))
    shutdown_engines()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        journal.exception("Ошибка запуска приложения")
        from engine.startup_diagnostics import report_failure
        report_failure(exc)
