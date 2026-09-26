import unittest
from unittest import mock

from flask import jsonify

from ui import app_state, profile_state, server


class SubscriptionAutoupdateTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(server._app_settings)
        self.groups = list(profile_state.groups)
        profile_state.groups[:] = [{"id": "sub-1", "name": "Подписка",
                                    "url": "https://sub.example/list", "servers": []}]

    def tearDown(self):
        server._app_settings.clear()
        server._app_settings.update(self.settings)
        profile_state.groups[:] = self.groups

    def run_on_start(self):
        with mock.patch.object(server, "_start_subscription_refresh_all",
                               side_effect=lambda: jsonify(ok=True, queued=1)) as refresh, \
                mock.patch.object(server, "_log"):
            server._autoupdate_subscriptions_on_start(delay=0)
        return refresh

    def test_enabled_by_default(self):
        self.assertTrue(app_state.DEFAULT_SETTINGS["sub_autoupdate"])
        self.assertIn("sub_autoupdate", app_state.USER_APP_SETTING_KEYS)

    def test_subscriptions_refresh_when_the_app_starts(self):
        server._app_settings["sub_autoupdate"] = True
        self.run_on_start().assert_called_once()

    def test_user_can_turn_it_off(self):
        server._app_settings["sub_autoupdate"] = False
        self.run_on_start().assert_not_called()

    def test_nothing_happens_without_subscriptions(self):
        server._app_settings["sub_autoupdate"] = True
        profile_state.groups[:] = [{"id": "manual", "name": "Вручную", "url": "", "servers": []}]
        with mock.patch.object(profile_state, "wg_groups", []):
            self.run_on_start().assert_not_called()

    def test_setting_accepts_only_booleans(self):
        self.assertIs(app_state.normalize_app_setting("sub_autoupdate", False), False)
        with self.assertRaises(ValueError):
            app_state.normalize_app_setting("sub_autoupdate", "yes")


if __name__ == "__main__":
    unittest.main()
