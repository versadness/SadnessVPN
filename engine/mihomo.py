"""engine/mihomo.py — единственное сетевое ядро VPN: запуск и владение mihomo.exe.

Раньше здесь жил только тонкий слой поверх SingBoxManager, а жизненный цикл
процесса принадлежал sing-box. Ядро sing-box удалено из проекта целиком, и весь
жизненный цикл переехал сюда. Правила владения процессом не изменились:
завершается только собственный процесс, чужой mihomo не трогается, занятый порт —
это отказ запуска, а не повод кого-то убить.

Zapret/winws остаётся отдельным компонентом обхода DPI и здесь не участвует.
"""
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from engine import owned_process
from engine.connection_health import DialHealth
from engine.core_logs import core_log_tag
from engine.paths import bin_path, data_dir

MIHOMO_VERSION = "1.19.30"

# Подсети, из которых выбирается адрес TUN, когда стандартная занята другим
# сетевым адаптером. Без этого Wintun падает уже после создания интерфейса.
_TUN_SUBNET_OCTETS = (19, 29, 31, 22, 18, 20)


def _core_errors(output: str) -> str:
    """Только строки ошибок ядра, без меток времени и путей временных файлов.

    Полный журнал запуска пользователю не нужен и содержит имя временного
    файла конфигурации: в сообщение уходит суть, а не всё подряд.
    """
    def collect(levels):
        found = []
        for line in (output or "").splitlines():
            if not any(level in line for level in levels):
                continue
            _, separator, message = line.partition("msg=")
            message = (message if separator else line).strip().strip('"')
            if message and message not in found:
                found.append(message)
        return found

    # Сначала настоящие ошибки; предупреждения годятся, когда ядро запустилось,
    # но соединение не состоялось — иначе причина осталась бы без объяснения.
    lines = collect(("level=error", "level=fatal")) or collect(("level=warning",))
    if not lines:
        tail = [line for line in (output or "").strip().splitlines() if line.strip()]
        return tail[-1][:400] if tail else "причина не сообщена"
    return " · ".join(lines)[:1000]


