"""Linux: права ядра (пароль один раз), автозапуск XDG, возможности платформы."""
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import autostart_linux, linux_core, platform_info


def capability(effective=True, net_admin=True):
    magic = 0x02000000 | (1 if effective else 0)
    permitted = (1 << linux_core.CAP_NET_ADMIN) if net_admin else 0
    return struct.pack("<IIIII", magic, permitted, 0, 0, 0)


class CapabilityParsingTests(unittest.TestCase):
    def check(self, raw):
        with mock.patch.object(linux_core.os, "getxattr", return_value=raw, create=True):
            return linux_core.has_net_admin("/core")

    def test_effective_net_admin_is_recognised(self):
        self.assertTrue(self.check(capability()))

    def test_missing_or_partial_capabilities_are_rejected(self):
        self.assertFalse(self.check(capability(effective=False)))
        self.assertFalse(self.check(capability(net_admin=False)))
        self.assertFalse(self.check(b"\x00"))
        with mock.patch.object(linux_core.os, "getxattr", side_effect=OSError(61, "no data"), create=True):
            self.assertFalse(linux_core.has_net_admin("/core"))


class PrivilegedCoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.bundled = os.path.join(self.directory.name, "mihomo")
        Path(self.bundled).write_bytes(b"core-v1")
        self.caps = {}
        self.calls = []
        patches = [
            mock.patch.object(linux_core, "has_net_admin", side_effect=lambda path: self.caps.get(path, False)),
            mock.patch.object(linux_core.os, "geteuid", return_value=1000, create=True),
            mock.patch.object(linux_core.shutil, "which",
                              side_effect=lambda name, path=None: f"/usr/bin/{name}"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.directory.cleanup()

    def runner(self, returncode=0, grant=True):
        def run(command, **kwargs):
            self.calls.append(command)
            if grant and returncode == 0:
                self.caps[linux_core.INSTALLED_CORE] = True
            return subprocess.CompletedProcess(command, returncode, "", "")
        return run

    def test_package_installed_core_needs_no_password(self):
        self.caps[self.bundled] = True
        self.assertEqual(linux_core.ready_core(self.bundled, runner=self.runner()), self.bundled)
        self.assertEqual(self.calls, [])

    def test_matching_installed_copy_needs_no_password(self):
        with mock.patch.object(linux_core, "_installed_matches", return_value=True):
            path = linux_core.ready_core(self.bundled, runner=self.runner())
        self.assertEqual(path, linux_core.INSTALLED_CORE)
        self.assertEqual(self.calls, [])

    def test_first_connection_asks_for_the_password_exactly_once(self):
        logs = []
        path = linux_core.ready_core(self.bundled, lambda m, t: logs.append(m), runner=self.runner())
        self.assertEqual(path, linux_core.INSTALLED_CORE)
        self.assertEqual(len(self.calls), 1)
        command = self.calls[0]
        self.assertEqual(command[:3], ["/usr/bin/pkexec", "/bin/sh", "-c"])
        self.assertIn("setcap", command[3])
        self.assertIn(linux_core.CAPABILITIES, command[3])
        self.assertTrue(any("один раз" in m for m in logs))
        # Следующее подключение: копия на месте — пароль не нужен.
        with mock.patch.object(linux_core, "_installed_matches", return_value=True):
            linux_core.ready_core(self.bundled, runner=self.runner())
        self.assertEqual(len(self.calls), 1)

    def test_cancelled_password_prompt_is_explained(self):
        with mock.patch.object(linux_core.os.path, "exists", return_value=False):
            with self.assertRaisesRegex(linux_core.CoreSetupError, "отменён"):
                linux_core.ready_core(self.bundled, runner=self.runner(returncode=126, grant=False))

    def test_missing_pkexec_gives_a_manual_command(self):
        with mock.patch.object(linux_core.shutil, "which",
                               side_effect=lambda name, path=None: None if name == "pkexec" else "/usr/sbin/setcap"):
            with self.assertRaisesRegex(linux_core.CoreSetupError, "sudo setcap"):
                linux_core.ready_core(self.bundled, runner=self.runner())

    def test_staged_copy_is_removed_after_install(self):
        linux_core.ready_core(self.bundled, runner=self.runner())
        staged = self.calls[0][-1]
        self.assertFalse(os.path.exists(staged))


class LinuxAutostartTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = {"XDG_CONFIG_HOME": self.directory.name,
                    "SADNESS_APP_EXEC": "/home/user/Apps/Sadness VPN.AppImage"}
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.directory.cleanup()

    def test_desktop_entry_quotes_the_appimage_path(self):
        entry = autostart_linux.desktop_entry()
        self.assertIn('Exec="/home/user/Apps/Sadness VPN.AppImage" --autostart', entry)
        self.assertIn("Type=Application", entry)

    def test_enable_disable_and_state(self):
        self.assertFalse(autostart_linux.enabled())
        autostart_linux.enable()
        path = Path(self.directory.name, "autostart", "sadness-vpn.desktop")
        self.assertTrue(path.is_file())
        self.assertTrue(autostart_linux.enabled())
        autostart_linux.disable()
        self.assertFalse(autostart_linux.enabled())

    def test_moved_appimage_is_followed(self):
        autostart_linux.enable()
        with mock.patch.dict(os.environ, {"SADNESS_APP_EXEC": "/opt/new/Sadness.AppImage"}):
            self.assertTrue(autostart_linux.ensure_current())
            self.assertIn("/opt/new/Sadness.AppImage", Path(self.directory.name, "autostart",
                                                             "sadness-vpn.desktop").read_text(encoding="utf-8"))
            self.assertFalse(autostart_linux.ensure_current())

    def test_special_characters_are_escaped(self):
        self.assertEqual(autostart_linux._quote('/a/$b"c'), '"/a/\\$b\\"c"')
        self.assertEqual(autostart_linux._quote("/usr/bin/app"), "/usr/bin/app")


class PlatformFeatureTests(unittest.TestCase):
    def test_windows_only_features_are_reported(self):
        with mock.patch.object(platform_info.os, "name", "posix"):
            features = platform_info.features()
        self.assertEqual(features["os"], "linux")
        self.assertFalse(features["zapret"])
        self.assertFalse(features["amneziawg"])
        self.assertFalse(features["updates"])


if __name__ == "__main__":
    unittest.main()
