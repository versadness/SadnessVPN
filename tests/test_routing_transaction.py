"""Транзакционное применение маршрутов: сначала ядро, потом диск.

«Сохранено и применено» не должно появляться там, где Mihomo откажется
запускаться с этой конфигурацией. Поэтому кандидат отдаётся ядру на проверку
до записи, а прежняя рабочая конфигурация остаётся нетронутой.
"""
import unittest
from unittest import mock

from engine.connection_state import ConnectionCoordinator
from ui import profile_state
from ui import server

BASE = "http://127.0.0.1:45678"

RULE = {"id": "rule-1", "kind": "suffix", "value": "example.com",
        "name": "Example", "destination": "proxy", "enabled": True}


class RoutingTransactionTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.groups = profile_state.groups
        self.apps_config = profile_state.apps_config
        self.connection = server._connection
        self.settings = dict(server._app_settings)
        server._connection = ConnectionCoordinator()
        self.live = {"remark": "Live", "protocol": "vless", "host": "127.0.0.1",
                     "port": 443, "uuid": "0" * 8, "security": "tls", "type": "tcp",
                     "ui_id": "alive"}
        profile_state.groups = [{"id": "g", "name": "G", "servers": [self.live]}]
        profile_state.apps_config = {"mode": "all", "apps": [], "rules": []}
        server._app_settings["selected_group"] = "g"
        server._app_settings["selected_index"] = 0
        server._app_settings["active_protocol"] = "vless"

    def tearDown(self):
        profile_state.groups = self.groups
        profile_state.apps_config = self.apps_config
        server._connection = self.connection
        server._app_settings.clear()
        server._app_settings.update(self.settings)

    def _post(self, rules):
        with mock.patch.object(server, "save_apps") as save, \
                mock.patch.object(server, "_broadcast"), mock.patch.object(server, "_log"):
            response = self.client.post("/api/routing/rules", json={"rules": rules},
                                        base_url=BASE)
        return response, save

    def test_the_real_core_accepts_a_valid_rule_set(self):
        response, save = self._post([RULE])

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        save.assert_called_once()
        self.assertEqual(profile_state.apps_config["rules"][0]["value"], "example.com")

    def test_a_rejected_configuration_is_never_written_to_disk(self):
        with mock.patch.object(server.vpn_engine, "validate",
                               return_value=(False, "unsupported rule")):
            response, save = self._post([RULE])

        self.assertEqual(response.status_code, 422)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("Ядро отклонило конфигурацию", body["error"])
        save.assert_not_called()
        # Прежняя конфигурация осталась прежней.
        self.assertEqual(profile_state.apps_config["rules"], [])

    def test_core_check_runs_without_creating_a_tun_or_clash_api(self):
        seen = {}

        def capture(config):
            seen.update(config)
            return True, ""

        with mock.patch.object(server.vpn_engine, "validate", side_effect=capture):
            self._post([RULE])

        self.assertFalse(seen["tun"]["enable"])
        self.assertNotIn("external-controller", seen)
        self.assertTrue(any(rule.startswith("DOMAIN-SUFFIX,example.com")
                            for rule in seen["rules"]))

    def test_without_a_selected_server_editing_rules_is_still_allowed(self):
        server._app_settings["selected_group"] = None
        server._app_settings["selected_index"] = None

        with mock.patch.object(server.vpn_engine, "validate") as validate:
            response, save = self._post([RULE])

        validate.assert_not_called()
        self.assertEqual(response.status_code, 200)
        save.assert_called_once()

    def test_an_unsupported_server_is_reported_instead_of_being_saved(self):
        profile_state.groups = [{"id": "g", "name": "G",
                                 "servers": [{**self.live, "type": "kcp"}]}]

        response, save = self._post([RULE])

        self.assertEqual(response.status_code, 422)
        self.assertIn("kcp", response.get_json()["error"])
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
