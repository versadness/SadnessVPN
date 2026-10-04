package com.sadness.vpn.core

import org.json.JSONObject

/** Перенос разбора ссылок из engine/config.py. */
object Links {
    val SUPPORTED_SCHEMES = listOf("vless://", "vmess://", "ss://", "trojan://", "hysteria2://", "hy2://")
    private val LINK_SCHEME = Regex("""^([a-z][a-z0-9+.-]{1,20})://""", RegexOption.IGNORE_CASE)

    private fun hostPort(value: String, defaultPort: Int?): Pair<String, Int> {
        if (value.startsWith("[")) {
            val end = value.indexOf(']')
            if (end < 0) throw IllegalArgumentException("Неверный IPv6-адрес")
            return value.substring(1, end) to value.substring(end + 2).toInt()
        }
        val colon = value.lastIndexOf(':')
        if (colon >= 0) return value.substring(0, colon) to value.substring(colon + 1).toInt()
        return value to (defaultPort ?: throw IllegalArgumentException("Нет порта в ссылке"))
    }

    private fun splitRemark(rest: String, default: String): Pair<String, String> {
        val hash = rest.lastIndexOf('#')
        return if (hash >= 0) rest.substring(0, hash) to unquote(rest.substring(hash + 1)) else rest to default
    }

    fun parseVless(link: String): Server {
        val text = link.trim()
        if (!text.startsWith("vless://")) throw IllegalArgumentException("Ожидается vless:// ссылка")
        val (rest, remark) = splitRemark(text.removePrefix("vless://"), "VLESS")
        if ('@' !in rest) throw IllegalArgumentException("Неверный формат vless://")
        val userId = rest.substringBefore('@')
        val hostPart = rest.substringAfter('@')
        val (hostPortText, query) = if ('?' in hostPart) hostPart.substringBefore('?') to hostPart.substringAfter('?') else hostPart to ""
        val (host, port) = hostPort(hostPortText, 443)
        val params = parseQuery(query)
        val type = params["type"]
        val server: Server = linkedMapOf(
            "remark" to remark, "host" to host, "port" to port, "uuid" to userId,
            "security" to (params["security"] ?: "none"),
            "type" to (if (type == "splithttp") "xhttp" else type ?: "tcp"),
        )
        if (type == "xhttp" || type == "splithttp") server["xhttp"] = Transports.xhttpFromQuery(params)
        server.putAll(linkedMapOf(
            "sni" to (params["sni"] ?: ""), "fp" to (params["fp"] ?: ""), "pbk" to (params["pbk"] ?: ""),
            "sid" to (params["sid"] ?: ""), "flow" to (params["flow"] ?: ""), "path" to (params["path"] ?: ""),
            "host_header" to (params["host"] ?: ""), "serviceName" to (params["serviceName"] ?: ""),
            "header_type" to (params["headerType"] ?: ""), "alpn" to (params["alpn"] ?: ""),
            "allowInsecure" to (params["allowInsecure"] ?: "0"),
            "pinned_cert" to (params["pcs"] ?: params["pinnedPeerCertSha256"] ?: ""),
            "verify_cert_name" to (params["vcn"] ?: params["verifyPeerCertByName"] ?: ""),
            "encryption" to (params["encryption"] ?: "none"),
        ))
        return server
    }

