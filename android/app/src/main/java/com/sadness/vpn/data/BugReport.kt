package com.sadness.vpn.data

import android.content.Context
import android.os.Build
import com.sadness.vpn.BuildConfig
import com.sadness.vpn.core.Failover
import java.io.File

/**
 * Отчёт об ошибке: версия, телефон, настройки и журнал ядра — без адресов
 * серверов, ключей, ссылок подписок, HWID и паролей. Пользователь видит отчёт
 * целиком до отправки.
 */
object BugReport {
    private val IPV4 = Regex("""\b\d{1,3}(\.\d{1,3}){3}\b""")
    private val IPV6 = Regex("""\b([0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b""")
    private val UUID = Regex("""\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b""")
    private val LONG_TOKEN = Regex("""\b[A-Za-z0-9+/_-]{32,}={0,2}""")
    private val URL = Regex("""https?://\S+""")

    fun redact(text: String): String = text
        .replace(URL, "<ссылка>").replace(UUID, "<uuid>").replace(LONG_TOKEN, "<ключ>")
        .replace(IPV6, "<ipv6>").replace(IPV4) { m -> if (m.value.startsWith("198.18.") || m.value.startsWith("172.19.0.")) m.value else "x.x.x.x" }

    fun build(context: Context, state: State): String {
        val s = state.settings
        val selected = state.selected()?.second
        val server = selected?.let {
            val flag = Failover.country(it).ifEmpty { "??" }
            "${it["protocol"] ?: "vless"} · ${Failover.transport(it)} · $flag"
        } ?: "не выбран"
        val log = File(context.cacheDir, "core-vpn.log").takeIf { it.isFile }?.readLines()?.takeLast(300)?.joinToString("\n")
            ?: "журнал пуст"
        return buildString {
            appendLine("Sadness VPN ${BuildConfig.VERSION_NAME} · Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
            appendLine("Телефон: ${Build.MANUFACTURER} ${Build.MODEL} · ${Build.SUPPORTED_ABIS.firstOrNull()}")
            appendLine("Сервер: $server · подписок: ${state.groups.size}, серверов: ${state.groups.sumOf { it.servers.size }}")
            appendLine("Настройки: DNS=${s.dnsPreset} ipv6=${s.ipv6} mux=${s.mux} udp-блок=${s.blockUdp} резерв=${s.failover} лучший=${s.autoBest}")
            appendLine("Маршруты: РФ-напрямую=${s.ruDirect} реклама=${s.adblock} сервисы=${s.servicesVpn} правил=${s.rules.size} приложения=${s.appsMode.key}(${s.apps.size})")
            appendLine("Прокси: socks=${s.socksEnabled} lan=${s.socksLan} wifi=${s.shareWifi} gemini=${s.geminiDns}")
            state.groups.filter { it.error.isNotEmpty() }.forEach { appendLine("Ошибка подписки «${it.name}»: ${it.error}") }
            appendLine()
            appendLine("── Журнал ядра (последние 300 строк) ──")
            append(redact(log))
        }
    }
}
