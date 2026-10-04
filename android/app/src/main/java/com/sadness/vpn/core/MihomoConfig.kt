package com.sadness.vpn.core

/**
 * Перенос engine/core_config.py под Android.
 *
 * Отличия от десктопа:
 * - туннель создаёт система (VpnService) и отдаёт ядру готовым дескриптором,
 *   маршруты ставит тоже она — у ядра auto-route выключен;
 * - соединения самого ядра идут мимо туннеля: приложение исключено из VPN
 *   (иначе трафик к серверу ушёл бы в туннель и закольцевался);
 * - локальных SOCKS/HTTP-портов нет: на телефоне к 127.0.0.1 может обратиться
 *   любое установленное приложение, а API управления закрыто секретом.
 */
object MihomoConfig {
    val SUPPORTED_PROTOCOLS = setOf("vless", "vmess", "ss", "trojan", "hysteria2")
    val SUPPORTED_NETWORKS = setOf("tcp", "ws", "httpupgrade", "grpc", "http", "h2", "xhttp", "splithttp")
    val SUPPORTED_SS_PLUGINS = setOf("obfs", "v2ray-plugin")

    /** Адрес интерфейса VPN; ядро и VpnService должны совпадать. */
    const val TUN_ADDRESS = "172.19.0.1"
    const val TUN_PREFIX = 30
    const val TUN_DNS = "172.19.0.2"
    const val TUN_ADDRESS6 = "fdfe:dcba:9876::1"
    const val TUN_MTU = 9000

    val DNS_PRESETS: Map<String, List<String>> = mapOf(
        "cf_google" to listOf("tls://1.1.1.1", "tls://8.8.8.8"),
        "google" to listOf("tls://8.8.8.8", "tls://8.8.4.4"),
        "cloudflare" to listOf("tls://1.1.1.1", "tls://1.0.0.1"),
        "adguard" to listOf("tls://94.140.14.14", "tls://94.140.15.15"),
        "quad9" to listOf("tls://9.9.9.9", "tls://149.112.112.112"),
        "comss" to listOf("udp://83.220.169.155", "udp://212.109.195.93"),
        "comss_dot" to listOf("tls://dns.comss.one", "tls://dns.comss.one"),
        "xbox" to listOf("udp://111.88.96.50", "udp://111.88.96.51"),
        "xbox_dot" to listOf("tls://xbox-dns.ru", "tls://xbox-dns.ru"),
    )
    /** Smart DNS: бутстрап по собственному raw IP, иначе петля. */
    val SMART_DNS_BOOTSTRAP = mapOf(
        "xbox" to "udp://111.88.96.50", "xbox_dot" to "udp://111.88.96.50",
        "comss" to "udp://83.220.169.155", "comss_dot" to "udp://83.220.169.155",
    )

    fun ensureSupported(server: Server): Server {
        val protocol = server.str("protocol", "vless").ifEmpty { "vless" }
        if (protocol !in SUPPORTED_PROTOCOLS) {
            throw IllegalArgumentException("Протокол $protocol не поддерживается ядром Mihomo. Другого ядра в приложении нет.")
        }
        if (protocol == "hysteria2") {
            Hysteria2.validate(server)
            return server
        }
        if (protocol == "ss") {
            val plugin = server["plugin"]?.toString().orEmpty()
            if (plugin.isNotEmpty() && plugin !in SUPPORTED_SS_PLUGINS) {
                throw IllegalArgumentException("Shadowsocks: плагин $plugin не поддерживается ядром Mihomo")
            }
            return server
        }
        val network = server.str("type", "tcp").ifEmpty { "tcp" }
        if (network !in SUPPORTED_NETWORKS) throw IllegalArgumentException("Транспорт $network не поддерживается ядром Mihomo")
        val header = server.str("header_type").ifEmpty { "none" }
        if (header != "none" && !(header == "http" && network == "tcp")) {
            throw IllegalArgumentException("Маскировка заголовка $header для транспорта $network не поддерживается")
        }
        if (network == "xhttp" || network == "splithttp") {
            if (protocol != "vless") throw IllegalArgumentException("Mihomo поддерживает XHTTP только для VLESS")
            Transports.mihomoXhttp(server)
        }
        return server
    }

