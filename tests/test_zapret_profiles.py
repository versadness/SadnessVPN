import unittest

from engine.flowseal_profiles import FLOWSEAL_COMMIT, FLOWSEAL_PROFILES
from engine.zapret import ZapretManager


class ZapretProfileTests(unittest.TestCase):
    def setUp(self):
        self.manager = ZapretManager()

    def test_all_official_flowseal_profiles_are_published(self):
        profiles = self.manager.get_strategies()

        self.assertEqual(
            [profile["id"] for profile in profiles],
            [
                "flowseal_general",
                "flowseal_alt",
                "flowseal_alt2",
                "flowseal_alt3",
                "flowseal_alt4",
                "flowseal_alt5",
                "flowseal_alt6",
                "flowseal_alt7",
                "flowseal_alt8",
                "flowseal_alt9",
                "flowseal_alt10",
                "flowseal_alt11",
                "flowseal_alt12",
                "flowseal_alt13",
                "flowseal_fake_tls_auto",
                "flowseal_fake_tls_auto_alt",
                "flowseal_fake_tls_auto_alt2",
                "flowseal_fake_tls_auto_alt3",
                "flowseal_simple_fake",
                "flowseal_simple_fake_alt",
                "flowseal_simple_fake_alt2",
                "flowseal_exp",
            ],
        )
        self.assertEqual(len(profiles), 22)
        self.assertTrue(all(profile["upstream_commit"] == FLOWSEAL_COMMIT for profile in profiles))
        self.assertEqual(len({profile["source_file"] for profile in profiles}), 22)

    def test_every_profile_resolves_paths_and_contains_current_discord_voice_payload(self):
        for profile in FLOWSEAL_PROFILES:
            with self.subTest(profile=profile["id"]):
                command = self.manager._build_cmd(profile["id"])

                self.assertEqual(command[0], self.manager._winws_path())
                self.assertTrue(any("ACTIVE_DISCORD_UDP.bin" in item for item in command))
                self.assertTrue(any(item.startswith("--filter-l7=discord,stun") for item in command))
                self.assertFalse(any("%BIN%" in item or "%LISTS%" in item for item in command))

    def test_fake_tls_legacy_profile_maps_to_official_alt3(self):
        command = self.manager._build_cmd("flowseal_fake_tls_auto_alt3")

        self.assertEqual(self.manager._build_cmd("flowseal_fake_tls"), command)
        self.assertTrue(any("--dpi-desync-fake-tls" in item for item in command))
        self.assertTrue(any("multisplit" in item for item in command))

    def test_old_profile_ids_map_to_matching_official_profiles(self):
        self.assertEqual(
            self.manager._build_cmd("general_alt"),
            self.manager._build_cmd("flowseal_alt"),
        )
        self.assertEqual(
            self.manager._build_cmd("general"),
            self.manager._build_cmd("flowseal_general"),
        )

    def test_generated_profiles_are_pinned_to_a_real_upstream_commit(self):
        self.assertRegex(FLOWSEAL_COMMIT, r"^[0-9a-f]{40}$")
        self.assertTrue(all(len(profile["source_sha256"]) == 64 for profile in FLOWSEAL_PROFILES))


if __name__ == "__main__":
    unittest.main()
