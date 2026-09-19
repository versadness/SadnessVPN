"""Standard-library-only diagnostics, usable before importing Flask/.NET/WebView."""
import ctypes
import datetime
import faulthandler
import os
import sys
import tempfile
import traceback

_stream = None
_path = None


def initialize():
    global _stream, _path
    if _stream is not None:
        return _path
    candidates = [os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
                               "SadnessVPN", "data", "diagnostics"),
                  os.path.join(tempfile.gettempdir(), "SadnessVPN-diagnostics")]
    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "startup-python.log")
            if os.path.isfile(path) and os.path.getsize(path) > 2 * 1024 * 1024:
                os.replace(path, path + ".previous")
            _stream = open(path, "a", encoding="utf-8", buffering=1)
            _path = path
            break
        except OSError:
            continue
    if _stream is None:
        return None
    _stream.write("\n" + datetime.datetime.now().isoformat() + " Python entry reached; pid=" + str(os.getpid()) + "\n")
    if getattr(sys, "frozen", False):
        sys.stdout = sys.stderr = _stream
    try:
        faulthandler.enable(file=_stream, all_threads=True)
    except (OSError, RuntimeError):
        pass
    return _path


def report_failure(exc):
    path = initialize()
    if _stream:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=_stream)
        _stream.flush()
    message = ("Sadness VPN не удалось запустить.\n\nПричина: " + type(exc).__name__ + ": " + str(exc)[:700]
               + "\n\nЖурнал: " + (path or "Не удалось создать файл — проверьте права записи.")
               + "\n\nОткрыть папку диагностики?")
    if sys.platform == "win32":
        result = ctypes.windll.user32.MessageBoxW(None, message, "Sadness VPN — ошибка запуска", 0x14)
        if result == 6 and path:
            os.startfile(os.path.dirname(path))


def notify_ready():
    """Signal only the one-time event created by the installed launcher."""
    prefix = "--startup-event="
    name = next((a[len(prefix):] for a in sys.argv if a.startswith(prefix)), "")
    if not name.startswith("Local\\SadnessVPN.Startup.") or len(name) > 100:
        return
    import ctypes.wintypes as wt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    kernel.OpenEventW.restype = wt.HANDLE
    kernel.SetEvent.argtypes = [wt.HANDLE]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.OpenEventW(2, False, name)
    if handle:
        try:
            kernel.SetEvent(handle)
        finally:
            kernel.CloseHandle(handle)
