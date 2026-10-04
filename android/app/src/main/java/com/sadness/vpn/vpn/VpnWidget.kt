package com.sadness.vpn.vpn

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.sadness.vpn.R
import com.sadness.vpn.data.Store
import com.sadness.vpn.ui.L

/** Виджет на рабочий стол: кнопка включения и текущий сервер. */
class VpnWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = render(context, manager, ids)

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_TOGGLE) {
            VpnToggle.toggle(context)
            refresh(context)
        }
    }

    companion object {
        private const val ACTION_TOGGLE = "com.sadness.vpn.WIDGET_TOGGLE"

        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, VpnWidget::class.java))
            if (ids.isNotEmpty()) render(context, manager, ids)
        }

        private fun render(context: Context, manager: AppWidgetManager, ids: IntArray) {
            val s = VpnController.state.value
            val selected = runCatching { Store(context).load().selected()?.second?.get("remark")?.toString() }.getOrNull()
            val on = s.status == Status.ON
            val views = RemoteViews(context.packageName, R.layout.widget_vpn).apply {
                setTextViewText(R.id.widget_server, (if (on) s.routeRemark.ifEmpty { null } else selected) ?: context.getString(R.string.app_name))
                setTextViewText(R.id.widget_status, L.t(when (s.status) {
                    Status.ON -> "Подключено"
                    Status.CONNECTING -> "Подключение…"
                    Status.STOPPING -> "Отключение…"
                    Status.OFF -> "Отключено"
                }))
                setImageViewResource(R.id.widget_button, if (on) R.drawable.widget_power_on else R.drawable.widget_power_off)
                val toggle = PendingIntent.getBroadcast(context, 0, Intent(context, VpnWidget::class.java).setAction(ACTION_TOGGLE),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
                setOnClickPendingIntent(R.id.widget_root, toggle)
            }
            manager.updateAppWidget(ids, views)
        }
    }
}
