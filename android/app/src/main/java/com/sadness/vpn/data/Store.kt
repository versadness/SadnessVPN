package com.sadness.vpn.data

import android.content.Context
import com.sadness.vpn.core.Failover
import com.sadness.vpn.core.Json
import com.sadness.vpn.core.MihomoConfig
import com.sadness.vpn.core.Server
import com.sadness.vpn.core.Subscription
import com.sadness.vpn.core.jsonToKotlin
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.UUID

/** Подписка: адрес хранится только на устройстве и никуда, кроме провайдера, не уходит. */
data class Group(
    val id: String,
    val name: String,
    val url: String,
    val servers: List<Server>,
    val meta: Map<String, Any?> = emptyMap(),
    val error: String = "",
)

enum class AppsMode(val key: String) {
    ALL("all"), ONLY("only"), EXCEPT("except");

    companion object {
        fun of(key: String?) = entries.firstOrNull { it.key == key } ?: ALL
    }
}

data class Settings(
    val dnsPreset: String = "cf_google",
    val ipv6: Boolean = true,
    val mux: Boolean = false,
    val failover: Boolean = true,
    val blockUdp: Boolean = false,
    val autoUpdate: Boolean = true,
    val appsMode: AppsMode = AppsMode.ALL,
    val apps: Set<String> = emptySet(),
    /** Российские банки, госуслуги и т. п. — напрямую, мимо VPN (см. RuApps). */
    val recommendedDirect: Boolean = true,
    /** Проверять при смене сети, не включил ли оператор белые списки. */
    val whitelistCheck: Boolean = true,
    /** Встроенный Telegram WS Proxy на 127.0.0.1 и его секрет (32 hex). */
    val tgProxy: Boolean = false,
    val tgProxySecret: String = "",
    /** Рекомендованные приложения, которые пользователь вернул в VPN. */
    val recommendedOff: Set<String> = emptySet(),
    /** Подключаться к последнему серверу при открытии приложения. */
    val connectOnLaunch: Boolean = false,
    /** "http" — настоящий запрос через сервер, "tcp" — только время соединения. */
    val pingMode: String = "http",
    /** DNS сервисов Google AI через Xbox Smart DNS, их трафик — напрямую. */
    val geminiDns: Boolean = false,
    /** Локальный SOCKS5 на порту ядра; всегда с паролем. */
    val socksEnabled: Boolean = false,
    val socksLan: Boolean = false,
    val socksUser: String = "svpn",
    val socksPassword: String = "",
    /** Раздача по Wi-Fi: прокси на 7897 для устройств в точке доступа телефона. */
    val shareWifi: Boolean = false,
    // Маршруты
    val ruDirect: Boolean = false,
    val adblock: Boolean = false,
    val servicesVpn: Boolean = false,
    val rules: List<MihomoConfig.Rule> = emptyList(),
    // Серверы
    val autoBest: Boolean = false,
    val favorites: Set<String> = emptySet(),
    /** "ping" или "order". */
    val sortMode: String = "order",
    val hideDead: Boolean = false,
    // Внешний вид: "system" | "dark" | "light"; язык "ru" | "en".
    val theme: String = "dark",
    /** Фон главного экрана: auto | ocean | sunset | neon | off. */
    val aurora: String = "auto",
    /** Отпечаток TLS для всех TLS/REALITY-серверов: firefox, edge, chrome или provider (как в подписке). */
    val tlsFingerprint: String = "firefox",
    val language: String = "ru",
    /** Предупреждение о фоновых ограничениях скрыто кнопкой «Позже». */
    val batteryDismissed: Boolean = false,
    // Подписки в фоне
    val bgRefresh: Boolean = true,
    val bgHours: Int = 6,
    val warnExpire: Boolean = true,
    val warnTraffic: Boolean = true,
)

data class State(
    val groups: List<Group> = emptyList(),
    val selectedGroup: String = "",
    val selectedServer: String = "",
    val settings: Settings = Settings(),
    val hwid: String = "",
    val todayDate: String = "",
    val todayBytes: Long = 0,
) {
    fun selected(): Pair<Group, Server>? {
        val group = groups.firstOrNull { it.id == selectedGroup } ?: return null
        val server = group.servers.firstOrNull { it["ui_id"] == selectedServer } ?: return null
        return group to server
    }

    fun failoverGroups() = groups.map { Failover.Group(it.id, it.servers) }
}

