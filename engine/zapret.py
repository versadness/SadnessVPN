"""
engine/zapret.py — управление zapret (winws.exe + WinDivert)
Стратегии синхронизированы с актуальными профилями Flowseal main.
"""
import subprocess
import threading
import os
import platform
import time

from engine import game_filter, owned_process, zapret_exclusions
from engine.flowseal_profiles import FLOWSEAL_COMMIT, FLOWSEAL_PROFILES, PROFILE_BY_ID
from engine.game_filter import GameFilterError
from engine.paths import bin_path


PROFILE_ALIASES = {
    "general": "flowseal_general",
    "general_alt": "flowseal_alt",
    "flowseal_fake_tls": "flowseal_fake_tls_auto_alt3",
}


class ZapretManager:
    def __init__(self, log_callback=None, exit_callback=None):
        self.process   = None
        self.running   = False
        self.log_cb    = log_callback or (lambda msg, tag: None)
        self.exit_cb   = exit_callback or (lambda return_code: None)
        self._strategy = None
        self._game_filter = game_filter.summary(None)
        self._game_filter_config = None
        # Адреса VPN-серверов, которые работающий winws прочитал при старте.
        self.excluded_addresses: list[str] = []
        self._restore_timestamps = False
        self._stop_requested = None

    # ── Пути ──────────────────────────────────────────────────────────────────

    def _winws_path(self):
        return bin_path("winws.exe")

    def _foreign_winws_running(self) -> bool:
        """Check for an existing winws process without modifying it."""
        if platform.system() != "Windows":
            return False
        try:
            import psutil

            return any(
                (process.info.get("name") or "").lower() == "winws.exe"
                for process in psutil.process_iter(["name"])
            )
        except ImportError:
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return '"winws.exe"' in result.stdout.lower()
            except Exception:
                return False
        except Exception:
            return False

    def _bin(self, filename: str) -> str:
        return bin_path(filename)

    def _lists(self, filename: str) -> str:
        bin_dir = os.path.dirname(self._winws_path())
        candidates = [
            os.path.join(bin_dir, "lists"),
            os.path.join(os.path.dirname(bin_dir), "lists"),
            bin_dir,  # Backward compatibility with older SadnessVPN layouts.
        ]
        for lists_dir in candidates:
            path = os.path.join(lists_dir, filename)
            if os.path.isfile(path):
                return path
        return os.path.join(candidates[0], filename)

    @staticmethod
    def canonical_strategy_id(strategy_id: str) -> str:
        return PROFILE_ALIASES.get(strategy_id, strategy_id)

    def _profile(self, strategy_id: str):
        return PROFILE_BY_ID.get(self.canonical_strategy_id(strategy_id))

    # ── Проверка файлов ───────────────────────────────────────────────────────

    def _check_files(self, strategy_id: str) -> bool:
        profile = self._profile(strategy_id)
        if not profile:
            self.log_cb(f"Неизвестная стратегия: {strategy_id}", "err")
            return False

        required_bin = {"winws.exe", "WinDivert.dll", "WinDivert64.sys"}
        required_lists = set()
        for arg in profile["args"]:
            if "%BIN%" in arg:
                required_bin.add(arg.split("%BIN%", 1)[1])
            if "%LISTS%" in arg:
                required_lists.add(arg.split("%LISTS%", 1)[1])

        # Файлы которые нужны но могут отсутствовать — создаём пустыми автоматически
        optional_lists = {
            "list-general-user.txt",
            "list-exclude-user.txt",
            "ipset-exclude-user.txt",
        }

        # Автосоздаём user-листы если их нет
        for f in sorted(required_lists & optional_lists):
            path = self._lists(f)
            if not os.path.exists(path):
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    open(path, "w", encoding="utf-8").close()
                    self.log_cb(f"Создан пустой файл: lists/{f}", "info")
                except Exception as e:
                    self.log_cb(f"Не удалось создать lists/{f}: {e}", "warn")

        missing = []
        for f in sorted(required_bin):
            if not os.path.exists(self._bin(f)):
                missing.append(f"bin/{f}")
        for f in sorted(required_lists - optional_lists):
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
        public_fields = (
            "id", "name", "category", "desc", "icon", "tags", "experimental", "source_file"
        )
        return [
            {
                **{field: profile[field] for field in public_fields},
                "upstream_commit": FLOWSEAL_COMMIT,
            }
            for profile in FLOWSEAL_PROFILES
        ]

    # ── Построение команды ────────────────────────────────────────────────────

    @staticmethod
    def _apply_game_filter(args, config) -> list:
        """Подставить проверенные игровые диапазоны вместо плейсхолдеров.

        Секции профиля разделены ``--new``. Игровой считается та, чей
        ``--filter-tcp`` / ``--filter-udp`` пришёл из плейсхолдера: только в
        ней режим IPSet «все адреса» снимает ограничение по ipset-all.
        Исключения (``--ipset-exclude``) остаются всегда — они защищают
        локальные и служебные адреса.
        """
        ports = game_filter.substitutions(config)
        ipset_all = game_filter.normalize(config)["ipset"] == "all"
        enabled = game_filter.enabled(config)

        sections, current = [], []
        for arg in args:
            if arg == "--new":
                sections.append(current)
                current = []
            else:
                current.append(arg)
        sections.append(current)

        result = []
        for index, section in enumerate(sections):
            is_game = any(
                arg.startswith(("--filter-tcp=", "--filter-udp="))
                and any(token in arg for token in ports)
                for arg in section
            )
            rendered = []
            for arg in section:
                for placeholder, value in ports.items():
                    arg = arg.replace(placeholder, value)
                if is_game and enabled and ipset_all and arg.startswith("--ipset="):
                    continue
                rendered.append(arg)
            if index:
                result.append("--new")
            result.extend(rendered)
        return result

    def _build_cmd(self, strategy_id: str, game_filter_config=None) -> list:
        profile = self._profile(strategy_id)
        if not profile:
            return []
        bin_prefix = os.path.dirname(self._winws_path()) + os.sep
        lists_prefix = os.path.dirname(self._lists("list-general.txt")) + os.sep
        args = self._apply_game_filter(profile["args"], game_filter_config)
        args = [
            arg.replace("%BIN%", bin_prefix).replace("%LISTS%", lists_prefix)
            for arg in args
        ]
        return [self._winws_path(), *args]

    @staticmethod
    def _netsh(*arguments):
        return subprocess.run(
            ["netsh", "interface", "tcp", *arguments],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _tcp_timestamps_state(self):
        """'enabled' / 'disabled' или None, если состояние определить не удалось."""
        try:
            result = self._netsh("show", "global")
        except Exception:
            return None
        text = result.stdout.decode("utf-8", errors="replace").lower()
        for line in text.splitlines():
            if "1323" in line and ":" in line:
                value = line.rsplit(":", 1)[1].strip()
                if value in ("enabled", "disabled"):
                    return value
        return None

    def _enable_tcp_timestamps(self):
        """Включить TCP timestamps для --dpi-desync-fooling=ts и запомнить прежнее значение.

        Это глобальная настройка Windows: она возвращается при остановке обхода,
        если приложение само её меняло.
        """
        if platform.system() != "Windows":
            return
        previous = self._tcp_timestamps_state()
        if previous == "enabled":
            return
        try:
            self._netsh("set", "global", "timestamps=enabled")
        except Exception:
            return
        if previous == "disabled":
            self._restore_timestamps = True
            self.log_cb("Zapret: включены TCP timestamps Windows (нужны стратегиям с fooling=ts); "
                        "прежнее значение вернётся при остановке обхода", "info")

    def _restore_tcp_timestamps(self):
        if not self._restore_timestamps:
            return
        self._restore_timestamps = False
        try:
            self._netsh("set", "global", "timestamps=disabled")
            self.log_cb("Zapret: TCP timestamps Windows возвращены в прежнее состояние", "info")
        except Exception:
            self.log_cb("Zapret: не удалось вернуть TCP timestamps в прежнее состояние", "warn")

    # ── Start ─────────────────────────────────────────────────────────────────

    def protect_vpn_endpoints(self, servers) -> list:
        """Исключить адреса VPN-серверов из перехвата WinDivert.

        Без этого winws десинхронизирует внешнее соединение с VPN-сервером —
        оно идёт по тем же портам, что и обычный трафик, — и рвёт туннель.
        """
        path = self._lists("ipset-exclude-user.txt")
        addresses = zapret_exclusions.write(path, servers)
        if addresses:
            self.log_cb(
                f"Zapret: адреса VPN-серверов исключены из перехвата ({len(addresses)})",
                "info",
            )
        return addresses

    def start(self, strategy_id: str = "flowseal_general", game_filter_config=None,
              vpn_servers=None) -> bool:
        # Проверяем настройку до всего остального: winws не должен стартовать
        # с наполовину собранной конфигурацией.
        try:
            game_filter_config = game_filter.normalize(game_filter_config)
        except GameFilterError as exc:
            self.log_cb(f"Игровой фильтр Zapret: {exc}", "err")
            return False

        if self.process:
            if self.process.poll() is None:
                self.stop()
            else:
                self._cleanup()

        if self._foreign_winws_running():
            self.log_cb(
                "winws.exe уже запущен другим приложением. "
                "SadnessVPN не будет завершать или заменять чужой процесс.",
                "err",
            )
            return False

        # Порядок важен: исключения должны лежать на диске до того, как
        # winws прочитает их при старте.
        excluded = self.protect_vpn_endpoints(vpn_servers)

        if not os.path.exists(self._winws_path()):
            self.log_cb(
                "winws.exe не найден!\n"
                "Скачай: https://github.com/Flowseal/zapret-discord-youtube\n"
                "Положи bin/ и lists/ в папку проекта.",
                "err",
            )
            return False

        canonical_strategy = self.canonical_strategy_id(strategy_id)
        if not self._check_files(canonical_strategy):
            return False

        cmd = self._build_cmd(canonical_strategy, game_filter_config)
        if not cmd:
            self.log_cb(f"Неизвестная стратегия: {strategy_id}", "err")
            return False

        self._enable_tcp_timestamps()
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(self._winws_path()),
                creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows" else 0,
            )
            stop_requested = threading.Event()
            self.process = process
            self._stop_requested = stop_requested
            self.running   = True
            self._strategy = canonical_strategy
            self._game_filter_config = game_filter_config
            self.excluded_addresses = list(excluded)
            owned_process.remember("winws", process.pid)

            time.sleep(0.8)
            if process.poll() is not None:
                out = process.stdout.read()
                self.log_cb("winws.exe упал сразу после запуска!", "err")
                for line in out.splitlines():
                    if line.strip():
                        self.log_cb(f"  {line}", "err")
                self._cleanup(process)
                self.running = False
                self._restore_tcp_timestamps()
                return False

            threading.Thread(
                target=self._read_output,
                args=(process, stop_requested),
                daemon=True,
            ).start()
            strategy_name = next(
                (s["name"] for s in self.get_strategies() if s["id"] == canonical_strategy),
                canonical_strategy
            )
            self.log_cb(f"zapret запущен: {strategy_name} (PID {self.process.pid})", "ok")
            effective = game_filter.summary(game_filter_config, strategy_name)
            self.log_cb(
                "Игровой фильтр: " + effective["mode_label"]
                + (f" · TCP {effective['tcp_label']} · UDP {effective['udp_label']}"
                   f" · IPSet: {effective['ipset_label']}" if effective["enabled"] else ""),
                "info",
            )
            self._game_filter = effective
            return True

        except PermissionError:
            self.log_cb(
                "Нет прав администратора!\n"
                "WinDivert требует запуска от администратора.",
                "err",
            )
            self._cleanup()
            self._restore_tcp_timestamps()
            return False
        except Exception as e:
            self.log_cb(f"Ошибка запуска winws.exe: {e}", "err")
            self._cleanup()
            self._restore_tcp_timestamps()
            return False

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self):
        process = self.process
        stop_requested = self._stop_requested
        if stop_requested:
            stop_requested.set()
        try:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        except (OSError, ProcessLookupError) as exc:
            self.log_cb(f"Не удалось остановить zapret: {exc}", "warn")
        finally:
            if process is None or self.process is process:
                self.running   = False
                self._strategy = None
                self._cleanup(process)
        self._restore_tcp_timestamps()
        time.sleep(0.3)
        self.log_cb("zapret остановлен", "info")

    def _cleanup(self, expected_process=None):
        if expected_process is not None and self.process is not expected_process:
            return False
        if self.process is not None:
            owned_process.forget("winws")
        self.process = None
        self._stop_requested = None
        self.excluded_addresses = []
        return True

    # ── Output reader ─────────────────────────────────────────────────────────

    def _read_output(self, process, stop_requested):
        try:
            for line in process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                # У winws нет уровней в выводе: слово «error» внутри строки — не
                # повод для всплывающего уведомления на каждую строку. Такие
                # строки остаются предупреждениями журнала, а настоящий сбой
                # (процесс завершился) сообщается ниже одной ошибкой.
                low = line.lower()
                if any(w in low for w in ["error", "failed", "fatal", "cannot", "could not", "warn"]):
                    tag = "warn"
                else:
                    tag = "log"
                self.log_cb(f"[zapret] {line}", tag)
        except Exception:
            pass

        if self.process is not process:
            return

        unexpected = not stop_requested.is_set()
        return_code = process.poll()
        self.running = False
        self._strategy = None
        self._cleanup(process)
        if unexpected:
            self._restore_tcp_timestamps()
            self.log_cb("Процесс zapret неожиданно завершился", "err")
            try:
                self.exit_cb(return_code)
            except Exception as exc:
                self.log_cb(f"Ошибка обработки остановки zapret: {exc}", "err")
        self.log_cb("zapret процесс завершён", "info")
