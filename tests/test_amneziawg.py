import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.amneziawg import AmneziaWGManager, build_amneziawg_config


def _server():
    return {
        "private_key": "A" * 43 + "=",
        "address": ["10.8.0.2/32"],
        "dns": ["1.1.1.1"],
        "mtu": 1280,
        "endpoint": "198.51.100.20",
        "port": 585,
        "peer_public_key": "B" * 43 + "=",
        "pre_shared_key": "C" * 43 + "=",
        "persistent_keepalive": 15,
        "source_allowed_ips": ["10.0.0.0/8"],
        "awg_fields": {
            "jc": "5",
            "jmin": "10",
            "jmax": "50",
            "s1": "64",
            "s2": "96",
            "h1": "123456",
            "h2": "234567",
            "h3": "345678",
            "h4": "456789",
            "i1": "<b 0x0c><r 16>",
        },
        "is_awg": True,
    }


class AmneziaWGConfigTests(unittest.TestCase):
    def test_native_config_preserves_obfuscation_fields(self):
        text = build_amneziawg_config(_server())

        self.assertIn("Jc = 5", text)
        self.assertIn("Jmin = 10", text)
        self.assertIn("S1 = 64", text)
        self.assertIn("H4 = 456789", text)
        self.assertIn("I1 = <b 0x0c><r 16>", text)
        self.assertIn("PersistentKeepalive = 15", text)
        self.assertIn("AllowedIPs = 0.0.0.0/0, ::/0", text)

    def test_diagnostic_config_can_keep_original_routes(self):
        text = build_amneziawg_config(_server(), force_full_route=False)

        self.assertIn("AllowedIPs = 10.0.0.0/8", text)
        self.assertNotIn("AllowedIPs = 0.0.0.0/0", text)

    def test_rejects_line_injection_from_persisted_data(self):
        server = _server()
        server["endpoint"] = "safe.example\nPostUp = calc.exe"

        with self.assertRaises(ValueError):
            build_amneziawg_config(server)


class AmneziaWGManagerTests(unittest.TestCase):
    def test_start_requires_verified_handshake(self):
        messages = []
        manager = AmneziaWGManager(
            log_callback=lambda message, tag: messages.append((message, tag))
        )

        with tempfile.TemporaryDirectory() as root:
            manager_exe = Path(root, "amneziawg.exe")
            awg_exe = Path(root, "awg.exe")
            manager_exe.touch()
            awg_exe.touch()
            config_path = Path(root, "SadnessVPN.conf")

            with (
                mock.patch.object(manager, "_manager_path", return_value=str(manager_exe)),
                mock.patch.object(manager, "_awg_path", return_value=str(awg_exe)),
                mock.patch.object(manager, "_write_config", return_value=str(config_path)),
                mock.patch.object(manager, "_uninstall_owned_service", return_value=True),
                mock.patch.object(manager, "_wait_handshake", return_value=True),
                mock.patch.object(manager, "_remove_config"),
                mock.patch.object(manager, "_monitor_service"),
                mock.patch("engine.amneziawg.platform.system", return_value="Windows"),
                mock.patch.object(
                    manager,
                    "_run",
                    return_value=mock.Mock(returncode=0, stdout="", stderr=""),
                ),
            ):
                result = manager.start(_server())

        self.assertTrue(result)
        self.assertTrue(manager.running)
        self.assertTrue(any("handshake" in message for message, _tag in messages))

    def test_failed_handshake_removes_own_service(self):
        manager = AmneziaWGManager()
        with tempfile.TemporaryDirectory() as root:
            manager_exe = Path(root, "amneziawg.exe")
            awg_exe = Path(root, "awg.exe")
            manager_exe.touch()
            awg_exe.touch()

            with (
                mock.patch.object(manager, "_manager_path", return_value=str(manager_exe)),
                mock.patch.object(manager, "_awg_path", return_value=str(awg_exe)),
                mock.patch.object(manager, "_write_config", return_value=str(Path(root, "SadnessVPN.conf"))),
                mock.patch.object(manager, "_wait_handshake", return_value=False),
                mock.patch.object(manager, "_remove_config"),
                mock.patch("engine.amneziawg.platform.system", return_value="Windows"),
                mock.patch.object(
                    manager,
                    "_run",
                    return_value=mock.Mock(returncode=0, stdout="", stderr=""),
                ),
                mock.patch.object(manager, "_uninstall_owned_service", return_value=True) as uninstall,
            ):
                result = manager.start(_server())

        self.assertFalse(result)
        self.assertGreaterEqual(uninstall.call_count, 2)


if __name__ == "__main__":
    unittest.main()
