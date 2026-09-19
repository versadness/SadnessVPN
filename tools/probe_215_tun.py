"""Opt-in live verification against existing profiles; never modifies subscriptions."""
import argparse
import copy
import http.client
import json
from pathlib import Path
import ssl
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.config import fetch_subscription
from engine.core_config import build_proxy_config
from engine.mihomo import MultiCoreManager
from engine.singbox import SingBoxManager
from engine.ping import tunnel_ping


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", choices=["mihomo", "singbox", "xray"], required=True)
    parser.add_argument("--group", type=int)
    parser.add_argument("--index", type=int, default=0)
    args = parser.parse_args()
    profile = Path.home() / "AppData/Local/SadnessVPN/data"
    groups = json.loads((profile / "servers.json").read_text(encoding="utf8"))
    settings = json.loads((profile / "settings.json").read_text(encoding="utf8"))
    if args.group is not None:
        server = groups[args.group]["servers"][args.index]
    elif args.core == "xray":
        group = next(g for g in groups if g.get("url") and any(s.get("type") == "xhttp" for s in g.get("servers", [])))
        fresh = fetch_subscription(group["url"], settings.get("hwid", ""))
        server = next(s for s in fresh if s.get("type") == "xhttp")
    else:
        group = next(g for g in groups if g["id"] == settings["selected_group"])
        server = group["servers"][settings["selected_index"]]
        if server.get("type") == "xhttp":
            server = next(s for s in group["servers"] if s.get("type", "tcp") == "tcp")
    probe = SingBoxManager()
    if not all(probe._port_free(p) for p in (1080, 8080, 9090)):
        raise RuntimeError("Stop the existing VPN before running this probe")
    config = build_proxy_config(server, preference=args.core, socks_port=1080, http_port=8080)
    logs = []
    manager = MultiCoreManager(lambda message, tag: logs.append((message, tag)))
    try:
        started = manager.start(config)
        if not started:
            # Core errors may contain endpoints. Keep the raw output local.
            raise RuntimeError("Core failed to start: " + repr([m for m, t in logs if t == "err"][-3:]))
        time.sleep(1)
        api = http.client.HTTPConnection("127.0.0.1", 9090, timeout=3)
        api.request("GET", "/version")
        r = api.getresponse()
        assert r.status == 200
        r.read()
        api.close()
        connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=15)
        connection.set_tunnel("www.gstatic.com", 443)
        connection.connect()
        connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname="www.gstatic.com")
        connection.request("GET", "/generate_204", headers={"Host": "www.gstatic.com"})
        response = connection.getresponse()
        response.read()
        connection.close()
        # An ordinary socket (no proxy configured) must also traverse TUN.
        direct_socket = http.client.HTTPSConnection("www.gstatic.com", timeout=15)
        direct_socket.request("GET", "/generate_204")
        tun_response = direct_socket.getresponse()
        tun_response.read()
        direct_socket.close()
        result = {"core": manager.name, "transport": server.get("type", "tcp"),
                  "reality": server.get("security") == "reality", "alive": manager.is_alive(),
                  "https_status": response.status,
                  "system_tun_https_status": tun_response.status,
                  "listener_ports": [p for p in (1080,8080,9090) if not probe._port_free(p)]}
        result["outbound_delay_ms"] = tunnel_ping(timeout=5)
        print(json.dumps(result), flush=True)
        assert response.status == 204 and tun_response.status == 204 and manager.is_alive()
        assert result["outbound_delay_ms"] is not None
    except Exception:
        from engine.diagnostics import redact
        text = "\n".join(redact(message).replace(str(server.get("host", "")), "[server]") for message, tag in logs[-12:])
        print(text.encode("ascii", "backslashreplace").decode(), flush=True)
        raise
    finally:
        manager.stop()
        print(json.dumps({"stopped": not manager.is_alive()}), flush=True)


if __name__ == "__main__":
    main()
