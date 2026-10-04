package com.sadness.vpn.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class LinksTest {
    private val uuid = "11111111-1111-4111-8111-111111111111"

    @Test fun vlessRealityWithFlow() {
        val s = Links.parse("vless://$uuid@203.0.113.1:443?security=reality&sni=www.example.com&fp=chrome&pbk=PUBKEY&sid=ab12&flow=xtls-rprx-vision&type=tcp#%F0%9F%87%A9%F0%9F%87%AA%20Germany")
        assertEquals("🇩🇪 Germany", s["remark"])
        assertEquals(443, s["port"]); assertEquals("reality", s["security"]); assertEquals("PUBKEY", s["pbk"])
        val proxy = MihomoConfig.proxy(s)
        assertEquals(mapOf("public-key" to "PUBKEY", "short-id" to "ab12"), proxy["reality-opts"])
        assertEquals("xtls-rprx-vision", proxy["flow"])
        assertEquals("www.example.com", proxy["servername"])
    }

    @Test fun vlessXhttpWithExtraBecomesMihomoOptions() {
        val extra = java.net.URLEncoder.encode("""{"xPaddingBytes":"100-1000","xmux":{"maxConcurrency":"16-32","cMaxLifetimeMs":0},"scMaxBufferedPosts":30}""", "UTF-8")
        val s = Links.parse("vless://$uuid@[2001:db8::1]:8443?security=tls&type=xhttp&path=%2Fx&mode=packet-up&extra=$extra#XHTTP")
        assertEquals("2001:db8::1", s["host"]); assertEquals(8443, s["port"]); assertEquals("xhttp", s["type"])
        val opts = MihomoConfig.proxy(s)["xhttp-opts"] as Map<*, *>
        assertEquals("/x", opts["path"]); assertEquals("packet-up", opts["mode"])
        assertEquals("100-1000", opts["x-padding-bytes"])
        assertEquals(mapOf("max-concurrency" to "16-32"), opts["reuse-settings"])
        assertFalse("scMaxBufferedPosts" in opts)
    }

    @Test fun xhttpUnknownParameterIsRefusedWithReason() {
        val extra = java.net.URLEncoder.encode("""{"downloadSettings":{}}""", "UTF-8")
        val error = assertThrows(IllegalArgumentException::class.java) {
            MihomoConfig.ensureSupported(Links.parse("vless://$uuid@h:443?type=xhttp&extra=$extra"))
        }
        assertTrue(error.message!!.contains("downloadSettings"))
    }

    @Test fun vmessV2rayNJson() {
        val json = """{"v":"2","ps":"VM","add":"203.0.113.2","port":"8080","id":"$uuid","aid":"0","net":"ws","path":"/ws","host":"cdn.example","tls":"tls","sni":"cdn.example"}"""
        val s = Links.parse("vmess://" + Base64.getEncoder().encodeToString(json.toByteArray()))
        assertEquals("vmess", s["protocol"]); assertEquals(8080, s["port"]); assertEquals("ws", s["type"])
        val proxy = MihomoConfig.proxy(s)
        assertEquals("ws", proxy["network"])
        assertEquals(mapOf("path" to "/ws", "headers" to mapOf("Host" to "cdn.example")), proxy["ws-opts"])
    }

    @Test fun shadowsocksSip002WithObfsPlugin() {
        val user = Base64.getUrlEncoder().withoutPadding().encodeToString("chacha20-ietf-poly1305:secret".toByteArray())
        val s = Links.parse("ss://$user@203.0.113.3:8388/?plugin=obfs-local%3Bobfs%3Dtls%3Bobfs-host%3Dexample.com#SS")
        assertEquals("chacha20-ietf-poly1305", s["method"]); assertEquals("secret", s["password"])
        assertEquals("obfs", s["plugin"]); assertEquals(mapOf("mode" to "tls", "host" to "example.com"), s["plugin_opts"])
    }

    @Test fun shadowsocksLegacyFullyEncoded() {
        val all = Base64.getEncoder().encodeToString("aes-256-gcm:pa:ss@203.0.113.4:443".toByteArray())
        val s = Links.parse("ss://$all#Old")
        assertEquals("aes-256-gcm", s["method"]); assertEquals("pa:ss", s["password"]); assertEquals(443, s["port"])
    }

    @Test fun trojanKeepsPlusInPassword() {
        val s = Links.parse("trojan://p%2Bw+d@203.0.113.5:443?sni=t.example#T")
        assertEquals("p+w+d", s["password"]); assertEquals("t.example", s["sni"])
    }

    @Test fun hysteria2PortHoppingAndPin() {
        val pin = "AB".repeat(32)
        val s = Links.parse("hy2://pass@203.0.113.6:20000-30000?sni=h.example&obfs=salamander&obfs-password=o&pinSHA256=$pin#HY2")
        assertEquals(20000, s["port"]); assertEquals("20000-30000", s["ports"]); assertEquals(pin.lowercase(), s["pinned_cert"])
        val proxy = MihomoConfig.proxy(s)
        assertEquals("salamander", proxy["obfs"]); assertEquals("20000-30000", proxy["ports"]); assertEquals("h.example", proxy["sni"])
    }

    @Test fun shareListKeepsGoodLinksAndExplainsBadOnes() {
        val raw = listOf(
            "vless://$uuid@203.0.113.1:443?security=tls#Good",
            "tuic://x@203.0.113.9:443#Tuic",
            "vless://$uuid@203.0.113.1:443?type=kcp#Kcp",
            "просто текст",
        ).joinToString("\n")
        val parsed = Links.parseShareLinks(raw)
        assertEquals(1, parsed.servers.size)
        assertEquals(3, parsed.received)
        assertEquals(listOf("Tuic", "Kcp"), parsed.rejected.map { it["name"] })
        assertTrue(parsed.rejected[0]["reason"]!!.contains("tuic"))
    }
}
