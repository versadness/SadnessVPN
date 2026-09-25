"""HTTP-контракт игрового фильтра: 400 на ввод, 409 на живой Zapret, 500 на запись."""
import unittest
from unittest import mock

from engine import game_filter
from ui import app_state, server

BASE = "http://127.0.0.1:45678"


class GameFilterApiTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.previous = app_state.app_settings.get("zapret_game_filter")
        app_state.app_settings["zapret_game_filter"] = dict(game_filter.DEFAULTS)
        patcher = mock.patch.object(app_state, "save_settings", return_value=True)
        self.save = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(
            app_state.app_settings.__setitem__, "zapret_game_filter", self.previous
        )

    def post(self, payload):
        return self.client.post("/api/zapret/game-filter", json=payload, base_url=BASE)

    def test_reading_returns_the_stored_value_and_its_effective_summary(self):
        response = self.client.get("/api/zapret/game-filter", base_url=BASE)
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["game_filter"]["mode"], "off")
        self.assertEqual(body["summary"]["mode_label"], "Выключен")
        self.assertIn("не то же самое", body["summary"]["note"])
        # Сырая командная строка наружу не уходит.
        self.assertNotIn("winws", repr(body))
        self.assertNotIn("--filter", repr(body))

    def test_a_valid_configuration_is_normalized_and_saved(self):
        response = self.post({"game_filter": {"mode": "both", "udp_start": "27000",
                                              "udp_end": 27100, "ipset": "all"}})
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["game_filter"]["udp_start"], 27000)
        self.assertEqual(body["game_filter"]["ipset"], "all")
        self.assertEqual(body["summary"]["udp_label"], "27000-27100")
        self.assertTrue(self.save.called)

    def test_invalid_user_input_is_a_400_and_nothing_is_written(self):
        for payload in (
            {"game_filter": {"mode": "both", "tcp_start": 0}},
            {"game_filter": {"mode": "both", "tcp_start": 70000}},
            {"game_filter": {"mode": "both", "tcp_start": 5000, "tcp_end": 100}},
            {"game_filter": {"mode": "everything"}},
            {"game_filter": {"mode": "both", "ipset": "everything"}},
            {"game_filter": "1024-65535"},
        ):
            with self.subTest(payload=payload):
                self.save.reset_mock()
                response = self.post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])
                self.assertFalse(self.save.called)
                self.assertEqual(app_state.app_settings["zapret_game_filter"]["mode"], "off")

    def test_a_failed_write_is_a_500_and_the_previous_value_is_restored(self):
        self.save.return_value = False
        response = self.post({"game_filter": {"mode": "tcp"}})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(app_state.app_settings["zapret_game_filter"]["mode"], "off")

    def test_changing_the_filter_while_zapret_runs_is_refused(self):
        with mock.patch.object(server.zapret_service, "state", "on"):
            response = self.post({"game_filter": {"mode": "tcp"}})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(app_state.app_settings["zapret_game_filter"]["mode"], "off")

    def test_starting_zapret_passes_the_stored_filter_to_the_engine(self):
        app_state.app_settings["zapret_game_filter"] = {"mode": "udp", "udp_start": 3074,
                                                        "udp_end": 3079, "ipset": "list"}
        captured = {}

        def finish_start(strategy_id, generation, config=None, vpn_servers=None):
            captured["strategy"] = strategy_id
            captured["config"] = config
            captured["vpn_servers"] = vpn_servers
            return True

        with mock.patch.object(server.zapret_service, "finish_start", finish_start), \
             mock.patch.object(server.zapret_service, "begin_start", return_value=1):
            response = self.client.post("/api/zapret/start",
                                        json={"strategy_id": "flowseal_general"}, base_url=BASE)

        self.assertTrue(response.get_json()["ok"])
        for _ in range(200):
            if "config" in captured:
                break
            import time
            time.sleep(0.01)
        self.assertEqual(captured["config"]["mode"], "udp")
        self.assertEqual(captured["config"]["udp_start"], 3074)


if __name__ == "__main__":
    unittest.main()
