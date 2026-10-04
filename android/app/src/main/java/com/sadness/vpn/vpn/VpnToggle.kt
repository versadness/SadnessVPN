package com.sadness.vpn.vpn

import android.content.Context
import android.content.Intent
import android.net.VpnService
import com.sadness.vpn.data.Store
import com.sadness.vpn.ui.MainActivity

/** Включить/выключить VPN из шторки или виджета. */
object VpnToggle {
    const val ACTION_CONNECT = "com.sadness.vpn.CONNECT"

    /** true — переключено; false — нужно открыть приложение (разрешение или нет сервера). */
    fun toggle(context: Context): Boolean {
        when (VpnController.state.value.status) {
            Status.ON, Status.CONNECTING -> { SvpnVpnService.stop(context); return true }
            Status.STOPPING -> return true
            Status.OFF -> Unit
        }
        if (VpnService.prepare(context) != null || Store(context).load().selected() == null) {
            context.startActivity(openIntent(context))
            return false
        }
        SvpnVpnService.start(context)
        return true
    }

    fun openIntent(context: Context): Intent = Intent(context, MainActivity::class.java)
        .setAction(ACTION_CONNECT).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
}
