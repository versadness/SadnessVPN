"""Регрессия: «Обновить подписки» обновлял только первую подписку.

Интерфейс слал запросы по всем группам параллельно, бэкенд принимал первый,
а остальные получали 409 «Подписка уже обновляется». Теперь все подписки
обновляются одной очередью, и сбой одной не мешает остальным.
"""
import time
import unittest
from unittest import mock

from engine.connection_state import ConnectionCoordinator
from engine.subscriptions import SubscriptionError, SubscriptionServers
from ui import profile_state
from ui import server


def node(remark, host, port=443, **extra):
    return {"remark": remark, "protocol": "vless", "host": host, "port": port,
            "uuid": "0" * 8, "security": "reality", "type": "xhttp", **extra}


class RefreshAllTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        self.saved = (profile_state.groups, profile_state.wg_groups, server._connection, dict(server._app_settings))
        server._connection = ConnectionCoordinator()
        profile_state.groups = [
            {"id": "down", "name": "Упавший провайдер", "url": "https://down.example/sub/a", "servers": [node("Old", "198.51.100.1")],
             "subscription": {"updated_at": 100, "error": ""}},
            {"id": "rw", "name": "Remnawave", "url": "https://rw.example/sub/b", "servers": [node("Germany", "198.51.100.2")],
             "subscription": {"updated_at": 100, "error": ""}},
        ]
        profile_state.wg_groups = []

    def tearDown(self):
        profile_state.groups, profile_state.wg_groups, server._connection, settings = self.saved
        server._app_settings.clear()
        server._app_settings.update(settings)

    def _wait_idle(self):
        deadline = time.time() + 5
        while server._subscription_lock.locked() and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(server._subscription_lock.locked())

    def test_every_subscription_is_refreshed_even_if_the_first_fails(self):
        calls = []

        def fake_fetch(url, hwid=""):
            calls.append(url)
            if "down" in url:
                error = SubscriptionError("Не удалось загрузить подписку: ошибка сети, DNS или TLS.")
                error.metadata = {}
                raise error
            return SubscriptionServers([node("Germany", "198.51.100.2"), node("Finland", "198.51.100.3")],
                                       {"received": 2, "accepted": 2, "rejected": []})

        with mock.patch.object(server, "fetch_subscription", side_effect=fake_fetch), \
                mock.patch.object(profile_state, "save_proxy_groups"), \
                mock.patch.object(server, "_save_settings", return_value=True), \
                mock.patch.object(server, "_repair_saved_routes"), \
                mock.patch.object(server, "_broadcast"), mock.patch.object(server, "_log"):
            response = self.client.post("/api/groups/refresh-all", json={}, base_url="http://127.0.0.1:45678")
            self.assertTrue(response.get_json()["ok"])
            self.assertEqual(response.get_json()["queued"], 2)
            self._wait_idle()

        self.assertEqual(calls, ["https://down.example/sub/a", "https://rw.example/sub/b"])
        down, rw = profile_state.groups
        # Сбой: последняя рабочая подписка сохранена, время успеха прежнее.
        self.assertEqual([s["remark"] for s in down["servers"]], ["Old"])
        self.assertEqual(down["subscription"]["updated_at"], 100)
        self.assertGreater(down["subscription"]["checked_at"], 100)
        self.assertTrue(down["subscription"]["error"])
        # Вторая подписка обновилась, хотя первая упала.
        self.assertEqual([s["remark"] for s in rw["servers"]], ["Germany", "Finland"])
        self.assertEqual(rw["subscription"]["accepted"], 2)
        self.assertEqual(rw["subscription"]["error"], "")
        self.assertGreater(rw["subscription"]["updated_at"], 100)

    def run_queue(self, fake_fetch, path="/api/groups/refresh-all", body=None):
        events = []
        with mock.patch.object(server, "fetch_subscription", side_effect=fake_fetch), \
                mock.patch.object(profile_state, "save_proxy_groups",
                                  side_effect=lambda: events.append({"type": "saved"})), \
                mock.patch.object(server, "_save_settings", return_value=True), \
                mock.patch.object(server, "_repair_saved_routes"), \
                mock.patch.object(server, "_broadcast_groups"), \
                mock.patch.object(server, "_broadcast", side_effect=events.append), \
                mock.patch.object(server, "_log"):
            response = self.client.post(path, json=body or {}, base_url="http://127.0.0.1:45678")
            self.assertTrue(response.get_json()["ok"])
            self._wait_idle()
            deadline = time.time() + 2
            while not any(e["type"] == "subscriptions_done" for e in events) and time.time() < deadline:
                time.sleep(0.02)
        return events

    def test_queue_reports_progress_each_result_and_a_summary(self):
        from engine.subscriptions import SubscriptionNotModified
        profile_state.groups.append(
            {"id": "same", "name": "Без изменений", "url": "https://same.example/sub/c",
             "servers": [node("Latvia", "198.51.100.4")], "subscription": {"updated_at": 100, "error": ""}})

        def fake_fetch(url, hwid=""):
            if "down" in url:
                error = SubscriptionError("Сервер подписки не ответил за 25 секунд.")
                error.metadata = {}
                raise error
            if "same" in url:
                error = SubscriptionNotModified()
                error.metadata = {}
                raise error
            return SubscriptionServers([node("Germany", "198.51.100.2"), node("Finland", "198.51.100.3")],
                                       {"received": 2, "accepted": 2, "rejected": []})

        events = self.run_queue(fake_fetch)
        kinds = [e["type"] for e in events]
        progress = [e for e in events if e["type"] == "subscription_progress"]
        self.assertEqual([(p["position"], p["total"]) for p in progress], [(1, 3), (2, 3), (3, 3)])
        results = {e["id"]: e for e in events if e["type"] == "subscription_result"}
        self.assertEqual(results["down"]["result"], "error")
        self.assertIn("25 секунд", results["down"]["error"])
        self.assertEqual((results["rw"]["result"], results["rw"]["accepted"]), ("updated", 2))
        self.assertEqual(results["same"]["result"], "unchanged")
        done = events[-1]
        self.assertEqual(done["type"], "subscriptions_done")
        self.assertEqual((done["total"], done["updated"], done["unchanged"], done["failed"]), (3, 1, 1, 1))
        self.assertFalse(done["auto"])
        # Итог — только после того, как результат сохранён.
        self.assertLess(max(i for i, k in enumerate(kinds) if k == "saved"), kinds.index("subscriptions_done"))
        # Итог последней попытки хранится в профиле и переживает перезапуск.
        by_id = {g["id"]: g["subscription"] for g in profile_state.groups}
        self.assertEqual((by_id["down"]["last_result"], by_id["rw"]["last_result"], by_id["same"]["last_result"]),
                         ("error", "updated", "unchanged"))
        # Ссылки подписок не попадают в события интерфейса.
        self.assertNotIn("example/sub", repr(events))

    def test_single_refresh_is_reported_as_one_result(self):
        events = self.run_queue(
            lambda url, hwid="": SubscriptionServers([node("Germany", "198.51.100.2")],
                                                     {"received": 1, "accepted": 1, "rejected": []}),
            path="/api/groups/refresh", body={"id": "rw"})
        done = events[-1]
        self.assertEqual((done["type"], done["total"], done["updated"], done["failed"]),
                         ("subscriptions_done", 1, 1, 0))
        self.assertEqual(done["results"][0]["name"], "Remnawave")

    def test_startup_refresh_is_marked_as_automatic(self):
        with mock.patch.object(server, "_run_subscription_jobs", return_value=("ok", 200)) as run:
            with server.app.app_context():
                server._start_subscription_refresh_all(auto=True)
        self.assertTrue(run.call_args.kwargs["auto"])


