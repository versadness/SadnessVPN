"""Reliable native Windows notification-area icon built on pywin32."""

from __future__ import annotations

import os
import sys
import threading


class WindowsTray:
    def __init__(self, icon_path: str, on_show, on_exit, tooltip="Sadness VPN"):
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_exit = on_exit
        self.tooltip = tooltip[:127]
        self.hwnd = None
        self.error = None
        self._notify_id = None
        self._thread = None
        self._message_id = None
        self._taskbar_created = None
        self._icon = None
        self._owns_icon = False
        self._ready = threading.Event()

    def start(self, wait=False, timeout=3.0) -> bool:
        if os.name != "nt":
            self.error = "Системный трей поддерживается только в Windows"
            return False
        if self._thread:
            return self._notify_id is not None
        self._thread = threading.Thread(target=self._run, daemon=True, name="sadness-tray")
        self._thread.start()
        if not wait:
            return True
        if not self._ready.wait(timeout):
            self.error = "Истекло время ожидания системного трея"
            return False
        return self.error is None and self._notify_id is not None

    def _load_icon(self):
        win32con = self._win32con
        win32gui = self._win32gui
        if os.path.isfile(self.icon_path):
            self._owns_icon = True
            return win32gui.LoadImage(
                0,
                self.icon_path,
                win32con.IMAGE_ICON,
                0,
                0,
                win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
            )

        large, small = win32gui.ExtractIconEx(sys.executable, 0)
        icon = small[0] if small else (large[0] if large else None)
        if icon:
            self._owns_icon = True
            for unused in [*large, *small]:
                if unused != icon:
                    try:
                        win32gui.DestroyIcon(unused)
                    except Exception:
                        pass
            return icon

        self._owns_icon = False
        return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

    def _add_icon(self):
        win32gui = self._win32gui
        self._notify_id = (
            self.hwnd,
            1,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            self._message_id,
            self._icon,
            self.tooltip,
        )
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._notify_id)

    def _run(self):
        try:
            import win32api
            import win32con
            import win32gui

            self._win32api = win32api
            self._win32con = win32con
            self._win32gui = win32gui
            self._message_id = win32con.WM_USER + 20
            self._taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
            class_name = f"SadnessVPNTrayWindow_{os.getpid()}"
            wnd_class = win32gui.WNDCLASS()
            wnd_class.hInstance = win32api.GetModuleHandle(None)
            wnd_class.lpszClassName = class_name
            wnd_class.lpfnWndProc = self._window_proc
            win32gui.RegisterClass(wnd_class)
            self.hwnd = win32gui.CreateWindow(
                class_name,
                class_name,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                wnd_class.hInstance,
                None,
            )
            self._icon = self._load_icon()
            self._add_icon()
            self._ready.set()
            win32gui.PumpMessages()
        except Exception as exc:
            self.error = str(exc)
            print(f"[tray] Не удалось создать значок: {exc}")
        finally:
            self._ready.set()
            self._remove_icon()

    def _remove_icon(self):
        try:
            if self._notify_id:
                self._win32gui.Shell_NotifyIcon(self._win32gui.NIM_DELETE, self._notify_id)
        except Exception:
            pass
        try:
            if self._icon and self._owns_icon:
                self._win32gui.DestroyIcon(self._icon)
        except Exception:
            pass

    def _window_proc(self, hwnd, msg, wparam, lparam):
        win32con = self._win32con
        win32gui = self._win32gui
        if msg == self._taskbar_created:
            try:
                self._add_icon()
            except Exception as exc:
                self.error = str(exc)
            return 0
        if msg == self._message_id:
            if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
                threading.Thread(target=self.on_show, daemon=True).start()
            elif lparam == win32con.WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == win32con.WM_COMMAND:
            command = wparam & 0xFFFF
            if command == 1001:
                threading.Thread(target=self.on_show, daemon=True).start()
            elif command == 1002:
                self.on_exit()
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        win32con = self._win32con
        win32gui = self._win32gui
        menu = win32gui.CreatePopupMenu()
        try:
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1001, "Открыть Sadness VPN")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1002, "Выйти")
            position = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self.hwnd)
            win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
                position[0],
                position[1],
                0,
                self.hwnd,
                None,
            )
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        finally:
            win32gui.DestroyMenu(menu)
