"""Игровой фильтр Zapret: нормализация, подстановка и сборка команды winws."""
import re
import unittest

from engine import game_filter
from engine.flowseal_profiles import FLOWSEAL_PROFILES
from engine.game_filter import GameFilterError
from engine.zapret import ZapretManager
from ui import app_state


PLACEHOLDERS = ("%GameFilterTCP%", "%GameFilterUDP%")


def game_ports(command):
    """Порты игровых секций: --filter-tcp/udp с одним диапазоном и wf-хвосты."""
    return [
        arg.split("=", 1)[1]
        for arg in command
        if arg.startswith(("--filter-tcp=", "--filter-udp="))
    ]


class GameFilterNormalizationTests(unittest.TestCase):
    def test_missing_configuration_migrates_to_a_disabled_filter(self):
        # Старый профиль без полей не должен внезапно начать перехватывать
        # весь игровой трафик пользователя.
        for legacy in (None, {}, {"ipset": "list"}):
            self.assertEqual(game_filter.normalize(legacy)["mode"], "off")
        self.assertFalse(game_filter.enabled(None))

    def test_defaults_are_the_flowseal_compatible_range(self):
        config = game_filter.normalize(None)
        self.assertEqual((config["tcp_start"], config["tcp_end"]), (1024, 65535))
        self.assertEqual((config["udp_start"], config["udp_end"]), (1024, 65535))
        self.assertEqual(config["ipset"], "list")

    def test_every_mode_is_accepted(self):
        for mode in ("off", "udp", "tcp", "both"):
            self.assertEqual(game_filter.normalize({"mode": mode})["mode"], mode)

    def test_boolean_configuration_from_an_older_build_still_loads(self):
        self.assertEqual(game_filter.normalize({"mode": True})["mode"], "both")
        self.assertEqual(game_filter.normalize({"mode": False})["mode"], "off")

    def test_custom_ranges_survive_normalization(self):
        config = game_filter.normalize(
            {"mode": "both", "tcp_start": 27015, "tcp_end": 27030,
             "udp_start": "3074", "udp_end": 3079, "ipset": "all"}
        )
        self.assertEqual(config["tcp_start"], 27015)
        self.assertEqual(config["udp_start"], 3074)
        self.assertEqual(config["ipset"], "all")

    def test_ports_outside_1_65535_are_rejected(self):
        for bad in (0, -1, 65536, 99999):
            with self.subTest(port=bad), self.assertRaises(GameFilterError):
                game_filter.normalize({"mode": "both", "tcp_start": bad})

    def test_start_above_end_is_rejected(self):
        with self.assertRaises(GameFilterError):
            game_filter.normalize({"mode": "both", "tcp_start": 5000, "tcp_end": 4000})
        with self.assertRaises(GameFilterError):
            game_filter.normalize({"mode": "udp", "udp_start": 60000, "udp_end": 100})

    def test_non_numeric_and_structurally_broken_input_is_rejected(self):
        for bad in ("abc", "1024-65535", None, True, [1024], {"a": 1}):
            with self.subTest(value=bad), self.assertRaises(GameFilterError):
                game_filter.normalize({"mode": "both", "tcp_start": bad})
        for bad in ("[]", 5, "yes"):
            with self.subTest(raw=bad), self.assertRaises(GameFilterError):
                game_filter.normalize(bad)

    def test_unknown_mode_and_ipset_are_rejected(self):
        with self.assertRaises(GameFilterError):
            game_filter.normalize({"mode": "everything"})
        with self.assertRaises(GameFilterError):
            game_filter.normalize({"mode": "both", "ipset": "whatever"})

    def test_stored_configuration_falls_back_instead_of_breaking_startup(self):
        self.assertEqual(game_filter.normalize_stored({"mode": "nonsense"}),
                         game_filter.DEFAULTS)


