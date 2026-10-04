package com.sadness.vpn.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Base64
import java.util.concurrent.TimeUnit

/** WireGuard/AmneziaWG, маршруты и «лучший сервер» (версия 1.2). */
class FeaturesTest {
    private val key = Base64.getEncoder().encodeToString(ByteArray(32) { 7 })
    private val key2 = Base64.getEncoder().encodeToString(ByteArray(32) { 9 })

    private val wgConf = """
        [Interface]
        PrivateKey = $key
        Address = 10.8.0.2/32, fd00::2/128
        DNS = 1.1.1.1
        MTU = 1380
        [Peer]
        PublicKey = $key2
        Endpoint = 203.0.113.10:51820
        AllowedIPs = 0.0.0.0/0, ::/0
        PersistentKeepalive = 25
    """.trimIndent()

    private val awgConf = wgConf.replace("MTU = 1380", "MTU = 1380\nJc = 4\nJmin = 40\nJmax = 70\nS1 = 15\nS2 = 20\nH1 = 1234\nH2 = 5678\nH3 = 9012\nH4 = 3456")

    @Test fun wireguardConfBecomesMihomoOutbound() {
        val server = WireGuard.parse(wgConf, "Germany WG").single()
        assertEquals("Germany WG", server["remark"])
        val proxy = MihomoConfig.proxy(server)
        assertEquals("wireguard", proxy["type"]); assertEquals("10.8.0.2", proxy["ip"]); assertEquals("fd00::2", proxy["ipv6"])
        assertEquals(1380, proxy["mtu"]); assertEquals(25, proxy["persistent-keepalive"])
        assertFalse("amnezia-wg-option" in proxy)
        assertEquals("wg", Failover.transport(server))
    }

    @Test fun amneziaFieldsGoToAmneziaOption() {
        val server = WireGuard.parse(awgConf, "Finland").single()
        assertTrue(server["remark"].toString().endsWith("AWG"))
        val awg = MihomoConfig.proxy(server)["amnezia-wg-option"] as Map<*, *>
        assertEquals(4, awg["jc"]); assertEquals(40, awg["jmin"]); assertEquals("1234", awg["h1"])
        assertFalse("version" in awg)
    }

    @Test fun amneziaV3SetsVersion() {
        val v3 = awgConf.replace("Jc = 4", "Jc = 4\nHeaderProtectionKey = $key")
        val server = WireGuard.parse(v3, "").single()
        assertEquals(3, (server["awg"] as Map<*, *>)["version"])
    }

    @Test fun brokenConfIsExplained() {
        val error = assertThrows(IllegalArgumentException::class.java) { WireGuard.parse(wgConf.replace(key2, "bad"), "") }
        assertTrue(error.message!!.contains("PublicKey"))
        assertThrows(IllegalArgumentException::class.java) { WireGuard.parse("hello", "") }
    }

    @Test fun customRulesAreNormalizedAndValidated() {
        assertEquals("example.com", MihomoConfig.normalizeRule("domain", "https://www.Example.com/path".replace("www.", "")))
        assertEquals("example.com", MihomoConfig.normalizeRule("domain", "*.example.com"))
        assertEquals("10.0.0.0/8", MihomoConfig.normalizeRule("ip", "10.0.0.0/8"))
        assertThrows(IllegalArgumentException::class.java) { MihomoConfig.normalizeRule("domain", "not a domain") }
        assertThrows(IllegalArgumentException::class.java) { MihomoConfig.normalizeRule("ip", "10.0.0.0/40") }
    }

