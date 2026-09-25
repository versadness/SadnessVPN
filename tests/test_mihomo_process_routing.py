"""Полный путь правила «процесс → выход» в конфигурации Mihomo.

Сообщение «Mihomo выдаёт ту же ошибку» само по себе ничего не доказывает,
поэтому здесь проверяется каждое звено: точное имя EXE из правила, формат
PROCESS-NAME, приоритет строки, итоговый outbound, безопасная починка
пропавшего server:<id> и отсутствие секретов в журналах.
"""
import unittest

from engine.app_routes import assignments, build_multi_route_config
from engine.route_repair import repair_routing
from engine.routing_rules import normalize_rule, resolve_rules, validate_rules

GAME_EXE = "DeadByDaylight-Win64-Shipping.exe"

SERVER = {
    "ui_id": "s1", "remark": "Тестовый", "host": "server.invalid", "port": 443,
    "uuid": "11111111-2222-3333-4444-555555555555", "protocol": "vless",
    "security": "reality", "type": "tcp", "pbk": "public-key", "sid": "beef",
}
GROUPS = [{"id": "g1", "name": "Группа", "servers": [SERVER]}]


def rule(**overrides):
    base = {"id": "r1", "kind": "process", "value": GAME_EXE,
            "destination": "proxy", "enabled": True, "name": "Игра"}
    return {**base, **overrides}


class ProcessRuleTests(unittest.TestCase):
    def test_exact_executable_name_survives_normalization(self):
        normalized = normalize_rule(rule())
        self.assertEqual(normalized["value"], GAME_EXE)

    def test_process_rules_render_as_process_name_with_the_exact_exe(self):
        routes = resolve_rules([rule()], GROUPS)
        self.assertEqual(routes[0]["match"], f"PROCESS-NAME,{GAME_EXE}")

    def test_a_different_executable_never_produces_the_same_match(self):
        launcher = resolve_rules([rule(value="Steam.exe")], GROUPS)[0]["match"]
        game = resolve_rules([rule()], GROUPS)[0]["match"]
        self.assertNotEqual(launcher, game)
        config = build_multi_route_config(SERVER, resolve_rules([rule()], GROUPS))
        self.assertFalse([r for r in config["rules"] if "Steam.exe" in r])

    def test_case_and_whitespace_do_not_silently_become_another_process(self):
        # Имя из списка процессов попадает в правило как есть: подгонять его
        # под «похожее» нельзя, иначе правило начнёт ловить чужой процесс.
        self.assertEqual(normalize_rule(rule(value=f"  {GAME_EXE}  "))["value"], GAME_EXE)
        self.assertEqual(normalize_rule(rule(value=GAME_EXE.lower()))["value"], GAME_EXE.lower())

    def test_rule_values_cannot_inject_extra_mihomo_rule_fields(self):
        for attack in (f"{GAME_EXE},DIRECT", "a(b).exe", "..\\evil.exe", "C:/games/g.exe"):
            with self.subTest(value=attack), self.assertRaises(ValueError):
                normalize_rule(rule(value=attack))

    def test_protected_system_processes_stay_unroutable(self):
        for blocked in ("svchost.exe", "lsass.exe", "winws.exe", "mihomo.exe"):
            with self.subTest(value=blocked), self.assertRaises(ValueError):
                normalize_rule(rule(value=blocked))


