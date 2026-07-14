"""
engine/singbox.py — управление sing-box (TUN + маршрутизация по процессам)
"""
import subprocess
import threading
import os
import json
import tempfile
import platform
import socket
import time
from engine.paths import bin_path


class SingBoxManager:
    def __init__(self, log_callback=None):
        self.process      = None
        self.running      = False
        self.log_cb       = log_callback or (lambda msg, tag: None)
        self._config_file = None

    def _singbox_path(self):
        return bin_path("sing-box.exe" if platform.system() == "Windows" else "sing-box")

    # ── Порты ──────────────────────────────────────────────────────────────────

    def _port_free(self, port: int) -> bool:
        """True, если порт свободен (никто не слушает)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) != 0

    def _wait_port_free(self, port: int, timeout: float = 4.0) -> bool:
        """Ждём, пока порт реально освободится после taskkill."""
        end = time.time() + timeout
        while time.time() < end:
            if self._port_free(port):
                return True
            time.sleep(0.2)
        return False

    def _kill_port(self, port: int):
        """Принудительно завершает процесс, удерживающий TCP-порт (Windows)."""
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
        except Exception:
            pass

    def _remove_tun_adapter(self):
        """Удаляет зависший Wintun TUN-адаптер (tun-in) через netsh.
        Нужно, когда sing-box упал не очистившись — Windows держит
        виртуальный интерфейс и новый запуск падает с
        'Cannot create a file when that file already exists'.
        """
        if platform.system() != "Windows":
            return
        try:
            # Метод 1: netsh — удаляем интерфейс tun-in
            subprocess.run(
                ["netsh", "interface", "delete", "interface", "name=tun-in"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
            )
        except Exception:
            pass
        try:
            # Метод 2: PowerShell — убираем адаптер Wintun через Get-NetAdapter
            subprocess.run(
                [
                    "powershell", "-NonInteractive", "-Command",
                    "Get-NetAdapter | Where-Object { $_.InterfaceDescription -like '*Wintun*' } "
                    "| Remove-NetAdapter -Confirm:$false -ErrorAction SilentlyContinue",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=8,
            )
        except Exception:
            pass
        # Даём системе время убрать адаптер
        time.sleep(0.5)

    def _kill_stale(self):
        """Завершает висящие sing-box, освобождает порт 9090 и удаляет
        зависший TUN-адаптер Wintun (fix: 'Cannot create a file when
        that file already exists').
        """
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "sing-box.exe", "/T"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                # Ждём, пока процесс отпустит порт Clash API
                if not self._wait_port_free(9090, timeout=3.0):
                    # Всё ещё занят — добиваем держателя порта
                    self._kill_port(9090)
                    self._wait_port_free(9090, timeout=3.0)
        except Exception:
            pass
        # Всегда чистим Wintun-адаптер — он может зависнуть даже
        # если процесс уже завершился
        self._remove_tun_adapter()

    def start(self, config: dict) -> bool:
        if self.running:
            self.stop()
        self._kill_stale()

        singbox = self._singbox_path()
        if not os.path.exists(singbox):
            self.log_cb(
                "sing-box не найден!\n"
                "Скачай: https://github.com/SagerNet/sing-box/releases\n"
                "Файл: sing-box.exe в папку bin/",
                "err"
            )
            return False

        # wintun.dll нужен только при TUN inbound
        has_tun = any(ib.get("type") == "tun" for ib in config.get("inbounds", []))
        if has_tun:
            wintun = bin_path("wintun.dll")
            if not os.path.exists(wintun):
                self.log_cb(
                    "wintun.dll не найден!\n"
                    "Скачай: https://wintun.net → wintun.dll в папку bin/",
                    "err"
                )
                return False

        fd, path = tempfile.mkstemp(suffix=".json", prefix="singbox_cfg_")
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        self._config_file = path

        try:
            self.process = subprocess.Popen(
                [singbox, "run", "-c", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(singbox),  # wintun.dll должен быть рядом
                creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows" else 0
            )
            self.running = True

            # ── Диагностика: ловим мгновенное падение ──
            time.sleep(0.8)
            if self.process.poll() is not None:
                out = self.process.stdout.read()
                self.log_cb("sing-box упал сразу после запуска!", "err")
                for line in out.splitlines():
                    if line.strip():
                        self.log_cb(f"  {line}", "err")
                self._cleanup()
                self.running = False
                return False

            threading.Thread(target=self._read_output, daemon=True).start()
            self.log_cb(f"sing-box запущен (PID {self.process.pid})", "ok")
            return True

        except PermissionError:
            self.log_cb(
                "Нет прав администратора!\n"
                "TUN-режим требует запуска от администратора.\n"
                "Запусти SadnessVPN.exe от имени администратора.",
                "err"
            )
            self._cleanup()
            self.running = False
            return False
        except Exception as e:
            self.log_cb(f"Ошибка запуска sing-box: {e}", "err")
            self._cleanup()
            self.running = False
            return False

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
        # Убеждаемся, что порт освобождён для следующего подключения
        self._wait_port_free(9090, timeout=3.0)
        # Удаляем Wintun-адаптер, чтобы следующий старт прошёл чисто
        self._remove_tun_adapter()
        self.log_cb("sing-box остановлен", "info")

    def _cleanup(self):
        if self._config_file and os.path.exists(self._config_file):
            try:
                os.remove(self._config_file)
            except Exception:
                pass
            self._config_file = None
        self.process = None

    def _read_output(self):
        try:
            for line in self.process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                low = line.lower()
                if any(w in low for w in ["error", "failed", "fatal"]):
                    tag = "err"
                elif "warn" in low:
                    tag = "warn"
                elif any(w in low for w in ["started", "listening", "tun"]):
                    tag = "ok"
                else:
                    tag = "log"
                self.log_cb(line, tag)
        except Exception:
            pass
        self.running = False
        self.log_cb("sing-box процесс завершён", "info")