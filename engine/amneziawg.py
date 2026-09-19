"""Native AmneziaWG tunnel service integration for Windows.

AWG obfuscation fields are not part of standard WireGuard and are not
supported by sing-box.  This manager uses the official AmneziaWG Windows
tunnel service for AWG configs while leaving normal WireGuard on sing-box.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path

from engine.paths import bin_path, data_dir
from engine.wg_config import AWG_INTERFACE_FIELDS, AWG_PEER_FIELDS


TUNNEL_NAME = "SadnessVPN"
SERVICE_NAME = f"AmneziaWGTunnel${TUNNEL_NAME}"
_SAFE_VALUE = re.compile(r"^[^\r\n]+$")


def _clean_value(value, label: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"В AWG-конфиге отсутствует {label}")
    if text and not _SAFE_VALUE.fullmatch(text):
        raise ValueError(f"Некорректное значение {label}")
    return text


def _list_value(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def build_amneziawg_config(
    server: dict,
    dns_servers: list[str] | None = None,
    force_full_route: bool = True,
) -> str:
    """Build an official AmneziaWG quick-config without logging secrets."""
    private_key = _clean_value(server.get("private_key"), "PrivateKey", required=True)
    public_key = _clean_value(server.get("peer_public_key"), "PublicKey", required=True)
    endpoint = _clean_value(server.get("endpoint"), "Endpoint", required=True)
    port = int(server.get("port", 51820))
    if not 1 <= port <= 65535:
        raise ValueError("Некорректный порт AWG")
    if ":" in endpoint and not endpoint.startswith("["):
        endpoint = f"[{endpoint}]"

    addresses = _list_value(server.get("address"))
    if not addresses:
        raise ValueError("В AWG-конфиге отсутствует Address")
    addresses = [_clean_value(item, "Address", required=True) for item in addresses]

    dns = _list_value(dns_servers if dns_servers is not None else server.get("dns"))
    dns = [_clean_value(item, "DNS", required=True) for item in dns]

    if force_full_route:
        allowed_ips = ["0.0.0.0/0", "::/0"]
    else:
        allowed_ips = _list_value(
            server.get("source_allowed_ips") or server.get("allowed_ips")
        )
    if not allowed_ips:
        allowed_ips = ["0.0.0.0/0", "::/0"]
    allowed_ips = [_clean_value(item, "AllowedIPs", required=True) for item in allowed_ips]

    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {', '.join(addresses)}",
    ]
    if dns:
        lines.append(f"DNS = {', '.join(dns)}")
    mtu = int(server.get("mtu", 1280))
    if 576 <= mtu <= 65535:
        lines.append(f"MTU = {mtu}")

    awg_fields = server.get("awg_fields") or {}
    for stored_name, config_name in AWG_INTERFACE_FIELDS.items():
        value = _clean_value(awg_fields.get(stored_name), config_name)
        if value:
            lines.append(f"{config_name} = {value}")

    lines.extend([
        "",
        "[Peer]",
        f"PublicKey = {public_key}",
    ])
    preshared = _clean_value(server.get("pre_shared_key"), "PresharedKey")
    if preshared:
        lines.append(f"PresharedKey = {preshared}")
    for stored_name, config_name in AWG_PEER_FIELDS.items():
        value = _clean_value(awg_fields.get(stored_name), config_name)
        if value:
            lines.append(f"{config_name} = {value}")
    lines.extend([
        f"Endpoint = {endpoint}:{port}",
        f"AllowedIPs = {', '.join(allowed_ips)}",
        f"PersistentKeepalive = {int(server.get('persistent_keepalive') or 25)}",
        "",
    ])
    return "\n".join(lines)


class AmneziaWGManager:
    """Owns only the ``AmneziaWGTunnel$SadnessVPN`` service."""

    def __init__(self, log_callback=None, exit_callback=None):
        self.running = False
        self.log_cb = log_callback or (lambda message, tag: None)
        self.exit_cb = exit_callback or (lambda return_code: None)
        self._config_file: str | None = None
        self._stop_requested = threading.Event()
        self._lock = threading.RLock()

    def _manager_path(self) -> str:
        return bin_path(os.path.join("amneziawg", "amneziawg.exe"))

    def _awg_path(self) -> str:
        return bin_path(os.path.join("amneziawg", "awg.exe"))

    @staticmethod
    def _creation_flags() -> int:
        return subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

    def _run(self, command: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=self._creation_flags(),
        )

    def _service_exists(self) -> bool:
        return self._service_state() != 0

    def _service_state(self) -> int:
        if platform.system() != "Windows":
            return 0
        try:
            result = self._run(["sc.exe", "query", SERVICE_NAME], timeout=5)
        except (OSError, subprocess.SubprocessError):
            return -1
        if result.returncode != 0:
            return 0 if result.returncode == 1060 else -1
        # The state label is localized, but the Win32 state number is not.
        for line in result.stdout.splitlines():
            match = re.search(r":\s*([1-7])\s+\S+", line)
            if match:
                return int(match.group(1))
        return -1

    def _latest_handshake(self) -> int:
        try:
            result = self._run(
                [self._awg_path(), "show", TUNNEL_NAME, "latest-handshakes"],
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        if result.returncode != 0:
            return 0
        latest = 0
        for line in result.stdout.splitlines():
            fields = line.split()
            if fields:
                try:
                    latest = max(latest, int(fields[-1]))
                except ValueError:
                    continue
        return latest

    def _wait_handshake(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stop_requested.is_set():
            timestamp = self._latest_handshake()
            if timestamp and time.time() - timestamp < 180:
                return True
            self._stop_requested.wait(0.5)
        return False

    def _write_config(self, text: str) -> str:
        runtime_dir = Path(data_dir(), "runtime")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        final_path = runtime_dir.joinpath(f"{TUNNEL_NAME}.conf")
        temp_path = runtime_dir.joinpath(f".{TUNNEL_NAME}.{os.getpid()}.tmp")
        temp_path.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temp_path, final_path)
        self._config_file = str(final_path)
        return str(final_path)

    def start(
        self,
        server: dict,
        dns_servers: list[str] | None = None,
        handshake_timeout: float = 15.0,
        force_full_route: bool = True,
        cancelled=None,
    ) -> bool:
        with self._lock:
            manager = self._manager_path()
            awg = self._awg_path()
            if platform.system() != "Windows":
                self.log_cb("AmneziaWG поддерживается только в Windows", "err")
                return False
            missing = [path for path in (manager, awg) if not os.path.isfile(path)]
            if missing:
                self.log_cb("Нативный движок AmneziaWG не найден в сборке", "err")
                return False

            self._stop_requested.set()
            if not self._uninstall_owned_service(log_errors=False):
                raise RuntimeError("Не удалось остановить предыдущую службу AmneziaWG")
            self._remove_config()
            self._stop_requested = threading.Event()
            if cancelled and cancelled():
                return False

            try:
                config_path = self._write_config(
                    build_amneziawg_config(
                        server,
                        dns_servers=dns_servers,
                        force_full_route=force_full_route,
                    )
                )
                result = self._run([manager, "/installtunnelservice", config_path])
            except PermissionError:
                self.log_cb("Для AmneziaWG нужны права администратора", "err")
                self._remove_config()
                return False
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.log_cb(f"Не удалось запустить AmneziaWG: {exc}", "err")
                self._remove_config()
                return False

            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                self.log_cb(
                    "AmneziaWG не установил туннельную службу"
                    + (f": {detail}" if detail else ""),
                    "err",
                )
                self._remove_config()
                return False

            if (cancelled and cancelled()) or not self._wait_handshake(handshake_timeout):
                self.log_cb(
                    "AmneziaWG запустился, но сервер не подтвердил handshake",
                    "err",
                )
                if not self._uninstall_owned_service(log_errors=True):
                    self.running = True
                    raise RuntimeError("AWG: не удалось остановить службу после неудачного подключения")
                self._remove_config()
                return False

            self.running = True
            self.log_cb("AmneziaWG handshake подтверждён", "ok")
            threading.Thread(target=self._monitor_service, daemon=True).start()
            return True

    def get_transfer(self) -> tuple[int, int]:
        """Return cumulative (upload, download) bytes for the active tunnel."""
        try:
            result = self._run(
                [self._awg_path(), "show", TUNNEL_NAME, "transfer"], timeout=5
            )
        except (OSError, subprocess.SubprocessError):
            return 0, 0
        if result.returncode != 0:
            return 0, 0
        uploaded = downloaded = 0
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 3:
                try:
                    downloaded += int(fields[-2])
                    uploaded += int(fields[-1])
                except ValueError:
                    continue
        return uploaded, downloaded

    def request_stop(self):
        """Signal handshake cancellation without waiting for the start lock."""
        self._stop_requested.set()

    def stop(self):
        self.request_stop()
        with self._lock:
            was_running = self.running
            self._stop_requested.set()
            if not was_running and not self._config_file:
                return True
            if not self._uninstall_owned_service(log_errors=True):
                raise RuntimeError("Не удалось подтвердить остановку службы AmneziaWG. Повторите отключение.")
            self.running = False
            self._remove_config()
            if was_running:
                self.log_cb("AmneziaWG остановлен", "info")
            return True

    def _uninstall_owned_service(self, log_errors: bool) -> bool:
        manager = self._manager_path()
        if not os.path.isfile(manager) or platform.system() != "Windows":
            return False
        try:
            result = self._run([manager, "/uninstalltunnelservice", TUNNEL_NAME])
        except (OSError, subprocess.SubprocessError) as exc:
            if log_errors:
                self.log_cb(f"Не удалось остановить AmneziaWG: {exc}", "warn")
            return False
        if result.returncode != 0 and log_errors:
            detail = (result.stderr or result.stdout).strip()
            self.log_cb(
                "Не удалось удалить службу SadnessVPN"
                + (f": {detail}" if detail else ""),
                "warn",
            )
        if result.returncode != 0:
            return self._service_state() == 0
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self._service_state() in (0, 1):
                return True
            time.sleep(.15)
        return False

    def _remove_config(self):
        path = self._config_file
        self._config_file = None
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                self.log_cb(f"Не удалось удалить временный AWG-конфиг: {exc}", "warn")

    def _monitor_service(self):
        stop_event = self._stop_requested
        while not stop_event.wait(2.0):
            state = self._service_state()
            if state not in (0, 1):
                # Unknown/query failure or a pending transition is not a confirmed stop.
                continue
            if state in (0, 1):
                with self._lock:
                    if stop_event is not self._stop_requested or stop_event.is_set():
                        return
                    self.running = False
                    self._remove_config()
                self.log_cb("Служба AmneziaWG неожиданно остановилась", "err")
                try:
                    self.exit_cb(1)
                except Exception as exc:
                    self.log_cb(f"Ошибка обработки остановки AmneziaWG: {exc}", "err")
                return
