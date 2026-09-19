"""Задача автозапуска в планировщике Windows.

Автозапуск живёт в планировщике, а не в ветке реестра Run: запуск требует
повышенных прав (/RL HIGHEST), которых запись в Run не даёт. Старая запись в
Run осталась от прежних версий и снимается при любом изменении, иначе
приложение стартовало бы дважды.
"""
import os
import subprocess
import sys

TASK_NAME = "SadnessVPN"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def target_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))


def _task_command() -> str:
    path = target_path()
    if getattr(sys, "frozen", False):
        return f'"{path}"'
    return f'"{sys.executable}" "{path}"'


def _run(*arguments):
    result = subprocess.run(["schtasks", *arguments], capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode, (result.stderr or result.stdout).strip()


def _drop_legacy_run_entry():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, TASK_NAME)
        winreg.CloseKey(key)
    except Exception:
        pass


def enable() -> str:
    """Создаёт задачу входа в систему. Возвращает путь для журнала."""
    code, message = _run("/Create", "/F", "/TN", TASK_NAME, "/TR", _task_command(),
                         "/SC", "ONLOGON", "/RL", "HIGHEST")
    if code != 0:
        raise RuntimeError(message)
    _drop_legacy_run_entry()
    return target_path()


def disable():
    # Задачи может не быть: пользователь мог снять её вручную или чистилкой.
    if enabled():
        code, message = _run("/Delete", "/F", "/TN", TASK_NAME)
        if code != 0:
            raise RuntimeError(message or "Не удалось отключить автозапуск")
    _drop_legacy_run_entry()


def enabled():
    if sys.platform != "win32":
        return False
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    scheduler = folder = task = None
    try:
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        try:
            folder = scheduler.GetFolder("\\")
            task = folder.GetTask("SadnessVPN")
        except pythoncom.com_error as exc:
            # HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND): no owned task.
            details = exc.excepinfo
            nested_code = details[5] if details and len(details) > 5 else None
            if exc.hresult == -2147024894 or (
                exc.hresult == -2147352567 and nested_code == -2147024894
            ):
                return False
            raise
        return bool(task.Enabled)
    finally:
        # Release COM interfaces on the same initialized thread, before COM
        # teardown. This avoids IUnknown release errors on missing tasks.
        task = folder = scheduler = None
        pythoncom.CoUninitialize()
