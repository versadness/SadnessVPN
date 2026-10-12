package com.sadness.vpn.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TlsFingerprintTest {
    private fun config(): MutableMap<String, Any?> = linkedMapOf("proxies" to mutableListOf<Any?>(
        linkedMapOf<String, Any?>("name" to "a", "type" to "vless", "tls" to true, "client-fingerprint" to "chrome"),
        linkedMapOf<String, Any?>("name" to "b", "type" to "vless", "tls" to false),
        linkedMapOf<String, Any?>("name" to "c", "type" to "trojan"),
        linkedMapOf<String, Any?>("name" to "d", "type" to "hysteria2"),
    ))

    @Suppress("UNCHECKED_CAST")
    private fun fp(config: Map<String, Any?>, i: Int) = ((config["proxies"] as List<Any?>)[i] as Map<String, Any?>)["client-fingerprint"]

    @Test fun choiceAppliesToEveryTlsServer() {
        val c = config(); MihomoConfig.applyTlsFingerprint(c, "firefox")
        assertEquals("firefox", fp(c, 0)); assertNull(fp(c, 1)); assertEquals("firefox", fp(c, 2)); assertNull(fp(c, 3))
    }

    @Test fun providerKeepsSubscriptionValue() {
        val c = config(); MihomoConfig.applyTlsFingerprint(c, "provider")
        assertEquals("chrome", fp(c, 0)); assertNull(fp(c, 2))
    }
}
