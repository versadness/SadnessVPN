"""
engine/zapret.py — управление zapret (winws.exe + WinDivert)
Стратегия: Flowseal general (ALT) — проверенная рабочая конфигурация
"""
import subprocess
import threading
import os
import platform
import time

from engine.paths import bin_path


class ZapretManager:
    def __init__(self, log_callback=None):
        self.process   = None
        self.running   = False
        self.log_cb    = log_callback or (lambda msg, tag: None)
        self._strategy = None

    # ── Пути ──────────────────────────────────────────────────────────────────

    def _winws_path(self):
        return bin_path("winws.exe")

    def _bin(self, filename: str) -> str:
        return bin_path(filename)

    def _lists(self, filename: str) -> str:
        bin_dir = os.path.dirname(self._winws_path())
        lists_dir = os.path.join(bin_dir, "lists")
        if not os.path.isdir(lists_dir):
            lists_dir = os.path.join(os.path.dirname(bin_dir), "lists")
        return os.path.join(lists_dir, filename)

    # ── Проверка файлов ───────────────────────────────────────────────────────

    def _check_files(self) -> bool:
        required_bin = [
            "winws.exe",
            "WinDivert.dll",
            "WinDivert64.sys",
            "quic_initial_www_google_com.bin",
            "tls_clienthello_www_google_com.bin",
            "stun.bin",
            "tls_clienthello_max_ru.bin",
        ]
        # Файлы которые нужны но могут отсутствовать — создаём пустыми автоматически
        optional_lists = [
            "list-general-user.txt",
            "list-exclude-user.txt",
            "ipset-exclude-user.txt",
        ]
        # Файлы которые обязаны существовать
        required_lists = [
            "list-general.txt",
            "list-google.txt",
            "list-exclude.txt",
            "ipset-exclude.txt",
        ]

        # Автосоздаём user-листы если их нет
        for f in optional_lists:
            path = self._lists(f)
            if not os.path.exists(path):
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    open(path, "w", encoding="utf-8").close()
                    self.log_cb(f"Создан пустой файл: lists/{f}", "info")
                except Exception as e:
                    self.log_cb(f"Не удалось создать lists/{f}: {e}", "warn")

        missing = []
        for f in required_bin:
            if not os.path.exists(self._bin(f)):
                missing.append(f"bin/{f}")
        for f in required_lists:
            if not os.path.exists(self._lists(f)):
                missing.append(f"lists/{f}")

        if missing:
            self.log_cb(
                "Не найдены файлы zapret:\n" + "\n".join(f"  • {m}" for m in missing) +
                "\nСкачай: https://github.com/Flowseal/zapret-discord-youtube",
                "err"
            )
            return False
        return True


    # ── Стратегии (для UI) ────────────────────────────────────────────────────

    def get_strategies(self) -> list:
        return [
            {
                "id":      "general_alt",
                "name":    "Discord + YouTube (ALT)",
                "desc":    "Рекомендуемая стратегия Flowseal",
                "icon":    "🚀",
                "targets": ["discord", "youtube"],
            },
            {
                "id":      "general",
                "name":    "Discord + YouTube (General)",
                "desc":    "Базовая стратегия Flowseal",
                "icon":    "🎮",
                "targets": ["discord", "youtube"],
            },
        ]

    # ── Построение команды ────────────────────────────────────────────────────

    def _build_cmd(self, strategy_id: str) -> list:
        winws = self._winws_path()
        B = self._bin
        L = self._lists

        if strategy_id == "general_alt":
            return [
                winws,
                "--wf-tcp=80,443,2053,2083,2087,2096,8443",
                "--wf-udp=443,19294-19344,50000-50100",
                "--filter-udp=443",
                f"--hostlist={L('list-general.txt')}",
                f"--hostlist={L('list-general-user.txt')}",
                f"--hostlist-exclude={L('list-exclude.txt')}",
                f"--hostlist-exclude={L('list-exclude-user.txt')}",
                f"--ipset-exclude={L('ipset-exclude.txt')}",
                f"--ipset-exclude={L('ipset-exclude-user.txt')}",
                "--dpi-desync=fake",
                "--dpi-desync-repeats=6",
                f"--dpi-desync-fake-quic={B('quic_initial_www_google_com.bin')}",
                "--new",
                "--filter-udp=19294-19344,50000-50100",
                "--filter-l7=discord,stun",
                "--dpi-desync=fake",
                "--dpi-desync-repeats=6",
                "--new",
                "--filter-tcp=2053,2083,2087,2096,8443",
                "--hostlist-domains=discord.media",
                "--dpi-desync=fake,fakedsplit",
                "--dpi-desync-repeats=6",
                "--dpi-desync-fooling=ts",
                "--dpi-desync-fakedsplit-pattern=0x00",
                f"--dpi-desync-fake-tls={B('tls_clienthello_www_google_com.bin')}",
                "--new",
                "--filter-tcp=443",
                f"--hostlist={L('list-google.txt')}",
                "--ip-id=zero",
                "--dpi-desync=fake,fakedsplit",
                "--dpi-desync-repeats=6",
                "--dpi-desync-fooling=ts",
                "--dpi-desync-fakedsplit-pattern=0x00",
                f"--dpi-desync-fake-tls={B('tls_clienthello_www_google_com.bin')}",
                "--new",
                "--filter-tcp=80,443",
                f"--hostlist={L('list-general.txt')}",
                f"--hostlist={L('list-general-user.txt')}",
                f"--hostlist-exclude={L('list-exclude.txt')}",
                f"--hostlist-exclude={L('list-exclude-user.txt')}",
                f"--ipset-exclude={L('ipset-exclude.txt')}",
                f"--ipset-exclude={L('ipset-exclude-user.txt')}",
                "--dpi-desync=fake,fakedsplit",
                "--dpi-desync-repeats=6",
                "--dpi-desync-fooling=ts",
                "--dpi-desync-fakedsplit-pattern=0x00",
                f"--dpi-desync-fake-tls={B('stun.bin')}",
                f"--dpi-desync-fake-tls={B('tls_clienthello_www_google_com.bin')}",
                f"--dpi-desync-fake-http={B('tls_clienthello_max_ru.bin')}",
                "--new",
                "--filter-udp=443",
                f"--ipset={L('ipset-all.txt')}",
                f"--hostlist-exclude={L('list-exclude.txt')}",
                f"--hostlist-exclude={L('list-exclude-user.txt')}",
                f"--ipset-exclude={L('ipset-exclude.txt')}",
                f"--ipset-exclude={L('ipset-exclude-user.txt')}",
                "--dpi-desync=fake",
                "--dpi-desync-repeats=6",
                f"--dpi-desync-fake-quic={B('quic_initial_www_google_com.bin')}",
                "--new",
                "--filter-tcp=80,443,8443",
                f"--ipset={L('ipset-all.txt')}",
                f"--hostlist-exclude={L('list-exclude.txt')}",
                f"--hostlist-exclude={L('list-exclude-user.txt')}",
                f"--ipset-exclude={L('ipset-exclude.txt')}",
                f"--ipset-exclude={L('ipset-exclude-user.txt')}",
                "--dpi-desync=fake,fakedsplit",
                "--dpi-desync-repeats=6",
                "--dpi-desync-fooling=ts",
                "--dpi-desync-fakedsplit-pattern=0x00",
                f"--dpi-desync-fake-tls={B('stun.bin')}",
                f"--dpi-desync-fake-tls={B('tls_clienthello_www_google_com.bin')}",
                f"--dpi-desync-fake-http={B('tls_clienthello_max_ru.bin')}",
            ]

        elif strategy_id == "general":
            return [
                winws,
                "--wf-tcp=80,443",
                "--wf-udp=443,50000-65535",
                "--filter-tcp=443",
                f"--hostlist={L('list-general.txt')}",
                f"--hostlist={L('list-google.txt')}",
                f"--hostlist-exclude={L('list-exclude.txt')}",
                "--dpi-desync=fake,fakedsplit",
                "--dpi-desync-repeats=6",
                "--dpi-desync-fooling=ts",
                f"--dpi-desync-fake-tls={B('tls_clienthello_www_google_com.bin')}",
                "--new",
                "--filter-udp=443",
                f"--hostlist={L('list-general.txt')}",
                f"--hostlist={L('list-google.txt')}",
                "--dpi-desync=fake",
                "--dpi-desync-repeats=6",
                f"--dpi-desync-fake-quic={B('quic_initial_www_google_com.bin')}",
                "--new",
                "--filter-udp=50000-65535",
                "--dpi-desync=fake",
                "--dpi-desync-repeats=6",
            ]

        return []

    # ── Kill stale ────────────────────────────────────────────────────────────

    def _kill_stale(self):
        if platform.system() != "Windows":
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "winws.exe", "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            time.sleep(0.4)
        except Exception:
            pass

    def _enable_tcp_timestamps(self):
        # Zapret использует --dpi-desync-fooling=ts, которому нужны TCP timestamps
        if platform.system() != "Windows":
            return
        try:
            subprocess.run(
                ["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self, strategy_id: str = "general_alt") -> bool:
        if self.running:
            self.stop()
        self._kill_stale()
        self._enable_tcp_timestamps()

        if not os.path.exists(self._winws_path()):
            self.log_cb(
                "winws.exe не найден!\n"
                "Скачай: https://github.com/Flowseal/zapret-discord-youtube\n"
                "Положи bin/ и lists/ в папку проекта.",
                "err",
            )
            return False

        if not self._check_files():
            return False

        cmd = self._build_cmd(strategy_id)
        if not cmd:
            self.log_cb(f"Неизвестная стратегия: {strategy_id}", "err")
            return False

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(self._winws_path()),
                creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows" else 0,
            )
            self.running   = True
            self._strategy = strategy_id

            time.sleep(0.8)
            if self.process.poll() is not None:
                out = self.process.stdout.read()
                self.log_cb("winws.exe упал сразу после запуска!", "err")
                for line in out.splitlines():
                    if line.strip():
                        self.log_cb(f"  {line}", "err")
                self._cleanup()
                self.running = False
                return False

            threading.Thread(target=self._read_output, daemon=True).start()
            strategy_name = next(
                (s["name"] for s in self.get_strategies() if s["id"] == strategy_id),
                strategy_id
            )
            self.log_cb(f"zapret запущен: {strategy_name} (PID {self.process.pid})", "ok")
            return True

        except PermissionError:
            self.log_cb(
                "Нет прав администратора!\n"
                "WinDivert требует запуска от администратора.",
                "err",
            )
            self._cleanup()
            return False
        except Exception as e:
            self.log_cb(f"Ошибка запуска winws.exe: {e}", "err")
            self._cleanup()
            return False

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.running   = False
        self._strategy = None
        self._cleanup()
        time.sleep(0.3)
        self.log_cb("zapret остановлен", "info")

    def _cleanup(self):
        self.process = None

    # ── Output reader ─────────────────────────────────────────────────────────

    def _read_output(self):
        try:
            for line in self.process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                low = line.lower()
                if any(w in low for w in ["error", "failed", "fatal", "cannot", "could not"]):
                    tag = "err"
                elif "warn" in low:
                    tag = "warn"
                elif any(w in low for w in ["start", "listen", "init", "ok", "loaded", "capture"]):
                    tag = "ok"
                else:
                    tag = "log"
                self.log_cb(f"[zapret] {line}", tag)
        except Exception:
            pass
        self.running = False
        self.log_cb("zapret процесс завершён", "info")