    fun parseVmess(link: String): Server {
        val text = link.trim()
        if (!text.startsWith("vmess://")) throw IllegalArgumentException("Ожидается vmess:// ссылка")
        val payload = text.removePrefix("vmess://").substringBefore('#').trim()
        val node = try {
            JSONObject(String(lenientBase64(payload), Charsets.UTF_8))
        } catch (_: Exception) {
            throw IllegalArgumentException("VMess: ссылка должна содержать base64 с JSON")
        }
        fun field(key: String) = node.opt(key)?.takeIf { it != JSONObject.NULL }?.toString().orEmpty()
        val host = field("add").trim()
        if (host.isEmpty()) throw IllegalArgumentException("VMess: не указан адрес сервера")
        val port = (field("port").ifEmpty { "443" }).toIntOrNull() ?: throw IllegalArgumentException("VMess: некорректный порт")
        if (port !in 1..65535) throw IllegalArgumentException("VMess: порт должен быть от 1 до 65535")
        if (field("id").isBlank()) throw IllegalArgumentException("VMess: не указан UUID")
        var network = field("net").ifEmpty { "tcp" }.lowercase()
        if (network == "splithttp") network = "xhttp"
        val tls = field("tls").lowercase()
        return linkedMapOf(
            "protocol" to "vmess", "remark" to field("ps").ifEmpty { "VMess" }, "host" to host, "port" to port,
            "uuid" to field("id").trim(), "alter_id" to (field("aid").toIntOrNull() ?: 0),
            "method" to field("scy").ifEmpty { "auto" },
            "security" to (if (tls == "reality") "reality" else if (tls == "tls") "tls" else "none"),
            "type" to network, "sni" to field("sni"), "fp" to field("fp"), "pbk" to field("pbk"), "sid" to field("sid"),
            "path" to field("path"), "host_header" to field("host"),
            "serviceName" to (if (network == "grpc") field("path") else ""),
            "header_type" to (if (network == "tcp") field("type") else ""),
            "alpn" to field("alpn"),
            "allowInsecure" to (if (field("allowInsecure") in setOf("1", "true")) "1" else "0"),
        )
    }

    fun parseSs(link: String): Server {
        val text = link.trim()
        if (!text.startsWith("ss://")) throw IllegalArgumentException("Ожидается ss:// ссылка")
        var (rest, remark) = splitRemark(text.removePrefix("ss://"), "Shadowsocks")
        var query = ""
        if ('?' in rest) { query = rest.substringAfter('?'); rest = rest.substringBefore('?') }
        rest = rest.trimEnd('/')
        val method: String
        val password: String
        val hostport: String
        if ('@' in rest) {
            val userinfo = rest.substringBeforeLast('@')
            hostport = rest.substringAfterLast('@')
            val decoded = runCatching { String(lenientBase64(userinfo), Charsets.UTF_8) }.getOrNull()
            val pair = if (decoded != null && ':' in decoded && decoded.all { !it.isISOControl() }) decoded else unquote(userinfo)
            method = pair.substringBefore(':'); password = pair.substringAfter(':', "")
        } else {
            val decoded = runCatching { String(lenientBase64(rest), Charsets.UTF_8) }.getOrNull()
                ?: throw IllegalArgumentException("Неверный формат ss://")
            if ('@' !in decoded) throw IllegalArgumentException("Неверный формат ss://")
            val userinfo = decoded.substringBeforeLast('@')
            hostport = decoded.substringAfterLast('@')
            method = userinfo.substringBefore(':'); password = userinfo.substringAfter(':', "")
        }
        val (host, port) = try {
            hostPort(hostport, null)
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("Нет порта в ss:// ссылке")
        }
        val server: Server = linkedMapOf("protocol" to "ss", "remark" to remark, "host" to host, "port" to port,
            "method" to method.trim(), "password" to password.trim())
        val plugin = parseQuery(query)["plugin"].orEmpty()
        if (plugin.isNotEmpty()) {
            val (name, opts) = parseSsPlugin(plugin)
            server["plugin"] = name; server["plugin_opts"] = opts
        }
        return server
    }

    /** SIP003 «name;key=value;flag» → (плагин Mihomo, plugin-opts). */
    fun parseSsPlugin(value: String): Pair<String, MutableMap<String, Any?>> {
        val parts = value.split(';').map { it.trim() }.filter { it.isNotEmpty() }.ifEmpty { listOf("") }
        val name = parts.first()
        val options = LinkedHashMap<String, Any>()
        for (part in parts.drop(1)) {
            val eq = part.indexOf('=')
            if (eq >= 0) options[part.substring(0, eq).trim()] = part.substring(eq + 1).trim() else options[part.trim()] = true
        }
        when (name) {
            "obfs-local", "simple-obfs", "obfs" -> {
                val mode = options["obfs"] as? String ?: "http"
                if (mode != "http" && mode != "tls") throw IllegalArgumentException("Shadowsocks obfs: режим $mode не поддерживается")
                val opts: MutableMap<String, Any?> = linkedMapOf("mode" to mode)
                (options["obfs-host"] as? String)?.let { opts["host"] = it }
                return "obfs" to opts
            }
            "v2ray-plugin" -> {
                val mode = options["mode"] as? String ?: "websocket"
                if (mode != "websocket") throw IllegalArgumentException("Shadowsocks v2ray-plugin: режим $mode не поддерживается ядром Mihomo")
                val opts: MutableMap<String, Any?> = linkedMapOf("mode" to "websocket", "tls" to (options["tls"] == true))
                for (key in listOf("host", "path")) (options[key] as? String)?.let { opts[key] = it }
                if (options["mux"] == true || options["mux"] == "1") opts["mux"] = true
                return "v2ray-plugin" to opts
            }
        }
        throw IllegalArgumentException("Shadowsocks: плагин ${name.ifEmpty { "без имени" }} не поддерживается ядром Mihomo")
    }