/** Состояние приложения в files/state.json. Запись атомарная: временный файл и переименование. */
class Store(context: Context) {
    private val file = File(context.filesDir, "state.json")

    @Synchronized
    fun load(): State {
        val state = if (file.isFile) runCatching { decode(JSONObject(file.readText())) }.getOrNull() else null
        var result = state ?: State()
        var changed = false
        if (result.hwid.isEmpty()) { result = result.copy(hwid = Subscription.generateHwid()); changed = true }
        if (result.settings.tgProxySecret.isEmpty()) {
            result = result.copy(settings = result.settings.copy(tgProxySecret = com.sadness.vpn.vpn.TgWsProxy.newSecret())); changed = true
        }
        // Пароль SOCKS5 создаётся сразу: прокси без пароля не включается никогда.
        if (result.settings.socksPassword.isEmpty()) {
            result = result.copy(settings = result.settings.copy(socksPassword = newSocksPassword())); changed = true
        }
        if (changed) save(result)
        return result
    }

    @Synchronized
    fun save(state: State) {
        val tmp = File(file.parentFile, "state.json.tmp")
        tmp.writeText(Json.encode(encode(state)))
        if (!tmp.renameTo(file)) {
            file.delete()
            tmp.renameTo(file)
        }
    }

    fun encode(state: State): Map<String, Any?> = linkedMapOf(
        "version" to 1,
        "groups" to state.groups.map { g ->
            linkedMapOf("id" to g.id, "name" to g.name, "url" to g.url, "servers" to g.servers, "meta" to g.meta, "error" to g.error)
        },
        "selected_group" to state.selectedGroup,
        "selected_server" to state.selectedServer,
        "hwid" to state.hwid,
        "today_date" to state.todayDate,
        "today_bytes" to state.todayBytes,
        "settings" to with(state.settings) {
            linkedMapOf("dns_preset" to dnsPreset, "ipv6" to ipv6, "mux" to mux, "failover" to failover,
                "block_udp" to blockUdp, "auto_update" to autoUpdate, "apps_mode" to appsMode.key, "apps" to apps.sorted(),
                "recommended_direct" to recommendedDirect, "whitelist_check" to whitelistCheck, "tg_proxy" to tgProxy, "tg_proxy_secret" to tgProxySecret, "recommended_off" to recommendedOff.sorted(),
                "connect_on_launch" to connectOnLaunch, "ping_mode" to pingMode, "gemini_dns" to geminiDns,
                "socks_enabled" to socksEnabled, "socks_lan" to socksLan, "socks_user" to socksUser, "socks_password" to socksPassword,
                "share_wifi" to shareWifi, "ru_direct" to ruDirect, "adblock" to adblock, "services_vpn" to servicesVpn,
                "rules" to rules.map { linkedMapOf("type" to it.type, "value" to it.value, "action" to it.action) },
                "auto_best" to autoBest, "favorites" to favorites.sorted(), "sort_mode" to sortMode, "hide_dead" to hideDead,
                "theme" to theme, "aurora" to aurora, "tls_fingerprint" to tlsFingerprint, "language" to language, "battery_dismissed" to batteryDismissed,
                "bg_refresh" to bgRefresh, "bg_hours" to bgHours, "warn_expire" to warnExpire, "warn_traffic" to warnTraffic)
        },
    )

