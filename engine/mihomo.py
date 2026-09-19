"""Mihomo process lifecycle using the same ownership rules as sing-box."""
import os
import platform
import subprocess
import ipaddress
import socket
import threading
import shutil

from engine.paths import bin_path, data_dir
from engine.singbox import SingBoxManager

MIHOMO_VERSION = "1.19.30"


class MihomoManager(SingBoxManager):
    def __init__(self, log_callback=None, exit_callback=None):
        callback = log_callback or (lambda message, tag: None)
        self._tun_ready = threading.Event()
        def log(message, tag):
            if "Tun adapter listening at:" in message:
                self._tun_ready.set()
            callback(message.replace("sing-box", "Mihomo"), tag)
        super().__init__(
            log,
            exit_callback,
        )

    def start(self, config):
        self._tun_ready.clear()
        # Resolve upstream hostnames before enabling TUN. This also handles
        # networks where public UDP DNS is blocked but Windows DNS works.
        hosts = config.setdefault("hosts", {})
        for proxy in config.get("proxies", []):
            endpoints = [proxy, proxy.get("xhttp-opts", {}).get("download-settings") or {}]
            for endpoint in endpoints:
                hostname = endpoint.get("server")
                if not hostname:
                    continue
                try:
                    ipaddress.ip_address(hostname)
                    continue
                except ValueError:
                    pass
                try:
                    addresses = socket.getaddrinfo(hostname, endpoint.get("port", 443),
                                                   socket.AF_UNSPEC if config.get("ipv6") else socket.AF_INET,
                                                   socket.SOCK_STREAM)
                    hosts[hostname] = list(dict.fromkeys(item[4][0] for item in addresses))
                except OSError:
                    self.log_cb("Mihomo: не удалось определить адрес VPN-сервера до запуска TUN. Проверьте DNS и доступность подписки.", "err")
                    return False
        started = super().start(config)
        if started and self._has_tun(config):
            if not self._tun_ready.wait(5) or not self.is_alive():
                self.log_cb("Mihomo: запуск TUN-адаптера не подтверждён", "err")
                self.stop()
                return False
        return started

    def _singbox_path(self):
        return bin_path("mihomo.exe" if platform.system() == "Windows" else "mihomo")

    def _command(self, executable, path):
        runtime = os.path.join(data_dir(), "runtime", "mihomo")
        os.makedirs(runtime, exist_ok=True)
        for name in ('geosite.dat', 'geoip.dat'):
            source = bin_path(name)
            target = os.path.join(runtime, name)
            if os.path.isfile(source) and (not os.path.isfile(target) or os.stat(source).st_mtime_ns != os.stat(target).st_mtime_ns):
                shutil.copy2(source, target)
        return [executable, "-d", runtime, "-f", path]

    def _has_tun(self, config):
        return bool(config.get("tun", {}).get("enable"))

    @staticmethod
    def _listener_ports(config):
        listeners = []
        controller = config.get("external-controller", "")
        if controller and controller.rpartition(":")[2].isdigit():
            listeners.append(("Clash API", int(controller.rpartition(":")[2])))
        for field in ("socks-port", "port", "mixed-port"):
            if config.get(field):
                listeners.append((field, config[field]))
        return listeners

    def _prepare_tun_addresses(self, config):
        # Mihomo derives TUN IPv4 from dns.fake-ip-range, not tun.inet4-address.
        if config["dns"].get("enhanced-mode") == "fake-ip":
            occupied = self._assigned_ipv4_networks()
            for cidr in ("198.18.0.1/16", "198.19.0.1/16", "172.29.0.1/16", "172.30.0.1/16"):
                if not any(ipaddress.ip_interface(cidr).network.overlaps(net) for net in occupied):
                    config["dns"]["fake-ip-range"] = cidr
                    return True
            self.log_cb("Mihomo: не найдена свободная подсеть FakeDNS", "err")
            return False
        inbound = {"type": "tun", "address": [config["dns"]["fake-ip-range"]]}
        if not super()._prepare_tun_addresses({"inbounds": [inbound]}):
            return False
        config["dns"]["fake-ip-range"] = inbound["address"][0]
        return True

    def _check_config(self, executable, path):
        result = subprocess.run(
            self._command(executable, path) + ["-t"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            self.log_cb("Ошибка конфигурации Mihomo: " + result.stdout[-2000:], "err")
            return False
        return True


class MultiCoreManager:
    """Only one proxy core owns the shared API and TUN at a time."""
    def __init__(self, log_callback=None, exit_callback=None):
        self.singbox = SingBoxManager(log_callback, exit_callback)
        self.mihomo = MihomoManager(log_callback, exit_callback)
        self.active = self.singbox
        self.name = "sing-box"

    _port_free = SingBoxManager._port_free
    _port_owner = staticmethod(SingBoxManager._port_owner)

    @property
    def running(self):
        return self.active.running

    def is_alive(self):
        return self.active.is_alive()

    def start(self, config):
        chosen = self.mihomo if "proxies" in config else self.singbox
        if self.active is not chosen and self.active.is_alive():
            self.active.stop()
        self.active = chosen
        self.name = "Mihomo" if chosen is self.mihomo else "sing-box"
        return chosen.start(config)

    def stop(self):
        self.active.stop()
