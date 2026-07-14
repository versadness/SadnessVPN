"""
engine/xray.py — управление процессом Xray-core
"""
import subprocess
import threading
import os
import json
import tempfile
import platform
import time

from engine.paths import bin_path


class XrayManager:
    def __init__(self, log_callback=None):
        self.process      = None
        self.running      = False
        self.log_cb       = log_callback or (lambda msg, tag: None)
        self._config_file = None

    def _xray_path(self):
        return bin_path("xray.exe" if platform.system() == "Windows" else "xray")

    # ── убить все висящие xray ───────────────
    def _kill_stale(self):
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "xray.exe", "/T"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                time.sleep(0.6)
        except Exception:
            pass

    # ── запуск ───────────────────────────────
    def start(self, config: dict) -> bool:
        # Если уже запущен — сначала останавливаем
        if self.running:
            self.stop()

        # Убиваем все зависшие xray процессы
        self._kill_stale()

        xray = self._xray_path()
        if not os.path.exists(xray):
            self.log_cb(
                f"Xray не найден: {xray}\n"
                "Скачай с https://github.com/XTLS/Xray-core/releases\n"
                "и положи в папку bin/",
                "err"
            )
            return False

        fd, path = tempfile.mkstemp(suffix=".json", prefix="xray_cfg_")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        self._config_file = path

        try:
            self.process = subprocess.Popen(
                [xray, "run", "-c", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows" else 0
            )
            self.running = True
            threading.Thread(target=self._read_output, daemon=True).start()
            self.log_cb(f"Xray запущен (PID {self.process.pid})", "ok")
            return True
        except Exception as e:
            self.log_cb(f"Ошибка запуска: {e}", "err")
            self._cleanup()
            return False

    # ── остановка ────────────────────────────
    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.running = False
        self._cleanup()
        time.sleep(0.6)
        self.log_cb("Xray остановлен", "info")

    def _cleanup(self):
        if self._config_file and os.path.exists(self._config_file):
            try:
                os.remove(self._config_file)
            except Exception:
                pass
            self._config_file = None
        self.process = None

    # ── чтение вывода ────────────────────────
    def _read_output(self):
        try:
            for line in self.process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tag = "err" if any(w in line.lower()
                                   for w in ["error", "failed", "warning"]) else "log"
                self.log_cb(line, tag)
        except Exception:
            pass
        self.running = False
        self.log_cb("Xray процесс завершён", "info")
