import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "ui" / "templates" / "index.html"
FLAGS = ROOT / "ui" / "static" / "flags" / "4x3"


class UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")
        cls.javascript = (ROOT / "ui" / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        cls.styles = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "ui" / "static" / "css" / "legacy.css",
                ROOT / "ui" / "static" / "css" / "redesign.css",
            )
        )

    def test_template_has_no_editor_chrome_or_remote_flags(self):
        self.assertNotIn("skill:chrome", self.html + self.javascript)
        self.assertNotIn("flagcdn.com", self.html + self.javascript)

    def test_shipped_controls_have_real_handlers_instead_of_placeholders(self):
        self.assertIn('onclick="exportRules()"', self.html)
        self.assertIn('onclick="refreshPublicIp()"', self.html)
        self.assertIn('onclick="toggleSecureDns()"', self.html)
        self.assertNotIn("будет добавлен следующим шагом", self.html + self.javascript)
        self.assertNotIn("toggleAiDns", self.html + self.javascript)

    def test_dynamic_rows_do_not_interpolate_inline_javascript(self):
        self.assertNotRegex(self.html + self.javascript, r'onclick="[^"]*\$\{')
        self.assertIn('data-action="edit-app"', self.javascript)
        self.assertIn('data-action="select-server"', self.javascript)

    def test_ping_completion_messages_are_handled(self):
        self.assertIn("case 'ping_done'", self.javascript)
        self.assertIn("case 'wg_ping_done'", self.javascript)

    def test_connect_button_keeps_its_round_dimensions_in_short_windows(self):
        self.assertIn("flex:0 0 176px; aspect-ratio:1", self.styles)
        short_window_css = re.search(
            r"@media \(max-height:560px\)\s*\{(.*?)\n\}",
            self.styles,
            re.DOTALL,
        ).group(1)
        self.assertNotIn(".power-wrap", short_window_css)
        self.assertNotIn(".connect-btn", short_window_css)

    def test_close_button_exits_and_first_launch_has_no_autostart_prompt(self):
        bridge = (Path(__file__).resolve().parent.parent / "renderer" / "js" / "shell-bridge.js").read_text(encoding="utf-8")
        self.assertIn("window.winClose = function () { shell.window.close(); };", bridge)
        self.assertNotIn('id="onboardingModal"', self.html)
        self.assertNotIn("showOnboardingIfNeeded", self.javascript)
        self.assertNotIn('data-sk="mintray"', self.html)

    def test_runtime_tray_icon_is_included_in_the_package(self):
        spec = (ROOT / "SadnessVPN.spec").read_text(encoding="utf-8")
        self.assertIn("('app.ico', '.')", spec)

    def test_all_country_flags_are_local_svg_assets(self):
        self.assertGreaterEqual(len(list(FLAGS.glob("*.svg"))), 250)
        self.assertTrue((FLAGS / "de.svg").is_file())
        self.assertTrue((FLAGS / "fi.svg").is_file())
        self.assertIn('/static/flags/4x3/${safe}.svg', self.javascript)
        self.assertIn("Intl.DisplayNames", self.javascript)

    def test_rule_dialog_uses_the_single_shared_process_picker(self):
        picker = (ROOT / "ui/static/js/process-picker.js").read_text(encoding="utf-8")
        self.assertIn('id="ruleModal"', self.html)
        self.assertIn("process-picker.js", self.html)
        self.assertIn("openProcessPicker(this)", self.html)
        # Одна реализация и один источник данных: старая модалка processModal
        # со своим списком из /api/apps/processes больше не существует.
        self.assertNotIn('id="processModal"', self.html)
        self.assertNotIn("/api/apps/processes", self.javascript)
        self.assertIn("window.openProcessPicker", picker)
        self.assertIn("/api/apps/catalog", picker)
        self.assertIn("dialog.showModal()", picker)
        # Правило привязывается к имени EXE, а не к PID или полному пути:
        # оба меняются между запусками приложения.
        code = re.sub(r"(?m)^\s*(//|\*|/\*).*$", "", picker)
        for forbidden in (".pid", "'pid'", '"pid"', "exe_path", "cmdline", "command_line"):
            self.assertNotIn(forbidden, code)

    def test_dns_dropdown_raises_its_settings_row(self):
        self.assertIn(".set-row.dd-open", self.styles)
        self.assertIn("classList.add('dd-open')", self.javascript)

    def test_home_dashboard_keeps_every_element_the_app_updates(self):
        # app.js обновляет эти элементы по id; потеря любого ломает главный экран.
        for element_id in ("connectBtn", "powerLbl", "statusTitle", "statusDesc", "hcServer",
                           "hcServerFlag", "hcMode", "homeCountry", "homePing", "stDown", "stUp",
                           "stSession", "stToday", "ipVal", "ipNote", "gaugeArc", "gaugeMax",
                           "tgTun", "tgWg", "tgSecureDns", "geminiDnsLabel", "protoBadge"):
            self.assertIn(f'id="{element_id}"', self.html, element_id)
        self.assertIn('/static/css/home.css', self.html)
        self.assertIn('class="dash-slide" id="connectBtn"', self.html)

    def test_home_dashboard_is_driven_by_live_data(self):
        self.assertIn("renderHomeDash();}", self.javascript)
        self.assertIn("setGauge(Math.max(0,dn))", self.javascript)
        self.assertIn("case 'ping':", self.javascript)
        self.assertIn("getElementById('stToday')", self.javascript)
        # Перетаскивание не должно повторно переключать VPN щелчком.
        self.assertIn("stopImmediatePropagation", self.javascript)

    def test_telegram_proxy_has_its_own_section_below_zapret(self):
        nav = self.html.split('<nav class="sidebar"', 1)[1].split("</nav>", 1)[0]
        self.assertLess(nav.index('data-page="zapret"'), nav.index('data-page="telegram"'))
        zapret_page = self.html.split('id="page-zapret"', 1)[1].split('id="page-telegram"', 1)[0]
        self.assertNotIn('id="tgProxy"', zapret_page)
        telegram_page = self.html.split('id="page-telegram"', 1)[1]
        for element_id in ("tgProxy", "tgpPort", "tgpSecret", "tgpBtn", "tgpOpen", "tgpError",
                           "tgpSummary", "tgpHeadState"):
            self.assertIn(f'id="{element_id}"', telegram_page, element_id)
        self.assertIn("case 'tgproxy_status'", self.javascript)
        self.assertIn("/api/tgproxy/start", self.javascript)

    def test_wireguard_configs_can_be_imported_as_files(self):
        wg_page = self.html.split('id="page-wg"', 1)[1]
        self.assertIn('id="wgFile"', wg_page)
        self.assertIn('accept=".conf,.txt" multiple', wg_page)
        self.assertIn("wgAddFiles(event.dataTransfer.files)", wg_page)
        self.assertIn("async function wgAddFiles(files)", self.javascript)

    def test_every_static_inline_handler_has_a_defined_function(self):
        handlers = set(re.findall(
            r'on\w+\s*=\s*["\']\s*(?:event\.stopPropagation\(\);\s*)?'
            r'([A-Za-z_$][\w$]*)\s*\(',
            self.javascript,
        ))
        functions = set(re.findall(
            r'\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(',
            self.html,
        ))
        self.assertEqual(handlers - functions, set())


if __name__ == "__main__":
    unittest.main()
