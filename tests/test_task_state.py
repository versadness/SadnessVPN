import unittest

from engine.task_state import BackgroundTaskCoordinator


class BackgroundTaskCoordinatorTests(unittest.TestCase):
    def test_replaced_task_cannot_publish_late_result(self):
        coordinator = BackgroundTaskCoordinator()
        old_generation, old_stop = coordinator.begin()
        new_generation, new_stop = coordinator.begin()
        published = []

        old_ran = coordinator.run_if_current(
            old_generation,
            old_stop,
            lambda: published.append("old"),
        )
        new_ran = coordinator.run_if_current(
            new_generation,
            new_stop,
            lambda: published.append("new"),
        )

        self.assertTrue(old_stop.is_set())
        self.assertFalse(old_ran)
        self.assertTrue(new_ran)
        self.assertEqual(published, ["new"])

    def test_cancelled_task_cannot_publish(self):
        coordinator = BackgroundTaskCoordinator()
        generation, stop = coordinator.begin()
        coordinator.cancel()

        self.assertTrue(stop.is_set())
        self.assertFalse(
            coordinator.run_if_current(generation, stop, lambda: self.fail("ran"))
        )


if __name__ == "__main__":
    unittest.main()
