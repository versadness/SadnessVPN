package com.sadness.vpn.data

import android.os.Build
import com.sadness.vpn.BuildConfig
import com.sadness.vpn.core.Subscription

/**
 * Обновление подписки — общее для экрана и фоновой задачи. Слияние результата
 * в состояние — чистая функция; запись — под общей блокировкой Store.LOCK.
 */
object SubscriptionUpdater {
    val client: Subscription.ClientInfo by lazy {
        Subscription.ClientInfo(
            version = BuildConfig.VERSION_NAME.removeSuffix("-debug"),
            osVersion = Build.VERSION.RELEASE,
            arch = when (Build.SUPPORTED_ABIS.firstOrNull()) {
                "arm64-v8a" -> "arm64"; "armeabi-v7a" -> "arm"; "x86_64" -> "amd64"; else -> "unknown"
            },
            model = Subscription.deviceModel(Build.MANUFACTURER.orEmpty(), Build.MODEL.orEmpty()),
        )
    }

    /** Новое состояние после успешной загрузки подписки groupId. */
    fun merge(state: State, groupId: String, fetched: Subscription.Result): State {
        val ids = HashMap<String, Int>()
        val servers = fetched.servers.map { server ->
            val base = Store.serverId(server)
            val n = ids.merge(base, 1, Int::plus)!!
            server.apply { this["ui_id"] = if (n == 1) base else "$base-$n" }
        }
        val title = fetched.metadata["provider_name"]?.toString().orEmpty()
        val groups = state.groups.map { group ->
            if (group.id != groupId) group else {
                // Отметки об уже показанных предупреждениях переживают обновление.
                val warned = group.meta["warned"]
                group.copy(
                    name = group.name.ifEmpty { title.ifEmpty { "Подписка" } },
                    servers = servers,
                    meta = if (warned != null) fetched.metadata + ("warned" to warned) else fetched.metadata,
                    error = "",
                )
            }
        }
        var next = state.copy(groups = groups)
        if (next.selected() == null && servers.isNotEmpty() && (state.selectedGroup.isEmpty() || state.selectedGroup == groupId)) {
            next = next.copy(selectedGroup = groupId, selectedServer = servers.first()["ui_id"].toString())
        }
        return next
    }

    /** Загрузить и сохранить; возвращает число серверов или бросает SubscriptionException. */
    fun refresh(store: Store, groupId: String): Int {
        val group = store.load().groups.firstOrNull { it.id == groupId } ?: return 0
        if (group.url.isEmpty()) return group.servers.size
        val fetched = Subscription.fetch(group.url, client, store.load().hwid)
        synchronized(Store.LOCK) { store.save(merge(store.load(), groupId, fetched)) }
        return fetched.servers.size
    }

    fun markError(store: Store, groupId: String, text: String) = synchronized(Store.LOCK) {
        val state = store.load()
        store.save(state.copy(groups = state.groups.map { if (it.id == groupId) it.copy(error = text) else it }))
    }
}
