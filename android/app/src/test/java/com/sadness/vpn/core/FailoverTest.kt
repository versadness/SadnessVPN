package com.sadness.vpn.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Перенос tests/test_failover.py десктопа. */
class FailoverTest {
    private fun node(remark: String, host: String, id: String, vararg extra: Pair<String, Any?>): Server = linkedMapOf<String, Any?>(
        "remark" to remark, "protocol" to "vless", "host" to host, "port" to 443, "ui_id" to id,
        "uuid" to "11111111-1111-4111-8111-111111111111", "security" to "tls", "type" to "tcp", "sni" to "example.com",
    ).apply { putAll(extra) }

    private fun hy2(remark: String, host: String, id: String, port: Int = 443) =
        node(remark, host, id, "protocol" to "hysteria2", "password" to "p", "type" to "quic", "port" to port)

    private val noResolve: (String) -> Set<String> = { emptySet() }

    private val groups = listOf(
        Failover.Group("rw", listOf(
            node("🇩🇪 Germany XHTTP", "198.51.100.1", "de-x", "type" to "xhttp", "path" to "/x"),
            node("🇩🇪 Germany TCP", "198.51.100.2", "de-t"),
            node("🇫🇮 Finland", "198.51.100.3", "fi"),
            hy2("🇩🇪 Germany HY2", "198.51.100.4", "de-h"),
            node("🇩🇪 Broken", "198.51.100.5", "de-bad", "type" to "kcp"),
        )),
        Failover.Group("cloud", listOf(
            node("🇩🇪 Германия", "198.51.100.6", "de-c"),
            node("🇳🇱 Нидерланды", "198.51.100.7", "nl"),
        )),
    )
    private val selected = groups[0].servers[1]

    @Test fun namesAreStableAndCarryNoAddress() {
        assertEquals("srv-de-t", Failover.proxyName(selected))
        val anonymous: Server = linkedMapOf("remark" to "x", "host" to "203.0.113.9", "port" to 1)
        assertEquals(Failover.proxyName(anonymous), Failover.proxyName(LinkedHashMap(anonymous)))
        assertFalse("203.0.113.9" in Failover.proxyName(anonymous))
    }

    @Test fun countryComesFromTheFlag() {
        assertEquals("DE", Failover.country(selected))
        assertEquals("", Failover.country(linkedMapOf("remark" to "Без флага")))
    }

    @Test fun backupsComeOnlyFromTheSelectedSubscriptionAndTransport() {
        val backups = Failover.pickBackups(selected, groups, resolve = noResolve).map { it["ui_id"] }
        assertEquals(listOf("fi"), backups)
    }

    @Test fun sameCountryFirstThenOtherCountries() {
        val g = listOf(Failover.Group("g", listOf(
            node("🇩🇪 A", "198.51.100.10", "a"), node("🇫🇮 B", "198.51.100.11", "b"),
            node("🇩🇪 C", "198.51.100.12", "c"), node("🇩🇪 D XHTTP", "198.51.100.13", "d", "type" to "xhttp", "path" to "/x"))))
        assertEquals(listOf("c", "b"), Failover.pickBackups(g[0].servers[0], g, resolve = noResolve).map { it["ui_id"] })
    }

    @Test fun serversOnTheSameMachineAreNeverBackups() {
        val g = listOf(Failover.Group("rw", listOf(
            hy2("🇫🇮 Finland · HY2", "198.51.100.20", "fi1", 10445),
            hy2("🇫🇮 Finland 2 · HY2", "198.51.100.20", "fi2"),
            hy2("🇩🇪 Germany · HY2", "198.51.100.21", "de1"),
            hy2("🇩🇪 Germany 3 · HY2", "198.51.100.21", "de3", 8443),
            hy2("🇩🇪 Germany 2 · HY2", "198.51.100.22", "de2"),
            hy2("🇳🇱 Netherlands · HY2", "nl.example", "nl"),
        )))
        val resolve: (String) -> Set<String> = { if (it == "nl.example") setOf("198.51.100.22") else emptySet() }
        val backups = Failover.pickBackups(g[0].servers[1], g, resolve = resolve).map { it["ui_id"] }
        assertFalse("fi1" in backups)
        assertEquals(listOf("de1", "de2"), backups)
    }

    @Test fun unresolvableDomainIsComparedByName() {
        val a = node("🇩🇪 A", "vpn.example", "a")
        val b = node("🇩🇪 B", "vpn.example", "b")
        assertTrue(Failover.pickBackups(a, listOf(Failover.Group("g", listOf(a, b))), resolve = noResolve).isEmpty())
    }

    @Suppress("UNCHECKED_CAST")
    @Test fun groupsKeepRulesOnProxyAndIncludeEveryServer() {
        val config = MihomoConfig.assemble(MihomoConfig.proxy(selected), MihomoConfig.Settings(), "127.0.0.1:9090", "s", 5)
        val live = Failover.applyServerGroups(config, selected, groups, resolve = noResolve)
        val names = (config["proxies"] as List<Map<String, Any?>>).map { it["name"] }
        assertEquals("srv-de-t", names[0])
        assertEquals(live.keys, names.toSet())
        assertFalse("srv-de-bad" in live)
        val byName = (config["proxy-groups"] as List<Map<String, Any?>>).associateBy { it["name"] }
        assertEquals("select", byName["manual"]!!["type"])
        assertEquals("srv-de-t", (byName["manual"]!!["proxies"] as List<*>)[0])
        assertEquals("fallback", byName["proxy"]!!["type"])
        assertEquals(listOf("manual", "backup"), byName["proxy"]!!["proxies"])
        assertEquals(listOf("srv-fi"), byName["backup"]!!["proxies"])
        assertTrue("MATCH,proxy" in (config["rules"] as List<*>))
    }

    @Suppress("UNCHECKED_CAST")
    @Test fun withoutFailoverProxyIsJustTheSelectedServer() {
        val config = MihomoConfig.assemble(MihomoConfig.proxy(selected), MihomoConfig.Settings(), "127.0.0.1:9090", "s", 5)
        Failover.applyServerGroups(config, selected, groups, failover = false, resolve = noResolve)
        val byName = (config["proxy-groups"] as List<Map<String, Any?>>).associateBy { it["name"] }
        assertEquals(mapOf("name" to "proxy", "type" to "select", "proxies" to listOf("manual")), byName["proxy"])
        assertFalse("backup" in byName)
    }

    @Suppress("UNCHECKED_CAST")
    @Test fun muxAppliesToEveryServerLikeTheMainOne() {
        val config = MihomoConfig.assemble(MihomoConfig.proxy(selected), MihomoConfig.Settings(mux = true), "127.0.0.1:9090", "s", 5)
        Failover.applyServerGroups(config, selected, groups, mux = true, resolve = noResolve)
        val byName = (config["proxies"] as List<Map<String, Any?>>).associateBy { it["name"] }
        assertTrue("smux" in byName["srv-de-t"]!!)
        assertTrue("smux" in byName["srv-de-c"]!!)
        assertFalse("smux" in byName["srv-de-h"]!!)
    }
}
