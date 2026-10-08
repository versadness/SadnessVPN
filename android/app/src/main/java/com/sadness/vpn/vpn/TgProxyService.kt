package com.sadness.vpn.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.sadness.vpn.R
import com.sadness.vpn.data.Store
import com.sadness.vpn.ui.L
import com.sadness.vpn.ui.MainActivity

/** Держит Telegram-прокси живым, пока он включён в настройках — с VPN и без него. */
class TgProxyService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val s = Store(this).load().settings
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, L.t("Telegram-прокси"), NotificationManager.IMPORTANCE_MIN))
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(L.t("Telegram-прокси работает"))
            .setContentText("127.0.0.1:${TgWsProxy.PORT}")
            .setContentIntent(open).setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(ID, n)
        if (!s.tgProxy || s.tgProxySecret.isEmpty()) { stopSelf(); return START_NOT_STICKY }
        if (!TgWsProxy.start(s.tgProxySecret)) { stopSelf(); return START_NOT_STICKY }
        return START_STICKY
    }

    override fun onDestroy() {
        TgWsProxy.stop()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "tg_proxy"
        private const val ID = 7
        fun sync(context: Context, on: Boolean) {
            val i = Intent(context, TgProxyService::class.java)
            if (on) runCatching { context.startForegroundService(i) } else context.stopService(i)
        }
    }
}