    @Suppress("UNCHECKED_CAST")
    @Test fun routingOrderIsCustomThenAdsThenServicesThenRussia() {
        val server: Server = linkedMapOf("protocol" to "ss", "remark" to "A", "host" to "203.0.113.1", "port" to 8388,
            "method" to "chacha20-ietf-poly1305", "password" to "p", "ui_id" to "a")
        val routing = MihomoConfig.Routing(ruDirect = true, adblock = true, servicesVpn = true,
            rules = listOf(MihomoConfig.Rule("domain", "sberbank.ru", "direct"), MihomoConfig.Rule("ip", "10.8.0.0/16", "block")))
        val c = MihomoConfig.assemble(MihomoConfig.proxy(server), MihomoConfig.Settings(routing = routing), "127.0.0.1:9090", "s", 5)
        val rules = c["rules"] as List<String>
        val idx = { prefix: String -> rules.indexOfFirst { it.startsWith(prefix) } }
        assertTrue(idx("DOMAIN-SUFFIX,sberbank.ru,DIRECT") < idx("RULE-SET,site-category-ads-all,REJECT"))
        assertTrue(idx("RULE-SET,site-category-ads-all") < idx("RULE-SET,site-youtube,proxy"))
        assertTrue(idx("RULE-SET,site-youtube") < idx("RULE-SET,site-category-ru,DIRECT"))
        assertTrue("IP-CIDR,10.8.0.0/16,REJECT,no-resolve" in rules)
        assertTrue("RULE-SET,ip-ru,DIRECT,no-resolve" in rules)
        assertEquals("MATCH,proxy", rules.last())
        val providers = c["rule-providers"] as Map<String, Map<String, Any?>>
        assertEquals("./rules/ip-ru.mrs", providers["ip-ru"]!!["path"])
        assertEquals("ipcidr", providers["ip-ru"]!!["behavior"])
    }

    @Suppress("UNCHECKED_CAST")
    @Test fun autoBestUsesUrlTestOverTheSubscription() {
        val a: Server = linkedMapOf("protocol" to "ss", "remark" to "A", "host" to "203.0.113.1", "port" to 1, "method" to "chacha20-ietf-poly1305", "password" to "p", "ui_id" to "a")
        val b: Server = LinkedHashMap(a).apply { put("ui_id", "b"); put("host", "203.0.113.2") }
        val other: Server = LinkedHashMap(a).apply { put("ui_id", "c"); put("host", "203.0.113.3") }
        val groups = listOf(Failover.Group("g1", listOf(a, b)), Failover.Group("g2", listOf(other)))
        val c = MihomoConfig.assemble(MihomoConfig.proxy(a), MihomoConfig.Settings(), "127.0.0.1:9090", "s", 5)
        Failover.applyServerGroups(c, a, groups, autoBest = true, resolve = { emptySet() })
        val byName = (c["proxy-groups"] as List<Map<String, Any?>>).associateBy { it["name"] }
        assertEquals("url-test", byName["manual"]!!["type"])
        assertEquals(listOf("srv-a", "srv-b"), byName["manual"]!!["proxies"])
        assertEquals(listOf("manual"), byName["proxy"]!!["proxies"])
    }

    /** Настоящий Mihomo принимает WireGuard, AmneziaWG, наборы правил и внутренний вход проверки. */
    @Test fun desktopMihomoAcceptsEverything() {
        val mihomo = listOf("../../bin/mihomo.exe", "../../bin-linux/mihomo").map(::File).firstOrNull { it.isFile && it.canExecute() } ?: return
        val rulesDir = File("src/main/assets/rules").takeIf { it.isDirectory } ?: return
        val wg = WireGuard.parse(wgConf, "WG").single().apply { put("ui_id", "wg") }
        val awg = WireGuard.parse(awgConf, "AWG").single().apply { put("ui_id", "awg"); put("host", "203.0.113.11") }
        val routing = MihomoConfig.Routing(ruDirect = true, adblock = true, servicesVpn = true,
            rules = listOf(MihomoConfig.Rule("domain", "chatgpt.com", "vpn")))
        val c = MihomoConfig.assemble(MihomoConfig.proxy(wg), MihomoConfig.Settings(routing = routing, geminiDns = true,
            socks = MihomoConfig.Socks(7897, "svpn", "pw", lan = true, noAuth = listOf("192.168.43.0/24")),
            checkProxy = MihomoConfig.CheckProxy(17001, "check", "x")), "127.0.0.1:9090", "secret", 5)
        Failover.applyServerGroups(c, wg, listOf(Failover.Group("g", listOf(wg, awg))), resolve = { emptySet() })
        c.remove("tun")
        val dir = createTempDir("svpn")
        rulesDir.copyRecursively(File(dir, "rules"))
        val file = File(dir, "config.yaml").apply { writeText(Json.encode(c)) }
        val process = ProcessBuilder(mihomo.absolutePath, "-t", "-d", dir.path, "-f", file.path).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().readText()
        assertTrue(process.waitFor(60, TimeUnit.SECONDS))
        assertEquals(output, 0, process.exitValue())
        assertTrue(output, "test is successful" in output)
        dir.deleteRecursively()
    }
}