    fun parseTrojan(link: String): Server {
        val text = link.trim()
        if (!text.startsWith("trojan://")) throw IllegalArgumentException("Ожидается trojan:// ссылка")
        var (rest, remark) = splitRemark(text.removePrefix("trojan://"), "Trojan")
        var query = ""
        if ('?' in rest) { query = rest.substringAfter('?'); rest = rest.substringBefore('?') }
        if ('@' !in rest) throw IllegalArgumentException("Неверный формат trojan://")
        val password = rest.substringBeforeLast('@')
        val (host, port) = hostPort(rest.substringAfterLast('@'), 443)
        val params = parseQuery(query)
        return linkedMapOf(
            "protocol" to "trojan", "remark" to remark, "host" to host, "port" to port,
            "password" to unquote(password), "sni" to (params["sni"] ?: params["peer"] ?: ""),
            "allowInsecure" to (params["allowInsecure"] ?: params["skip-cert-verify"] ?: "0"),
            "alpn" to (params["alpn"] ?: ""), "fp" to (params["fp"] ?: ""), "type" to (params["type"] ?: "tcp"),
            "path" to (params["path"] ?: ""), "host_header" to (params["host"] ?: ""),
            "serviceName" to (params["serviceName"] ?: ""), "header_type" to (params["headerType"] ?: ""),
        )
    }

    fun parse(link: String): Server {
        val text = link.trim()
        return when {
            text.startsWith("vless://") -> parseVless(text)
            text.startsWith("vmess://") -> parseVmess(text)
            text.startsWith("ss://") -> parseSs(text)
            text.startsWith("trojan://") -> parseTrojan(text)
            text.startsWith("hysteria2://") || text.startsWith("hy2://") -> Hysteria2.parseUri(text)
            else -> throw IllegalArgumentException("Неподдерживаемый протокол. Ожидается: vless://, vmess://, ss://, trojan://, hysteria2://")
        }
    }

    /** Имя узла из #фрагмента — без UUID, паролей и адреса. */
    private fun label(line: String): String {
        val name = if ('#' in line) printable(unquote(line.substringAfterLast('#'))).trim().take(80) else ""
        return name.ifEmpty { line.substringBefore("://") + "-узел" }
    }

    data class Parsed(val servers: MutableList<Server>, val rejected: MutableList<Map<String, String>>, val received: Int)

    fun parseShareLinks(raw: String): Parsed {
        val servers = mutableListOf<Server>()
        val rejected = mutableListOf<Map<String, String>>()
        var received = 0
        for (rawLine in raw.lines()) {
            val line = rawLine.trim()
            val match = LINK_SCHEME.find(line) ?: continue
            received++
            if (SUPPORTED_SCHEMES.none { line.startsWith(it) }) {
                rejected += mapOf("name" to label(line), "reason" to "протокол ${match.groupValues[1].lowercase()} не поддерживается ядром Mihomo")
                continue
            }
            try {
                val server = parse(line)
                MihomoConfig.ensureSupported(server)
                servers += server
            } catch (e: IllegalArgumentException) {
                rejected += mapOf("name" to label(line), "reason" to (e.message ?: "ссылка повреждена").take(200))
            } catch (_: RuntimeException) {
                rejected += mapOf("name" to label(line), "reason" to "ссылка повреждена")
            }
        }
        return Parsed(servers, rejected, received)
    }

    fun looksLikeLinks(raw: String): Boolean =
        LINK_SCHEME.containsMatchIn(raw.trimStart()) || SUPPORTED_SCHEMES.any { it in raw }
}
