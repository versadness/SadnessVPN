package com.sadness.vpn.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.concurrent.TimeUnit

class ConfigTest {
    private val server: Server = linkedMapOf("protocol" to "ss", "remark" to "A", "host" to "203.0.113.1", "port" to 8388,
        "method" to "chacha20-ietf-poly1305", "password" to "p", "ui_id" to "a")

    private fun config(settings: MihomoConfig.Settings, tunFd: Int = 5) =
        MihomoConfig.assemble(MihomoConfig.proxy(server), settings, "127.0.0.1:9090", "secret", tunFd)

    @Test fun socksIsOffByDefault() {
        val c = config(MihomoConfig.Settings())
        assertFalse("mixed-port" in c)
        assertFalse("authentication" in c)
    }

    @Test fun socksAlwaysRequiresPasswordEvenFromLocalhost() {
        val c = config(MihomoConfig.Settings(socks = MihomoConfig.Socks(7897, "svpn", "pw", lan = false)))
        assertEquals(7897, c["mixed-port"])
        assertEquals("127.0.0.1", c["bind-address"])
        assertEquals(false, c["allow-lan"])
        assertEquals(listOf("svpn:pw"), c["authentication"])
        // Пустой список: иначе Mihomo пускает 127.0.0.0/8 без пароля.
        assertEquals(emptyList<String>(), c["skip-auth-prefixes"])
    }

    @Test fun socksLanBindsAllInterfaces() {
        val c = config(MihomoConfig.Settings(socks = MihomoConfig.Socks(7897, "svpn", "pw", lan = true)))
        assertEquals("*", c["bind-address"]); assertEquals(true, c["allow-lan"])
    }

    @Test fun probeCoreNeverOpensSocks() {
        val c = config(MihomoConfig.Settings(socks = MihomoConfig.Socks(7897, "svpn", "pw", lan = false)), tunFd = -1)
        assertFalse("mixed-port" in c)
    }

    @Suppress("UNCHECKED_CAST")
    @Test fun geminiGoesDirectWithXboxDns() {
        val c = config(MihomoConfig.Settings(geminiDns = true))
        val rules = c["rules"] as List<String>
        assertTrue("DOMAIN-SUFFIX,gemini.google.com,DIRECT" in rules)
        assertTrue(rules.indexOf("DOMAIN-SUFFIX,aistudio.google.com,DIRECT") < rules.indexOf("MATCH,proxy"))
        val policy = (c["dns"] as Map<String, Any?>)["nameserver-policy"] as Map<String, Any?>
        assertEquals("111.88.96.50#DIRECT", policy["+.aistudio.google.com"])
        assertFalse("nameserver-policy" in (config(MihomoConfig.Settings())["dns"] as Map<String, Any?>))
    }

    /** Настоящий Mihomo принимает конфигурацию с SOCKS5 и Gemini. */
    @Test fun desktopMihomoAcceptsSocksAndGemini() {
        val mihomo = listOf("../../bin/mihomo.exe", "../../bin-linux/mihomo").map(::File).firstOrNull { it.isFile && it.canExecute() } ?: return
        val c = config(MihomoConfig.Settings(geminiDns = true, socks = MihomoConfig.Socks(7897, "svpn", "pw", lan = true)))
        c.remove("tun")  // дескриптор туннеля есть только на телефоне
        val dir = createTempDir("svpn")
        val file = File(dir, "config.yaml").apply { writeText(Json.encode(c)) }
        val process = ProcessBuilder(mihomo.absolutePath, "-t", "-d", dir.path, "-f", file.path).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().readText()
        assertTrue(process.waitFor(60, TimeUnit.SECONDS))
        assertEquals(output, 0, process.exitValue())
        assertTrue(output, "test is successful" in output)
        dir.deleteRecursively()
    }
}
