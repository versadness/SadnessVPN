package com.sadness.vpn.core

import java.net.InetAddress

/**
 * WireGuard и AmneziaWG из файлов .conf — перенос engine/wg_config.py.
 *
 * На телефоне оба работают через Mihomo: его outbound wireguard принимает
 * amnezia-wg-option всех версий (1.x, 1.5, 2, 3), отдельная служба не нужна.
 */
object WireGuard {
    /** Поле .conf → ключ amnezia-wg-option у Mihomo. */
    private val AWG_KEYS = mapOf(
        "jc" to "jc", "jmin" to "jmin", "jmax" to "jmax",
        "s1" to "s1", "s2" to "s2", "s3" to "s3", "s4" to "s4",
        "h1" to "h1", "h2" to "h2", "h3" to "h3", "h4" to "h4",
        "i1" to "i1", "i2" to "i2", "i3" to "i3", "i4" to "i4", "i5" to "i5",
        "j1" to "j1", "j2" to "j2", "j3" to "j3", "itime" to "itime",
        "headerprotectionkey" to "header-protection-key", "contentpaddingaddition" to "content-padding-addition",
        "rekeyaftertime" to "rekey-after-time", "rekeytimeout" to "rekey-timeout",
        "rejectaftertime" to "reject-after-time", "keepalivetimeout" to "keepalive-timeout",
        "maxhandshakeattempts" to "max-handshake-attempts",
        "randomtrailers" to "random-trailers", "disablecookies" to "disable-cookies",
    )
    private val INT_KEYS = setOf("jc", "jmin", "jmax", "s1", "s2", "s3", "s4", "itime")
    private val BOOL_KEYS = setOf("random-trailers", "disable-cookies")
    private val V3_KEYS = setOf("header-protection-key", "content-padding-addition", "rekey-after-time", "rekey-timeout",
        "reject-after-time", "keepalive-timeout", "max-handshake-attempts", "random-trailers", "disable-cookies")

    /** Разобрать файл (в нём может быть несколько [Interface]); name — имя файла без расширения. */
    fun parse(text: String, name: String = ""): List<Server> {
        val chunks = text.split(Regex("(?i)(?=\\[Interface\\])")).map { it.trim() }.filter { "[INTERFACE]" in it.uppercase() }
        if (chunks.isEmpty()) throw IllegalArgumentException("В файле нет секции [Interface] — это не конфиг WireGuard.")
        return chunks.mapIndexed { index, chunk ->
            val label = when {
                name.isEmpty() -> ""
                chunks.size == 1 -> name
                else -> "$name ${index + 1}"
            }
            parseOne(chunk, label)
        }
    }

    private fun parseOne(text: String, name: String): Server {
        var section = ""
        var peers = 0
        var privateKey = ""; var publicKey = ""; var psk = ""; var endpoint = ""; var port = 51820
        var addresses = listOf<String>(); var mtu = 1280; var keepalive = 0
        val awg = LinkedHashMap<String, Any?>()
        for (rawLine in text.lines()) {
            val line = rawLine.trim()
            if (line.isEmpty() || line.startsWith("#") || line.startsWith(";")) continue
            if (line.startsWith("[")) {
                section = line.trim('[', ']').lowercase()
                if (section == "peer" && ++peers > 1) throw IllegalArgumentException("Несколько Peer в одном конфиге пока не поддерживаются.")
                continue
            }
            val eq = line.indexOf('=')
            if (eq < 0) continue
            val key = line.substring(0, eq).trim().lowercase()
            val value = line.substring(eq + 1).trim()
            when {
                section == "interface" && key == "privatekey" -> privateKey = value
                section == "interface" && key == "address" -> addresses = value.split(',').map { it.trim() }.filter { it.isNotEmpty() }
                section == "interface" && key == "mtu" -> mtu = value.toIntOrNull() ?: mtu
                section == "peer" && key == "publickey" -> publicKey = value
                section == "peer" && key == "presharedkey" -> psk = value
                section == "peer" && key == "persistentkeepalive" -> keepalive = (value.toIntOrNull() ?: 0).coerceIn(0, 65535)
                section == "peer" && key == "endpoint" -> {
                    val colon = value.lastIndexOf(':')
                    if (colon < 0) throw IllegalArgumentException("Endpoint должен содержать адрес и порт")
                    endpoint = value.substring(0, colon).trim('[', ']')
                    port = value.substring(colon + 1).toIntOrNull() ?: throw IllegalArgumentException("Неверный порт Endpoint")
                }
                key in AWG_KEYS -> {
                    val target = AWG_KEYS.getValue(key)
                    awg[target] = when (target) {
                        in INT_KEYS -> value.toLongOrNull()?.let { if (target == "itime") it else it.toInt() }
                            ?: throw IllegalArgumentException("AmneziaWG: $key должен быть числом")
                        in BOOL_KEYS -> value.lowercase() in setOf("1", "true", "yes", "on")
                        else -> value
                    }
                }
            }
        }
        if (awg.keys.any { it in V3_KEYS }) awg["version"] = 3
        val awgOn = awg.isNotEmpty()
        val remark = name.ifEmpty { if (endpoint.isNotEmpty()) "$endpoint:$port" else "WireGuard" }
        val server: Server = linkedMapOf(
            "protocol" to "wireguard", "type" to "wg", "remark" to (if (awgOn && !name.contains("AWG", true)) "$remark · AWG" else remark),
            "host" to endpoint, "port" to port, "private_key" to privateKey, "peer_public_key" to publicKey,
            "pre_shared_key" to psk, "address" to addresses, "mtu" to mtu, "persistent_keepalive" to keepalive,
        )
        if (awgOn) server["awg"] = awg
        validate(server)
        return server
    }