    fun proxy(server: Server): MutableMap<String, Any?> {
        val proto = server.str("protocol", "vless").ifEmpty { "vless" }
        ensureSupported(server)
        val proxy: MutableMap<String, Any?> = linkedMapOf(
            "name" to "proxy", "type" to proto, "server" to server.str("host"),
            "port" to server["port"].toString().toInt(), "udp" to true,
        )
        if (proto == "ss") {
            proxy["cipher"] = server.str("method"); proxy["password"] = server.str("password")
            if (truthy(server["plugin"])) {
                proxy["plugin"] = server["plugin"]
                proxy["plugin-opts"] = deepCopy(server["plugin_opts"] ?: emptyMap<String, Any?>())
            }
            return proxy
        }
        val security = server.str("security")
        val tls = security == "tls" || security == "reality" || proto == "trojan" || proto == "hysteria2"
        when (proto) {
            "vless" -> {
                proxy["uuid"] = server.str("uuid"); proxy["tls"] = tls
                server.str("flow").takeIf { it.isNotEmpty() && it != "none" }?.let { proxy["flow"] = it }
                server.str("encryption").takeIf { it.isNotEmpty() && it != "none" }?.let { proxy["encryption"] = it }
            }
            "vmess" -> {
                proxy["uuid"] = server.str("uuid"); proxy["tls"] = tls
                proxy["cipher"] = server.str("method").ifEmpty { "auto" }
                proxy["alterId"] = server["alter_id"]?.toString()?.toIntOrNull() ?: 0
            }
            else -> proxy["password"] = server.str("password")
        }
        proxy[if (proto == "trojan" || proto == "hysteria2") "sni" else "servername"] = server.str("sni").ifEmpty { server.str("host") }
        proxy["skip-cert-verify"] = server.str("allowInsecure") == "1" || truthy(server["insecure"])
        server.str("fp").takeIf { it.isNotEmpty() }?.let { proxy["client-fingerprint"] = it }
        server.str("pinned_cert").takeIf { it.isNotEmpty() }?.let { proxy["fingerprint"] = it }
        server.str("verify_cert_name").takeIf { it.isNotEmpty() }?.let { proxy["name-cert-verify"] = it }
        server.str("alpn").takeIf { it.isNotEmpty() }?.let { alpn ->
            proxy["alpn"] = alpn.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        }
        if (security == "reality") {
            proxy["reality-opts"] = linkedMapOf("public-key" to server.str("pbk"), "short-id" to server.str("sid"))
        }
        if (proto == "hysteria2") {
            if (truthy(server["ech"])) Hysteria2.echOpts(server["ech"])?.let { proxy["ech-opts"] = it }
            if (truthy(server["obfs"])) {
                proxy["obfs"] = server["obfs"]; proxy["obfs-password"] = server.str("obfs_password")
            }
            for ((source, target) in listOf("ports" to "ports", "hop_interval" to "hop-interval", "up" to "up", "down" to "down")) {
                if (truthy(server[source])) proxy[target] = server[source]
            }
            return proxy
        }
        val network = server.str("type", "tcp").ifEmpty { "tcp" }
        val path = server.str("path").ifEmpty { "/" }
        val host = server.str("host_header").ifEmpty { server.str("sni").ifEmpty { server.str("host") } }
        when {
            network == "xhttp" || network == "splithttp" -> {
                proxy["network"] = "xhttp"
                proxy["xhttp-opts"] = Transports.mihomoXhttp(server)
                if (!tls && proxy["alpn"] == null) proxy["alpn"] = listOf("http/1.1")
            }
            network == "ws" || network == "httpupgrade" -> {
                proxy["network"] = "ws"
                val opts: MutableMap<String, Any?> = linkedMapOf("path" to path, "headers" to linkedMapOf("Host" to host))
                if (network == "httpupgrade") opts["v2ray-http-upgrade"] = true
                proxy["ws-opts"] = opts
            }
            network == "grpc" -> {
                proxy["network"] = "grpc"
                proxy["grpc-opts"] = linkedMapOf("grpc-service-name" to server.str("serviceName"))
            }
            network == "http" || network == "h2" -> {
                proxy["network"] = "h2"
                proxy["h2-opts"] = linkedMapOf("path" to path, "host" to listOf(host))
            }
            network == "tcp" && server.str("header_type") == "http" -> {
                val opts: MutableMap<String, Any?> = linkedMapOf("method" to "GET", "path" to listOf(server.str("path").ifEmpty { "/" }))
                server.str("host_header").takeIf { it.isNotEmpty() }?.let { hh ->
                    opts["headers"] = linkedMapOf("Host" to hh.split(',').map { it.trim() }.filter { it.isNotEmpty() })
                }
                proxy["network"] = "http"
                proxy["http-opts"] = opts
            }
        }
        return proxy
    }

    fun withMux(proxy: MutableMap<String, Any?>, mux: Boolean): MutableMap<String, Any?> {
        if (mux && proxy["type"] !in setOf("hysteria2", "wireguard") && proxy["network"] != "xhttp" && proxy["flow"] == null) {
            proxy["smux"] = linkedMapOf("enabled" to true, "protocol" to "smux", "max-connections" to 4)
        }
        return proxy
    }

    data class Settings(
        val dnsPreset: String = "cf_google",
        val ipv6: Boolean = false,
        val mux: Boolean = false,
        val blockUdp: Boolean = false,
        val geminiDns: Boolean = false,
        /** Локальный SOCKS5: порт, логин и пароль; null — выключен. */
        val socks: Socks? = null,
    )

    data class Socks(val port: Int, val user: String, val password: String, val lan: Boolean)