    @Suppress("UNCHECKED_CAST")
    fun decode(json: JSONObject): State {
        val root = jsonToKotlin(json) as Map<String, Any?>
        val groups = (root["groups"] as? List<Any?>).orEmpty().mapNotNull { item ->
            val g = item as? Map<String, Any?> ?: return@mapNotNull null
            Group(
                id = g["id"]?.toString() ?: newId(),
                name = g["name"]?.toString().orEmpty(),
                url = g["url"]?.toString().orEmpty(),
                servers = (g["servers"] as? List<Any?>).orEmpty().mapNotNull { (it as? Map<String, Any?>)?.toMutableMap() },
                meta = (g["meta"] as? Map<String, Any?>).orEmpty(),
                error = g["error"]?.toString().orEmpty(),
            )
        }
        val s = root["settings"] as? Map<String, Any?> ?: emptyMap()
        return State(
            groups = groups,
            selectedGroup = root["selected_group"]?.toString().orEmpty(),
            selectedServer = root["selected_server"]?.toString().orEmpty(),
            hwid = root["hwid"]?.toString().orEmpty(),
            todayDate = root["today_date"]?.toString().orEmpty(),
            todayBytes = (root["today_bytes"] as? Number)?.toLong() ?: 0,
            settings = Settings(
                dnsPreset = s["dns_preset"]?.toString() ?: "cf_google",
                ipv6 = s["ipv6"] as? Boolean ?: true,
                mux = s["mux"] as? Boolean ?: false,
                failover = s["failover"] as? Boolean ?: true,
                blockUdp = s["block_udp"] as? Boolean ?: false,
                autoUpdate = s["auto_update"] as? Boolean ?: true,
                appsMode = AppsMode.of(s["apps_mode"]?.toString()),
                apps = (s["apps"] as? List<Any?>).orEmpty().map { it.toString() }.toSet(),
                recommendedDirect = s["recommended_direct"] as? Boolean ?: true,
                whitelistCheck = s["whitelist_check"] as? Boolean ?: true,
                tgProxy = s["tg_proxy"] as? Boolean ?: false,
                tgProxySecret = s["tg_proxy_secret"] as? String ?: "",
                recommendedOff = (s["recommended_off"] as? List<Any?>).orEmpty().map { it.toString() }.toSet(),
                connectOnLaunch = s["connect_on_launch"] as? Boolean ?: false,
                pingMode = if (s["ping_mode"] == "tcp") "tcp" else "http",
                geminiDns = s["gemini_dns"] as? Boolean ?: false,
                socksEnabled = s["socks_enabled"] as? Boolean ?: false,
                socksLan = s["socks_lan"] as? Boolean ?: false,
                socksUser = s["socks_user"]?.toString()?.ifEmpty { null } ?: "svpn",
                socksPassword = s["socks_password"]?.toString().orEmpty(),
                shareWifi = s["share_wifi"] as? Boolean ?: false,
                ruDirect = s["ru_direct"] as? Boolean ?: false,
                adblock = s["adblock"] as? Boolean ?: false,
                servicesVpn = s["services_vpn"] as? Boolean ?: false,
                rules = (s["rules"] as? List<Any?>).orEmpty().mapNotNull { item ->
                    val r = item as? Map<String, Any?> ?: return@mapNotNull null
                    MihomoConfig.Rule(r["type"]?.toString() ?: return@mapNotNull null, r["value"]?.toString() ?: return@mapNotNull null,
                        r["action"]?.toString() ?: "vpn")
                },
                autoBest = s["auto_best"] as? Boolean ?: false,
                favorites = (s["favorites"] as? List<Any?>).orEmpty().map { it.toString() }.toSet(),
                sortMode = if (s["sort_mode"] == "ping") "ping" else "order",
                hideDead = s["hide_dead"] as? Boolean ?: false,
                aurora = s["aurora"]?.toString()?.takeIf { it in setOf("auto", "ocean", "sunset", "neon", "off") } ?: "auto",
                tlsFingerprint = s["tls_fingerprint"]?.toString()?.takeIf { it in MihomoConfig.TLS_FINGERPRINTS } ?: "firefox",
                theme = s["theme"]?.toString()?.takeIf { it in setOf("system", "dark", "light") } ?: "dark",
                language = if (s["language"] == "en") "en" else "ru",
                batteryDismissed = s["battery_dismissed"] as? Boolean ?: false,
                bgRefresh = s["bg_refresh"] as? Boolean ?: true,
                bgHours = (s["bg_hours"] as? Number)?.toInt()?.takeIf { it in setOf(3, 6, 12, 24) } ?: 6,
                warnExpire = s["warn_expire"] as? Boolean ?: true,
                warnTraffic = s["warn_traffic"] as? Boolean ?: true,
            ),
        )
    }

    companion object {
        /** Общая блокировка записи state.json для экрана, службы и фоновых задач. */
        val LOCK = Any()

        fun newId(): String = UUID.randomUUID().toString().take(8)

        const val SOCKS_PORT = 7897

        /** 16 символов без похожих букв — удобно переписать вручную. */
        fun newSocksPassword(): String {
            val alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
            val random = java.security.SecureRandom()
            return (1..16).map { alphabet[random.nextInt(alphabet.length)] }.joinToString("")
        }

        /** Стабильный ID сервера: не меняется при обновлении подписки, если сервер тот же. */
        fun serverId(server: Server): String {
            val raw = listOf(server["protocol"] ?: "vless", server["host"], server["port"], server["remark"]).joinToString("|")
            return MessageDigest.getInstance("SHA-256").digest(raw.toByteArray()).joinToString("") { "%02x".format(it) }.take(12)
        }
    }
}