class GameFilterSubstitutionTests(unittest.TestCase):
    def test_disabled_filter_keeps_the_upstream_sentinel_port(self):
        values = game_filter.substitutions({"mode": "off"})
        self.assertEqual(values["%GameFilterTCP%"], "12")
        self.assertEqual(values["%GameFilterUDP%"], "12")

    def test_each_mode_enables_only_its_own_protocol(self):
        cases = {
            "udp": ("12", "1024-65535"),
            "tcp": ("1024-65535", "12"),
            "both": ("1024-65535", "1024-65535"),
        }
        for mode, (tcp, udp) in cases.items():
            with self.subTest(mode=mode):
                values = game_filter.substitutions({"mode": mode})
                self.assertEqual(values["%GameFilterTCP%"], tcp)
                self.assertEqual(values["%GameFilterUDP%"], udp)

    def test_only_normalized_numeric_ranges_reach_the_command(self):
        values = game_filter.substitutions(
            {"mode": "both", "tcp_start": 27015, "tcp_end": 27030,
             "udp_start": 3074, "udp_end": 3074}
        )
        self.assertEqual(values["%GameFilterTCP%"], "27015-27030")
        # Диапазон из одного порта не превращается в «3074-3074».
        self.assertEqual(values["%GameFilterUDP%"], "3074")
        for rendered in values.values():
            self.assertRegex(rendered, r"^\d{1,5}(-\d{1,5})?$")

    def test_summary_reports_the_effective_setting_without_a_command_line(self):
        summary = game_filter.summary({"mode": "udp"}, "General")
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["mode_label"], "Только UDP")
        self.assertEqual(summary["tcp_label"], "не перехватывается")
        self.assertEqual(summary["udp_label"], "1024-65535")
        self.assertEqual(summary["strategy"], "General")
        self.assertIn("не то же самое", summary["note"])
        self.assertNotIn("winws", repr(summary))


class ProfileTemplateTests(unittest.TestCase):
    """Плейсхолдеры обязаны пережить синхронизацию профилей Flowseal."""

    def test_every_profile_keeps_its_game_filter_placeholders(self):
        for profile in FLOWSEAL_PROFILES:
            with self.subTest(profile=profile["id"]):
                joined = " ".join(profile["args"])
                for placeholder in PLACEHOLDERS:
                    self.assertIn(placeholder, joined)

    def test_no_profile_bakes_the_disabled_sentinel_port_in(self):
        # Корень исходной поломки: tools/sync_flowseal_profiles.py подставлял
        # «12» при импорте, и игровой фильтр не работал ни в одном профиле.
        for profile in FLOWSEAL_PROFILES:
            for arg in profile["args"]:
                if arg.startswith(("--filter-tcp=", "--filter-udp=", "--wf-tcp=", "--wf-udp=")):
                    self.assertNotRegex(arg, r"(?<![\d-])12(?![\d-])", profile["id"])

    def test_the_sync_tool_no_longer_replaces_the_placeholders(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1]
                  / "tools" / "sync_flowseal_profiles.py").read_text(encoding="utf-8")
        self.assertNotIn('replace("%GameFilterTCP%"', source)
        self.assertNotIn('replace("%GameFilterUDP%"', source)
        self.assertIn("%GameFilterTCP%", source)


class CoverageScopeTests(unittest.TestCase):
    """Охват обхода: три режима и честное описание того, что реально ловится."""

    def test_legacy_configuration_without_scope_is_derived_not_reset(self):
        self.assertEqual(game_filter.normalize({"mode": "off"})["scope"], "standard")
        self.assertEqual(game_filter.normalize({"mode": "both"})["scope"], "extended")
        custom = game_filter.normalize({"mode": "both", "tcp_start": 27015, "tcp_end": 27030})
        self.assertEqual(custom["scope"], "custom")
        # Пользовательские границы переживают миграцию.
        self.assertEqual((custom["tcp_start"], custom["tcp_end"]), (27015, 27030))

    def test_standard_scope_adds_nothing_to_the_strategy(self):
        config = game_filter.normalize({"scope": "standard", "mode": "both", "ipset": "all"})
        self.assertEqual(config["mode"], "off")
        self.assertEqual(config["ipset"], "list")
        values = game_filter.substitutions(config)
        self.assertEqual(values["%GameFilterTCP%"], game_filter.DISABLED_PORTS)
        self.assertEqual(values["%GameFilterUDP%"], game_filter.DISABLED_PORTS)

    def test_extended_scope_uses_the_verified_ranges_and_keeps_the_ipset_choice(self):
        config = game_filter.normalize({"scope": "extended", "tcp_start": 5, "ipset": "all"})
        self.assertEqual(config["mode"], "both")
        self.assertEqual((config["tcp_start"], config["tcp_end"]), (1024, 65535))
        self.assertEqual(config["ipset"], "all")

    def test_custom_scope_keeps_user_ranges(self):
        config = game_filter.normalize({"scope": "custom", "mode": "udp",
                                        "udp_start": 27000, "udp_end": 27100})
        self.assertEqual(game_filter.substitutions(config)["%GameFilterUDP%"], "27000-27100")

    def test_unknown_scope_is_rejected(self):
        with self.assertRaises(GameFilterError):
            game_filter.normalize({"scope": "everything"})