    /**
     * Сервисы Google AI через Smart DNS: Xbox DNS отдаёт адреса своих узлов,
     * которые пускают к Gemini из России. Запросы и трафик идут напрямую —
     * Smart DNS должен видеть настоящий адрес телефона.
     */
    val GEMINI_DOMAINS = listOf(
        "gemini.google.com", "gemini.google", "aistudio.google.com", "ai.google.dev",
        "generativelanguage.googleapis.com", "makersuite.google.com", "alkalimakersuite-pa.clients6.google.com",
        "notebooklm.google", "notebooklm.google.com", "labs.google", "bard.google.com", "deepmind.google",
        "proactivebackend-pa.googleapis.com", "robinfrontend-pa.googleapis.com",
    )
    const val XBOX_DNS = "111.88.96.50"

    fun dnsBlock(settings: Settings, ipv6: Boolean): MutableMap<String, Any?> {
        val preset = settings.dnsPreset
        val raw = DNS_PRESETS[preset] ?: DNS_PRESETS.getValue("cf_google")
        val bootstrap = SMART_DNS_BOOTSTRAP[preset]
        return linkedMapOf<String, Any?>(
            "enable" to true,
            "ipv6" to ipv6,
            // На телефоне fake-ip: приложения получают адреса из служебного
            // диапазона мгновенно, а настоящее имя разрешается уже за сервером.
            "enhanced-mode" to "fake-ip",
            "fake-ip-range" to "198.18.0.1/16",
            "nameserver" to raw.map { it.removePrefix("udp://") },
            "proxy-server-nameserver" to listOf("1.1.1.1", "8.8.8.8"),
            "default-nameserver" to (if (bootstrap != null) listOf(bootstrap.removePrefix("udp://")) else listOf("1.1.1.1", "8.8.8.8")),
            "respect-rules" to (preset !in SMART_DNS_BOOTSTRAP),
        ).also { dns ->
            if (settings.geminiDns) {
                // «#DIRECT» — запрос к Xbox DNS идёт мимо сервера, с настоящего адреса.
                dns["nameserver-policy"] = LinkedHashMap<String, Any?>().apply {
                    GEMINI_DOMAINS.forEach { put("+.$it", "$XBOX_DNS#DIRECT") }
                }
            }
        }
    }

    /**
     * Полная конфигурация вокруг готового outbound «proxy».
     * tunFd < 0 — ядро без туннеля, только для проверки серверов.
     */
    fun assemble(proxy: MutableMap<String, Any?>, settings: Settings, controller: String, secret: String, tunFd: Int): MutableMap<String, Any?> {
        withMux(proxy, settings.mux)
        val ipv6 = settings.ipv6 && settings.dnsPreset !in setOf("xbox", "xbox_dot")
        val rules = mutableListOf(
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve", "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve", "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
            "IP-CIDR6,fc00::/7,DIRECT,no-resolve", "IP-CIDR6,fe80::/10,DIRECT,no-resolve",
        )
        if (settings.geminiDns) GEMINI_DOMAINS.forEach { rules += "DOMAIN-SUFFIX,$it,DIRECT" }
        if (settings.blockUdp) rules += "NETWORK,UDP,REJECT"
        rules += "MATCH,proxy"
        val config: MutableMap<String, Any?> = linkedMapOf(
            "mode" to "rule", "log-level" to "info",
            "ipv6" to true,
            "external-controller" to controller, "secret" to secret,
            "find-process-mode" to "off", "geo-auto-update" to false,
            "unified-delay" to true,
            // store-fake-ip: после перезапуска ядра на том же туннеле приложения
            // продолжают ходить по уже выданным адресам 198.18.x.x — новое ядро
            // восстанавливает их соответствие доменам из cache.db.
            "profile" to linkedMapOf("store-selected" to false, "store-fake-ip" to true),
            "dns" to dnsBlock(settings, ipv6),
            "proxies" to mutableListOf<Any?>(proxy),
            "rules" to rules,
        )
        settings.socks?.takeIf { tunFd >= 0 }?.let { socks ->
            // К 127.0.0.1 на телефоне может обратиться любое приложение, поэтому
            // пароль обязателен всегда: skip-auth-prefixes пуст (по умолчанию
            // Mihomo пропускает 127.0.0.0/8 без пароля).
            config["socks-port"] = socks.port
            config["allow-lan"] = socks.lan
            config["bind-address"] = if (socks.lan) "*" else "127.0.0.1"
            config["authentication"] = listOf("${socks.user}:${socks.password}")
            config["skip-auth-prefixes"] = emptyList<String>()
        }
        if (tunFd >= 0) {
            config["tun"] = linkedMapOf(
                "enable" to true, "stack" to "gvisor", "file-descriptor" to tunFd,
                "auto-route" to false, "auto-detect-interface" to false,
                // Свой IPv4-адрес у туннеля Mihomo 1.19 берёт из fake-ip-range
                // (ключа inet4-address больше нет); пакеты всё равно приходят
                // готовым дескриптором, так что адрес интерфейса VpnService свой.
                "inet6-address" to listOf("$TUN_ADDRESS6/126"),
                "mtu" to TUN_MTU,
                "dns-hijack" to listOf("any:53", "tcp://any:53"),
            )
        }
        // Без туннеля (проверка серверов) DNS-секция остаётся: через неё ядро
        // само разрешает имена серверов, системного resolv.conf на Android нет.
        return config
    }
}
