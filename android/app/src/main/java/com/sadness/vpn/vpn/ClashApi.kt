package com.sadness.vpn.vpn

import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Клиент API управления Mihomo на 127.0.0.1 с секретом. */
class ClashApi(private val port: Int, private val secret: String) {
    private fun open(path: String, method: String = "GET", timeoutMs: Int = 5000): HttpURLConnection =
        (URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            setRequestProperty("Authorization", "Bearer $secret")
        }

    private fun request(path: String, method: String = "GET", body: String? = null, timeoutMs: Int = 5000): Pair<Int, String> {
        val connection = open(path, method, timeoutMs)
        try {
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = connection.responseCode
            val text = (if (code < 400) connection.inputStream else connection.errorStream)?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
            return code to text
        } finally {
            connection.disconnect()
        }
    }

    fun ready(): Boolean = runCatching { request("/version", timeoutMs = 1000).first == 200 }.getOrDefault(false)

    /** Выбрать сервер в группе manual — смена на лету без перезапуска туннеля. */
    fun select(group: String, name: String): Boolean =
        runCatching { request("/proxies/${enc(group)}", "PUT", JSONObject().put("name", name).toString()).first in 200..299 }.getOrDefault(false)

    /** Оборвать старые соединения, чтобы приложения переподключились через новый сервер. */
    fun closeConnections() {
        runCatching { request("/connections", "DELETE") }
    }

    /** Задержка через сервер в мс или null, если сервер не ответил. */
    fun delay(name: String, url: String, timeoutMs: Int = 5000): Int? = runCatching {
        val (code, text) = request("/proxies/${enc(name)}/delay?timeout=$timeoutMs&url=${enc(url)}", timeoutMs = timeoutMs + 2000)
        if (code == 200) JSONObject(text).optInt("delay", -1).takeIf { it > 0 } else null
    }.getOrNull()

    /** Текущий выбор группы (поле now). */
    fun now(group: String): String? = runCatching {
        val (code, text) = request("/proxies/${enc(group)}")
        if (code == 200) JSONObject(text).optString("now").ifEmpty { null } else null
    }.getOrNull()

    /** Принудительная перепроверка группы (fallback/url-test). */
    fun recheck(group: String, url: String) {
        runCatching { request("/group/${enc(group)}/delay?timeout=5000&url=${enc(url)}", timeoutMs = 8000) }
    }

    /** Поток скорости: вызывает onSample(up, down) раз в секунду, пока не прерван. */
    fun streamTraffic(onSample: (Long, Long) -> Unit) {
        val connection = open("/traffic", timeoutMs = 10_000)
        try {
            connection.inputStream.bufferedReader().use { reader ->
                while (!Thread.currentThread().isInterrupted) {
                    val line = reader.readLine() ?: break
                    if (line.isBlank()) continue
                    val json = JSONObject(line)
                    onSample(json.optLong("up"), json.optLong("down"))
                }
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun enc(value: String) = URLEncoder.encode(value, "UTF-8").replace("+", "%20")
}
