package com.sadness.vpn.ui

import android.app.Application
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sadness.vpn.BuildConfig
import com.sadness.vpn.core.Failover
import com.sadness.vpn.core.MihomoConfig
import com.sadness.vpn.core.Subscription
import com.sadness.vpn.core.SubscriptionException
import com.sadness.vpn.data.AppsMode
import com.sadness.vpn.data.Group
import com.sadness.vpn.data.Settings
import com.sadness.vpn.data.State
import com.sadness.vpn.data.Store
import com.sadness.vpn.vpn.Core
import com.sadness.vpn.vpn.Status
import com.sadness.vpn.vpn.SvpnVpnService
import com.sadness.vpn.vpn.VpnController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

data class AppEntry(val pkg: String, val label: String, val system: Boolean)

/** Новая версия на GitHub. */
data class UpdateInfo(val version: String, val notes: List<String>, val url: String, val size: Long, val sha256: String, val name: String)

/** Итог «Проверки соединения». null в полях — проверка ещё идёт или не удалась. */
data class CheckResult(
    val country: String? = null, val countryCode: String? = null, val ip: String? = null,
    val youtube: Int? = null, val telegram: Int? = null,
    val dnsCountries: List<String>? = null, val dnsLeak: Boolean? = null,
)

data class UiState(
    val data: State = State(),
    /** ui_id → задержка в мс; -1 — сервер не ответил. */
    val pings: Map<String, Int> = emptyMap(),
    val pinging: Boolean = false,
    val busyGroups: Set<String> = emptySet(),
    val message: String = "",
    val apps: List<AppEntry> = emptyList(),
    val appsLoading: Boolean = false,
    val update: UpdateInfo? = null,
    /** 0..100 — идёт загрузка обновления; -1 — нет. */
    val updateProgress: Int = -1,
    val check: CheckResult? = null,
    val checking: Boolean = false,
    /** Текст из буфера, похожий на подписку или ссылки, — предложить добавить. */
    val clipboardOffer: String = "",
)

class AppModel(app: Application) : AndroidViewModel(app) {
    private val store = Store(app)
    private val _ui = MutableStateFlow(UiState(data = store.load()))
    val ui: StateFlow<UiState> = _ui
    val vpn = VpnController.state

    private val client = Subscription.ClientInfo(
        version = BuildConfig.VERSION_NAME,
        osVersion = Build.VERSION.RELEASE,
        arch = when (Build.SUPPORTED_ABIS.firstOrNull()) {
            "arm64-v8a" -> "arm64"; "armeabi-v7a" -> "arm"; "x86_64" -> "amd64"; else -> "unknown"
        },
    )

    init {
        L.lang = _ui.value.data.settings.language
        Palette.apply(_ui.value.data.settings.theme)
        if (_ui.value.data.settings.autoUpdate && _ui.value.data.groups.isNotEmpty()) refreshAll(silent = true)
        checkUpdates(manual = false)
        com.sadness.vpn.data.SubscriptionWork.schedule(app, _ui.value.data.settings)
        viewModelScope.launch(Dispatchers.IO) { com.sadness.vpn.data.SubscriptionWork.checkWarnings(app) }
    }

    private fun mutate(block: (State) -> State) {
        synchronized(Store.LOCK) {
            val next = block(store.load())
            store.save(next)
            _ui.update { it.copy(data = next) }
        }
    }

    fun message(text: String) = _ui.update { it.copy(message = text) }
    fun clearMessage() = _ui.update { it.copy(message = "") }

    // ── Подписки ────────────────────────────────────────────

    fun addSubscription(url: String, name: String) {
        val link = url.trim()
        if (!link.startsWith("http://") && !link.startsWith("https://")) {
            message(L.t("Нужна ссылка подписки вида https://…"))
            return
        }
        val id = Store.newId()
        mutate { it.copy(groups = it.groups + Group(id = id, name = name.trim(), url = link, servers = emptyList())) }
        refresh(id, removeOnFailure = true)
    }

    fun refreshAll(silent: Boolean = false) = _ui.value.data.groups.forEach { refresh(it.id, silent = silent) }

