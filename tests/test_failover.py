"""Смена сервера на лету и автоматический резерв (engine/failover.py)."""
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from engine import failover
from engine.connection_state import ConnectionCoordinator
from engine.core_config import build_proxy_config
from engine.paths import bin_path
from ui import profile_state, server

BASE = "http://127.0.0.1:45678"
MIHOMO = bin_path("mihomo.exe")


def node(remark, host, ui_id, **extra):
    return {"remark": remark, "protocol": "vless", "host": host, "port": 443, "ui_id": ui_id,
            "uuid": "11111111-1111-4111-8111-111111111111", "security": "tls", "type": "tcp",
            "sni": "example.com", **extra}


def sample_groups():
    return [
        {"id": "rw", "name": "Remnawave", "servers": [
            node("🇩🇪 Germany XHTTP", "198.51.100.1", "de-x", type="xhttp", path="/x"),
            node("🇩🇪 Germany TCP", "198.51.100.2", "de-t"),
            node("🇫🇮 Finland", "198.51.100.3", "fi"),
            {**node("🇩🇪 Germany HY2", "198.51.100.4", "de-h"), "protocol": "hysteria2",
             "password": "p", "type": "quic"},
            node("🇩🇪 Broken", "198.51.100.5", "de-bad", type="kcp"),
        ]},
        {"id": "cloud", "name": "Cloud", "servers": [
            node("🇩🇪 Германия", "198.51.100.6", "de-c"),
            node("🇳🇱 Нидерланды", "198.51.100.7", "nl"),
        ]},
    ]


class FailoverConfigTests(unittest.TestCase):
    def setUp(self):
        self.groups = sample_groups()
        self.selected = self.groups[0]["servers"][1]  # Germany TCP

    def test_names_are_stable_and_carry_no_address(self):
        self.assertEqual(failover.proxy_name(self.selected), "srv-de-t")
        anonymous = {"remark": "x", "host": "203.0.113.9", "port": 1}
        self.assertEqual(failover.proxy_name(anonymous), failover.proxy_name(dict(anonymous)))
        self.assertNotIn("203.0.113.9", failover.proxy_name(anonymous))

    def test_country_comes_from_the_flag(self):
        self.assertEqual(failover.country(self.selected), "DE")
        self.assertEqual(failover.country({"remark": "Без флага"}), "")

    def test_backups_prefer_same_country_and_other_transport(self):
        backups = [s["ui_id"] for s in failover.pick_backups(self.selected, self.groups)]
        # Та же страна и другой транспорт → та же страна, тот же транспорт.
        # Финляндия из той же подписки — последней; неподдерживаемый kcp — никогда.
        self.assertEqual(backups, ["de-x", "de-h", "de-c", "fi"])
        self.assertNotIn("de-bad", backups)
        self.assertEqual(len(failover.pick_backups(self.selected, self.groups, limit=2)), 2)

    def test_groups_keep_rules_on_proxy_and_include_every_server(self):
        config = build_proxy_config(self.selected)
        live = failover.apply_server_groups(config, self.selected, self.groups)
        names = [p["name"] for p in config["proxies"]]
        self.assertEqual(names[0], "srv-de-t")
        self.assertEqual(set(live), set(names))
        self.assertNotIn("srv-de-bad", live)
        groups = {g["name"]: g for g in config["proxy-groups"]}
        self.assertEqual(groups["manual"]["type"], "select")
        self.assertEqual(groups["manual"]["proxies"][0], "srv-de-t")
        self.assertEqual(groups["proxy"]["type"], "fallback")
        self.assertEqual(groups["proxy"]["proxies"], ["manual", "backup"])
        self.assertEqual(groups["backup"]["type"], "url-test")
        self.assertEqual(groups["backup"]["proxies"], ["srv-de-x", "srv-de-h", "srv-de-c", "srv-fi"])
        self.assertIn("MATCH,proxy", config["rules"])

    def test_without_failover_proxy_is_just_the_selected_server(self):
        config = build_proxy_config(self.selected)
        failover.apply_server_groups(config, self.selected, self.groups, failover=False)
        groups = {g["name"]: g for g in config["proxy-groups"]}
        self.assertEqual(groups["proxy"], {"name": "proxy", "type": "select", "proxies": ["manual"]})
        self.assertNotIn("backup", groups)

    def test_mux_applies_to_every_server_like_the_main_one(self):
        config = build_proxy_config(self.selected, mux=True)
        failover.apply_server_groups(config, self.selected, self.groups, mux=True)
        by_name = {p["name"]: p for p in config["proxies"]}
        self.assertIn("smux", by_name["srv-de-t"])
        self.assertIn("smux", by_name["srv-de-c"])
        self.assertNotIn("smux", by_name["srv-de-h"])  # hysteria2 — без smux

    @unittest.skipUnless(os.path.isfile(MIHOMO), "bin/mihomo.exe отсутствует")
    def test_bundled_mihomo_accepts_the_groups(self):
        config = build_proxy_config(self.selected)
        failover.apply_server_groups(config, self.selected, self.groups)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "c.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False)
            result = subprocess.run([MIHOMO, "-d", directory, "-f", path, "-t"], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout[-500:])


class LiveSwitchTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.groups_backup = profile_state.groups
        self.saved = (server._connection, dict(server._app_settings), dict(server._live_servers),
                      dict(server._route_state))
        profile_state.groups = sample_groups()
        server._connection = ConnectionCoordinator()
        attempt = server._connection.begin()
        server._connection.complete(attempt)
        server._app_settings.update(selected_group="rw", selected_index=1, active_protocol="vless")
        selected = profile_state.groups[0]["servers"][1]
        config = build_proxy_config(selected)
        server._live_servers.clear()
        server._live_servers.update(failover.apply_server_groups(config, selected, profile_state.groups))
        server._route_state.update(name="srv-de-t", backup=False, failover=True)
        self.calls, self.events, self.logs = [], [], []
        patches = [
            mock.patch.object(server, "_clash", side_effect=self.fake_clash),
            mock.patch.object(server, "_broadcast", side_effect=self.events.append),
            mock.patch.object(server, "_log", side_effect=lambda m, t="log": self.logs.append((t, m))),
            mock.patch.object(server, "_save_settings", return_value=True),
            mock.patch.object(server, "_recheck_route"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.proxy_now, self.manual_now, self.backup_now = "manual", "srv-de-t", "srv-de-x"

    def tearDown(self):
        profile_state.groups = self.groups_backup
        server._connection, settings, live, route = self.saved
        server._app_settings.clear(); server._app_settings.update(settings)
        server._live_servers.clear(); server._live_servers.update(live)
        server._route_state.clear(); server._route_state.update(route)

    def fake_clash(self, method, path, body=None, timeout=6.0):
        self.calls.append((method, path, body))
        if method == "PUT":
            self.manual_now = body["name"]
            return 204, None
        if path == "/proxies/proxy":
            return 200, {"now": self.proxy_now}
        if path == "/proxies/manual":
            return 200, {"now": self.manual_now}
        if path == "/proxies/backup":
            return 200, {"now": self.backup_now}
        return 204, None

    def select(self, gid, index):
        return self.client.post("/api/servers/select", json={"group_id": gid, "index": index}, base_url=BASE)

    def test_selecting_a_server_while_connected_switches_it_without_reconnect(self):
        response = self.select("cloud", 0)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["live"])
        self.assertIn(("PUT", "/proxies/manual", {"name": "srv-de-c"}), self.calls)
        self.assertIn(("DELETE", "/connections", None), self.calls)
        self.assertEqual((server._app_settings["selected_group"], server._app_settings["selected_index"]), ("cloud", 0))
        self.assertEqual(server._connection.state, "on")
        self.assertTrue(any("без переподключения" in m for _, m in self.logs))

    def test_server_missing_from_the_running_core_asks_to_reconnect(self):
        profile_state.groups[1]["servers"].append(node("🇩🇪 Новый", "198.51.100.8", "de-new"))
        response = self.select("cloud", 2)
        self.assertEqual(response.status_code, 409)
        self.assertIn("переподключитесь", response.get_json()["error"])
        self.assertEqual(server._app_settings["selected_group"], "rw")

    def test_switch_is_refused_while_connecting_and_in_wireguard(self):
        server._app_settings["active_protocol"] = "wg"
        self.assertEqual(self.select("cloud", 0).status_code, 409)
        server._app_settings["active_protocol"] = "vless"
        server._connection = ConnectionCoordinator()
        server._connection.begin()  # идёт подключение
        response = self.select("cloud", 0)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Дождитесь", response.get_json()["error"])

    def test_failover_and_return_are_reported_once(self):
        self.proxy_now = "backup"
        route = server._current_route()
        self.assertEqual(route, ("srv-de-x", True))
        server._publish_route(route)
        self.assertEqual(server._current_route(), server._current_route())
        event = next(e for e in self.events if e["type"] == "active_server")
        self.assertTrue(event["backup"])
        self.assertIn("Germany XHTTP", event["name"])
        self.assertIn("не отвечает", event["message"])
        self.proxy_now = "manual"
        server._publish_route(server._current_route())
        events = [e for e in self.events if e["type"] == "active_server"]
        self.assertEqual(len(events), 2)
        self.assertFalse(events[-1]["backup"])
        self.assertIn("снова идёт через выбранный", events[-1]["message"])

    def test_first_route_on_the_selected_server_is_not_announced(self):
        server._route_state.update(name=None, backup=False)
        server._publish_route(("srv-de-t", False))
        self.assertFalse(any(e["type"] == "active_server" for e in self.events))


class FailoverSettingTests(unittest.TestCase):
    def test_enabled_by_default_and_user_controlled(self):
        from ui import app_state
        self.assertTrue(app_state.DEFAULT_SETTINGS["auto_failover"])
        self.assertIn("auto_failover", app_state.USER_APP_SETTING_KEYS)
        with self.assertRaises(ValueError):
            app_state.normalize_app_setting("auto_failover", "yes")


if __name__ == "__main__":
    unittest.main()
