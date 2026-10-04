package com.sadness.vpn.core

import org.json.JSONArray
import org.json.JSONObject
import org.snakeyaml.engine.v2.api.Load
import org.snakeyaml.engine.v2.api.LoadSettings

/** Перенос engine/transports.py: XHTTP из ссылок и безопасный импорт узлов Clash. */
object Transports {
    fun xhttpFromQuery(params: Map<String, String>): MutableMap<String, Any?> {
        val settings: MutableMap<String, Any?> = linkedMapOf(
            "path" to (params["path"]?.ifEmpty { null } ?: "/"),
            "host" to (params["host"] ?: ""),
            "mode" to (params["mode"]?.ifEmpty { null } ?: "auto"),
        )
        params["extra"]?.takeIf { it.isNotEmpty() }?.let { raw ->
            val extra = try {
                jsonToKotlin(JSONObject(raw))
            } catch (_: Exception) {
                if (raw.trimStart().startsWith("{")) throw IllegalArgumentException("XHTTP: extra должен содержать корректный JSON")
                throw IllegalArgumentException("XHTTP: extra должен быть JSON-объектом")
            }
            settings["extra"] = extra
        }
        return settings
    }

    private val XHTTP_KEYS = mapOf(
        "path" to "path", "host" to "host", "mode" to "mode", "headers" to "headers",
        "noGRPCHeader" to "no-grpc-header", "xPaddingBytes" to "x-padding-bytes",
        "xPaddingObfsMode" to "x-padding-obfs-mode", "xPaddingKey" to "x-padding-key",
        "xPaddingHeader" to "x-padding-header", "xPaddingPlacement" to "x-padding-placement",
        "xPaddingMethod" to "x-padding-method", "uplinkHTTPMethod" to "uplink-http-method",
        "sessionPlacement" to "session-placement", "sessionKey" to "session-key",
        "sessionTable" to "session-table", "sessionLength" to "session-length",
        "seqPlacement" to "seq-placement", "seqKey" to "seq-key",
        "uplinkDataPlacement" to "uplink-data-placement", "uplinkDataKey" to "uplink-data-key",
        "uplinkChunkSize" to "uplink-chunk-size", "scMaxEachPostBytes" to "sc-max-each-post-bytes",
        "scMinPostsIntervalMs" to "sc-min-posts-interval-ms",
    )
    private val XMUX_KEYS = mapOf(
        "maxConcurrency" to "max-concurrency", "maxConnections" to "max-connections",
        "cMaxReuseTimes" to "c-max-reuse-times", "hMaxRequestTimes" to "h-max-request-times",
        "hMaxReusableSecs" to "h-max-reusable-secs", "hKeepAlivePeriod" to "h-keep-alive-period",
    )
    // Xray оставляет их в ссылке, но на соединение они не влияют (см. десктоп).
    private val XHTTP_IGNORED = setOf("scMaxConcurrentPosts", "scMaxBufferedPosts", "scStreamUpServerSecs", "noSSEHeader")
    private val XMUX_IGNORED = setOf("cMaxLifetimeMs")

    @Suppress("UNCHECKED_CAST")
    fun mihomoXhttp(server: Server): MutableMap<String, Any?> {
        server["mihomo_xhttp"]?.let { return deepCopy(it) as MutableMap<String, Any?> }
        val settings = (deepCopy(server["xhttp"] ?: linkedMapOf(
            "path" to (server.str("path").ifEmpty { "/" }), "host" to server.str("host_header"),
        )) as MutableMap<String, Any?>)
        val extra = settings.remove("extra") as? Map<String, Any?> ?: emptyMap()
        settings.putAll(extra)
        val result = LinkedHashMap<String, Any?>()
        for ((key, value) in settings) {
            when {
                key == "xmux" -> {
                    val xmux = value as? Map<String, Any?> ?: emptyMap()
                    val unsupported = xmux.keys - XMUX_KEYS.keys - XMUX_IGNORED
                    if (unsupported.isNotEmpty()) {
                        throw IllegalArgumentException("XHTTP XMUX: эти параметры не поддерживаются — " + unsupported.sorted().joinToString(", "))
                    }
                    val reuse = xmux.filterKeys { it in XMUX_KEYS }.mapKeys { XMUX_KEYS.getValue(it.key) }
                    if (reuse.isNotEmpty()) result["reuse-settings"] = LinkedHashMap(reuse)
                }
                key in XHTTP_KEYS -> result[XHTTP_KEYS.getValue(key)] = value
                key in XHTTP_IGNORED -> Unit
                else -> throw IllegalArgumentException("XHTTP: параметр $key не поддерживается. Нужна ссылка без него.")
            }
        }
        return result
    }

