"""Оболочка отклоняет разрешения Chromium, кроме записи в буфер обмена.

Глухой отказ на все разрешения ломал копирование журнала и локального ID:
Chromium отказывает navigator.clipboard.writeText без clipboard-sanitized-write,
и кнопка отвечала «Нет доступа к буферу обмена».
"""
import re
import unittest
from pathlib import Path

MAIN_JS = Path(__file__).resolve().parent.parent / "electron" / "main.js"
UI_JS = Path(__file__).resolve().parent.parent / "ui" / "static" / "js" / "app.js"


class ShellPermissionTests(unittest.TestCase):
    def setUp(self):
        self.source = MAIN_JS.read_text(encoding="utf-8")

    def test_both_permission_handlers_are_installed(self):
        for handler in ("setPermissionRequestHandler", "setPermissionCheckHandler"):
            self.assertIn(handler, self.source)

    def test_nothing_grants_permissions_unconditionally(self):
        self.assertNotIn("setPermissionCheckHandler(() => true)", self.source)
        self.assertNotRegex(self.source, r"setPermissionRequestHandler\([^)]*callback\(true\)")

    def test_clipboard_write_is_the_only_allowed_permission(self):
        allowed = re.findall(r"permission === '([a-z-]+)'", self.source)
        self.assertEqual(allowed, ["clipboard-sanitized-write"])

    def test_permission_is_scoped_to_the_local_backend_origin(self):
        self.assertIn("backend.baseUrl", self.source)

    def test_ui_still_copies_through_the_clipboard_api(self):
        ui = UI_JS.read_text(encoding="utf-8")
        self.assertEqual(ui.count("navigator.clipboard.writeText"), 2)
        self.assertIn("Нет доступа к буферу обмена", ui)


if __name__ == "__main__":
    unittest.main()
