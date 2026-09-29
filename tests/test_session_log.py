"""Журнал подключения содержит только последнюю сессию.

Проверяются сам журнал (engine/session_log.py) и жизненный цикл в бэкенде:
нажатие «Подключить» и автоподключение начинают новую сессию, отключение и
ошибка её закрывают, внутреннее переподключение и повторный клик журнал не
очищают, запоздавшая запись прошлой сессии в новую не попадает.
"""
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from engine.connection_state import ConnectionCoordinator
from engine.session_log import SessionLog
from ui import profile_state, server
from ui.routes import system as system_routes

BASE = "http://127.0.0.1:45678"


class SessionLogFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.log = SessionLog(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_start_clears_the_previous_session_before_its_first_record(self):
        first = self.log.start("подключение вручную")
        self.log.write("первая сессия")
        self.log.start("подключение вручную")
        text = self.log.read()
        self.assertNotIn("первая сессия", text)
        self.assertTrue(text.startswith("=== Сессия подключения"))
        # Запоздавшая запись прошлой сессии отбрасывается.
        self.assertFalse(self.log.write("поздняя строка", "log", first))
        self.assertNotIn("поздняя строка", self.log.read())

    def test_closed_session_stays_readable_and_rejects_new_records(self):
        self.log.start("подключение вручную")
        self.log.write("Отключено", "info")
        self.log.close()
        self.assertFalse(self.log.write("после отключения"))
        self.assertIn("Отключено", self.log.read())

    def test_last_session_survives_an_application_restart(self):
        self.log.start("подключение вручную")
        self.log.write("до перезапуска", "ok")
        self.log.close()
        restarted = SessionLog(self.directory.name)
        self.assertIn("до перезапуска", restarted.read())
        self.assertFalse(restarted.open)
        self.assertFalse(restarted.write("вне сессии"))

    def test_secrets_are_not_written(self):
        self.log.start("подключение вручную")
        self.log.write("PrivateKey = SECRETKEY https://sub.example/token/ABC password=hunter2", "err")
        text = self.log.read()
        for secret in ("SECRETKEY", "sub.example/token", "hunter2"):
            self.assertNotIn(secret, text)

    def test_long_session_keeps_its_beginning_and_bounded_size(self):
        small = SessionLog(self.directory.name, head_limit=400, tail_limit=400)
        small.start("подключение вручную")
        small.write("начало: подготовка конфигурации")
        for index in range(200):
            small.write(f"строка {index:03d} " + "x" * 40)
        text = small.read()
        self.assertIn("начало: подготовка конфигурации", text)
        self.assertIn("строка 199", text)
        self.assertIn("опущена", text)
        self.assertLess(len(text), 2000)


class FakeEngine:
    """Ядро без процесса: пишет в журнал так же, как MihomoManager."""
    name = "Mihomo"

    def __init__(self):
        self.log_cb = lambda message, tag: None
        self.running = False
        self.fail_next = False
        self.runs = 0

    def start(self, config):
        self.runs += 1
        self.log_cb(f"Mihomo запущен · запуск {self.runs}", "ok")
        if self.fail_next:
            self.fail_next = False
            self.log_cb("Ошибка конфигурации Mihomo: сервер не отвечает", "err")
            return False
        self.running = True
        return True

    def stop(self):
        if self.running:
            self.running = False
            self.log_cb("Mihomo остановлен", "info")

    def is_alive(self):
        return self.running

    def request_stop(self):
        pass

    def has_owned_service(self):
        return False

    @staticmethod
    def _port_free(_port):
        return True

    @staticmethod
    def _port_owner(_port):
        return ""


class ConnectionSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = server.app.test_client()
        self.events = []
        self.engine, self.awg = FakeEngine(), FakeEngine()
        self.saved = (profile_state.groups, profile_state.apps_config, server._connection,
                      dict(server._app_settings))
        server._connection = ConnectionCoordinator()
        profile_state.groups = [{"id": "g", "name": "G", "servers": [
            {"remark": "Germany", "protocol": "vless", "host": "127.0.0.1", "port": 443,
             "uuid": "0" * 8, "security": "tls", "type": "tcp", "ui_id": "de"}]}]
        profile_state.apps_config = {"mode": "all", "apps": [], "rules": []}
        server._app_settings.update(selected_group="g", selected_index=0, active_protocol="vless",
                                    reconnect=False)
        self.session_log = SessionLog(self.directory.name)
        patches = [
            mock.patch.object(server, "session_log", self.session_log),
            mock.patch.object(system_routes.deps, "session_log", self.session_log),
            mock.patch.object(server, "vpn_engine", self.engine),
            mock.patch.object(server, "awg_engine", self.awg),
            mock.patch.object(server, "_broadcast", side_effect=self.events.append),
            mock.patch.object(server, "_wait_clash_ready", return_value=True),
            mock.patch.object(server, "_repair_saved_routes"),
            mock.patch.object(server, "_protect_vpn_from_zapret"),
            mock.patch.object(server, "_start_ping_monitor"),
            mock.patch.object(server, "_start_traffic_monitor"),
            mock.patch.object(server, "_stop_ping_monitor"),
            mock.patch.object(server, "_stop_traffic_monitor"),
            mock.patch.object(server, "stats_tracker"),
            mock.patch.object(server, "_ensure_clash_port", return_value=9090),
            mock.patch.object(server, "_ensure_local_proxy_ports", return_value=False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        profile_state.groups, profile_state.apps_config, server._connection, settings = self.saved
        server._app_settings.clear()
        server._app_settings.update(settings)
        self.directory.cleanup()

    # ── помощники ──────────────────────────────────────────────────────────

    def wait_for(self, predicate, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("состояние не наступило")

    def connect(self, **body):
        response = self.client.post("/api/connect", json={"protocol": "vless", **body}, base_url=BASE)
        return response

    def connect_and_wait(self, **body):
        response = self.connect(**body)
        self.assertTrue(response.get_json()["ok"], response.get_json())
        self.wait_for(lambda: server._connection.state in ("on", "off")
                      and not any(t.name == "session-test" for t in threading.enumerate()))
        self.wait_for(lambda: server._connection.state == "on" or not self.session_log.open)
        return response

    def disconnect_and_wait(self):
        self.client.post("/api/disconnect", json={}, base_url=BASE)
        self.wait_for(lambda: server._connection.state == "off" and not server._stopping
                      and not self.session_log.open)

    def journal(self):
        return self.client.get("/api/diagnostics", base_url=BASE).get_json()

    def resets(self):
        return sum(1 for e in self.events if e.get("type") == "session_log_reset")

    # ── сценарии ───────────────────────────────────────────────────────────

    def test_1_first_session_is_kept_after_disconnect(self):
        self.connect_and_wait()
        self.assertEqual(server._connection.state, "on")
        self.disconnect_and_wait()
        body = self.journal()
        self.assertFalse(body["empty"])
        self.assertFalse(body["active"])
        text = body["text"]
        for line in ("подключение вручную", "Подключение к Germany", "Mihomo запущен · запуск 1",
                     "TUN-интерфейс поднят", "Mihomo остановлен", "Отключено"):
            self.assertIn(line, text)
        # После отключения посторонние записи в журнал сессии не попадают.
        server._log("Изменены настройки после отключения", "info")
        self.assertNotIn("после отключения", self.journal()["text"])

    def test_2_second_connection_replaces_the_first_session(self):
        self.connect_and_wait()
        self.disconnect_and_wait()
        self.connect_and_wait()
        text = self.journal()["text"]
        self.assertNotIn("запуск 1", text)
        self.assertIn("запуск 2", text)
        self.assertEqual(text.count("=== Сессия подключения"), 1)
        self.assertEqual(self.resets(), 2)
        self.disconnect_and_wait()

    def test_3_failed_connection_is_kept_until_the_next_attempt(self):
        self.engine.fail_next = True
        self.connect()
        self.wait_for(lambda: server._connection.state == "off" and not self.session_log.open)
        text = self.journal()["text"]
        self.assertIn("Ошибка конфигурации Mihomo", text)
        self.assertIn("Подключение не установлено", text)
        # Ошибка до начала попытки тоже остаётся в журнале.
        server._app_settings["selected_index"] = 7
        response = self.connect()
        self.assertFalse(response.get_json()["ok"])
        text = self.journal()["text"]
        self.assertIn("Сервер не выбран", text)
        self.assertNotIn("Ошибка конфигурации Mihomo", text)
        self.assertFalse(self.session_log.open)

    def test_4_auto_connect_starts_a_new_session(self):
        self.connect_and_wait()
        self.disconnect_and_wait()
        self.connect_and_wait(auto=True)
        text = self.journal()["text"]
        self.assertIn("автоподключение", text.splitlines()[0])
        self.assertNotIn("запуск 1", text)
        self.disconnect_and_wait()

    def test_5_reconnect_and_repeated_click_do_not_clear_the_journal(self):
        server._app_settings["reconnect"] = True
        self.connect_and_wait()
        # Повторный клик, пока VPN работает: отказ без очистки журнала.
        self.assertEqual(self.connect().status_code, 409)
        # Ядро неожиданно завершилось — переподключение внутри той же сессии.
        with mock.patch.object(server._reconnector, "start",
                               side_effect=lambda: server._reconnect_selected()):
            self.engine.running = False
            server._handle_vpn_exit(1)
        self.wait_for(lambda: server._connection.state == "on")
        text = self.journal()["text"]
        self.assertIn("запуск 1", text)
        self.assertIn("запуск 2", text)
        self.assertEqual(self.resets(), 1)
        self.assertEqual(text.count("=== Сессия подключения"), 1)
        self.disconnect_and_wait()

    def test_5b_click_during_connection_is_rejected_before_clearing(self):
        gate = threading.Event()
        original = self.engine.start

        def slow_start(config):
            gate.wait(5)
            return original(config)

        self.engine.start = slow_start
        self.assertTrue(self.connect().get_json()["ok"])
        self.wait_for(lambda: server._connection.state == "connecting")
        server._log("идёт подключение", "info")
        self.assertEqual(self.connect().status_code, 409)
        self.assertIn("идёт подключение", self.journal()["text"])
        self.assertEqual(self.resets(), 1)
        gate.set()
        self.wait_for(lambda: server._connection.state == "on")
        self.disconnect_and_wait()

    def test_5c_late_record_from_the_previous_session_is_dropped(self):
        self.connect_and_wait()
        stale_logger = self.engine.log_cb
        self.disconnect_and_wait()
        self.connect_and_wait()
        stale_logger("поздняя строка старого ядра", "info")
        self.assertNotIn("поздняя строка", self.journal()["text"])
        self.disconnect_and_wait()

    def test_6_last_journal_is_available_after_restart_without_connecting(self):
        self.connect_and_wait()
        self.disconnect_and_wait()
        restarted = SessionLog(self.directory.name)
        with mock.patch.object(system_routes.deps, "session_log", restarted):
            body = self.journal()
        self.assertIn("Отключено", body["text"])
        self.assertIn("запуск 1", body["text"])

    def test_system_events_never_enter_the_session_journal(self):
        self.connect_and_wait()
        server._system_log("Подписка «Remnawave» обновлена", "ok")
        self.assertNotIn("Remnawave", self.journal()["text"])
        self.disconnect_and_wait()


if __name__ == "__main__":
    unittest.main()
