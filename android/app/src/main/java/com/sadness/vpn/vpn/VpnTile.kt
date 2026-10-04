package com.sadness.vpn.vpn

import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.sadness.vpn.ui.L

/** Кнопка VPN в шторке быстрых настроек. */
class VpnTile : TileService() {
    override fun onStartListening() = render()

    override fun onClick() {
        val status = VpnController.state.value.status
        val needsApp = status == Status.OFF &&
            (android.net.VpnService.prepare(this) != null || com.sadness.vpn.data.Store(this).load().selected() == null)
        if (needsApp) {
            // Разрешения на VPN ещё нет — открыть приложение поверх шторки.
            val intent = VpnToggle.openIntent(this)
            if (Build.VERSION.SDK_INT >= 34) {
                startActivityAndCollapse(PendingIntent.getActivity(this, 2, intent, PendingIntent.FLAG_IMMUTABLE))
            } else {
                @Suppress("DEPRECATION", "StartActivityAndCollapseDeprecated")
                startActivityAndCollapse(intent)
            }
        } else {
            VpnToggle.toggle(this)
        }
        render()
    }

    private fun render() {
        val tile = qsTile ?: return
        val s = VpnController.state.value
        tile.state = if (s.status == Status.OFF) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        if (Build.VERSION.SDK_INT >= 29) {
            tile.subtitle = when (s.status) {
                Status.ON -> s.routeRemark.ifEmpty { L.t("Подключено") }
                Status.CONNECTING -> L.t("Подключение…")
                Status.STOPPING -> L.t("Отключение…")
                Status.OFF -> L.t("Отключено")
            }
        }
        tile.updateTile()
    }

    companion object {
        fun refresh(context: Context) {
            runCatching { requestListeningState(context, ComponentName(context, VpnTile::class.java)) }
        }
    }
}