class CoverageDescriptionTests(unittest.TestCase):
    def setUp(self):
        from engine import zapret_scope
        self.describe = zapret_scope.describe_by_id

    def test_extended_scope_actually_widens_the_covered_ports(self):
        standard = self.describe("flowseal_general", {"scope": "standard"})
        extended = self.describe("flowseal_general", {"scope": "extended"})
        self.assertNotIn("1024-65535", standard["tcp_ports"])
        self.assertIn("1024-65535", extended["tcp_ports"])
        self.assertIn("1024-65535", extended["udp_ports"])

    def test_disabled_sentinel_port_is_never_shown_as_covered(self):
        standard = self.describe("flowseal_general", {"scope": "standard"})
        self.assertNotIn(game_filter.DISABLED_PORTS, standard["tcp_ports"])
        self.assertNotIn(game_filter.DISABLED_PORTS, standard["udp_ports"])

    def test_list_limits_are_reported_so_coverage_is_not_oversold(self):
        coverage = self.describe("flowseal_general", {"scope": "extended"})
        self.assertIn("list-general.txt", coverage["hostlists"])
        self.assertIn("ipset-all.txt", coverage["ipsets"])
        self.assertTrue(any("списками сайтов" in note for note in coverage["notes"]))

    def test_all_addresses_mode_clears_the_ipset_limit_in_the_description(self):
        coverage = self.describe("flowseal_general", {"scope": "extended", "ipset": "all"})
        self.assertEqual(coverage["ipsets"], [])
        self.assertTrue(any("любые адреса" in note for note in coverage["notes"]))

    def test_exclusions_and_the_vpn_limitation_are_always_stated(self):
        coverage = self.describe("flowseal_general", {"scope": "extended"})
        self.assertIn("ipset-exclude.txt", coverage["excludes"])
        self.assertTrue(any("внутри VPN-туннеля" in note for note in coverage["notes"]))
        self.assertTrue(coverage["restart_required"])

    def test_protocols_are_named_from_the_filters_not_from_the_profile_name(self):
        coverage = self.describe("flowseal_general", {"scope": "extended"})
        self.assertIn("Discord", coverage["protocols"])
        self.assertIn("QUIC (HTTP/3)", coverage["protocols"])
        # Секция по игровым диапазонам не выдаётся за разбор протокола.
        self.assertIn("трафик выбранных портов без разбора протокола", coverage["protocols"])

    def test_full_tunnel_vpn_is_not_advertised_as_whole_pc_coverage(self):
        coverage = self.describe("flowseal_general", {"scope": "extended"})
        joined = " ".join(coverage["notes"])
        self.assertNotIn("весь компьютер", joined)

        from engine.zapret_scope import describe_by_id
        with_vpn = describe_by_id("flowseal_general", {"scope": "extended"}, "all")
        self.assertTrue(any("остал" in note for note in with_vpn["notes"]))
        self.assertEqual(with_vpn["vpn_mode"], "all")

        selected = describe_by_id("flowseal_general", {"scope": "extended"}, "whitelist")
        self.assertTrue(any("напрямую" in note for note in selected["notes"]))

    def test_every_profile_can_be_described(self):
        for profile in FLOWSEAL_PROFILES:
            with self.subTest(profile=profile["id"]):
                coverage = self.describe(profile["id"], {"scope": "extended"})
                self.assertTrue(coverage["ports_label"])
                self.assertTrue(coverage["protocols"])


