package com.sadness.vpn.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.Base64
import java.util.concurrent.TimeUnit

class SubscriptionTest {
    private val uuid = "11111111-1111-4111-8111-111111111111"

    @Test fun base64ListIsDecoded() {
        val links = "vless://$uuid@203.0.113.1:443?security=tls#A\nhy2://p@203.0.113.2:443#B\n"
        val body = Base64.getEncoder().encodeToString(links.toByteArray())
        val result = Subscription.parse(Subscription.decode(body.toByteArray()), linkedMapOf())
        assertEquals(2, result.servers.size)
        assertEquals(2, result.metadata["accepted"])
    }

    @Test fun clashYamlIsImported() {
        val yaml = """
            proxies:
              - name: "🇫🇮 Finland"
                type: hysteria2
                server: 203.0.113.3
                port: 443
                password: p
                sni: f.example
              - name: WG
                type: wireguard
                server: 203.0.113.4
                port: 51820
        """.trimIndent()
        val result = Subscription.parse(Subscription.decode(yaml.toByteArray()), linkedMapOf())
        assertEquals(1, result.servers.size)
        assertEquals("quic", result.servers[0]["type"])
        val rejected = result.metadata["rejected"] as List<*>
        assertEquals(1, rejected.size)
    }

    @Test fun yamlAliasesAreRefused() {
        val yaml = "base: &b {type: vless}\nproxies:\n  - *b\n"
        val error = assertThrows(IllegalArgumentException::class.java) { Transports.parseClashNodes(yaml) }
        assertTrue(error.message!!.contains("якор"))
    }

    @Test fun htmlPageGivesAClearError() {
        val error = assertThrows(SubscriptionException::class.java) { Subscription.decode("<!DOCTYPE html><html>".toByteArray()) }
        assertTrue(error.message!!.contains("веб-страница"))
    }

    @Test fun emptyProxiesListIsExplained() {
        val error = assertThrows(SubscriptionException::class.java) { Subscription.parse("proxies: []", linkedMapOf()) }
        assertTrue(error.message!!.contains("proxies: []"))
    }

    @Test fun metadataTitleTrafficAndExpire() {
        val title = "base64:" + Base64.getEncoder().encodeToString("Мой VPN".toByteArray())
        val meta = Subscription.parseMetadata(mapOf("Profile-Title" to title,
            "Subscription-Userinfo" to "upload=10; download=20; total=1000; expire=1893456000"), now = 1)
        assertEquals("Мой VPN", meta["provider_name"])
        assertEquals(10L, meta["upload"]); assertEquals(1000L, meta["total"]); assertEquals(1893456000L, meta["expire"])
    }

    @Test fun deviceLimitIsExplained() {
        val error = assertThrows(SubscriptionException::class.java) {
            Subscription.checkDeviceHeaders(mapOf("X-Hwid-Max-Devices-Reached" to "true"))
        }
        assertTrue(error.message!!.contains("лимит устройств"))
    }

    @Test fun headersIdentifyAndroidWithoutPhoneModel() {
        val h = Subscription.headers(Subscription.ClientInfo("1.0.0", "14", "arm64"), "svpn-0123456789abcdef0123456789abcdef")
        assertEquals("SadnessVPN/v1.0.0 platform/android platform-version/14 arch/arm64", h["User-Agent"])
        assertEquals("Android", h["X-Device-OS"]); assertEquals("Phone", h["X-Device-Model"])
        val named = Subscription.headers(Subscription.ClientInfo("1.0.0", "16", "arm64", "samsung SM-S928B"), "")
        assertEquals("samsung SM-S928B", named["X-Device-Model"])
        assertEquals("Xiaomi 2311DRK48G", Subscription.deviceModel("Xiaomi", "2311DRK48G"))
        assertEquals("Pixel 8", Subscription.deviceModel("Google", "Pixel 8").removePrefix("Google "))
        assertEquals("samsung SM-S928B", Subscription.deviceModel("samsung", "samsung SM-S928B"))
        assertEquals("Phone", Subscription.deviceModel("", "\u0416\u0416"))
        assertEquals("svpn-0123456789abcdef0123456789abcdef", h["HWID"])
        assertTrue(Subscription.generateHwid().matches(Regex("svpn-[0-9a-f]{32}")))
    }

    /** Настоящий Mihomo из десктопной сборки проверяет конфигурацию Android-клиента. */
    @Test fun desktopMihomoAcceptsTheAndroidConfig() {
        val mihomo = listOf("../../bin/mihomo.exe", "../../bin-linux/mihomo").map(::File).firstOrNull { it.isFile && it.canExecute() }
            ?: return
        val servers = Subscription.parse(listOf(
            "vless://$uuid@203.0.113.1:443?security=reality&sni=a.example&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&sid=ab&type=tcp&flow=xtls-rprx-vision#🇩🇪 A",
            "vless://$uuid@203.0.113.2:443?security=tls&type=xhttp&path=%2Fx#🇩🇪 B",
            "hy2://p@203.0.113.3:443?sni=h.example#🇫🇮 C",
            "trojan://p@203.0.113.4:443?sni=t.example&type=grpc&serviceName=g#🇳🇱 D",
        ).joinToString("\n"), linkedMapOf()).servers
        servers.forEachIndexed { i, s -> s["ui_id"] = "id$i" }
        val config = MihomoConfig.assemble(MihomoConfig.proxy(servers[0]), MihomoConfig.Settings(), "127.0.0.1:9090", "secret", -1)
        Failover.applyServerGroups(config, servers[0], listOf(Failover.Group("g", servers)), resolve = { emptySet() })
        val dir = createTempDir("svpn")
        val file = File(dir, "config.yaml").apply { writeText(Json.encode(config)) }
        val process = ProcessBuilder(mihomo.absolutePath, "-t", "-d", dir.path, "-f", file.path).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().readText()
        assertTrue(process.waitFor(60, TimeUnit.SECONDS))
        assertEquals(output, 0, process.exitValue())
        dir.deleteRecursively()
    }
}
