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
import ipaddress
from engine.paths import bin_path
from engine.core_logs import core_log_tag

SINGBOX_VERSION = "1.10.7"


class SingBoxManager:
    def __init__(self, log_callback=None, exit_callback=None):
        self.process         = None
        self.running         = False
        self.log_cb          = log_callback or (lambda msg, tag: None)
        self.exit_cb         = exit_callback or (lambda return_code: None)
        self._config_file    = None
        self._stop_requested = None
        self._api_port       = 9090

    def _singbox_path(self):
        return bin_path("sing-box.exe" if platform.system() == "Windows" else "sing-box")

    def _command(self, executable, path):
        return [executable, "run", "-c", path]

    def _has_tun(self, config):
        return any(ib.get("type") == "tun" for ib in config.get("inbounds", []))

    def _check_config(self, executable, path):
        return True

    # ── Порты ──────────────────────────────────────────────────────────────────

    def _port_free(self, port: int) -> bool:
        """True, если порт свободен (никто не слушает)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) != 0

    def _wait_port_free(self, port: int, timeout: float = 4.0) -> bool:
        """Ждём, пока порт освободится после остановки нашего процесса."""
        end = time.time() + timeout
        while time.time() < end:
            if self._port_free(port):
                return True
            time.sleep(0.2)
        return False

    @staticmethod
    def _listener_ports(config: dict) -> list[tuple[str, int]]:
        """Return every TCP listener that sing-box will create.

        Checking only the Clash API is too late: sing-box can create the TUN and
        then fail on a SOCKS/HTTP port, which makes Wintun tear down under load.
        """
        listeners = []
        controller = config.get("experimental", {}).get("clash_api", {}).get("external_controller", "")
        if isinstance(controller, str):
            _host, separator, raw_port = controller.rpartition(":")
            if separator and raw_port.isdigit():
                listeners.append(("Clash API", int(raw_port)))
        for inbound in config.get("inbounds", []):
            if not isinstance(inbound, dict):
                continue
            port = inbound.get("listen_port")
            if type(port) is int and 1 <= port <= 65535:
                label = str(inbound.get("tag") or inbound.get("type") or "inbound")
                listeners.append((label, port))
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

    @staticmethod
    def _assigned_ipv4_networks():
        """Return IPv4 networks already attached to Windows interfaces."""
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
    def _replacement_tun_address(occupied_networks) -> str | None:
        """Pick a small private subnet that does not overlap another adapter."""
        occupied = list(occupied_networks)
        for second_octet in (19, 29, 31, 22, 18, 20):
            for third_octet in range(256):
                candidate = ipaddress.ip_interface(
                    f"172.{second_octet}.{third_octet}.1/30"
                )
                if not any(candidate.network.overlaps(network) for network in occupied):
                    return str(candidate)
        return None

    def _prepare_tun_addresses(self, config: dict) -> bool:
        """Avoid a Wintun crash/failure when another VPN owns our TUN subnet."""
        occupied = self._assigned_ipv4_networks()
        for inbound in config.get("inbounds", []):
            if not isinstance(inbound, dict) or inbound.get("type") != "tun":
                continue
            raw_addresses = inbound.get("address", [])
            scalar = isinstance(raw_addresses, str)
            addresses = [raw_addresses] if scalar else list(raw_addresses or [])
            for index, raw_address in enumerate(addresses):
                try:
                    interface = ipaddress.ip_interface(raw_address)
                except (TypeError, ValueError):
                    continue
                if interface.version != 4:
                    continue
                conflict = any(
                    interface.network.overlaps(network) for network in occupied
                )
                if conflict:
                    replacement = self._replacement_tun_address(occupied)
                    if replacement is None:
                        self.log_cb(
                            "sing-box не запущен: Windows не оставила свободную "
                            "внутреннюю подсеть для TUN.",
                            "err",
                        )
                        return False
                    addresses[index] = replacement
                    self.log_cb(
                        f"Подсеть TUN {raw_address} уже используется другим "
                        f"сетевым интерфейсом; выбрана свободная {replacement}.",
                        "warn",
                    )
                    interface = ipaddress.ip_interface(replacement)
                occupied.append(interface.network)
            inbound["address"] = addresses[0] if scalar else addresses
        return True

    def start(self, config: dict) -> bool:
        if self.process:
            if self.process.poll() is None:
                self.stop()
            else:
                self._cleanup()

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
        has_tun = self._has_tun(config)
        if has_tun:
            wintun = bin_path("wintun.dll")
            if not os.path.exists(wintun):
                self.log_cb(
                    "wintun.dll не найден!\n"
                    "Скачай: https://wintun.net → wintun.dll в папку bin/",
                    "err"
                )
                return False
            if not self._prepare_tun_addresses(config):
                return False

        listeners = list(self._listener_ports(config))
        # Порт Clash API выбирает вызывающая сторона; stop() должен дождаться
        # освобождения именно его, а не прежнего жёстко зашитого 9090.
        self._api_port = next((port for label, port in listeners if label == "Clash API"), self._api_port)
        conflicts = []
        seen = set()
        for label, port in listeners:
            if port in seen:
                conflicts.append(f"{label}: {port} дублируется в конфигурации")
            elif not self._port_free(port):
                conflicts.append(f"{label}: порт {port} занят ({self._port_owner(port)})")
            seen.add(port)
        if conflicts:
            self.log_cb(
                "sing-box не запущен: " + "; ".join(conflicts) + ". "
                "TUN не создавался, чужие процессы не завершались.",
                "err",
            )
            return False

        fd, path = tempfile.mkstemp(suffix=".json", prefix="singbox_cfg_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        self._config_file = path

        try:
            if not self._check_config(singbox, path):
                self._cleanup()
                return False
            process = subprocess.Popen(
                self._command(singbox, path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=os.path.dirname(singbox),  # wintun.dll должен быть рядом
                creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows" else 0
            )
            stop_requested = threading.Event()
            self.process = process
            self._stop_requested = stop_requested
            self.running = True

            # ── Диагностика: ловим мгновенное падение ──
            time.sleep(0.8)
            if process.poll() is not None:
                out = process.stdout.read()
                self.log_cb("sing-box упал сразу после запуска!", "err")
                for line in out.splitlines():
                    if line.strip():
                        self.log_cb(f"  {line}", "err")
                self._cleanup(process)
                self.running = False
                return False

            threading.Thread(
                target=self._read_output,
                args=(process, stop_requested),
                daemon=True,
            ).start()
            self.log_cb(f"sing-box запущен (PID {process.pid})", "ok")
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
            self.log_cb(f"Не удалось остановить sing-box: {exc}", "warn")
        finally:
            if process is None or self.process is process:
                self.running = False
                self._cleanup(process)
        # Убеждаемся, что порт освобождён для следующего подключения
        self._wait_port_free(self._api_port, timeout=3.0)
        self.log_cb("sing-box остановлен", "info")

    def _cleanup(self, expected_process=None):
        if expected_process is not None and self.process is not expected_process:
            return False
        if self._config_file and os.path.exists(self._config_file):
            try:
                os.remove(self._config_file)
            except Exception:
                pass
            self._config_file = None
        self.process = None
        self._stop_requested = None
        return True

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
            self.log_cb(
                f"sing-box неожиданно завершился (код {return_code})",
                "err",
            )
            try:
                self.exit_cb(return_code)
            except Exception as exc:
                self.log_cb(f"Ошибка обработки остановки sing-box: {exc}", "err")