class ZapretCommandTests(unittest.TestCase):
    def setUp(self):
        self.manager = ZapretManager()

    def test_disabled_filter_reproduces_the_upstream_disabled_command(self):
        command = self.manager._build_cmd("flowseal_general", {"mode": "off"})
        self.assertIn("--filter-tcp=12", command)
        self.assertIn("--filter-udp=12", command)
        self.assertIn("--wf-tcp=80,443,2053,2083,2087,2096,8443,12", command)

    def test_enabled_modes_put_real_ranges_into_the_command(self):
        cases = {
            "udp": ("--filter-tcp=12", "--filter-udp=1024-65535"),
            "tcp": ("--filter-tcp=1024-65535", "--filter-udp=12"),
            "both": ("--filter-tcp=1024-65535", "--filter-udp=1024-65535"),
        }
        for mode, (tcp, udp) in cases.items():
            with self.subTest(mode=mode):
                command = self.manager._build_cmd("flowseal_general", {"mode": mode})
                self.assertIn(tcp, command)
                self.assertIn(udp, command)
                self.assertIn(f"--wf-udp=443,19294-19344,50000-50100,{udp.split('=')[1]}", command)

    def test_custom_ranges_reach_every_profile(self):
        config = {"mode": "both", "tcp_start": 27015, "tcp_end": 27030,
                  "udp_start": 27000, "udp_end": 27100}
        for profile in FLOWSEAL_PROFILES:
            with self.subTest(profile=profile["id"]):
                command = self.manager._build_cmd(profile["id"], config)
                self.assertIn("--filter-tcp=27015-27030", command)
                self.assertIn("--filter-udp=27000-27100", command)
                self.assertFalse([a for a in command if "%GameFilter" in a])

    def test_ipset_all_only_relaxes_the_game_sections(self):
        listed = self.manager._build_cmd("flowseal_general", {"mode": "both", "ipset": "list"})
        every = self.manager._build_cmd("flowseal_general", {"mode": "both", "ipset": "all"})
        self.assertEqual(sum(1 for a in listed if a.startswith("--ipset=")), 4)
        self.assertEqual(sum(1 for a in every if a.startswith("--ipset=")), 2)
        # Исключения остаются: они защищают локальные и служебные адреса.
        self.assertEqual(
            sum(1 for a in listed if a.startswith("--ipset-exclude=")),
            sum(1 for a in every if a.startswith("--ipset-exclude=")),
        )
        # Браузерные секции не трогаем ни в одном режиме IPSet.
        self.assertIn("--filter-udp=443", every)
        self.assertIn("--filter-tcp=80,443", every)

    def test_ipset_all_is_ignored_while_the_filter_is_off(self):
        off = self.manager._build_cmd("flowseal_general", {"mode": "off", "ipset": "all"})
        self.assertEqual(sum(1 for a in off if a.startswith("--ipset=")), 4)

    def test_the_command_is_an_argument_list_without_shell_metacharacters(self):
        command = self.manager._build_cmd(
            "flowseal_general", {"mode": "both", "tcp_start": 1, "tcp_end": 65535}
        )
        self.assertIsInstance(command, list)
        self.assertTrue(all(isinstance(item, str) for item in command))
        for arg in command:
            if arg.startswith(("--filter-tcp=", "--filter-udp=", "--wf-tcp=", "--wf-udp=")):
                self.assertRegex(arg.split("=", 1)[1], r"^[\d,\-]+$")

    def test_a_broken_configuration_never_starts_winws(self):
        messages = []
        manager = ZapretManager(log_callback=lambda message, tag: messages.append((tag, message)))
        launched = []
        manager._build_cmd = lambda *a, **k: launched.append(a) or []
        started = manager.start("flowseal_general", {"mode": "both", "tcp_start": 70000})
        self.assertFalse(started)
        self.assertEqual(launched, [])
        self.assertTrue(any(tag == "err" for tag, _ in messages))

    def test_injection_attempts_are_rejected_rather_than_concatenated(self):
        for attack in ("1024 --dpi-desync=none", "1024;calc.exe", "1024,443", "1024|9"):
            with self.subTest(value=attack), self.assertRaises(GameFilterError):
                game_filter.substitutions({"mode": "both", "tcp_start": attack})


class SettingsMigrationTests(unittest.TestCase):
    def test_settings_defaults_carry_a_disabled_game_filter(self):
        self.assertEqual(
            app_state.DEFAULT_SETTINGS["zapret_game_filter"], game_filter.DEFAULTS
        )

    def test_broken_stored_value_does_not_prevent_loading_settings(self):
        self.assertEqual(
            app_state.normalize_zapret_game_filter({"mode": "udp"})["mode"], "udp"
        )
        with self.assertRaises(GameFilterError):
            app_state.normalize_zapret_game_filter({"mode": "udp", "udp_start": 0})


class PackagedBinaryTests(unittest.TestCase):
    def test_the_game_payload_and_windivert_ship_with_the_build(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for name in ("ACTIVE_GAME_UDP.bin", "ACTIVE_DISCORD_UDP.bin",
                     "winws.exe", "WinDivert.dll", "WinDivert64.sys"):
            with self.subTest(name=name):
                self.assertTrue((root / "bin" / name).is_file(), name)
        spec = (root / "SadnessVPN.spec").read_text(encoding="utf-8")
        self.assertIn("bin", spec)

    def test_every_payload_referenced_by_a_profile_exists_in_bin(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        referenced = {
            arg.split("%BIN%", 1)[1]
            for profile in FLOWSEAL_PROFILES for arg in profile["args"] if "%BIN%" in arg
        }
        missing = sorted(name for name in referenced if not (root / "bin" / name).is_file())
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