    fun validate(server: Server) {
        for (key in listOf("private_key", "peer_public_key", "pre_shared_key")) {
            val value = server.str(key)
            if (key == "pre_shared_key" && value.isEmpty()) continue
            val ok = runCatching { strictBase64(value).size == 32 }.getOrDefault(false)
            if (!ok) throw IllegalArgumentException(when (key) {
                "private_key" -> "PrivateKey не найден или некорректен"
                "peer_public_key" -> "PublicKey пира не найден или некорректен"
                else -> "PresharedKey некорректен"
            })
        }
        val addresses = (server["address"] as? List<*>).orEmpty().map { it.toString() }
        if (addresses.isEmpty()) throw IllegalArgumentException("Address не задан")
        addresses.forEach { ipOf(it) }
        val host = server.str("host")
        if (host.isEmpty() || host.any { it.isWhitespace() }) throw IllegalArgumentException("Endpoint не задан или некорректен")
        if ((server["port"].toString().toIntOrNull() ?: 0) !in 1..65535) throw IllegalArgumentException("Порт Endpoint должен быть от 1 до 65535")
    }

    private fun ipOf(cidr: String): InetAddress {
        val ip = cidr.substringBefore('/')
        if (!Regex("[0-9a-fA-F:.]+").matches(ip)) throw IllegalArgumentException("Неверный Address: $cidr")
        return runCatching { InetAddress.getByName(ip) }.getOrElse { throw IllegalArgumentException("Неверный Address: $cidr") }
    }

    fun proxy(server: Server): MutableMap<String, Any?> {
        validate(server)
        val addresses = (server["address"] as? List<*>).orEmpty().map { it.toString() }
        val v4 = addresses.map { it.substringBefore('/') }.firstOrNull { '.' in it }
        val v6 = addresses.map { it.substringBefore('/') }.firstOrNull { ':' in it }
        val proxy: MutableMap<String, Any?> = linkedMapOf(
            "name" to "proxy", "type" to "wireguard", "server" to server.str("host"),
            "port" to server["port"].toString().toInt(),
            "private-key" to server.str("private_key"), "public-key" to server.str("peer_public_key"),
            "allowed-ips" to listOf("0.0.0.0/0", "::/0"), "udp" to true,
            "mtu" to (server["mtu"].toString().toIntOrNull() ?: 1280),
        )
        v4?.let { proxy["ip"] = it }
        v6?.let { proxy["ipv6"] = it }
        server.str("pre_shared_key").takeIf { it.isNotEmpty() }?.let { proxy["pre-shared-key"] = it }
        (server["persistent_keepalive"].toString().toIntOrNull() ?: 0).takeIf { it > 0 }?.let { proxy["persistent-keepalive"] = it }
        (server["awg"] as? Map<*, *>)?.takeIf { it.isNotEmpty() }?.let { proxy["amnezia-wg-option"] = LinkedHashMap(it) }
        return proxy
    }
}
