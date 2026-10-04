package com.sadness.vpn.data

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.app.Notification
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.sadness.vpn.R
import com.sadness.vpn.core.SubscriptionException
import com.sadness.vpn.ui.L
import com.sadness.vpn.ui.MainActivity
import com.sadness.vpn.ui.formatBytes
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/** Подписки в фоне: обновление раз в N часов и предупреждения о сроке и трафике. */
class SubscriptionWork(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val store = Store(applicationContext)
        L.lang = store.load().settings.language
        for (group in store.load().groups.filter { it.url.isNotEmpty() }) {
            try {
                SubscriptionUpdater.refresh(store, group.id)
            } catch (e: SubscriptionException) {
                if (!e.notModified) SubscriptionUpdater.markError(store, group.id, e.message.orEmpty())
            } catch (_: Exception) {
                // Сеть пропала посреди загрузки — следующая попытка по расписанию.
            }
        }
        checkWarnings(applicationContext)
        return Result.success()
    }

    companion object {
        private const val NAME = "subscriptions"
        private const val CHANNEL = "subscriptions"

        /** Включить, перенастроить или выключить фоновое обновление по настройкам. */
        fun schedule(context: Context, settings: Settings) {
            val manager = WorkManager.getInstance(context)
            if (!settings.bgRefresh) {
                manager.cancelUniqueWork(NAME)
                return
            }
            val request = PeriodicWorkRequestBuilder<SubscriptionWork>(settings.bgHours.toLong(), TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .addTag("h${settings.bgHours}")
                .build()
            manager.enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
        }

        /** Предупредить о конце подписки и трафика — каждое предупреждение один раз за период. */
        fun checkWarnings(context: Context) {
            val store = Store(context)
            val pending = mutableListOf<Pair<String, String>>()
            synchronized(Store.LOCK) {
                val state = store.load()
                val s = state.settings
                val now = System.currentTimeMillis() / 1000
                val groups = state.groups.map { group ->
                    val warned = (group.meta["warned"] as? List<*>).orEmpty().map { it.toString() }.toMutableSet()
                    val before = warned.size
                    val expire = (group.meta["expire"] as? Number)?.toLong() ?: 0
                    if (s.warnExpire && expire > now) {
                        val days = (expire - now) / 86400
                        val date = Instant.ofEpochSecond(expire).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("dd.MM.yyyy"))
                        when {
                            days < 1 && warned.add("e1:$expire") -> pending += L.t("Подписка «") + group.name + L.t("» закончится сегодня") to
                                L.t("Действует до ") + date + L.t(". Продлите у провайдера, чтобы VPN не отключился.")
                            days < 3 && "e1:$expire" !in warned && warned.add("e3:$expire") -> pending += L.t("Подписка «") + group.name +
                                L.t("» закончится через ") + "${days + 1} " + L.plural(days + 1, "день", "дня", "дней") to
                                L.t("Действует до ") + date + L.t(". Продлите у провайдера, чтобы VPN не отключился.")
                        }
                    }
                    val total = (group.meta["total"] as? Number)?.toLong() ?: 0
                    if (s.warnTraffic && total > 0) {
                        val used = ((group.meta["upload"] as? Number)?.toLong() ?: 0) + ((group.meta["download"] as? Number)?.toLong() ?: 0)
                        val period = if (expire > 0) expire else total
                        val text = formatBytes(used) + L.t(" из ") + formatBytes(total) + L.t(" использовано.")
                        when {
                            used >= total && warned.add("t100:$period") -> pending += "«${group.name}»: " + L.t("трафик закончился") to text
                            used >= total * 9 / 10 && "t100:$period" !in warned && warned.add("t90:$period") ->
                                pending += "«${group.name}»: " + L.t("осталось 10% трафика") to text
                        }
                    }
                    if (warned.size != before) group.copy(meta = group.meta + ("warned" to warned.sorted())) else group
                }
                if (pending.isNotEmpty()) store.save(state.copy(groups = groups))
            }
            pending.forEach { (title, text) -> notify(context, title, text) }
        }

        private fun notify(context: Context, title: String, text: String) {
            val manager = context.getSystemService(NotificationManager::class.java)
            if (manager.getNotificationChannel(CHANNEL) == null) {
                manager.createNotificationChannel(NotificationChannel(CHANNEL, L.t("Подписки"), NotificationManager.IMPORTANCE_DEFAULT))
            }
            val open = PendingIntent.getActivity(context, 3, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            val notification = Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(Notification.BigTextStyle().bigText(text))
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            runCatching { manager.notify((title.hashCode() and 0x7fffffff) + 100, notification) }
        }
    }
}