class ConfigurationTests(unittest.TestCase):
    def build(self, rules, **settings):
        return build_multi_route_config(
            SERVER, resolve_rules(rules, GROUPS), **settings
        )

    def test_explicit_process_rules_outrank_the_catch_all(self):
        config = self.build([rule(destination="direct")])
        index = config["rules"].index(f"PROCESS-NAME,{GAME_EXE},DIRECT")
        catch_all = next(i for i, r in enumerate(config["rules"]) if r.startswith("MATCH,"))
        self.assertLess(index, catch_all)

    def test_lan_bypass_still_runs_before_the_process_rules(self):
        config = self.build([rule()])
        private = max(i for i, r in enumerate(config["rules"]) if r.startswith(("IP-CIDR,", "IP-CIDR6,")))
        self.assertLess(private, config["rules"].index(f"PROCESS-NAME,{GAME_EXE},proxy"))

    def test_rule_order_from_the_editor_is_preserved(self):
        rules = [rule(id="r1", value="one.exe"), rule(id="r2", value="two.exe"),
                 rule(id="r3", value="three.exe")]
        config = self.build(rules)
        positions = [config["rules"].index(f"PROCESS-NAME,{r['value']},proxy") for r in rules]
        self.assertEqual(positions, sorted(positions))

    def test_a_per_rule_server_gets_its_own_outbound(self):
        config = self.build([rule(destination="server:s1")])
        tags = {proxy["name"] for proxy in config["proxies"]}
        target = next(r for r in config["rules"] if r.startswith("PROCESS-NAME,")).rsplit(",", 1)[1]
        self.assertIn(target, tags)
        self.assertNotIn(target, {"proxy", "DIRECT"})

    def test_the_resulting_configuration_is_valid_for_process_matching(self):
        config = self.build([rule()])
        self.assertEqual(config["find-process-mode"], "always")
        self.assertEqual(config["mode"], "rule")
        self.assertTrue(config["rules"][-1].startswith("MATCH,"))
        self.assertTrue(all(isinstance(r, str) and r.count(",") >= 1 for r in config["rules"]))
        # Mihomo выбирается по наличию "proxies": ядро не должно уехать на sing-box.
        self.assertIn("proxies", config)

    def test_disabled_rules_do_not_reach_the_configuration(self):
        config = self.build([rule(enabled=False)])
        self.assertFalse([r for r in config["rules"] if GAME_EXE in r])

    def test_a_missing_destination_server_is_reported_not_guessed(self):
        with self.assertRaises(ValueError) as caught:
            resolve_rules([rule(destination="server:gone")], GROUPS)
        self.assertNotIn(SERVER["uuid"], str(caught.exception))
        self.assertNotIn(SERVER["host"], str(caught.exception))


class RouteRepairTests(unittest.TestCase):
    """Логика восстановления из 3.0.9 должна остаться нетронутой."""

    def setUp(self):
        self.config = {
            "mode": "all",
            "apps": [{"exe": "app.exe", "name": "App", "destination": "server:gone", "enabled": True}],
            "rules": [rule(destination="server:gone"),
                      rule(id="r2", value="keep.exe", destination="direct")],
        }

    def test_missing_server_moves_apps_to_default_and_rules_to_proxy(self):
        repaired, report = repair_routing(self.config, GROUPS)
        self.assertEqual(repaired["apps"][0]["destination"], "default")
        self.assertEqual(repaired["rules"][0]["destination"], "proxy")
        self.assertTrue(report["changed"])
        self.assertEqual(report["total"], 2)

    def test_repair_keeps_the_rule_with_its_id_order_value_and_state(self):
        repaired, _ = repair_routing(self.config, GROUPS)
        self.assertEqual([r["id"] for r in repaired["rules"]], ["r1", "r2"])
        self.assertEqual(repaired["rules"][0]["value"], GAME_EXE)
        self.assertEqual(repaired["rules"][0]["enabled"], True)
        self.assertEqual(repaired["rules"][1]["destination"], "direct")

    def test_repair_never_picks_a_similar_looking_server(self):
        repaired, _ = repair_routing(self.config, GROUPS)
        self.assertNotIn("server:s1", [r["destination"] for r in repaired["rules"]])
        self.assertNotIn("server:s1", [a["destination"] for a in repaired["apps"]])

    def test_repair_never_turns_a_lost_route_into_direct(self):
        repaired, _ = repair_routing(self.config, GROUPS)
        self.assertNotEqual(repaired["rules"][0]["destination"], "direct")

    def test_connecting_still_works_after_the_repair(self):
        repaired, _ = repair_routing(self.config, GROUPS)
        routes = resolve_rules(repaired["rules"], GROUPS) + assignments(repaired["apps"], GROUPS)
        config = build_multi_route_config(SERVER, routes)
        self.assertIn(f"PROCESS-NAME,{GAME_EXE},proxy", config["rules"])

    def test_repair_message_carries_no_server_details(self):
        _, report = repair_routing(self.config, GROUPS)
        for text in (report["message"], report["notice"]):
            self.assertTrue(text)
            for secret in (SERVER["uuid"], SERVER["host"], SERVER["pbk"], SERVER["remark"]):
                self.assertNotIn(secret, text)


class ValidationContractTests(unittest.TestCase):
    def test_saving_rules_rejects_malformed_input_before_it_is_stored(self):
        with self.assertRaises(ValueError):
            validate_rules([rule(value="no-extension")], GROUPS)
        with self.assertRaises(ValueError):
            validate_rules([rule(), rule()], GROUPS)  # повторяющийся ID
        self.assertEqual(len(validate_rules([rule()], GROUPS)), 1)

    def test_accepted_rules_round_trip_unchanged(self):
        stored = validate_rules([rule()], GROUPS)
        self.assertEqual(validate_rules(stored, GROUPS), stored)


if __name__ == "__main__":
    unittest.main()