class StableIdentityTests(unittest.TestCase):
    def setUp(self):
        self.saved = (profile_state.groups, dict(server._app_settings))

    def tearDown(self):
        profile_state.groups, settings = self.saved
        server._app_settings.clear()
        server._app_settings.update(settings)

    def test_changed_address_keeps_selection_and_route_identity(self):
        # Панель перевела Финляндию на ретранслятор: адрес и порт другие,
        # имя и протокол прежние — это тот же сервер.
        finland = node("🇫🇮 Finland VLESS-XHTTP", "198.51.100.3", 30444, ui_id="fi")
        germany = node("🇩🇪 Germany VLESS-XHTTP", "198.51.100.2", 30444, ui_id="de")
        group = {"id": "g", "name": "G", "url": "https://example.invalid", "servers": [finland, germany]}
        profile_state.groups = [group]
        server._app_settings["selected_group"] = "g"
        server._app_settings["selected_index"] = 0
        fresh = [node("🇫🇮 Finland VLESS-XHTTP", "198.51.100.2", 10446), node("🇩🇪 Germany VLESS-XHTTP", "198.51.100.2", 30444)]

        with mock.patch.object(server, "_save_settings", return_value=True):
            server._replace_group_servers(group, fresh)

        self.assertEqual([s["ui_id"] for s in group["servers"]], ["fi", "de"])
        self.assertEqual(server._app_settings["selected_index"], 0)

    def test_ambiguous_names_are_not_guessed(self):
        old = [node("Auto", "198.51.100.4", ui_id="a1"), node("Auto", "198.51.100.5", ui_id="a2")]
        group = {"id": "g", "name": "G", "url": "https://example.invalid", "servers": old}
        profile_state.groups = [group]
        server._app_settings["selected_group"] = None
        server._app_settings["selected_index"] = None
        fresh = [node("Auto", "198.51.100.6"), node("Auto", "198.51.100.7")]

        with mock.patch.object(server, "_save_settings", return_value=True):
            server._replace_group_servers(group, fresh)

        self.assertFalse({s["ui_id"] for s in group["servers"]} & {"a1", "a2"})


if __name__ == "__main__":
    unittest.main()
