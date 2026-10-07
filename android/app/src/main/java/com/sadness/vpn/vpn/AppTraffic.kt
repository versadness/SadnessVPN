package com.sadness.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.os.Build
import android.system.OsConstants
import com.sadness.vpn.core.Json
import com.sadness.vpn.core.jsonToKotlin
import org.json.JSONObject
import java.io.File
import java.net.InetSocketAddress
import java.time.LocalDate

/**
 * Трафик через VPN по приложениям. Ядро сообщает для каждого соединения адрес
 * приложения в туннеле (sourceIP:sourcePort) и адрес, к которому оно подключалось
 * (inboundIP:inboundPort). По этой паре Android отдаёт VPN-приложению UID владельца
 * (getConnectionOwnerUid, Android 10+). Учёт — по дням, хранится 31 день.
 */
class AppTraffic(private val context: Context) {
    private val file = File(context.filesDir, "app_traffic.json")
    private val previous = HashMap<String, Long>()
    private val owners = HashMap<String, Int>()
    /** Байты соединения за последний опрос — вес для доли закрывшихся соединений. */
    private val lastDelta = HashMap<String, Long>()
    private var lastTotal = -1L
    private val today = HashMap<Int, Long>()
    private var lastSave = 0L

    /** Один опрос ядра: прибавить новые байты к UID владельцев соединений. */
    fun poll(snapshot: ClashApi.Snapshot) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val alive = HashSet<String>()
        var attributed = 0L
        for (c in snapshot.connections) {
            alive += c.id
            val total = c.upload + c.download
            val delta = total - (previous[c.id] ?: 0L)
            previous[c.id] = total
            lastDelta[c.id] = delta.coerceAtLeast(0)
            if (delta <= 0) continue
            attributed += delta
            val uid = owners.getOrPut(c.id) { ownerUid(cm, c) }
            today[uid] = (today[uid] ?: 0L) + delta
        }
        // Соединение могло закрыться между опросами — его последние байты видны
        // только в общем счётчике ядра. Остаток делится между закрывшимися
        // соединениями по их последней скорости, а если таких нет — «не определено».
        val globalDelta = if (lastTotal < 0 || snapshot.total < lastTotal) 0 else snapshot.total - lastTotal
        lastTotal = snapshot.total
        val rest = globalDelta - attributed
        val closed = previous.keys.filter { it !in alive }
        if (rest > 0) {
            val weights = closed.associateWith { lastDelta[it] ?: 0L }
            val sum = weights.values.sum()
            if (closed.isEmpty()) today[-1] = (today[-1] ?: 0L) + rest
            else for (id in closed) {
                val share = if (sum > 0) rest * (weights[id] ?: 0) / sum else rest / closed.size
                val uid = owners[id] ?: -1
                today[uid] = (today[uid] ?: 0L) + share
            }
        }
        previous.keys.retainAll(alive)
        owners.keys.retainAll(alive)
        lastDelta.keys.retainAll(alive)
        if (System.currentTimeMillis() - lastSave > 30_000) flush()
    }

    private fun ownerUid(cm: ConnectivityManager, c: ClashApi.Connection): Int = runCatching {
        val protocol = if (c.network == "udp") OsConstants.IPPROTO_UDP else OsConstants.IPPROTO_TCP
        val local = InetSocketAddress(c.sourceIp, c.sourcePort)
        val remote = InetSocketAddress(c.inboundIp, c.inboundPort)
        cm.getConnectionOwnerUid(protocol, local, remote)
    }.getOrDefault(-1)

    /** Сохранить накопленное за сегодня (по пакетам) и забыть его из памяти. */
    @Synchronized
    fun flush() {
        lastSave = System.currentTimeMillis()
        if (today.isEmpty()) return
        val data = load(context)
        val day = LocalDate.now().toString()
        val bucket = (data[day] ?: emptyMap()).toMutableMap()
        for ((uid, bytes) in today) {
            val key = packageOf(context, uid)
            bucket[key] = (bucket[key] ?: 0L) + bytes
        }
        today.clear()
        data[day] = bucket
        val keep = LocalDate.now().minusDays(31).toString()
        data.keys.removeAll { it < keep }
        val tmp = File(file.parentFile, "app_traffic.json.tmp")
        tmp.writeText(Json.encode(data))
        if (!tmp.renameTo(file)) { file.delete(); tmp.renameTo(file) }
    }

    companion object {
        /** UID → имя пакета; системные службы без пакета — «uid:N». */
        fun packageOf(context: Context, uid: Int): String = when {
            uid < 0 -> "?"
            else -> context.packageManager.getPackagesForUid(uid)?.firstOrNull() ?: "uid:$uid"
        }

        @Suppress("UNCHECKED_CAST")
        fun load(context: Context): MutableMap<String, Map<String, Long>> {
            val file = File(context.filesDir, "app_traffic.json")
            val raw = runCatching { jsonToKotlin(JSONObject(file.readText())) as Map<String, Any?> }.getOrNull() ?: return LinkedHashMap()
            return raw.mapValues { (_, v) -> (v as? Map<String, Any?>).orEmpty().mapValues { (it.value as? Number)?.toLong() ?: 0L } }.toMutableMap()
        }

        /** Сумма по пакетам за последние days дней (включая сегодня). */
        fun summary(context: Context, days: Int): List<Pair<String, Long>> {
            val from = LocalDate.now().minusDays((days - 1).toLong()).toString()
            val sum = HashMap<String, Long>()
            load(context).filterKeys { it >= from }.values.forEach { day -> day.forEach { (k, v) -> sum[k] = (sum[k] ?: 0L) + v } }
            return sum.entries.map { it.key to it.value }.sortedByDescending { it.second }
        }
    }
}
