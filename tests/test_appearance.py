"""Пользовательский фон: загрузка, замена, сброс и сохранение после перезапуска."""
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from ui import app_state, server

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:45678"


def image_bytes(fmt, color=(40, 120, 200), size=(64, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


class WallpaperApiTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.directory = tempfile.TemporaryDirectory()
        self.settings_path = os.path.join(self.directory.name, "settings.json")
        self.saved = dict(app_state.app_settings)
        self.events = []
        self.patches = [
            mock.patch.object(app_state, "PROFILE_DIR", os.path.join(self.directory.name, "profile")),
            mock.patch.object(app_state, "SETTINGS_PATH", self.settings_path),
            mock.patch.object(app_state, "SETTINGS_BAK_PATH", self.settings_path + ".bak"),
            mock.patch("ui.routes.appearance.deps.broadcast", side_effect=self.events.append),
        ]
        for patch in self.patches:
            patch.start()
        app_state.app_settings["wallpaper_file"] = ""

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        app_state.app_settings.clear()
        app_state.app_settings.update(self.saved)
        self.directory.cleanup()

    def upload(self, data, name="bg.png"):
        return self.client.post("/api/appearance/wallpaper", base_url=BASE,
                                data={"file": (io.BytesIO(data), name)},
                                content_type="multipart/form-data")

    def test_upload_is_served_and_survives_a_restart(self):
        response = self.upload(image_bytes("PNG"))
        body = response.get_json()
        self.assertTrue(body["ok"], body)
        # Интерфейс получает настоящее имя файла, а не выводит его из адреса.
        self.assertEqual(body["file"], "wallpaper.png")
        self.assertEqual(self.events[-1]["file"], "wallpaper.png")
        served = self.client.get(body["url"], base_url=BASE)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["Cache-Control"], "no-store")
        self.assertTrue(served.data.startswith(b"\x89PNG"))
        # Перезапуск: настройки читаются с диска заново.
        self.assertEqual(app_state.load_settings()["wallpaper_file"], "wallpaper.png")

    def test_replacement_removes_the_old_file_and_bad_upload_keeps_it(self):
        self.upload(image_bytes("PNG"))
        body = self.upload(image_bytes("JPEG"), "photo.jpg").get_json()
        self.assertEqual(body["file"], "wallpaper.jpg")
        profile = Path(app_state.PROFILE_DIR)
        self.assertEqual(sorted(p.name for p in profile.iterdir()), ["wallpaper.jpg"])
        broken = self.upload(b"\x89PNG\r\n\x1a\nnot really a png")
        self.assertFalse(broken.get_json()["ok"])
        oversized = self.upload(b"\xff\xd8\xff" + b"0" * (8 * 1024 * 1024 + 1), "big.jpg")
        self.assertFalse(oversized.get_json()["ok"])
        self.assertIn("слишком большое", oversized.get_json()["error"])
        # Прежний рабочий фон остаётся.
        self.assertEqual(app_state.app_settings["wallpaper_file"], "wallpaper.jpg")
        with self.client.get("/api/appearance/wallpaper", base_url=BASE) as served:
            self.assertEqual(served.status_code, 200)

    def test_reset_clears_the_background(self):
        self.upload(image_bytes("PNG"))
        self.assertTrue(self.client.post("/api/appearance/wallpaper/reset", base_url=BASE).get_json()["ok"])
        self.assertEqual(self.events[-1], {"type": "appearance_updated", "kind": "wallpaper", "url": "", "file": ""})
        with self.client.get("/api/appearance/wallpaper", base_url=BASE) as served:
            self.assertEqual(served.status_code, 404)
        self.assertEqual(app_state.load_settings()["wallpaper_file"], "")


class WallpaperVisibilityTests(unittest.TestCase):
    def test_electron_shell_shows_the_wallpaper_layer(self):
        # Раньше слой скрывался в оболочке Electron целиком: display:none !important.
        css = (ROOT / "renderer" / "css" / "glass-shell.css").read_text(encoding="utf-8")
        hidden = re.findall(r"([^{}]*)\{\s*display:\s*none\s*!important;?\s*\}", css)
        self.assertFalse(any("#customWallpaper" in selector for selector in hidden))
        active = re.search(r"html\.shell-glass #customWallpaper\.active\s*\{([^}]*)\}", css).group(1)
        self.assertIn("display: block", active)
        self.assertIn("opacity: 1", active)
        # Фон лежит под тонировкой окна (body::before, z-index -1), поэтому
        # прозрачность и затемнение стекла действуют на картинку.
        self.assertIn("z-index: -2", active)
        self.assertIn("z-index: -1", re.search(r"html\.shell-glass body::before\s*\{([^}]*)\}", css).group(1))
        for mode in ("glass-blur", "glass-acrylic"):
            rule = re.search(rf"html\.shell-glass\.{mode} #customWallpaper\.active\s*\{{([^}}]*)\}}", css).group(1)
            self.assertIn("filter: blur(", rule)
        bridge = (ROOT / "renderer" / "js" / "shell-bridge.js").read_text(encoding="utf-8")
        self.assertIn("root.classList.toggle('glass-blur', appearance.glassMode === 'blur')", bridge)
        self.assertIn("root.classList.toggle('glass-acrylic', appearance.glassMode === 'acrylic')", bridge)

    def test_interface_takes_the_file_name_from_the_server(self):
        javascript = (ROOT / "ui" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("=d.file||''", javascript)
        self.assertIn("=result.file||''", javascript)
        self.assertNotIn("d.url.split('?')", javascript)


if __name__ == "__main__":
    unittest.main()
