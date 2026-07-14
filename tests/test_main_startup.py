import json
import unittest
from unittest import mock

import main


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size < 0:
            return self._payload
        return self._payload[:size]


class LocalServerStartupTests(unittest.TestCase):
    def test_silent_startup_preference_is_loaded_safely(self):
        with (
            mock.patch.object(main, "data_dir", return_value=r"C:\data"),
            mock.patch("builtins.open", mock.mock_open(read_data='{"silent": true}')),
        ):
            self.assertEqual(main.load_startup_preferences(), {"silent": True})

    def test_wait_accepts_only_the_expected_server_instance(self):
        response = _Response({"app": "SadnessVPN", "instance": "expected"})

        with mock.patch.object(main.urllib.request, "urlopen", return_value=response):
            self.assertTrue(
                main.wait_for_server(timeout=0.2, expected_instance="expected")
            )

    def test_wait_rejects_another_service_on_the_same_port(self):
        response = _Response({"app": "SadnessVPN", "instance": "foreign"})

        with (
            mock.patch.object(main.urllib.request, "urlopen", return_value=response),
            mock.patch.object(main.time, "perf_counter", side_effect=[0.0, 0.0, 1.0]),
            mock.patch.object(main.time, "sleep"),
        ):
            self.assertFalse(
                main.wait_for_server(timeout=0.2, expected_instance="expected")
            )


if __name__ == "__main__":
    unittest.main()
