"""Маршрут, потерявший свой сервер, чинится, а не блокирует подключение."""
import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from engine.connection_state import ConnectionCoordinator
from engine.route_repair import known_server_ids, repair_routing
from ui import profile_state
from ui import server


def app_rule(**overrides):
    rule = {"name": "Chat", "exe": "chat.exe", "path": r"C:\Apps\chat.exe",
            "enabled": True, "destination": "server:gone"}
    rule.update(overrides)
    return rule


def custom_rule(**overrides):
    rule = {"id": "rule-1", "kind": "suffix", "value": "example.com", "name": "Example",
            "destination": "server:gone", "enabled": True}
    rule.update(overrides)
    return rule


class RepairRoutingTests(unittest.TestCase):
    def setUp(self):
        self.groups = [{"id": "g", "name": "Group", "servers": [
            {"remark": "Alive", "protocol": "vless", "ui_id": "alive"},
        ]}]

    def test_known_ids_ignore_broken_entries(self):
        groups = [{"servers": [{"ui_id": "a"}, {"ui_id": ""}, {}, "junk"]}, {}, None]
        self.assertEqual(known_server_ids(groups), {"a"})

    def test_missing_app_server_falls_back_to_the_shared_mode(self):
        config = {"mode": "all", "apps": [app_rule()], "rules": []}

        repaired, report = repair_routing(config, self.groups)

        self.assertEqual(repaired["apps"][0]["destination"], "default")
        self.assertEqual(report["apps"], ["chat.exe"])
        self.assertEqual(report["total"], 1)

    def test_missing_rule_server_falls_back_to_the_main_vpn(self):
        config = {"mode": "all", "apps": [], "rules": [custom_rule()]}

        repaired, report = repair_routing(config, self.groups)

        self.assertEqual(repaired["rules"][0]["destination"], "proxy")
        self.assertEqual(report["rules"], ["rule-1"])

    def test_repair_never_produces_a_direct_route(self):
        config = {"mode": "all", "apps": [app_rule(), app_rule(exe="b.exe")],
                  "rules": [custom_rule(), custom_rule(id="rule-2")]}

        repaired, _ = repair_routing(config, self.groups)

        destinations = [a["destination"] for a in repaired["apps"]] + \
            [r["destination"] for r in repaired["rules"]]
        self.assertNotIn("direct", destinations)

    def test_nothing_is_removed_disabled_or_reordered(self):
        config = {"mode": "blacklist",
                  "apps": [app_rule(enabled=False), app_rule(exe="keep.exe", destination="direct")],
                  "rules": [custom_rule(enabled=False), custom_rule(id="rule-2", value="b.example")]}
        original = copy.deepcopy(config)

        repaired, report = repair_routing(config, self.groups)

        self.assertEqual(config, original, "исходная конфигурация не должна меняться")
        self.assertEqual(len(repaired["apps"]), 2)
        self.assertEqual(len(repaired["rules"]), 2)
        self.assertEqual([a["exe"] for a in repaired["apps"]], ["chat.exe", "keep.exe"])
        self.assertEqual([r["id"] for r in repaired["rules"]], ["rule-1", "rule-2"])
        self.assertFalse(repaired["apps"][0]["enabled"])
        self.assertFalse(repaired["rules"][0]["enabled"])
        self.assertEqual(repaired["apps"][0]["path"], r"C:\Apps\chat.exe")
        self.assertEqual(repaired["rules"][1]["value"], "b.example")
        self.assertEqual(repaired["rules"][1]["kind"], "suffix")
        self.assertEqual(report["total"], 3, "правило с direct трогать не за что")

    def test_unrelated_routes_and_servers_are_untouched(self):
        config = {"mode": "all",
                  "apps": [app_rule(exe="ok.exe", destination="server:alive"),
                           app_rule(exe="plain.exe", destination="default"),
                           app_rule(exe="bypass.exe", destination="direct")],
                  "rules": [custom_rule(id="ok", destination="server:alive"),
                            custom_rule(id="main", destination="proxy"),
                            custom_rule(id="out", destination="direct")]}

        repaired, report = repair_routing(config, self.groups)

        self.assertFalse(report["changed"])
        self.assertEqual(repaired, config)
        self.assertEqual(report["message"], "")

    def test_message_and_notice_stay_free_of_secrets(self):
        config = {"apps": [app_rule()], "rules": [custom_rule(), custom_rule(id="rule-2")]}

        _, report = repair_routing(config, self.groups)

        self.assertEqual(
            report["message"],
            "Маршрутизация восстановлена: 1 приложение и 2 правила переведены на основной VPN",
        )
        self.assertIn("3", report["notice"])
        for text in (report["message"], report["notice"]):
            self.assertNotIn("server:", text)
            self.assertNotIn("example.com", text)


class ProfileRepairPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.groups = profile_state.groups
        self.apps_config = profile_state.apps_config
        profile_state.groups = [{"id": "g", "name": "G", "servers": [{"ui_id": "alive"}]}]
        profile_state.apps_config = {"mode": "all", "apps": [app_rule()], "rules": [custom_rule()]}

    def tearDown(self):
        profile_state.groups = self.groups
        profile_state.apps_config = self.apps_config

    def test_repaired_config_is_written_to_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "apps.json")
            def store(data):
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump(data, stream)

            with mock.patch.object(profile_state, "save_apps", store):
                report = profile_state.repair_saved_routes()

            self.assertTrue(report["changed"])
            self.assertTrue(report["saved"])
            with open(path, encoding="utf-8") as stream:
                stored = json.load(stream)
        self.assertEqual(stored["apps"][0]["destination"], "default")
        self.assertEqual(stored["rules"][0]["destination"], "proxy")
        self.assertEqual(profile_state.apps_config["rules"][0]["destination"], "proxy")

    def test_failed_write_still_repairs_memory(self):
        def refuse(_data):
            raise OSError("disk full")

        with mock.patch.object(profile_state, "save_apps", refuse):
            report = profile_state.repair_saved_routes()

        self.assertFalse(report["saved"])
        self.assertEqual(profile_state.apps_config["apps"][0]["destination"], "default")

    def test_server_broadcasts_one_notice_for_the_whole_repair(self):
        with mock.patch.object(profile_state, "save_apps"), \
                mock.patch.object(server, "_broadcast") as broadcast, \
                mock.patch.object(server, "_log"):
            report = server._repair_saved_routes("тест")

        self.assertEqual(report["total"], 2)
        kinds = [call.args[0]["type"] for call in broadcast.call_args_list]
        self.assertEqual(kinds.count("routing_repaired"), 1)
        self.assertIn("apps_config", kinds)
        notice = next(c.args[0] for c in broadcast.call_args_list if c.args[0]["type"] == "routing_repaired")
        self.assertEqual(notice["total"], 2)


class SubscriptionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.groups = profile_state.groups
        self.settings = dict(server._app_settings)

    def tearDown(self):
        profile_state.groups = self.groups
        server._app_settings.clear()
        server._app_settings.update(self.settings)

    def test_reordered_subscription_keeps_ui_ids_and_assignments(self):
        first = {"remark": "First", "protocol": "vless", "host": "a.example", "ui_id": "id-a"}
        second = {"remark": "Second", "protocol": "trojan", "host": "b.example", "ui_id": "id-b"}
        group = {"id": "g", "name": "G", "url": "https://example.invalid", "servers": [first, second]}
        profile_state.groups = [group]
        server._app_settings["selected_group"] = "g"
        server._app_settings["selected_index"] = 0
        fresh = [{k: v for k, v in item.items() if k != "ui_id"} for item in (second, first)]
        # Провайдер вернул те же серверы в другом порядке и с новым remark.
        fresh[0]["remark"] = "Second (renamed)"

        with mock.patch.object(server, "_save_settings", return_value=True):
            server._replace_group_servers(group, fresh)

        self.assertEqual([item["ui_id"] for item in group["servers"]], ["id-b", "id-a"])
        self.assertEqual(server._app_settings["selected_index"], 1)
        config = {"apps": [app_rule(destination="server:id-a")],
                  "rules": [custom_rule(destination="server:id-b")]}
        _, report = repair_routing(config, profile_state.groups)
        self.assertFalse(report["changed"])

    def test_new_server_does_not_inherit_a_removed_identity(self):
        old = {"remark": "Old", "protocol": "vless", "host": "a.example", "ui_id": "id-a"}
        group = {"id": "g", "name": "G", "url": "https://example.invalid", "servers": [old]}
        profile_state.groups = [group]
        server._app_settings["selected_group"] = None
        server._app_settings["selected_index"] = None
        fresh = [{"remark": "Brand new", "protocol": "vless", "host": "c.example"}]

        with mock.patch.object(server, "_save_settings", return_value=True):
            server._replace_group_servers(group, fresh)

        self.assertNotEqual(group["servers"][0]["ui_id"], "id-a")
        config = {"apps": [app_rule(destination="server:id-a")], "rules": []}
        repaired, report = repair_routing(config, profile_state.groups)
        self.assertTrue(report["changed"])
        self.assertEqual(repaired["apps"][0]["destination"], "default")


class GroupDeletionTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.groups = profile_state.groups
        self.apps_config = profile_state.apps_config

    def tearDown(self):
        profile_state.groups = self.groups
        profile_state.apps_config = self.apps_config

    def test_deleting_a_group_repairs_only_its_routes(self):
        profile_state.groups = [
            {"id": "doomed", "name": "Doomed", "servers": [{"ui_id": "gone-1"}]},
            {"id": "kept", "name": "Kept", "servers": [{"ui_id": "alive"}]},
        ]
        profile_state.apps_config = {
            "mode": "all",
            "apps": [app_rule(exe="a.exe", destination="server:gone-1"),
                     app_rule(exe="b.exe", destination="server:alive")],
            "rules": [custom_rule(id="r1", destination="server:gone-1"),
                      custom_rule(id="r2", destination="server:alive")],
        }

        with mock.patch.object(profile_state, "save_proxy_groups"), \
                mock.patch.object(profile_state, "save_apps"), \
                mock.patch.object(server, "_save_settings", return_value=True), \
                mock.patch.object(server, "_broadcast"), mock.patch.object(server, "_log"):
            response = self.client.post("/api/groups/delete", json={"id": "doomed"},
                                        base_url="http://127.0.0.1:45678")

        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(profile_state.apps_config["apps"][0]["destination"], "default")
        self.assertEqual(profile_state.apps_config["apps"][1]["destination"], "server:alive")
        self.assertEqual(profile_state.apps_config["rules"][0]["destination"], "proxy")
        self.assertEqual(profile_state.apps_config["rules"][1]["destination"], "server:alive")


class ConnectStatusTests(unittest.TestCase):
    """Подключение не запускается: поток сборки конфигурации подменён."""

    def setUp(self):
        self.client = server.app.test_client()
        self.groups = profile_state.groups
        self.apps_config = profile_state.apps_config
        self.connection = server._connection
        self.settings = dict(server._app_settings)
        server._connection = ConnectionCoordinator()
        self.live = {"remark": "Live", "protocol": "vless", "host": "127.0.0.1", "port": 443,
                     "uuid": "0" * 8, "security": "tls", "type": "tcp", "ui_id": "alive"}
        profile_state.groups = [{"id": "g", "name": "G", "servers": [self.live]}]
        server._app_settings["selected_group"] = "g"
        server._app_settings["selected_index"] = 0
        server._app_settings["active_protocol"] = "vless"

    def tearDown(self):
        profile_state.groups = self.groups
        profile_state.apps_config = self.apps_config
        server._connection = self.connection
        server._app_settings.clear()
        server._app_settings.update(self.settings)

    def _connect(self):
        with mock.patch.object(profile_state, "save_apps"), \
                mock.patch.object(server, "_broadcast"), mock.patch.object(server, "_log"), \
                mock.patch.object(server.threading, "Thread") as thread:
            thread.return_value.start.return_value = None
            return self.client.post("/api/connect", json={}, base_url="http://127.0.0.1:45678")

    def test_missing_rule_server_no_longer_fails_the_connection(self):
        profile_state.apps_config = {"mode": "all", "apps": [app_rule()],
                                     "rules": [custom_rule()]}

        response = self._connect()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(profile_state.apps_config["apps"][0]["destination"], "default")
        self.assertEqual(profile_state.apps_config["rules"][0]["destination"], "proxy")

    def test_unfixable_user_configuration_returns_422_with_json(self):
        # Транспорта, которого нет у единственного ядра, достаточно: отказ
        # должен приходить до подключения и с понятной причиной.
        profile_state.apps_config = {"mode": "all", "apps": [], "rules": []}
        broken = dict(self.live, type="kcp")
        profile_state.groups = [{"id": "g", "name": "G", "servers": [broken]}]

        response = self._connect()

        self.assertEqual(response.status_code, 422)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("kcp", body["error"])

    def test_invalid_request_still_returns_400(self):
        response = self.client.post("/api/routing/rules",
                                    json={"rules": [{"kind": "suffix", "value": "\u0000bad"}]},
                                    base_url="http://127.0.0.1:45678")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_internal_failure_still_returns_500_and_is_logged(self):
        profile_state.apps_config = {"mode": "all", "apps": [], "rules": []}

        with mock.patch.object(server, "build_proxy_config", side_effect=OSError("disk gone")), \
                mock.patch.object(server, "_broadcast"), mock.patch.object(server, "_log"), \
                self.assertLogs(server.app.logger, level="ERROR"):
            response = self.client.post("/api/connect", json={},
                                        base_url="http://127.0.0.1:45678")

        self.assertEqual(response.status_code, 500)

    def test_vless_xhttp_over_mihomo_still_builds(self):
        profile_state.apps_config = {"mode": "all", "apps": [], "rules": [
            custom_rule(destination="proxy")]}
        xhttp = dict(self.live, type="xhttp", path="/x")
        profile_state.groups = [{"id": "g", "name": "G", "servers": [xhttp]}]

        response = self._connect()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_hysteria2_still_builds(self):
        from engine.config import parse_link
        hy2 = {**parse_link("hy2://secret@127.0.0.1:443/"), "ui_id": "alive"}
        profile_state.groups = [{"id": "g", "name": "G", "servers": [hy2]}]
        profile_state.apps_config = {"mode": "all", "apps": [], "rules": []}

        response = self._connect()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
