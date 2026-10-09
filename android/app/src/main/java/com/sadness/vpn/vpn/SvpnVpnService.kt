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
        Whitelist.start(this)
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
                    startForegroundCompat(notification(com.sadness.vpn.ui.L.t("Подключение…"), ""))
                    Thread { connect() }.apply { name = "svpn-connect" }.start()
                }
            }
        }
        return START_STICKY
    }

    private fun connect() {
        val store = Store(this)
        val state = store.load()
        // Служба может стартовать без интерфейса (постоянный VPN после перезагрузки).
        com.sadness.vpn.ui.L.lang = state.settings.language
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
            // Рекомендуемые исключения: российские банки, госуслуги и т. п. — напрямую.
            if (settings.recommendedDirect && settings.appsMode != AppsMode.ONLY) {
                com.sadness.vpn.data.RuApps.installed(this, settings.recommendedOff + settings.apps)
                    .forEach { runCatching { builder.addDisallowedApplication(it) } }
            }
            val fd = builder.establish() ?: throw IllegalStateException("Android не разрешил создать VPN. Откройте приложение и подключитесь ещё раз.")
            tun = fd
            // Запуск ядра на уже открытом туннеле. Им же ядро перезапускается после
            // неожиданного выхода: туннель остаётся, приложения не теряют сеть.
            launchCore = {
                val current = store.load()
                val selected = current.selected()?.second ?: server
                val s = current.settings
                Core.start(this, selected, current.failoverGroups(), coreSettings(s, Core.newCheckProxy()),
                    failover = s.failover, tunFd = fd.fd, tag = "vpn", autoBest = s.autoBest)
            }
            val core = launchCore!!()
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
            VpnTile.refresh(this)
            startWorkers(core, store)
        } catch (e: Exception) {
            shutdown(e.message ?: "Не удалось подключиться.")
        }
    }

    private var launchCore: (() -> Core)? = null
    private var appTraffic: AppTraffic? = null
    private var countedCore: Core? = null
    private var baseUp = 0L
    private var baseDown = 0L

    /** Экран включён — только тогда нужны живая скорость и частые опросы. */
    private fun screenOn(): Boolean = getSystemService(android.os.PowerManager::class.java)?.isInteractive != false

    private fun startWorkers(@Suppress("UNUSED_PARAMETER") first: Core, store: Store) {
        // Ядро упало — до трёх перезапусков на том же туннеле (как на десктопе);
        // не вышло — VPN выключается с объяснением, а не остаётся «подключённым»
        // без интернета. Здесь же раз в 3 секунды — через какой сервер идёт трафик.
        workers += Thread {
            var lastRoute = ""
            var restarts = 0
            var restartedAt = 0L
            while (!stopping) {
                val core = VpnController.core ?: return@Thread
                // Десять минут стабильной работы — сбои считаются заново.
                if (restarts > 0 && System.currentTimeMillis() - restartedAt > 10 * 60_000) restarts = 0
                if (!core.alive()) {
                    val reason = core.lastError()
                    if (restarts >= MAX_RESTARTS || launchCore == null) {
                        shutdown("Ядро VPN неожиданно завершилось" + if (reason.isEmpty()) "." else ": $reason")
                        return@Thread
                    }
                    restarts++
                    restartedAt = System.currentTimeMillis()
                    try {
                        val fresh = launchCore!!()
                        if (stopping) { fresh.stop(); return@Thread }
                        VpnController.core = fresh
                        lastRoute = ""
                        val selected = Store(this).load().selected()?.second
                        VpnController.update {
                            it.copy(serverId = selected?.get("ui_id")?.toString() ?: it.serverId, hasBackup = fresh.hasBackup, onBackup = false)
                        }
                    } catch (e: Exception) {
                        shutdown("Ядро VPN завершилось и не перезапустилось: " + (e.message ?: reason.ifEmpty { "причина неизвестна" }))
                        return@Thread
                    }
                    continue
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
                try { Thread.sleep(if (screenOn()) 3000 else 15_000) } catch (_: InterruptedException) { return@Thread }
            }
        }.apply { name = "svpn-monitor"; isDaemon = true; start() }
        // Скорость, объём за сессию и трафик по приложениям — одним запросом
        // соединений ядра (как на ПК). Поток /traffic на части телефонов не
        // доходил до приложения, а его поле «за секунду» часто показывает 0.
        // Экран включён — раз в секунду, погашен — раз в 20 с.
        appTraffic = AppTraffic(this)
        workers += Thread {
            var prevUp = -1L; var prevDown = -1L; var prevAt = 0L
            var shownUp = 0.0; var shownDown = 0.0
            var lastNotify = 0L
            while (!stopping) {
                val core = VpnController.core
                val snapshot = core?.takeIf { it.alive() }?.let { runCatching { it.api.connections() }.getOrNull() }
                if (core != null && snapshot != null) {
                    // Новое ядро начинает счёт с нуля — сессия продолжается с накопленного.
                    if (core !== countedCore) {
                        countedCore = core
                        val s = VpnController.state.value
                        baseUp = s.sessionUp; baseDown = s.sessionDown
                        prevUp = -1L
                    }
                    val on = screenOn()
                    val nowNs = System.nanoTime()
                    if (on && prevUp >= 0 && snapshot.upTotal >= prevUp && snapshot.downTotal >= prevDown) {
                        val dt = ((nowNs - prevAt) / 1e9).coerceAtLeast(0.2)
                        shownUp = shownUp * 0.3 + (snapshot.upTotal - prevUp) / dt * 0.7
                        shownDown = shownDown * 0.3 + (snapshot.downTotal - prevDown) / dt * 0.7
                    } else if (!on) { shownUp = 0.0; shownDown = 0.0 }
                    prevUp = snapshot.upTotal; prevDown = snapshot.downTotal; prevAt = nowNs
                    VpnController.update {
                        it.copy(up = shownUp.toLong(), down = shownDown.toLong(),
                            sessionUp = baseUp + snapshot.upTotal, sessionDown = baseDown + snapshot.downTotal)
                    }
                    runCatching { appTraffic?.poll(snapshot) }
                    val now = System.currentTimeMillis()
                    if (on && now - lastNotify >= 2000) { lastNotify = now; updateNotification() }
                }
                try { Thread.sleep(if (screenOn()) 1000 else 20_000) } catch (_: InterruptedException) { break }
            }
        }.apply { name = "svpn-traffic"; isDaemon = true; start() }
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
        synchronized(Store.LOCK) {
            val state = store.load()
            val base = if (state.todayDate == today) state.todayBytes else 0
            store.save(state.copy(todayDate = today, todayBytes = base + delta))
        }
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
        runCatching { appTraffic?.flush() }
        VpnController.core?.let { core ->
            runCatching { saveToday(Store(this), todaySaved) }
            core.stop()
        }
        VpnController.core = null
        runCatching { tun?.close() }
        tun = null
        VpnController.update { ConnState(status = Status.OFF, error = error) }
        VpnWidget.refresh(this)
        VpnTile.refresh(this)
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
        if (s.status != Status.ON) return
        val title = com.sadness.vpn.ui.L.t(if (s.onBackup) "VPN подключён через запасной сервер" else "VPN подключён") +
            if (s.routeRemark.isNotEmpty()) " · " + s.routeRemark else ""
        val seconds = (System.currentTimeMillis() - s.startedAt) / 1000
        val text = "↓ ${speed(s.down)} · ↑ ${speed(s.up)} · %02d:%02d:%02d".format(seconds / 3600, seconds / 60 % 60, seconds % 60)
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(title, text))
        VpnWidget.refresh(this)
    }

    private fun speed(bytes: Long): String {
        return com.sadness.vpn.ui.formatRateText(bytes)
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
            .setOnlyAlertOnce(true)
            .addAction(Notification.Action.Builder(null, com.sadness.vpn.ui.L.t("Отключить"), stop).build())
            .build()
    }

    companion object {
        /** Настройки приложения → настройки ядра. */
        fun coreSettings(s: com.sadness.vpn.data.Settings, check: MihomoConfig.CheckProxy? = null): MihomoConfig.Settings {
            // Раздача по Wi-Fi включает тот же прокси, открытый в сеть; без пароля —
            // только подсеть точки доступа, остальным (и приложениям телефона) — с паролем.
            val hotspot = if (s.shareWifi) Hotspot.addresses().map { it.cidr } else emptyList()
            val proxyOn = (s.socksEnabled || s.shareWifi) && s.socksPassword.isNotEmpty()
            return MihomoConfig.Settings(
                dnsPreset = s.dnsPreset, ipv6 = s.ipv6, mux = s.mux, blockUdp = s.blockUdp, geminiDns = s.geminiDns,
                socks = if (proxyOn) MihomoConfig.Socks(Store.SOCKS_PORT, s.socksUser, s.socksPassword,
                    lan = s.socksLan || s.shareWifi, noAuth = hotspot) else null,
                routing = MihomoConfig.Routing(ruDirect = s.ruDirect, adblock = s.adblock, servicesVpn = s.servicesVpn, rules = s.rules),
                checkProxy = check,
            )
        }

        const val ACTION_STOP = "com.sadness.vpn.STOP"
        private const val MAX_RESTARTS = 3
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