class MihomoManager:
    """Жизненный цикл mihomo.exe. Ядро одно, выбора ядра больше нет."""

    name = "Mihomo"

    def __init__(self, log_callback=None, exit_callback=None):
        self.process = None
        self.running = False
        self.exit_cb = exit_callback or (lambda return_code: None)
        self._config_file = None
        self._stop_requested = None
        self._api_port = 9090
        self._tun_ready = threading.Event()
        self.health = DialHealth()
        callback = log_callback or (lambda message, tag: None)

        def log(message, tag):
            if "Tun adapter listening at:" in message:
                self._tun_ready.set()
            self.health.feed(message)
            callback(message, tag)

        self.log_cb = log

    # -- Пути и команда -------------------------------------------------------

    def _core_path(self):
        return bin_path("mihomo.exe" if platform.system() == "Windows" else "mihomo")

    def _runtime_dir(self):
        runtime = os.path.join(data_dir(), "runtime", "mihomo")
        os.makedirs(runtime, exist_ok=True)
        for name in ("geosite.dat", "geoip.dat"):
            source = bin_path(name)
            target = os.path.join(runtime, name)
            if os.path.isfile(source) and (
                not os.path.isfile(target)
                or os.stat(source).st_mtime_ns != os.stat(target).st_mtime_ns
            ):
                shutil.copy2(source, target)
        return runtime

    def _command(self, executable, path):
        return [executable, "-d", self._runtime_dir(), "-f", path]

    @staticmethod
    def _has_tun(config):
        return bool(config.get("tun", {}).get("enable"))

    # -- Порты ----------------------------------------------------------------

    def _port_free(self, port: int) -> bool:
        """True, если порт свободен (никто не слушает)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) != 0

    def _wait_port_free(self, port: int, timeout: float = 4.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._port_free(port):
                return True
            time.sleep(0.2)
        return False

    @staticmethod
    def _listener_ports(config: dict) -> list[tuple[str, int]]:
        """Каждый TCP-слушатель, который создаст mihomo.

        Проверять только Clash API поздно: ядро успевает поднять TUN и упасть
        на SOCKS/HTTP-порту, после чего Wintun рвётся под нагрузкой.
        """
        listeners = []
        controller = config.get("external-controller", "")
        if isinstance(controller, str):
            _host, separator, raw_port = controller.rpartition(":")
            if separator and raw_port.isdigit():
                listeners.append(("Clash API", int(raw_port)))
        for field in ("socks-port", "port", "mixed-port"):
            port = config.get(field)
            if type(port) is int and 1 <= port <= 65535:
                listeners.append((field, port))
        return listeners

    @staticmethod
    def _port_owner(port: int) -> str:
        try:
            import psutil
            for connection in psutil.net_connections(kind="tcp"):
                if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                    continue
                if connection.laddr.port == port and connection.pid:
                    try:
                        return psutil.Process(connection.pid).name()
                    except (psutil.Error, OSError):
                        return f"PID {connection.pid}"
        except (ImportError, OSError):
            pass
        return "другим приложением"

    def is_alive(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    # -- Подсеть TUN ----------------------------------------------------------

    @staticmethod
    def _assigned_ipv4_networks():
        """Сети IPv4, уже привязанные к интерфейсам Windows."""
        networks = []
        try:
            import psutil
            for addresses in psutil.net_if_addrs().values():
                for item in addresses:
                    if item.family != socket.AF_INET or not item.address:
                        continue
                    netmask = item.netmask or "255.255.255.255"
                    try:
                        networks.append(
                            ipaddress.ip_network(f"{item.address}/{netmask}", strict=False)
                        )
                    except ValueError:
                        continue
        except (ImportError, OSError):
            pass
        return networks

    @staticmethod
    def _replacement_tun_address(occupied_networks):
        occupied = list(occupied_networks)
        for second_octet in _TUN_SUBNET_OCTETS:
            for third_octet in range(256):
                candidate = ipaddress.ip_interface(f"172.{second_octet}.{third_octet}.1/30")
                if not any(candidate.network.overlaps(network) for network in occupied):
                    return str(candidate)
        return None

    def _prepare_tun_addresses(self, config: dict) -> bool:
        """Mihomo берёт адрес TUN из dns.fake-ip-range, а не из tun.inet4-address."""
        dns = config.setdefault("dns", {})
        occupied = self._assigned_ipv4_networks()
        if dns.get("enhanced-mode") == "fake-ip":
            for cidr in ("198.18.0.1/16", "198.19.0.1/16", "172.29.0.1/16", "172.30.0.1/16"):
                if not any(ipaddress.ip_interface(cidr).network.overlaps(net) for net in occupied):
                    dns["fake-ip-range"] = cidr
                    return True
            self.log_cb("Mihomo: не найдена свободная подсеть FakeDNS", "err")
            return False
        raw_address = dns.get("fake-ip-range", "172.19.0.1/30")
        try:
            interface = ipaddress.ip_interface(raw_address)
        except (TypeError, ValueError):
            self.log_cb("Mihomo: некорректная внутренняя подсеть TUN", "err")
            return False
        if any(interface.network.overlaps(network) for network in occupied):
            replacement = self._replacement_tun_address(occupied)
            if replacement is None:
                self.log_cb(
                    "Mihomo не запущен: Windows не оставила свободную "
                    "внутреннюю подсеть для TUN.",
                    "err",
                )
                return False
            self.log_cb(
                f"Подсеть TUN {raw_address} уже используется другим сетевым "
                f"интерфейсом; выбрана свободная {replacement}.",
                "warn",
            )
            dns["fake-ip-range"] = replacement
        return True

    # -- Проверка конфигурации средствами ядра --------------------------------

    def _check_config(self, executable, path) -> bool:
        try:
            result = subprocess.run(
                self._command(executable, path) + ["-t"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            self.log_cb("Mihomo: проверка конфигурации не завершилась за 15с", "err")
            return False
        if result.returncode:
            self.log_cb("Ошибка конфигурации Mihomo: " + _core_errors(result.stdout), "err")
            return False
        return True

    def validate(self, config: dict):
        """Проверить конфигурацию ядром, ничего не запуская.

        Возвращает (успех, сообщение). Используется транзакционным применением
        настроек маршрутизации: конфигурация отвергается до того, как поднят TUN.
        """
        executable = self._core_path()
        if not os.path.exists(executable):
            return False, "mihomo.exe не найден в папке bin/"
        messages = []
        original = self.log_cb
        self.log_cb = lambda message, tag: messages.append(message)
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="mihomo_check_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle, indent=2, ensure_ascii=False)
            ok = self._check_config(executable, path)
        finally:
            self.log_cb = original
            try:
                os.remove(path)
            except OSError:
                pass
        return ok, "" if ok else " ".join(messages)

    # -- Резолв адресов серверов до поднятия TUN ------------------------------

    def _resolve_endpoints(self, config: dict) -> bool:
        """Разрешить имена узлов до включения TUN.

        Иначе первый же DNS-запрос уходит в только что созданный туннель,
        который ещё не знает адрес собственного сервера, — классическая петля.
        """
        hosts = config.setdefault("hosts", {})
        for proxy in config.get("proxies", []):
            hostname = proxy.get("server")
            if not hostname:
                continue
            try:
                ipaddress.ip_address(hostname)
                continue
            except ValueError:
                pass
            try:
                addresses = socket.getaddrinfo(
                    hostname, proxy.get("port", 443),
                    socket.AF_UNSPEC if (config.get("dns") or {}).get("ipv6") else socket.AF_INET,
                    socket.SOCK_STREAM,
                )
                hosts[hostname] = list(dict.fromkeys(item[4][0] for item in addresses))
            except OSError:
                self.log_cb(
                    "Mihomo: не удалось определить адрес VPN-сервера до запуска TUN. "
                    "Проверьте DNS и доступность сети.",
                    "err",
                )
                return False
        return True

    # -- Start ----------------------------------------------------------------

    def start(self, config: dict) -> bool:
        self._tun_ready.clear()
        self.health.reset()
        if self.process:
            if self.process.poll() is None:
                self.stop()
            else:
                self._cleanup()

        executable = self._core_path()
        if not os.path.exists(executable):
            self.log_cb(
                "mihomo.exe не найден!\n"
                "Скачай: https://github.com/MetaCubeX/mihomo/releases\n"
                "Файл: mihomo.exe в папку bin/",
                "err",
            )
            return False

        if not self._resolve_endpoints(config):
            return False

        has_tun = self._has_tun(config)
        if has_tun:
            wintun = bin_path("wintun.dll")
            if not os.path.exists(wintun):
                self.log_cb(
                    "wintun.dll не найден!\n"
                    "Скачай: https://wintun.net -> wintun.dll в папку bin/",
                    "err",
                )
                return False
            if not self._prepare_tun_addresses(config):
                return False

        listeners = list(self._listener_ports(config))
        self._api_port = next(
            (port for label, port in listeners if label == "Clash API"), self._api_port
        )
        conflicts, seen = [], set()
        for label, port in listeners:
            if port in seen:
                conflicts.append(f"{label}: {port} дублируется в конфигурации")
            elif not self._port_free(port):
                conflicts.append(f"{label}: порт {port} занят ({self._port_owner(port)})")
            seen.add(port)
        if conflicts:
            self.log_cb(
                "Mihomo не запущен: " + "; ".join(conflicts) + ". "
                "TUN не создавался, чужие процессы не завершались.",
                "err",
            )
            return False

        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="mihomo_cfg_")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # JSON — подмножество YAML 1.2, mihomo читает его своим парсером.
            json.dump(config, handle, indent=2, ensure_ascii=False)
        self._config_file = path

        try:
            if not self._check_config(executable, path):
                self._cleanup()
                return False
            process = subprocess.Popen(
                self._command(executable, path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=os.path.dirname(executable),  # wintun.dll должен быть рядом
                creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows" else 0,
            )
            stop_requested = threading.Event()
            self.process = process
            self._stop_requested = stop_requested
            self.running = True
            owned_process.remember("mihomo", process.pid)

            time.sleep(0.8)
            if process.poll() is not None:
                out = process.stdout.read()
                self.log_cb("mihomo.exe упал сразу после запуска!", "err")
                for line in (out or "").splitlines():
                    if line.strip():
                        self.log_cb(f"  {line}", "err")
                self._cleanup(process)
                self.running = False
                return False

            threading.Thread(
                target=self._read_output, args=(process, stop_requested), daemon=True
            ).start()
            self.log_cb(f"Mihomo запущен (PID {process.pid})", "ok")

            if has_tun and (not self._tun_ready.wait(5) or not self.is_alive()):
                self.log_cb("Mihomo: запуск TUN-адаптера не подтверждён", "err")
                self.stop()
                return False
            return True

        except PermissionError:
            self.log_cb(
                "Нет прав администратора!\n"
                "TUN-режим требует запуска от администратора.\n"
                "Запусти SadnessVPN.exe от имени администратора.",
                "err",
            )
            self._cleanup()
            self.running = False
            return False
        except Exception as exc:
            self.log_cb(f"Ошибка запуска Mihomo: {exc}", "err")
            self._cleanup()
            self.running = False
            return False

    # -- Stop -----------------------------------------------------------------

    def stop(self):
        process = self.process
        stop_requested = self._stop_requested
        if stop_requested:
            stop_requested.set()
        try:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        except (OSError, ProcessLookupError) as exc:
            self.log_cb(f"Не удалось остановить Mihomo: {exc}", "warn")
        finally:
            if process is None or self.process is process:
                self.running = False
                self._cleanup(process)
        self._wait_port_free(self._api_port, timeout=3.0)
        self.log_cb("Mihomo остановлен", "info")

    def _cleanup(self, expected_process=None):
        if expected_process is not None and self.process is not expected_process:
            return False
        if self.process is not None:
            owned_process.forget("mihomo")
        if self._config_file and os.path.exists(self._config_file):
            try:
                os.remove(self._config_file)
            except OSError:
                pass
            self._config_file = None
        self.process = None
        self._stop_requested = None
        return True

    # -- Output reader --------------------------------------------------------

    def _read_output(self, process, stop_requested):
        try:
            for line in process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self.log_cb(line, core_log_tag(line))
        except Exception:
            pass

        if self.process is not process:
            return

        unexpected = not stop_requested.is_set()
        return_code = process.poll()
        self.running = False
        self._cleanup(process)

        if unexpected:
            self.log_cb(f"Mihomo неожиданно завершился (код {return_code})", "err")
            try:
                self.exit_cb(return_code)
            except Exception as exc:
                self.log_cb(f"Ошибка обработки остановки Mihomo: {exc}", "err")
