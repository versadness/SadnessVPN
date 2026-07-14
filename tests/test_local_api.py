import unittest

from ui import server


class LocalApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_health_identifies_this_exact_server_instance(self):
        response = self.client.get(
            "/api/health",
            base_url="http://127.0.0.1:45678",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["instance"], server.SERVER_INSTANCE_ID)

    def test_dns_rebinding_host_is_rejected(self):
        response = self.client.get("/api/health", base_url="http://attacker.invalid")

        self.assertEqual(response.status_code, 403)

    def test_cross_origin_browser_request_is_rejected(self):
        response = self.client.get(
            "/api/health",
            base_url="http://127.0.0.1:45678",
            headers={"Origin": "https://attacker.invalid"},
        )

        self.assertEqual(response.status_code, 403)

    def test_non_loopback_client_is_rejected(self):
        response = self.client.get(
            "/api/health",
            base_url="http://127.0.0.1:45678",
            environ_base={"REMOTE_ADDR": "192.0.2.10"},
        )

        self.assertEqual(response.status_code, 403)

    def test_invalid_or_reserved_proxy_ports_are_rejected_without_mutation(self):
        original = (server._socks_port, server._http_port)
        cases = (
            {"socks": 0, "http": 8080},
            {"socks": 8080, "http": 8080},
            {"socks": 45678, "http": 8080},
            {"socks": 1080, "http": 9090},
        )

        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/settings",
                    json=payload,
                    base_url="http://127.0.0.1:45678",
                )
                self.assertFalse(response.get_json()["ok"])
                self.assertEqual((server._socks_port, server._http_port), original)

    def test_invalid_tunnel_setting_is_rejected_without_mutation(self):
        original = server._app_settings["preferred_ip"]

        response = self.client.post(
            "/api/tunnel-settings",
            json={"preferred_ip": "sideways"},
            base_url="http://127.0.0.1:45678",
        )

        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(server._app_settings["preferred_ip"], original)


if __name__ == "__main__":
    unittest.main()
