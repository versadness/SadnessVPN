package com.sadness.vpn.vpn

import com.sadness.vpn.core.Failover
import com.sadness.vpn.core.Server
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

enum class Status { OFF, CONNECTING, ON, STOPPING }

data class ConnState(
    val status: Status = Status.OFF,
    val error: String = "",
    /** ui_id выбранного сервера, через который подключались. */
    val serverId: String = "",
    /** Название сервера, через который сейчас реально идёт трафик (резерв). */
    val routeRemark: String = "",
    val onBackup: Boolean = false,
    val hasBackup: Boolean = false,
    val up: Long = 0,
    val down: Long = 0,
    val sessionUp: Long = 0,
    val sessionDown: Long = 0,
    val startedAt: Long = 0,
)

/** Общее для службы и интерфейса состояние VPN (один процесс). */
object VpnController {
    private val _state = MutableStateFlow(ConnState())
    val state: StateFlow<ConnState> = _state

    @Volatile var core: Core? = null
        internal set

    internal fun update(block: (ConnState) -> ConnState) = _state.update(block)

    /**
     * Сменить сервер на лету. true — переключено без переподключения;
     * false — сервера нет в работающем ядре, нужно переподключиться.
     */
    fun switchLive(server: Server): Boolean {
        val running = core ?: return false
        if (_state.value.status != Status.ON) return false
        val name = Failover.proxyName(server)
        if (name !in running.live) return false
        if (!running.api.select(Failover.MANUAL_GROUP, name)) return false
        running.api.closeConnections()
        Thread { running.api.recheck(Failover.MAIN_GROUP, Failover.HEALTH_URL) }.start()
        update { it.copy(serverId = server["ui_id"]?.toString().orEmpty(), routeRemark = server["remark"]?.toString().orEmpty(), onBackup = false) }
        return true
    }
}