    fun refresh(groupId: String, removeOnFailure: Boolean = false, silent: Boolean = false) {
        val group = _ui.value.data.groups.firstOrNull { it.id == groupId } ?: return
        if (group.url.isEmpty()) return  // ссылки и файлы WireGuard — обновлять неоткуда
        _ui.update { it.copy(busyGroups = it.busyGroups + groupId) }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { Subscription.fetch(group.url, com.sadness.vpn.data.SubscriptionUpdater.client, store.load().hwid) }
            }
            _ui.update { it.copy(busyGroups = it.busyGroups - groupId) }
            result.onSuccess { fetched ->
                mutate { state -> com.sadness.vpn.data.SubscriptionUpdater.merge(state, groupId, fetched) }
                com.sadness.vpn.data.SubscriptionWork.checkWarnings(getApplication())
                if (!silent) message("«${_ui.value.data.groups.firstOrNull { it.id == groupId }?.name}»: ${fetched.servers.size} " + L.t("серверов"))
            }.onFailure { error ->
                val text = (error as? SubscriptionException)?.message ?: L.t("Не удалось обновить подписку.")
                if ((error as? SubscriptionException)?.notModified == true) return@onFailure
                if (removeOnFailure) {
                    mutate { state -> state.copy(groups = state.groups.filter { it.id != groupId }) }
                } else {
                    mutate { state -> state.copy(groups = state.groups.map { if (it.id == groupId) it.copy(error = text) else it }) }
                }
                if (!silent || removeOnFailure) message(text)
            }
        }
    }

    fun deleteGroup(groupId: String) = mutate { state ->
        state.copy(groups = state.groups.filter { it.id != groupId },
            selectedGroup = if (state.selectedGroup == groupId) "" else state.selectedGroup,
            selectedServer = if (state.selectedGroup == groupId) "" else state.selectedServer)
    }

    fun renameGroup(groupId: String, name: String) = mutate { state ->
        state.copy(groups = state.groups.map { if (it.id == groupId) it.copy(name = name.trim().ifEmpty { it.name }) else it })
    }

    // ── Серверы и подключение ───────────────────────────────

    fun select(groupId: String, serverId: String) {
        val wasAuto = _ui.value.data.settings.autoBest
        // Ручной выбор выключает «лучший сервер»: в ядре другая группа — нужно переподключение.
        mutate { it.copy(selectedGroup = groupId, selectedServer = serverId, settings = it.settings.copy(autoBest = false)) }
        if (wasAuto) {
            message(L.t("Выбран сервер вручную — «Подключаться к лучшему» выключено."))
            if (vpn.value.status == Status.ON) viewModelScope.launch(Dispatchers.IO) { reconnect() }
            return
        }
        if (vpn.value.status == Status.ON) {
            val server = _ui.value.data.selected()?.second ?: return
            viewModelScope.launch(Dispatchers.IO) {
                if (!VpnController.switchLive(server)) {
                    // Сервера нет в работающем ядре (например, подписку обновили) — переподключение.
                    reconnect()
                }
            }
        }
    }

    fun connect() {
        if (_ui.value.data.selected() == null) {
            message(L.t("Сначала добавьте подписку и выберите сервер."))
            return
        }
        SvpnVpnService.start(getApplication())
    }

    fun disconnect() = SvpnVpnService.stop(getApplication())

    private suspend fun reconnect() {
        withContext(Dispatchers.Main) { disconnect() }
        val deadline = System.currentTimeMillis() + 8000
        while (vpn.value.status != Status.OFF && System.currentTimeMillis() < deadline) kotlinx.coroutines.delay(100)
        withContext(Dispatchers.Main) { connect() }
    }

    /**
     * Задержка серверов. HTTP — настоящий запрос через каждый сервер (ядро);
     * TCP — только время установки соединения до сервера, быстрее, но без
     * проверки протокола. У Hysteria 2 нет TCP — она всегда проверяется через ядро.
     */
    fun pingAll() {
        val data = _ui.value.data
        val servers = data.groups.flatMap { it.servers }
        if (servers.isEmpty() || _ui.value.pinging) return
        _ui.update { it.copy(pinging = true, pings = emptyMap()) }
        val tcpMode = data.settings.pingMode == "tcp"
        viewModelScope.launch(Dispatchers.IO) {
            var temp: Core? = null
            try {
                val gate = Semaphore(8)
                val viaCore = if (tcpMode) servers.filter { Failover.transport(it) == "quic" } else servers
                val jobs = mutableListOf<kotlinx.coroutines.Deferred<Unit>>()
                if (tcpMode) {
                    servers.filter { Failover.transport(it) != "quic" }.forEach { server ->
                        jobs += async {
                            gate.withPermit {
                                val ms = tcpPing(server["host"].toString(), server["port"].toString().toIntOrNull() ?: 443)
                                _ui.update { it.copy(pings = it.pings + (server["ui_id"].toString() to ms)) }
                            }
                        }
                    }
                }
                if (viaCore.isNotEmpty()) {
                    val ids = viaCore.map { it["ui_id"].toString() }.toSet()
                    val core = VpnController.core ?: Core.start(getApplication(), servers.first(), data.failoverGroups(),
                        MihomoConfig.Settings(dnsPreset = data.settings.dnsPreset), failover = false, tunFd = -1, tag = "probe").also { temp = it }
                    core.live.filter { it.value["ui_id"].toString() in ids }.forEach { (name, server) ->
                        jobs += async {
                            gate.withPermit {
                                val ms = core.api.delay(name, Failover.HEALTH_URL, 5000) ?: -1
                                _ui.update { it.copy(pings = it.pings + (server["ui_id"].toString() to ms)) }
                            }
                        }
                    }
                }
                jobs.awaitAll()
            } catch (e: Exception) {
                message(e.message ?: L.t("Проверка серверов не удалась."))
            } finally {
                temp?.stop()
                _ui.update { it.copy(pinging = false) }
            }
        }
    }

    private fun tcpPing(host: String, port: Int): Int = try {
        java.net.Socket().use { socket ->
            val started = System.nanoTime()
            socket.connect(java.net.InetSocketAddress(host, port), 3000)
            ((System.nanoTime() - started) / 1_000_000).toInt().coerceAtLeast(1)
        }
    } catch (_: Exception) {
        -1
    }

    /** Выбрать подписку: её первый сервер, если выбранный сейчас не из неё. */
    fun selectGroup(groupId: String) {
        val group = _ui.value.data.groups.firstOrNull { it.id == groupId } ?: return
        if (_ui.value.data.selectedGroup == groupId) return
        val first = group.servers.firstOrNull() ?: run { message(L.t("В подписке нет серверов — обновите её.")); return }
        select(groupId, first["ui_id"].toString())
    }

    fun regenerateSocksPassword() = updateSettings { it.copy(socksPassword = Store.newSocksPassword()) }

    /** IPv4-адрес телефона в локальной сети — для подключения к SOCKS5 с других устройств. */
    fun lanAddress(): String = runCatching {
        java.net.NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback && !it.name.startsWith("tun") }
            .flatMap { it.inetAddresses.toList() }
            .firstOrNull { it is java.net.Inet4Address && it.isSiteLocalAddress }?.hostAddress
    }.getOrNull() ?: L.t("адрес не найден — подключитесь к Wi-Fi")

    // ── Импорт: ссылки, буфер, QR, файлы WireGuard, deep link ──

    /** Добавить что угодно: ссылку подписки, ссылки серверов, конфиг WireGuard. */
    fun importText(raw: String, fileName: String = ""): Boolean {
        val text = raw.trim().removePrefix("﻿")
        if (text.isEmpty()) return false
        if (text.startsWith("sadnessvpn://")) {
            val url = android.net.Uri.parse(text).getQueryParameter("url")
            return if (url != null) importText(url) else false
        }
        if (text.startsWith("http://") || text.startsWith("https://")) {
            addSubscription(text.lines().first().trim(), "")
            return true
        }
        if ("[INTERFACE]" in text.uppercase()) {
            val servers = runCatching { com.sadness.vpn.core.WireGuard.parse(text, fileName.substringBeforeLast('.')) }
                .getOrElse { message(it.message ?: L.t("Не удалось прочитать конфиг WireGuard")); return false }
            addLocal(LOCAL_WG, "WireGuard", servers)
            message(L.t("Добавлено серверов WireGuard: ") + servers.size)
            return true
        }
        val parsed = com.sadness.vpn.core.Links.parseShareLinks(text)
        if (parsed.servers.isEmpty()) {
            message(parsed.rejected.firstOrNull()?.get("reason") ?: L.t("Не нашли ни ссылки подписки, ни ссылок серверов."))
            return false
        }
        addLocal(LOCAL_LINKS, L.t("Свои серверы"), parsed.servers)
        message(L.t("Добавлено серверов: ") + parsed.servers.size)
        return true
    }

    /** Локальная группа без ссылки: серверы из ссылок или файлов. Повторы не дублируются. */
    private fun addLocal(id: String, name: String, servers: List<com.sadness.vpn.core.Server>) {
        mutate { state ->
            val existing = state.groups.firstOrNull { it.id == id }
            val known = existing?.servers?.map { it["ui_id"].toString() }?.toMutableSet() ?: mutableSetOf()
            val fresh = servers.mapNotNull { s ->
                val uid = Store.serverId(s)
                if (!known.add(uid)) null else s.apply { this["ui_id"] = uid }
            }
            val group = (existing ?: Group(id = id, name = name, url = "", servers = emptyList()))
                .let { it.copy(servers = it.servers + fresh, meta = it.meta + ("updated_at" to System.currentTimeMillis() / 1000)) }
            var next = state.copy(groups = if (existing == null) state.groups + group else state.groups.map { if (it.id == id) group else it })
            if (next.selected() == null && group.servers.isNotEmpty()) {
                next = next.copy(selectedGroup = id, selectedServer = group.servers.first()["ui_id"].toString())
            }
            next
        }
    }

    private var dismissedClipboard = ""

    /** Похоже ли содержимое буфера на то, что можно добавить (и ещё не добавлено). */
    fun offerClipboard(text: String?) {
        val value = text?.trim().orEmpty()
        if (value.isEmpty() || value.length > 64 * 1024 || value == dismissedClipboard) return
        val first = value.lines().first().trim()
        val looks = first.startsWith("https://") || first.startsWith("http://") ||
            com.sadness.vpn.core.Links.SUPPORTED_SCHEMES.any { first.startsWith(it) } || "[INTERFACE]" in value.uppercase()
        if (!looks) return
        if (_ui.value.data.groups.any { it.url == first }) return
        _ui.update { it.copy(clipboardOffer = value) }
    }

    fun dismissClipboard() {
        dismissedClipboard = _ui.value.clipboardOffer
        _ui.update { it.copy(clipboardOffer = "") }
    }

    fun acceptClipboard() {
        val text = _ui.value.clipboardOffer
        dismissClipboard()
        importText(text)
    }

    // ── Серверы: избранное ──

    fun toggleFavorite(id: String) = mutate { s ->
        val fav = s.settings.favorites
        s.copy(settings = s.settings.copy(favorites = if (id in fav) fav - id else fav + id))
    }

    // ── Маршруты ──

    fun addRule(type: String, value: String, action: String): Boolean {
        val normalized = runCatching { MihomoConfig.normalizeRule(type, value) }
            .getOrElse { message(L.t(it.message ?: L.t("Неверное правило"))); return false }
        updateSettings { it.copy(rules = it.rules + MihomoConfig.Rule(type, normalized, action)) }
        return true
    }

    fun removeRule(index: Int) = updateSettings { it.copy(rules = it.rules.filterIndexed { i, _ -> i != index }) }

    // ── Проверка соединения ──

    fun checkConnection() {
        val core = VpnController.core
        val check = core?.check
        if (core == null || check == null || vpn.value.status != Status.ON) {
            message(L.t("Сначала подключите VPN."))
            return
        }
        _ui.update { it.copy(checking = true, check = CheckResult()) }
        viewModelScope.launch(Dispatchers.IO) {
            val proxy = java.net.Proxy(java.net.Proxy.Type.HTTP, java.net.InetSocketAddress("127.0.0.1", check.port))
            val auth = "Basic " + java.util.Base64.getEncoder().encodeToString("${check.user}:${check.password}".toByteArray())
            // HTTPS через прокси с паролем: Android не отдаёт пароль в CONNECT сам (Mihomo
            // не присылает вызов Proxy-Authenticate), поэтому туннель открывается вручную.
            fun getHttps(host: String, path: String): String? = runCatching {
                java.net.Socket().use { raw ->
                    raw.connect(java.net.InetSocketAddress("127.0.0.1", check.port), 8000)
                    raw.soTimeout = 10_000
                    val crlf = "\r\n"
                    raw.getOutputStream().write(("CONNECT $host:443 HTTP/1.1$crlf" + "Host: $host:443$crlf" +
                        "Proxy-Authorization: $auth$crlf$crlf").toByteArray())
                    val input = raw.getInputStream()
                    val head = StringBuilder()
                    while (!head.endsWith("$crlf$crlf")) {
                        val b = input.read()
                        if (b < 0) break
                        head.append(b.toChar())
                    }
                    if (!head.startsWith("HTTP/1.1 200") && !head.startsWith("HTTP/1.0 200")) return@use null
                    val factory = javax.net.ssl.SSLSocketFactory.getDefault() as javax.net.ssl.SSLSocketFactory
                    (factory.createSocket(raw, host, 443, false) as javax.net.ssl.SSLSocket).use { s ->
                        s.startHandshake()
                        s.outputStream.write(("GET $path HTTP/1.0$crlf" + "Host: $host$crlf" +
                            "User-Agent: SadnessVPN$crlf" + "Connection: close$crlf$crlf").toByteArray())
                        val text = s.inputStream.readBytes().decodeToString()
                        if (text.startsWith("HTTP/1.1 200") || text.startsWith("HTTP/1.0 200")) text.substringAfter("$crlf$crlf") else null
                    }
                }
            }.getOrNull()
            fun get(url: String, viaVpn: Boolean): String? = runCatching {
                val c = java.net.URL(url).openConnection(if (viaVpn) proxy else java.net.Proxy.NO_PROXY) as java.net.HttpURLConnection
                c.connectTimeout = 8000
                c.readTimeout = 8000
                if (viaVpn) c.setRequestProperty("Proxy-Authorization", auth)
                try { c.inputStream.bufferedReader().readText() } finally { c.disconnect() }
            }.getOrNull()
            val vpnIp = get("http://ip-api.com/json/?fields=status,country,countryCode,query&lang=" + L.lang, viaVpn = true)
                ?.let { runCatching { org.json.JSONObject(it) }.getOrNull() }
            _ui.update { it.copy(check = CheckResult(country = vpnIp?.optString("country") ?: "", countryCode = vpnIp?.optString("countryCode"),
                ip = vpnIp?.optString("query"))) }
            val youtube = core.api.delay(Failover.MAIN_GROUP, "https://www.youtube.com/generate_204", 6000) ?: -1
            val telegram = core.api.delay(Failover.MAIN_GROUP, "https://telegram.org/", 6000) ?: -1
            _ui.update { it.copy(check = it.check?.copy(youtube = youtube, telegram = telegram)) }
            // Утечка DNS: страна DNS-серверов, которые видит bash.ws, не должна совпадать
            // с настоящей страной телефона (если она отличается от страны VPN).
            val realCountry = get("http://ip-api.com/json/?fields=countryCode", viaVpn = false)
                ?.let { runCatching { org.json.JSONObject(it).optString("countryCode") }.getOrNull() }
            val id = getHttps("bash.ws", "/id")?.trim()?.takeIf { it.length in 4..64 && it.all(Char::isLetterOrDigit) }
            var dnsCountries: List<String> = emptyList()
            var leak: Boolean? = null
            if (id != null) {
                (1..6).forEach { n -> get("http://$n.$id.bash.ws", viaVpn = true) }
                val json = getHttps("bash.ws", "/dnsleak/test/$id?json")
                runCatching {
                    val arr = org.json.JSONArray(json)
                    val dns = (0 until arr.length()).map { arr.getJSONObject(it) }.filter { it.optString("type") == "dns" }
                    dnsCountries = dns.map { it.optString("country_name") }.filter { it.isNotEmpty() }.distinct()
                    val codes = dns.map { it.optString("country").uppercase() }
                    val vpnCode = vpnIp?.optString("countryCode")?.uppercase()
                    leak = realCountry != null && realCountry.uppercase() != vpnCode && realCountry.uppercase() in codes
                }
            }
            _ui.update { it.copy(checking = false, check = it.check?.copy(dnsCountries = dnsCountries, dnsLeak = leak)) }
        }
    }

    // ── Обновления с GitHub ──

    fun checkUpdates(manual: Boolean) {
        viewModelScope.launch(Dispatchers.IO) {
            val info = runCatching { Updates.latest() }.getOrElse {
                if (manual) message(L.t("Не удалось проверить обновления: нет связи с GitHub."))
                return@launch
            }
            if (info == null) {
                if (manual) message(L.t("У вас последняя версия."))
            } else {
                _ui.update { it.copy(update = info) }
            }
        }
    }

    fun dismissUpdate() = _ui.update { it.copy(update = null) }

    /** Скачать APK, сверить SHA-256 с GitHub и передать установщику Android. */
    fun downloadUpdate(onReady: (java.io.File) -> Unit) {
        val info = _ui.value.update ?: return
        _ui.update { it.copy(updateProgress = 0) }
        viewModelScope.launch(Dispatchers.IO) {
            val file = runCatching {
                Updates.download(getApplication(), info) { p -> _ui.update { it.copy(updateProgress = p) } }
            }.getOrElse {
                _ui.update { s -> s.copy(updateProgress = -1) }
                message(L.t(it.message ?: L.t("Не удалось скачать обновление.")))
                return@launch
            }
            _ui.update { it.copy(updateProgress = -1) }
            withContext(Dispatchers.Main) { onReady(file) }
        }
    }

    // ── Приложения ──────────────────────────────────────────

    fun loadApps() {
        if (_ui.value.apps.isNotEmpty() || _ui.value.appsLoading) return
        _ui.update { it.copy(appsLoading = true) }
        viewModelScope.launch(Dispatchers.IO) {
            val pm = getApplication<Application>().packageManager
            val own = getApplication<Application>().packageName
            // Без QUERY_ALL_PACKAGES Android показывает приложениям только те, у которых
            // есть иконка (см. <queries> в манифесте). Ранее выбранные без иконки
            // остаются в списке по имени пакета — VPN всё равно их учитывает.
            val launcher = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                .map { it.activityInfo.packageName }.toSet() +
                pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LEANBACK_LAUNCHER), 0)
                    .map { it.activityInfo.packageName }
            val selected = _ui.value.data.settings.apps
            val apps = (launcher + selected).filter { it != own }.map { pkg ->
                val info = runCatching { pm.getApplicationInfo(pkg, 0) }.getOrNull()
                val system = info == null || (info.flags and ApplicationInfo.FLAG_SYSTEM != 0 && pkg !in launcher)
                AppEntry(pkg, info?.let { pm.getApplicationLabel(it).toString() } ?: pkg, system)
            }.sortedWith(compareBy({ it.system }, { it.label.lowercase() }))
            _ui.update { it.copy(apps = apps, appsLoading = false) }
        }
    }

    fun setAppsMode(mode: AppsMode) = updateSettings { it.copy(appsMode = mode) }

    fun toggleApp(pkg: String) = updateSettings { s -> s.copy(apps = if (pkg in s.apps) s.apps - pkg else s.apps + pkg) }

    // ── Настройки ───────────────────────────────────────────

    fun updateSettings(block: (Settings) -> Settings) {
        mutate { it.copy(settings = block(it.settings)) }
        com.sadness.vpn.data.SubscriptionWork.schedule(getApplication(), _ui.value.data.settings)
        if (vpn.value.status == Status.ON) message(L.t("Изменения применятся при следующем подключении."))
    }

    fun regenerateHwid() = mutate { it.copy(hwid = Subscription.generateHwid()) }

    fun setTheme(theme: String) { Palette.apply(theme); updateSettingsQuiet { it.copy(theme = theme) } }
    fun setLanguage(lang: String) { L.lang = lang; updateSettingsQuiet { it.copy(language = lang) } }

    /** Изменение настроек, не влияющих на работающий VPN (без сообщения о переподключении). */
    fun updateSettingsQuiet(block: (Settings) -> Settings) {
        mutate { it.copy(settings = block(it.settings)) }
        com.sadness.vpn.data.SubscriptionWork.schedule(getApplication(), _ui.value.data.settings)
    }

    // ── Резервная копия и отчёт ──

    fun exportBackup(includeHwid: Boolean, password: String?): ByteArray =
        com.sadness.vpn.data.Backup.export(store, store.load(), includeHwid, password)

    /** Восстановить из файла. null — успешно; иначе текст ошибки. */
    fun importBackup(bytes: ByteArray, password: String?): String? = try {
        val restored = com.sadness.vpn.data.Backup.import(store, bytes, password, store.load())
        mutate { restored }
        L.lang = restored.settings.language
        Palette.apply(restored.settings.theme)
        com.sadness.vpn.data.SubscriptionWork.schedule(getApplication(), restored.settings)
        if (vpn.value.status == Status.ON) message(L.t("Восстановлено. Переподключите VPN, чтобы применить."))
        else message(L.t("Резервная копия восстановлена."))
        null
    } catch (e: com.sadness.vpn.data.Backup.NeedPassword) {
        "need-password"
    } catch (e: com.sadness.vpn.data.Backup.WrongPassword) {
        L.t("Неверный пароль резервной копии.")
    } catch (e: Exception) {
        L.t(e.message ?: "Не удалось прочитать резервную копию.")
    }

    fun bugReport(): String = com.sadness.vpn.data.BugReport.build(getApplication(), store.load())

    companion object {
        const val LOCAL_LINKS = "local-links"
        const val LOCAL_WG = "local-wg"
    }
}
