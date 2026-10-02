"""Задача автозапуска в планировщике Windows.

Автозапуск живёт в планировщике, а не в ветке реестра Run: запуск требует
повышенных прав (/RL HIGHEST), которых запись в Run не даёт. Старая запись в
Run осталась от прежних версий и снимается при любом изменении, иначе
приложение стартовало бы дважды.

Задача запускает лаунчер с --autostart, а не бэкенд: сам по себе бэкенд не
поднимает ни окна, ни трея, и автоподключение (оно живёт в интерфейсе) при
таком запуске не срабатывало.
"""
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SadnessVPN"
AUTOSTART_ARGUMENT = "--autostart"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _command() -> tuple[str, list[str]]:
    """(исполняемый файл, аргументы) для запуска приложения при входе в Windows."""
    if getattr(sys, "frozen", False):
        # INSTALLDIR/runtime/SadnessVPN.exe — бэкенд, INSTALLDIR/SadnessVPN.exe — лаунчер.
        launcher = Path(sys.executable).resolve().parent.parent / "SadnessVPN.exe"
        if not launcher.is_file():
            raise RuntimeError("Не найден лаунчер Sadness VPN рядом с установленной программой")
        return str(launcher), [AUTOSTART_ARGUMENT]
    electron = _PROJECT_ROOT / "node_modules" / "electron" / "dist" / "electron.exe"
    return str(electron), [str(_PROJECT_ROOT), AUTOSTART_ARGUMENT]


def target_path() -> str:
    return _command()[0]


def _quote(value: str) -> str:
    return f'"{value}"' if " " in value or not value else value


def _task_command() -> str:
    executable, arguments = _command()
    return " ".join([f'"{executable}"', *(_quote(item) for item in arguments)])


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


def _read_task():
    """(включена, путь, аргументы) задачи или None, если задачи нет."""
    if sys.platform != "win32":
        return None
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    scheduler = folder = task = action = None
    try:
        scheduler = win32com.client.Dispatch("Schedule.Service")
        scheduler.Connect()
        try:
            folder = scheduler.GetFolder("\\")
            task = folder.GetTask(TASK_NAME)
        except pythoncom.com_error as exc:
            # HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND): no owned task.
            details = exc.excepinfo
            nested_code = details[5] if details and len(details) > 5 else None
            if exc.hresult == -2147024894 or (
                exc.hresult == -2147352567 and nested_code == -2147024894
            ):
                return None
            raise
        path = arguments = ""
        try:
            action = task.Definition.Actions.Item(1)
            path, arguments = str(action.Path or ""), str(action.Arguments or "")
        except Exception:
            pass
        return bool(task.Enabled), path, arguments
    finally:
        # Release COM interfaces on the same initialized thread, before COM
        # teardown. This avoids IUnknown release errors on missing tasks.
        action = task = folder = scheduler = None
        pythoncom.CoUninitialize()


def enabled():
    task = _read_task()
    return bool(task and task[0])


def ensure_current() -> bool:
    """Перенаправить задачу прежних версий с бэкенда на лаунчер.

    Возвращает True, если задача была пересоздана.
    """
    task = _read_task()
    if not task or not task[0]:
        return False
    executable, _arguments = _command()
    path = os.path.normcase(os.path.abspath(task[1].strip('"'))) if task[1] else ""
    if path == os.path.normcase(os.path.abspath(executable)) and AUTOSTART_ARGUMENT in task[2]:
        return False
    enable()
    return True


if sys.platform != "win32":
    # Linux: автозапуск через ~/.config/autostart (engine/autostart_linux.py).
    from engine.autostart_linux import (  # noqa: E402,F811
        disable, enable, enabled, ensure_current, target_path,
    )
