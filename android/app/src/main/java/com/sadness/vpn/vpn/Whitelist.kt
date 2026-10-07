package com.sadness.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import com.sadness.vpn.data.Store
import com.sadness.vpn.ui.L
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Белые списки оператора: при них напрямую открываются только разрешённые
 * российские сайты, а всё зарубежное — нет. Проверяем при смене сети: само
 * приложение идёт мимо VPN, поэтому видит сеть оператора как есть.
 * Никакого постоянного опроса — только по событию сети (батарея не тратится).
 */
object Whitelist {
    enum class State { UNKNOWN, OFF, ON }

    private val _state = MutableStateFlow(State.UNKNOWN)
    val state: StateFlow<State> = _state

    private val RU = listOf("https://ya.ru", "https://www.gosuslugi.ru", "https://vk.com")
    private val FOREIGN = listOf("https://www.google.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace", "https://github.com")

    private val pool = Executors.newSingleThreadScheduledExecutor { Thread(it, "svpn-whitelist").apply { isDaemon = true } }
    private var started = false
    private var pending: java.util.concurrent.ScheduledFuture<*>? = null
    private lateinit var app: Context

    /** Подписаться на смену сети; повторный вызов ничего не делает. */
    @Synchronized
    fun start(context: Context) {
        if (started) return
        started = true
        app = context.applicationContext
        val cm = app.getSystemService(ConnectivityManager::class.java)
        runCatching {
            cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = schedule()
                override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                    if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) schedule()
                }
                override fun onLost(network: Network) { _state.value = State.UNKNOWN }
            })
        }
        schedule()
    }

    /** Проверить сейчас (например, по кнопке). */
    fun recheck() = schedule(0)

    @Synchronized
    private fun schedule(delaySec: Long = 3) {
        if (!enabled()) { _state.value = State.UNKNOWN; return }
        pending?.cancel(false)
        pending = pool.schedule({ probe() }, delaySec, TimeUnit.SECONDS)
    }

    private fun enabled() = runCatching { Store(app).load().settings.whitelistCheck }.getOrDefault(true)

    private fun reachable(url: String): Boolean = runCatching {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 4000; c.readTimeout = 4000; c.requestMethod = "HEAD"; c.instanceFollowRedirects = false
        try { c.responseCode > 0 } finally { c.disconnect() }
    }.getOrDefault(false)

    private fun anyOf(urls: List<String>): Boolean {
        val tasks = urls.map { u -> Executors.newSingleThreadExecutor().let { ex -> ex.submit<Boolean> { reachable(u) }.also { ex.shutdown() } } }
        return tasks.any { runCatching { it.get(6, TimeUnit.SECONDS) }.getOrDefault(false) }
    }

    private fun probe() {
        val ru = anyOf(RU)
        if (!ru) { _state.value = State.UNKNOWN; return } // интернета нет вовсе — не о чем говорить
        val foreign = anyOf(FOREIGN)
        val next = if (foreign) State.OFF else State.ON
        val before = _state.value
        _state.value = next
        if (next == State.ON && before != State.ON) {
            com.sadness.vpn.data.SubscriptionWork.notify(app, L.t("Оператор включил белые списки"),
                L.t("Зарубежные сайты напрямую не открываются. Если VPN перестал работать — выберите сервер для белых списков."))
        }
    }
}
