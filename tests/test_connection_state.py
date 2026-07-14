import threading
import unittest
from pathlib import Path

from engine.connection_state import ConnectionCoordinator


class ConnectionCoordinatorTests(unittest.TestCase):
    def test_rejects_overlapping_connection_attempt(self):
        coordinator = ConnectionCoordinator()

        first = coordinator.begin()
        second = coordinator.begin()

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(coordinator.state, "connecting")

    def test_cancelled_attempt_cannot_complete_later(self):
        coordinator = ConnectionCoordinator()
        attempt = coordinator.begin()
        activated = []

        coordinator.cancel()
        completed = coordinator.complete(attempt, lambda: activated.append(True))

        self.assertFalse(completed)
        self.assertEqual(activated, [])
        self.assertEqual(coordinator.state, "off")
        self.assertFalse(coordinator.connected)

    def test_current_attempt_completes_once(self):
        coordinator = ConnectionCoordinator()
        attempt = coordinator.begin()
        activated = []

        first = coordinator.complete(attempt, lambda: activated.append(True))
        second = coordinator.complete(attempt, lambda: activated.append(True))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(activated, [True])
        self.assertTrue(coordinator.connected)

    def test_cancelled_attempt_cannot_publish_late_progress(self):
        coordinator = ConnectionCoordinator()
        attempt = coordinator.begin()
        published = []
        coordinator.cancel()

        ran = coordinator.run_if_current(attempt, lambda: published.append(True))

        self.assertFalse(ran)
        self.assertEqual(published, [])

    def test_failure_from_cancelled_attempt_does_not_replace_new_state(self):
        coordinator = ConnectionCoordinator()
        old_attempt = coordinator.begin()
        coordinator.cancel()
        new_attempt = coordinator.begin()

        failed = coordinator.fail(old_attempt)

        self.assertFalse(failed)
        self.assertTrue(coordinator.is_current(new_attempt))
        self.assertEqual(coordinator.state, "connecting")

    def test_cancel_waits_for_active_transition_then_wins(self):
        coordinator = ConnectionCoordinator()
        attempt = coordinator.begin()
        transition_started = threading.Event()
        release_transition = threading.Event()
        cancel_finished = threading.Event()

        def transition():
            transition_started.set()
            release_transition.wait(timeout=2)

        def cancel():
            coordinator.cancel()
            cancel_finished.set()

        transition_thread = threading.Thread(
            target=lambda: coordinator.run_if_current(attempt, transition)
        )
        cancel_thread = threading.Thread(target=cancel)

        transition_thread.start()
        self.assertTrue(transition_started.wait(timeout=1))
        cancel_thread.start()
        self.assertFalse(cancel_finished.wait(timeout=0.05))
        release_transition.set()
        transition_thread.join(timeout=1)
        cancel_thread.join(timeout=1)

        self.assertFalse(transition_thread.is_alive())
        self.assertFalse(cancel_thread.is_alive())
        self.assertTrue(cancel_finished.is_set())
        self.assertEqual(coordinator.state, "off")


class ServerConnectionSafetyTests(unittest.TestCase):
    def test_server_does_not_use_unsynchronised_connected_flag(self):
        path = Path(__file__).resolve().parents[1].joinpath("ui", "server.py")
        source = path.read_text(encoding="utf-8")

        self.assertNotIn("_connected", source)
        self.assertIn("ConnectionCoordinator", source)
        self.assertIn("_connection.cancel", source)

    def test_ui_can_cancel_a_connecting_attempt(self):
        path = Path(__file__).resolve().parents[1].joinpath(
            "ui", "templates", "index.html"
        )
        source = path.read_text(encoding="utf-8")

        self.assertIn(
            "ST.status==='on'||ST.status==='connecting'",
            source,
        )
        self.assertIn("lbl.textContent='Отменить'", source)

    def test_server_handles_unexpected_engine_exit(self):
        path = Path(__file__).resolve().parents[1].joinpath("ui", "server.py")
        source = path.read_text(encoding="utf-8")

        self.assertIn("def _handle_vpn_exit", source)
        self.assertIn("exit_callback=_handle_vpn_exit", source)


if __name__ == "__main__":
    unittest.main()