    /** Clash/Mihomo YAML → серверы; несовместимые узлы уходят в rejected с причиной. */
    @Suppress("UNCHECKED_CAST")
    fun parseClashNodes(raw: String, rejected: MutableList<Map<String, String>> = mutableListOf()): MutableList<Server> {
        // Без ссылок на якоря: они позволяют построить рекурсивный граф узлов.
        // Парсер с лимитом 0 отказывает на первой же ссылке.
        val settings = LoadSettings.builder().setAllowRecursiveKeys(false).setMaxAliasesForCollections(0).build()
        val document = try {
            Load(settings).loadFromString(raw)
        } catch (e: org.snakeyaml.engine.v2.exceptions.YamlEngineException) {
            if ("alias" in (e.message ?: "").lowercase()) throw IllegalArgumentException("Подписка YAML с якорями не поддерживается")
            throw IllegalArgumentException("Подписка YAML повреждена")
        }
        val proxies = (document as? Map<String, Any?>)?.get("proxies") as? List<Any?> ?: return mutableListOf()
        val result = mutableListOf<Server>()
        for (item in proxies) {
            val node = item as? Map<String, Any?> ?: continue
            val label = printable((node["name"] ?: node["type"] ?: "узел").toString()).take(80)
            val type = node["type"]?.toString()
            if (type !in setOf("vless", "vmess", "ss", "trojan", "hysteria2", "hy2")) {
                rejected += mapOf("name" to label, "reason" to "протокол $type не поддерживается ядром Mihomo")
                continue
            }
            if (!truthy(node["server"]) || !truthy(node["port"])) {
                rejected += mapOf("name" to label, "reason" to "не указан адрес или порт")
                continue
            }
            try {
                val server = clashNode(node)
                MihomoConfig.ensureSupported(server)
                result += server
            } catch (e: IllegalArgumentException) {
                rejected += mapOf("name" to label, "reason" to (e.message ?: "узел повреждён").take(200))
            } catch (_: RuntimeException) {
                rejected += mapOf("name" to label, "reason" to "узел повреждён")
            }
        }
        return result
    }

