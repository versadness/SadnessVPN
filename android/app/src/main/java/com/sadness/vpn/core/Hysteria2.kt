package com.sadness.vpn.core

/** Перенос engine/hysteria2.py: разбор hysteria2:// и проверка под Mihomo. */
object Hysteria2 {
    private val PORTS = Regex("""\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*""")
    private val HEX64 = Regex("[0-9a-f]{64}")

    /** Первый порт и исходная строка диапазона. */
    fun ports(value: Any?): Pair<Int, String> {
        val text = value.toString().trim()
        if (!PORTS.matches(text)) throw IllegalArgumentException("HY2: неверный порт или диапазон портов")
        for (part in text.split(',')) {
            val bounds = part.split('-').map { it.toIntOrNull() ?: -1 }
            if (!bounds.all { it in 1..65535 } || bounds.first() > bounds.last()) {
                throw IllegalArgumentException("HY2: порт должен быть от 1 до 65535, диапазон — возрастающим")
            }
        }
        return text.split(',')[0].split('-')[0].toInt() to text
    }

    fun fingerprint(value: Any?): String {
        val normalized = value.toString().replace(":", "").lowercase()
        if (!HEX64.matches(normalized)) {
            throw IllegalArgumentException("HY2: отпечаток сертификата должен содержать 64 шестнадцатеричных символа")
        }
        return normalized
    }

    /** ech= из ссылки или ech-opts из Clash → {enable, config}; null — ECH выключен. */
    fun echOpts(value: Any?): Map<String, Any?>? {
        if (value is Map<*, *> && value["enable"] == false) return null
        val config = (if (value is Map<*, *>) value["config"] else value)?.toString()?.trim().orEmpty()
        if (config.isEmpty()) return null
        try {
            strictBase64(config)
        } catch (_: IllegalArgumentException) {
            throw IllegalArgumentException("HY2: ECH-конфиг должен быть строкой base64")
        }
        return linkedMapOf("enable" to true, "config" to config)
    }

    fun validate(server: Server) {
        val obfs = server["obfs"]?.toString().orEmpty()
        if (obfs !in setOf("", "salamander")) throw IllegalArgumentException("HY2: эта сборка поддерживает только obfs=salamander")
        if (obfs.isNotEmpty() && server.str("obfs_password").isEmpty()) {
            throw IllegalArgumentException("HY2: для Salamander необходим obfs-password")
        }
        if (truthy(server["realm-opts"])) {
            throw IllegalArgumentException("HY2: Realm требует адрес control-сервера и пока не поддерживается")
        }
        if (truthy(server["ech"])) echOpts(server["ech"])
        ports(server["port"] ?: 443)
        if (truthy(server["ports"])) ports(server["ports"])
        if (truthy(server["pinned_cert"])) fingerprint(server["pinned_cert"])
    }

    fun parseUri(link: String): Server {
        val text = link.trim()
        val scheme = text.substringBefore("://", "")
        if (scheme != "hysteria2" && scheme != "hy2") throw IllegalArgumentException("Ожидается hysteria2:// или hy2:// ссылка")
        var rest = text.substringAfter("://")
        val fragment = rest.substringAfter('#', "").also { rest = rest.substringBefore('#') }
        val query = rest.substringAfter('?', "").also { rest = rest.substringBefore('?') }
        val path = if ('/' in rest) rest.substring(rest.indexOf('/')) else ""
        val netloc = rest.substringBefore('/')
        if (path !in setOf("", "/")) throw IllegalArgumentException("HY2: после адреса допустим только /, без пути")
        val at = netloc.lastIndexOf('@')
        val auth = if (at >= 0) netloc.substring(0, at) else ""
        val address = if (at >= 0) netloc.substring(at + 1) else netloc
        val host: String
        var portText: String
        if (address.startsWith("[")) {
            val end = address.indexOf(']')
            if (end < 0 || (address.length > end + 1 && address[end + 1] != ':')) throw IllegalArgumentException("HY2: неверный IPv6-адрес")
            host = address.substring(1, end)
            portText = if (address.length > end + 2) address.substring(end + 2) else "443"
        } else {
            val colon = address.indexOf(':')
            host = if (colon >= 0) address.substring(0, colon) else address
            portText = if (colon >= 0) address.substring(colon + 1) else "443"
        }
        if (host.isEmpty() || host.any { it.isWhitespace() }) throw IllegalArgumentException("HY2: не указан корректный адрес сервера")
        val (port, normalizedPorts) = ports(portText)
        portText = normalizedPorts
        val params = parseQuery(query)
        val insecure = (params["insecure"] ?: params["allowInsecure"] ?: "0").lowercase()
        if (insecure !in setOf("0", "1", "true", "false")) throw IllegalArgumentException("HY2: insecure должен быть 0 или 1")
        val server: Server = linkedMapOf(
            "protocol" to "hysteria2", "type" to "quic", "security" to "tls",
            "remark" to unquote(fragment).ifEmpty { "Hysteria 2" }, "host" to host,
            "port" to port, "password" to unquote(auth), "sni" to (params["sni"] ?: ""),
            "insecure" to (insecure == "1" || insecure == "true"), "alpn" to (params["alpn"] ?: ""),
            "obfs" to (params["obfs"] ?: ""), "obfs_password" to (params["obfs-password"] ?: ""),
        )
        val hopping = params["mport"] ?: if (',' in portText || '-' in portText) portText else ""
        if (hopping.isNotEmpty()) server["ports"] = ports(hopping).second
        params["pinSHA256"]?.let { server["pinned_cert"] = fingerprint(it) }
        params["ech"]?.let { server["ech"] = it }
        validate(server)
        return server
    }
}

/** Истинность значения в смысле Python: пустые строки, 0, false, null, пустые коллекции — ложь. */
fun truthy(value: Any?): Boolean = when (value) {
    null -> false
    is Boolean -> value
    is String -> value.isNotEmpty()
    is Number -> value.toDouble() != 0.0
    is Collection<*> -> value.isNotEmpty()
    is Map<*, *> -> value.isNotEmpty()
    else -> true
}
