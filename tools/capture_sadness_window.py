"""Capture only the Sadness VPN window for local visual smoke testing."""

from __future__ import annotations

import sys
import time
import ctypes
from pathlib import Path

import win32gui
import win32ui
from PIL import ImageGrab
from PIL import Image


def main() -> int:
    output = Path(sys.argv[1]).resolve()
    title = sys.argv[2] if len(sys.argv) > 2 else "Sadness VPN"
    deadline = time.time() + 10
    hwnd = 0
    while time.time() < deadline:
        hwnd = win32gui.FindWindow(None, title)
        if hwnd and win32gui.IsWindowVisible(hwnd):
            break
        time.sleep(0.1)
    if not hwnd or not win32gui.IsWindowVisible(hwnd):
        print("VISIBLE_WINDOW_NOT_FOUND")
        return 1
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if right <= left or bottom <= top:
        print("INVALID_WINDOW_RECT")
        return 1
    try:
        image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    except OSError:
        width, height = right - left, bottom - top
        window_dc = win32gui.GetWindowDC(hwnd)
        source_dc = win32ui.CreateDCFromHandle(window_dc)
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)
        try:
            # PW_RENDERFULLCONTENT asks WebView-backed child windows to render.
            ctypes.windll.user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), 2)
            info = bitmap.GetInfo()
            bits = bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                "RGB",
                (info["bmWidth"], info["bmHeight"]),
                bits,
                "raw",
                "BGRX",
                0,
                1,
            )
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            source_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, window_dc)
    image.save(output)
    print(f"CAPTURED={output} SIZE={image.width}x{image.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