    @Suppress("UNCHECKED_CAST")
    private fun clashNode(node: Map<String, Any?>): Server {
        val proto = if (node["type"] == "hy2") "hysteria2" else node["type"].toString()
        var network = node["network"]?.toString() ?: "tcp"
        if (network == "splithttp") network = "xhttp"
        val reality = node["reality-opts"] as? Map<String, Any?> ?: emptyMap()
        val transport = node["$network-opts"] as? Map<String, Any?> ?: emptyMap()
        if (network == "ws" && truthy(transport["v2ray-http-upgrade"])) network = "httpupgrade"
        val headers = transport["headers"] as? Map<String, Any?> ?: emptyMap()
        val alpn = node["alpn"]
        val skip = truthy(node["skip-cert-verify"])
        val server: Server = linkedMapOf(
            "protocol" to proto, "remark" to (node["name"]?.toString() ?: proto),
            "host" to node["server"].toString(), "port" to node["port"].toString().toInt(), "type" to network,
            "security" to when {
                reality.isNotEmpty() -> "reality"
                truthy(node["tls"]) || proto == "trojan" || proto == "hysteria2" -> "tls"
                else -> "none"
            },
            "uuid" to (node["uuid"]?.toString() ?: ""), "password" to (node["password"]?.toString() ?: ""),
            "method" to (node["cipher"]?.toString() ?: ""), "sni" to (node["servername"] ?: node["sni"] ?: "").toString(),
            "fp" to (node["client-fingerprint"]?.toString() ?: ""), "pbk" to (reality["public-key"]?.toString() ?: ""),
            "pinned_cert" to (node["fingerprint"]?.toString() ?: ""), "verify_cert_name" to (node["name-cert-verify"]?.toString() ?: ""),
            "sid" to (reality["short-id"]?.toString() ?: ""), "flow" to (node["flow"]?.toString() ?: ""),
            "path" to (transport["path"] ?: ""), "host_header" to (transport["host"] ?: headers["Host"] ?: ""),
            "serviceName" to (transport["grpc-service-name"]?.toString() ?: ""),
            "alpn" to (if (alpn is List<*>) alpn.joinToString(",") else alpn?.toString() ?: ""),
            "allowInsecure" to (if (skip) "1" else "0"), "insecure" to skip,
            "encryption" to (node["encryption"]?.toString() ?: "none"),
            "obfs" to (node["obfs"]?.toString() ?: ""), "obfs_password" to (node["obfs-password"]?.toString() ?: ""),
        )
        if (network == "http") {
            // В Clash network: http — TCP с маскировкой под HTTP/1.1, а не HTTP/2.
            val paths = transport["path"] ?: listOf("/")
            val hosts = headers["Host"] ?: emptyList<String>()
            server["type"] = "tcp"; server["header_type"] = "http"
            server["path"] = (if (paths is List<*>) paths.firstOrNull() ?: "/" else paths).toString()
            server["host_header"] = if (hosts is List<*>) hosts.joinToString(",") else hosts.toString()
        } else {
            val hh = server["host_header"]
            if (hh is List<*>) server["host_header"] = hh.firstOrNull()?.toString() ?: ""
            else server["host_header"] = hh?.toString() ?: ""
            server["path"] = server["path"]?.toString() ?: ""
        }
        if (proto == "ss" && truthy(node["plugin"])) {
            val plugin = node["plugin"].toString()
            if (plugin !in MihomoConfig.SUPPORTED_SS_PLUGINS) {
                throw IllegalArgumentException("Shadowsocks: плагин $plugin не поддерживается ядром Mihomo")
            }
            server["plugin"] = plugin
            server["plugin_opts"] = deepCopy(node["plugin-opts"] ?: emptyMap<String, Any?>())
        }
        if (proto == "vmess") {
            server["alter_id"] = node["alterId"]?.toString()?.let {
                it.toIntOrNull() ?: throw IllegalArgumentException("VMess: alterId должен быть числом")
            } ?: 0
            server["method"] = node["cipher"]?.toString()?.ifEmpty { null } ?: "auto"
        }
        if (network == "xhttp") {
            if ("download-settings" in transport) {
                throw IllegalArgumentException("XHTTP: раздельный канал загрузки (download-settings) не поддерживается")
            }
            server["mihomo_xhttp"] = deepCopy(transport)
        }
        if (proto == "hysteria2") {
            server["type"] = "quic"
            for ((source, target) in listOf("ports" to "ports", "hop-interval" to "hop_interval", "up" to "up",
                "down" to "down", "ech-opts" to "ech", "realm-opts" to "realm-opts")) {
                if (truthy(node[source])) server[target] = deepCopy(node[source])
            }
            if (truthy(server["pinned_cert"])) server["pinned_cert"] = Hysteria2.fingerprint(server["pinned_cert"])
            Hysteria2.validate(server)
        }
        return server
    }
}

/** org.json → обычные Map/List. */
fun jsonToKotlin(value: Any?): Any? = when (value) {
    is JSONObject -> LinkedHashMap<String, Any?>().also { map -> value.keys().forEach { map[it] = jsonToKotlin(value.get(it)) } }
    is JSONArray -> (0 until value.length()).map { jsonToKotlin(value.get(it)) }.toMutableList()
    JSONObject.NULL -> null
    else -> value
}
