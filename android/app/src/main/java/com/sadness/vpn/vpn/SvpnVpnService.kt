package com.sadness.vpn.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import com.sadness.vpn.R
import com.sadness.vpn.core.Failover
import com.sadness.vpn.core.MihomoConfig
import com.sadness.vpn.data.AppsMode
import com.sadness.vpn.data.Store
import com.sadness.vpn.ui.MainActivity
import java.time.LocalDate

/**
 * VPN через системный VpnService: туннель создаёт Android (root не нужен,
 * разрешение спрашивается один раз), трафик внутри туннеля обрабатывает ядро.
 */
class SvpnVpnService : VpnService() {
    private var tun: ParcelFileDescriptor? = null
    private var workers = mutableListOf<Thread>()
    @Volatile private var stopping = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                Thread { shutdown("") }.start()
                return START_NOT_STICKY
            }
            else -> {
                // Включение из системы (always-on VPN) приходит без нашего действия.
                if (VpnController.state.value.status == Status.OFF) {
                    stopping = false
                    VpnController.update { ConnState(status = Status.CONNECTING) }
                    startForegroundCompat(notification(getString(R.string.notif_connecting), ""))
                    Thread { connect() }.apply { name = "svpn-connect" }.start()
                }
            }
        }
        return START_STICKY
    }

    private fun connect() {
        val store = Store(this)
        val state = store.load()
        val selection = state.selected()
        if (selection == null) {
            shutdown("Сначала выберите сервер.")
            return
        }
        val (_, server) = selection
        try {
            val settings = state.settings
            val builder = Builder()
                .setSession(getString(R.string.app_name))
                .setMtu(MihomoConfig.TUN_MTU)
                .addAddress(MihomoConfig.TUN_ADDRESS, MihomoConfig.TUN_PREFIX)
                .addDnsServer(MihomoConfig.TUN_DNS)
                .addRoute("0.0.0.0", 0)
                // IPv6 тоже заворачивается в туннель: иначе в сетях с IPv6
                // приложения ходили бы мимо VPN.
                .addAddress(MihomoConfig.TUN_ADDRESS6, 126)
                .addRoute("::", 0)
                .setConfigureIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) builder.setMetered(false)
            // Само приложение (и ядро — это его процесс) идёт мимо туннеля:
            // соединения с VPN-сервером не должны попадать обратно в VPN.
            when (settings.appsMode) {
                AppsMode.ONLY -> {
                    val apps = settings.apps.filter { it != packageName }
                    if (apps.isEmpty()) throw IllegalStateException("В режиме «Только эти» выберите хотя бы одно приложение.")
                    apps.forEach { runCatching { builder.addAllowedApplication(it) } }
                }
                AppsMode.EXCEPT -> {
                    builder.addDisallowedApplication(packageName)
                    settings.apps.filter { it != packageName }.forEach { runCatching { builder.addDisallowedApplication(it) } }
                }
                AppsMode.ALL -> builder.addDisallowedApplication(packageName)
            }
            val fd = builder.establish() ?: throw IllegalStateException("Android не разрешил создать VPN. Откройте приложение и подключитесь ещё раз.")
            tun = fd
            val core = Core.start(this, server, state.failoverGroups(), MihomoConfig.Settings(
                dnsPreset = settings.dnsPreset, ipv6 = settings.ipv6, mux = settings.mux, blockUdp = settings.blockUdp,
            ), failover = settings.failover, tunFd = fd.fd, tag = "vpn")
            if (stopping) {
                core.stop()
                return
            }
            VpnController.core = core
            val hasBackup = core.hasBackup
            VpnController.update {
                it.copy(status = Status.ON, error = "", serverId = server["ui_id"].toString(),
                    routeRemark = server["remark"].toString(), startedAt = System.currentTimeMillis(), hasBackup = hasBackup)
            }
            updateNotification()
            startWorkers(core, store)
        } catch (e: Exception) {
            shutdown(e.message ?: "Не удалось подключиться.")
        }
    }

    private fun startWorkers(core: Core, store: Store) {
        // Скорость и объём за сессию.
        workers += Thread {
            while (!stopping && core.alive()) {
                try {
                    core.api.streamTraffic { up, down ->
                        VpnController.update { it.copy(up = up, down = down, sessionUp = it.sessionUp + up, sessionDown = it.sessionDown + down) }
                    }
                } catch (_: Exception) {
                    if (stopping) break
                    Thread.sleep(1000)
                }
            }
        }.apply { name = "svpn-traffic"; isDaemon = true; start() }
        // Ядро упало — VPN выключается с объяснением, а не остаётся «подключённым» без интернета.
        // Здесь же раз в 3 секунды — через какой сервер реально идёт трафик.
        workers += Thread {
            var lastRoute = ""
            while (!stopping) {
                if (!core.alive()) {
                    shutdown("Ядро VPN неожиданно завершилось. " + core.tail(3).lines().lastOrNull().orEmpty().take(160))
                    return@Thread
                }
                val route = currentRoute(core)
                if (route != null && route != lastRoute) {
                    lastRoute = route
                    val server = core.live[route]
                    val selectedId = VpnController.state.value.serverId
                    VpnController.update {
                        it.copy(routeRemark = server?.get("remark")?.toString().orEmpty(),
                            onBackup = server != null && server["ui_id"]?.toString() != selectedId)
                    }
                    updateNotification()
                }
                try { Thread.sleep(3000) } catch (_: InterruptedException) { return@Thread }
            }
        }.apply { name = "svpn-monitor"; isDaemon = true; start() }
        // Учёт трафика за день — раз в минуту и при отключении.
        workers += Thread {
            var saved = 0L
            while (!stopping) {
                try { Thread.sleep(60_000) } catch (_: InterruptedException) { break }
                saved = saveToday(store, saved)
            }
        }.apply { name = "svpn-today"; isDaemon = true; start() }
    }

    private var todaySaved = 0L

    private fun saveToday(store: Store, alreadySaved: Long): Long {
        val s = VpnController.state.value
        val total = s.sessionUp + s.sessionDown
        val delta = total - alreadySaved
        if (delta <= 0) return alreadySaved
        val today = LocalDate.now().toString()
        val state = store.load()
        val base = if (state.todayDate == today) state.todayBytes else 0
        store.save(state.copy(todayDate = today, todayBytes = base + delta))
        todaySaved = total
        return total
    }

    /** Имя сервера в ядре, через который сейчас идёт трафик. */
    private fun currentRoute(core: Core): String? {
        val api = core.api
        val main = api.now(Failover.MAIN_GROUP) ?: return null
        return when (main) {
            Failover.MANUAL_GROUP -> api.now(Failover.MANUAL_GROUP)
            Failover.BACKUP_GROUP -> api.now(Failover.BACKUP_GROUP)
            else -> main
        }
    }

    @Synchronized
    private fun shutdown(error: String) {
        if (stopping && VpnController.state.value.status == Status.OFF) return
        stopping = true
        VpnController.update { it.copy(status = Status.STOPPING) }
        workers.forEach { it.interrupt() }
        workers.clear()
        VpnController.core?.let { core ->
            runCatching { saveToday(Store(this), todaySaved) }
            core.stop()
        }
        VpnController.core = null
        runCatching { tun?.close() }
        tun = null
        VpnController.update { ConnState(status = Status.OFF, error = error) }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onRevoke() {
        // Другое VPN-приложение забрало туннель или разрешение отозвано.
        Thread { shutdown("VPN отключён системой: включено другое VPN-приложение.") }.start()
    }

    override fun onDestroy() {
        if (!stopping) shutdown("")
        super.onDestroy()
    }

    private fun updateNotification() {
        val s = VpnController.state.value
        val title = if (s.onBackup) getString(R.string.notif_backup) else getString(R.string.notif_connected)
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(title, s.routeRemark))
    }

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun notification(title: String, text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, SvpnVpnService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, getString(R.string.disconnect), stop).build())
            .build()
    }

    companion object {
        const val ACTION_STOP = "com.sadness.vpn.STOP"
        private const val CHANNEL = "vpn"
        private const val NOTIFICATION_ID = 1

        fun start(context: Context) {
            context.startForegroundService(Intent(context, SvpnVpnService::class.java))
        }

        fun stop(context: Context) {
            context.startService(Intent(context, SvpnVpnService::class.java).setAction(ACTION_STOP))
        }
    }
}
