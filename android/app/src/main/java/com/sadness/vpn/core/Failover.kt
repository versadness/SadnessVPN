package com.sadness.vpn.core

import java.net.InetAddress
import java.security.MessageDigest

/**
 * Перенос engine/failover.py: смена сервера на лету и автоматический резерв.
 *
 * manual (select)   — выбранный пользователем сервер, переключается через API ядра;
 * backup (url-test) — до BACKUP_LIMIT запасных из той же подписки и на том же транспорте;
 * proxy  (fallback) — [manual, backup]: пока выбранный отвечает — через него.
 */
object Failover {
    const val MANUAL_GROUP = "manual"
    const val BACKUP_GROUP = "backup"
    const val MAIN_GROUP = "proxy"
    const val BACKUP_LIMIT = 4
    const val HEALTH_URL = "https://www.gstatic.com/generate_204"

    /** Подписка для подбора резерва: её серверы. */
    data class Group(val id: String, val servers: List<Server>)

    /** Стабильное имя сервера в ядре. Адрес и ключи в имя не попадают. */
    fun proxyName(server: Server): String {
        val ident = server["ui_id"]?.toString()?.takeIf { it.isNotEmpty() } ?: run {
            val raw = "${server["host"]}:${server["port"]}:${server["remark"]}"
            MessageDigest.getInstance("SHA-256").digest(raw.toByteArray()).joinToString("") { "%02x".format(it) }.take(12)
        }
        return "srv-$ident"
    }

    /** Код страны по флагу в названии (🇩🇪 → DE) или пустая строка. */
    fun country(server: Server): String {
        val remark = server.str("remark")
        val letters = StringBuilder()
        var i = 0
        while (i < remark.length) {
            val cp = remark.codePointAt(i)
            if (cp in 0x1F1E6..0x1F1FF) letters.append(('A'.code + cp - 0x1F1E6).toChar())
            i += Character.charCount(cp)
        }
        return if (letters.length >= 2) letters.substring(0, 2) else ""
    }

    fun transport(server: Server): String =
        if (server["protocol"] == "hysteria2") "quic" else server.str("type", "tcp").ifEmpty { "tcp" }

    fun supported(server: Server): Boolean = try {
        MihomoConfig.ensureSupported(server)
        MihomoConfig.proxy(server)
        true
    } catch (_: RuntimeException) {
        false
    }

    private val IPV4 = Regex("""\d{1,3}(\.\d{1,3}){3}""")

    /** Адреса машины сервера; если имя не разрешилось — само имя. */
    fun machine(server: Server, resolve: (String) -> Set<String> = ::defaultResolve): Set<String> {
        val host = server.str("host").trim().lowercase().trim('[', ']')
        if (IPV4.matches(host) || ':' in host) return setOf(normalizeIp(host))
        return resolve(host).ifEmpty { setOf(host) }
    }

    private fun normalizeIp(host: String): String =
        runCatching { InetAddress.getByName(host).hostAddress ?: host }.getOrDefault(host)

    fun defaultResolve(host: String): Set<String> =
        runCatching { InetAddress.getAllByName(host).mapNotNull { it.hostAddress }.toSet() }.getOrDefault(emptySet())

    fun pickBackups(selected: Server, groups: List<Group>, limit: Int = BACKUP_LIMIT,
                    resolve: (String) -> Set<String> = ::defaultResolve): List<Server> {
        val home = groups.firstOrNull { group -> group.servers.any { it === selected } } ?: return emptyList()
        val homeCountry = country(selected)
        val used = machine(selected, resolve).toMutableSet()
        val selectedName = proxyName(selected)
        val candidates = mutableListOf<Triple<Boolean, Int, Server>>()
        for (server in home.servers) {
            if (server === selected || proxyName(server) == selectedName) continue
            if (transport(server) != transport(selected) || !supported(server)) continue
            val sameCountry = homeCountry.isNotEmpty() && country(server) == homeCountry
            candidates += Triple(!sameCountry, candidates.size, server)
        }
        val backups = mutableListOf<Server>()
        for ((_, _, server) in candidates.sortedWith(compareBy({ it.first }, { it.second }))) {
            val addresses = machine(server, resolve)
            if (addresses.any { it in used }) continue
            used += addresses
            backups += server
            if (backups.size == limit) break
        }
        return backups
    }

    /**
     * Превратить одиночный «proxy» в группы manual/backup/proxy.
     * Возвращает {имя в ядре: сервер} для смены на лету.
     */
    @Suppress("UNCHECKED_CAST")
    fun applyServerGroups(config: MutableMap<String, Any?>, selected: Server, groups: List<Group>,
                          failover: Boolean = true, mux: Boolean = false, autoBest: Boolean = false,
                          resolve: (String) -> Set<String> = ::defaultResolve): LinkedHashMap<String, Server> {
        val proxies = config["proxies"] as MutableList<Any?>
        val main = proxies.first { (it as Map<String, Any?>)["name"] == MAIN_GROUP } as MutableMap<String, Any?>
        val mainName = proxyName(selected)
        main["name"] = mainName
        val live = linkedMapOf(mainName to selected)
        for (group in groups) {
            for (server in group.servers) {
                val name = proxyName(server)
                if (name in live || !supported(server)) continue
                val proxy = MihomoConfig.withMux(MihomoConfig.proxy(server), mux)
                proxy["name"] = name
                proxies += proxy
                live[name] = server
            }
        }
        val manual = listOf(mainName) + live.keys.filter { it != mainName }
        if (autoBest) {
            // «Лучший сервер»: ядро само держит самый быстрый сервер подписки и
            // уходит с упавшего — отдельный резерв не нужен.
            val home = groups.firstOrNull { g -> g.servers.any { it === selected } }?.servers.orEmpty()
            val candidates = home.map { proxyName(it) }.filter { it in live }.ifEmpty { listOf(mainName) }
            config["proxy-groups"] = mutableListOf<Any?>(
                linkedMapOf("name" to MANUAL_GROUP, "type" to "url-test", "proxies" to candidates,
                    "url" to HEALTH_URL, "interval" to 120, "tolerance" to 50, "timeout" to 5000, "lazy" to false),
                linkedMapOf("name" to MAIN_GROUP, "type" to "select", "proxies" to listOf(MANUAL_GROUP)),
            )
            return live
        }
        val groupsConfig = mutableListOf<Any?>(linkedMapOf("name" to MANUAL_GROUP, "type" to "select", "proxies" to manual))
        val backups = if (failover) pickBackups(selected, groups, resolve = resolve).map { proxyName(it) } else emptyList()
        if (backups.isNotEmpty()) {
            groupsConfig += linkedMapOf("name" to BACKUP_GROUP, "type" to "url-test", "proxies" to backups,
                "url" to HEALTH_URL, "interval" to 60, "tolerance" to 50, "timeout" to 5000, "lazy" to false)
            groupsConfig += linkedMapOf("name" to MAIN_GROUP, "type" to "fallback", "proxies" to listOf(MANUAL_GROUP, BACKUP_GROUP),
                "url" to HEALTH_URL, "interval" to 30, "timeout" to 5000, "lazy" to false, "max-failed-times" to 3)
        } else {
            groupsConfig += linkedMapOf("name" to MAIN_GROUP, "type" to "select", "proxies" to listOf(MANUAL_GROUP))
        }
        config["proxy-groups"] = groupsConfig
        return live
    }
}
