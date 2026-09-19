"""Read-only public preview of the Sadness VPN interface.

This server deliberately never imports the desktop backend and never exposes
subscription data, credentials, HWID, application settings, or control APIs.
It serves the real UI assets with a small, synthetic state payload instead.
"""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from engine.app_meta import APP_VERSION
from engine.flowseal_profiles import FLOWSEAL_PROFILES


UI_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = UI_ROOT / "static"
TEMPLATE_FILE = UI_ROOT / "templates" / "index.html"

DEMO_STATE = {
    "type": "state",
    "connected": False,
    "status": "off",
    "server": "",
    "activeProtocol": "vless",
    "groups": [
        {
            "id": "demo-vless",
            "name": "Sadness VPN · Premium",
            "servers": [
                {"remark": "Finland | Helsinki", "protocol": "vless"},
                {"remark": "Germany | Frankfurt", "protocol": "vless"},
                {"remark": "Netherlands | Amsterdam", "protocol": "vless"},
            ],
        }
    ],
    "selGroup": "demo-vless",
    "selIndex": 0,
    "wgGroups": [
        {
            "id": "demo-wg",
            "name": "WireGuard",
            "servers": [
                {"remark": "Finland | WireGuard", "protocol": "wg"},
                {"remark": "Germany | AmneziaWG", "protocol": "wg", "is_awg": True},
            ],
        }
    ],
    "selWgGroup": "demo-wg",
    "selWgIndex": 0,
    "appsConfig": {
        "mode": "whitelist",
        "apps": [
            {"exe": "Discord.exe", "name": "Discord", "enabled": True},
            {"exe": "chrome.exe", "name": "Google Chrome", "enabled": True},
            {"exe": "Telegram.exe", "name": "Telegram", "enabled": True},
        ],
    },
    "appSettings": {
        "socks": 1080,
        "http": 8080,
        "startup": True,
        "silent": True,
        "mintray": True,
        "autoconnect": False,
        "lan": False,
        "onboarding_complete": True,
        "favorite_servers": [],
        "avatar_file": "",
        "wallpaper_file": "",
    },
    "tunnelSettings": {
        "strict_route": True,
        "block_udp": False,
        "mux": True,
        "fake_dns": False,
        "preferred_ip": "auto",
        "server_sort": "default",
        "dns_preset": "xbox_dot",
        "ping_type": "tcp",
        "ping_url": "https://www.gstatic.com/generate_204",
        "ping_timeout": 3000,
        "socks5_user": "demo",
        "socks5_pass": "preview-only",
    },
    "hwid": "svpn_demo_preview_only",
    "zapretStrategies": [
        {
            key: profile[key]
            for key in (
                "id", "name", "category", "desc", "icon", "tags", "experimental", "source_file"
            )
        }
        for profile in FLOWSEAL_PROFILES
    ],
    "zapretStrategy": "flowseal_general",
    "zapretRunning": False,
    "appVersion": APP_VERSION,
    "engineVersion": "1.10.x",
    "stats": {
        "today": {"up": 184_000_000, "down": 912_000_000},
        "total": {"up": 1_400_000_000, "down": 6_800_000_000},
    },
}


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "SadnessVPNPreview/1.0"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = unquote(urlsplit(self.path).path)
        if path in {"", "/"}:
            self._send_file(TEMPLATE_FILE, "text/html; charset=utf-8")
            return
        if path == "/static/js/app.js":
            source = (STATIC_ROOT / "js" / "app.js").read_text(encoding="utf-8")
            demo = json.dumps(DEMO_STATE, ensure_ascii=False, separators=(",", ":"))
            source = f"const MOBILE_DEMO_STATE={demo};\n" + source
            source = source.replace(
                "\nconnectWS();",
                "\nhandle(MOBILE_DEMO_STATE); ST.backendOnline=true; "
                "document.getElementById('tbState').textContent='Мобильный preview';",
            )
            self._send_bytes(source.encode("utf-8"), "text/javascript; charset=utf-8")
            return
        if path.startswith("/static/"):
            relative = Path(path.removeprefix("/static/").replace("/", "\\"))
            target = (STATIC_ROOT / relative).resolve()
            try:
                target.relative_to(STATIC_ROOT.resolve())
            except ValueError:
                self.send_error(404)
                return
            if target.is_file():
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self._send_file(target, content_type)
                return
        if path.startswith("/api/") or path == "/ws":
            self._send_json(
                {"ok": False, "error": "Мобильный preview работает только для просмотра"},
                status=403,
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send_json(
            {"ok": False, "error": "Мобильный preview работает только для просмотра"},
            status=403,
        )

    def _send_file(self, path: Path, content_type: str) -> None:
        self._send_bytes(path.read_bytes(), content_type)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
        )

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[mobile-preview] {self.address_string()} {format % args}")


def run(host: str = "127.0.0.1", port: int = 45679) -> None:
    print(f"Sadness VPN mobile preview: http://{host}:{port}")
    ThreadingHTTPServer((host, port), PreviewHandler).serve_forever()


if __name__ == "__main__":
    run()
