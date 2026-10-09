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
                // onCapabilitiesChanged на мобильной сети приходит постоянно (уровень
                // сигнала, пропускная способность). Проверка — только когда сеть
                // сменилась или впервые прошла проверку системы, иначе каждый такой
                // сигнал будил бы радиомодуль шестью запросами.
                override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                    val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
                    val key = network.toString()
                    if (!validated) { if (key == lastNetwork) lastValidated = false; return }
                    if (key == lastNetwork && lastValidated) return
                    lastNetwork = key; lastValidated = true
                    schedule()
                }
                override fun onLost(network: Network) {
                    if (network.toString() == lastNetwork) { lastNetwork = ""; lastValidated = false }
                    _state.value = State.UNKNOWN
                }
            })
        }
    }

    @Volatile private var lastNetwork = ""
    @Volatile private var lastValidated = false
    /** Когда и для какой сети была последняя проверка — не чаще раза в 10 минут. */
    private var probedNetwork = ""
    private var probedAt = 0L
    private const val MIN_INTERVAL_MS = 10 * 60_000L

    /** Проверить сейчас (например, по кнопке). */
    fun recheck() = schedule(0, force = true)

    @Synchronized
    private fun schedule(delaySec: Long = 3, force: Boolean = false) {
        if (!enabled()) { _state.value = State.UNKNOWN; return }
        val now = System.currentTimeMillis()
        if (!force && lastNetwork == probedNetwork && now - probedAt < MIN_INTERVAL_MS) return
        probedNetwork = lastNetwork; probedAt = now
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
