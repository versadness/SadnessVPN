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

data class UiState(
    val data: State = State(),
    /** ui_id → задержка в мс; -1 — сервер не ответил. */
    val pings: Map<String, Int> = emptyMap(),
    val pinging: Boolean = false,
    val busyGroups: Set<String> = emptySet(),
    val message: String = "",
    val apps: List<AppEntry> = emptyList(),
    val appsLoading: Boolean = false,
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
        if (_ui.value.data.settings.autoUpdate && _ui.value.data.groups.isNotEmpty()) refreshAll(silent = true)
    }

    private fun mutate(block: (State) -> State) {
        synchronized(store) {
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
            message("Нужна ссылка подписки вида https://…")
            return
        }
        val id = Store.newId()
        mutate { it.copy(groups = it.groups + Group(id = id, name = name.trim(), url = link, servers = emptyList())) }
        refresh(id, removeOnFailure = true)
    }

    fun refreshAll(silent: Boolean = false) = _ui.value.data.groups.forEach { refresh(it.id, silent = silent) }

    fun refresh(groupId: String, removeOnFailure: Boolean = false, silent: Boolean = false) {
        val group = _ui.value.data.groups.firstOrNull { it.id == groupId } ?: return
        _ui.update { it.copy(busyGroups = it.busyGroups + groupId) }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { Subscription.fetch(group.url, client, store.load().hwid) }
            }
            _ui.update { it.copy(busyGroups = it.busyGroups - groupId) }
            result.onSuccess { fetched ->
                val ids = HashMap<String, Int>()
                val servers = fetched.servers.map { server ->
                    val base = Store.serverId(server)
                    val n = ids.merge(base, 1, Int::plus)!!
                    server.apply { this["ui_id"] = if (n == 1) base else "$base-$n" }
                }
                val title = fetched.metadata["provider_name"]?.toString().orEmpty()
                mutate { state ->
                    val groups = state.groups.map {
                        if (it.id != groupId) it else it.copy(
                            name = it.name.ifEmpty { title.ifEmpty { "Подписка" } },
                            servers = servers, meta = fetched.metadata, error = "",
                        )
                    }
                    var next = state.copy(groups = groups)
                    if (next.selected() == null && servers.isNotEmpty() && (state.selectedGroup.isEmpty() || state.selectedGroup == groupId)) {
                        next = next.copy(selectedGroup = groupId, selectedServer = servers.first()["ui_id"].toString())
                    }
                    next
                }
                if (!silent) message("«${_ui.value.data.groups.firstOrNull { it.id == groupId }?.name}»: ${servers.size} серверов")
            }.onFailure { error ->
                val text = (error as? SubscriptionException)?.message ?: "Не удалось обновить подписку."
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
        mutate { it.copy(selectedGroup = groupId, selectedServer = serverId) }
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
            message("Сначала добавьте подписку и выберите сервер.")
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

    /** Задержка через каждый сервер — настоящим запросом через ядро. */
    fun pingAll() {
        val data = _ui.value.data
        val servers = data.groups.flatMap { it.servers }
        if (servers.isEmpty() || _ui.value.pinging) return
        _ui.update { it.copy(pinging = true, pings = emptyMap()) }
        viewModelScope.launch(Dispatchers.IO) {
            var temp: Core? = null
            try {
                val running = VpnController.core
                val core = running ?: Core.start(getApplication(), servers.first(), data.failoverGroups(),
                    MihomoConfig.Settings(dnsPreset = data.settings.dnsPreset), failover = false, tunFd = -1, tag = "probe").also { temp = it }
                val gate = Semaphore(8)
                core.live.map { (name, server) ->
                    async {
                        gate.withPermit {
                            val ms = core.api.delay(name, Failover.HEALTH_URL, 5000) ?: -1
                            _ui.update { it.copy(pings = it.pings + (server["ui_id"].toString() to ms)) }
                        }
                    }
                }.awaitAll()
            } catch (e: Exception) {
                message(e.message ?: "Проверка серверов не удалась.")
            } finally {
                temp?.stop()
                _ui.update { it.copy(pinging = false) }
            }
        }
    }

    // ── Приложения ──────────────────────────────────────────

    fun loadApps() {
        if (_ui.value.apps.isNotEmpty() || _ui.value.appsLoading) return
        _ui.update { it.copy(appsLoading = true) }
        viewModelScope.launch(Dispatchers.IO) {
            val pm = getApplication<Application>().packageManager
            val own = getApplication<Application>().packageName
            val launchable = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                .map { it.activityInfo.packageName }.toSet()
            val apps = pm.getInstalledApplications(PackageManager.GET_META_DATA)
                .filter { it.packageName != own && pm.checkPermission(android.Manifest.permission.INTERNET, it.packageName) == PackageManager.PERMISSION_GRANTED }
                .map { info ->
                    val system = info.flags and ApplicationInfo.FLAG_SYSTEM != 0 && info.packageName !in launchable
                    AppEntry(info.packageName, pm.getApplicationLabel(info).toString(), system)
                }
                .sortedWith(compareBy({ it.system }, { it.label.lowercase() }))
            _ui.update { it.copy(apps = apps, appsLoading = false) }
        }
    }

    fun setAppsMode(mode: AppsMode) = updateSettings { it.copy(appsMode = mode) }

    fun toggleApp(pkg: String) = updateSettings { s -> s.copy(apps = if (pkg in s.apps) s.apps - pkg else s.apps + pkg) }

    // ── Настройки ───────────────────────────────────────────

    fun updateSettings(block: (Settings) -> Settings) {
        mutate { it.copy(settings = block(it.settings)) }
        if (vpn.value.status == Status.ON) message("Изменения применятся при следующем подключении.")
    }

    fun regenerateHwid() = mutate { it.copy(hwid = Subscription.generateHwid()) }
}
