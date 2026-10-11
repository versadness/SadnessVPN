package com.sadness.vpn.core

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.security.SecureRandom
import java.util.zip.GZIPInputStream
import java.util.zip.InflaterInputStream

/** Ошибка подписки: текст показывается пользователю, без адресов и тел ответа. */
class SubscriptionException(message: String, val notModified: Boolean = false) : Exception(message)

/** Перенос engine/subscriptions.py + fetch_subscription из engine/config.py. */
object Subscription {
    const val APP_NAME = "Sadness VPN"
    const val MAX_BYTES = 8 * 1024 * 1024
    const val HWID_PREFIX = "svpn-"
    private val HWID_FORMAT = Regex("[a-zA-Z0-9=-]{10,64}")

    /** Непрозрачный 128-битный ID без данных об устройстве — как на десктопе. */
    fun generateHwid(random: SecureRandom = SecureRandom()): String {
        val bytes = ByteArray(16).also(random::nextBytes)
        return HWID_PREFIX + bytes.joinToString("") { "%02x".format(it) }
    }

    /** model — производитель и модель («samsung SM-S928B»): по ней провайдер показывает устройство в списке. */
    data class ClientInfo(val version: String, val osVersion: String, val arch: String, val model: String = "Phone")

    /** «Xiaomi» + «2311DRK48G» → «Xiaomi 2311DRK48G»; модель уже с производителем не дублируется. */
    fun deviceModel(manufacturer: String, model: String): String {
        val m = model.trim(); val brand = manufacturer.trim()
        val full = if (brand.isEmpty() || m.lowercase().startsWith(brand.lowercase())) m else "$brand $m"
        // В заголовок HTTP — только печатаемый ASCII.
        return full.filter { it.code in 32..126 }.trim().take(64).ifEmpty { "Phone" }
    }

    fun headers(client: ClientInfo, hwid: String): Map<String, String> {
        val result = linkedMapOf(
            "User-Agent" to "SadnessVPN/v${client.version} platform/android platform-version/${client.osVersion} arch/${client.arch}",
            "Accept" to "*/*",
            "X-Client-Name" to APP_NAME,
            "X-Client-Version" to client.version,
            "X-Platform" to "android",
            "X-Platform-Version" to client.osVersion,
            "X-Device-OS" to "Android",
            "X-Ver-OS" to client.osVersion,
            // Модель — как у других клиентов (INCY, Happ): провайдер видит в списке
            // устройств «samsung SM-S928B (16)», а не безликое «Phone».
            "X-Device-Model" to client.model,
        )
        if (hwid.isNotEmpty()) {
            result["HWID"] = hwid; result["X-HWID"] = hwid; result["Device-Id"] = hwid
        }
        return result
    }

    fun parseMetadata(headers: Map<String, String>, now: Long = System.currentTimeMillis() / 1000): MutableMap<String, Any?> {
        val h = headers.mapKeys { it.key.lowercase() }
        val result: MutableMap<String, Any?> = linkedMapOf("updated_at" to now)
        var title = h["profile-title"].orEmpty()
        if (title.lowercase().startsWith("base64:")) {
            title = runCatching { String(lenientBase64(title.substring(7)), Charsets.UTF_8) }.getOrDefault("")
        }
        title = printable(title).trim().take(160)
        if (title.isNotEmpty()) result["provider_name"] = title
        for (part in h["subscription-userinfo"].orEmpty().split(';')) {
            val key = part.substringBefore('=', "").trim().lowercase()
            val value = part.substringAfter('=', "").trim()
            if (key in setOf("upload", "download", "total", "expire") && Regex("\\d{1,16}").matches(value)) {
                val number = value.toLong()
                if (key != "expire" || number <= 253402300799L) result[key] = number
            }
        }
        result["hwid_active"] = h["x-hwid-active"].orEmpty().lowercase() == "true"
        return result
    }

    fun checkDeviceHeaders(headers: Map<String, String>) {
        val h = headers.map { it.key.lowercase() to it.value.lowercase() }.toMap()
        if (h["x-hwid-max-devices-reached"] == "true" || h["x-hwid-limit"] == "true") {
            throw SubscriptionException("Достигнут лимит устройств подписки. Удалите ненужное устройство в боте провайдера; сбрасывать HWID не нужно.")
        }
        if (h["x-hwid-not-supported"] == "true") {
            throw SubscriptionException("Провайдер не принял HWID клиента. Проверьте поддержку Sadness VPN у провайдера.")
        }
    }

    data class Download(val body: ByteArray, val metadata: MutableMap<String, Any?>)

    fun download(url: String, client: ClientInfo, hwid: String): Download {
        if (hwid.isNotEmpty() && !HWID_FORMAT.matches(hwid)) {
            throw SubscriptionException("Сохранённый HWID несовместим с форматом подписок. В настройках можно создать новый ID; это зарегистрирует новое устройство у провайдера.")
        }
        val connection = try {
            URL(url).openConnection() as HttpURLConnection
        } catch (_: Exception) {
            throw SubscriptionException("Ссылка подписки некорректна. Нужен адрес вида https://…")
        }
        try {
            connection.connectTimeout = 25_000
            connection.readTimeout = 25_000
            connection.instanceFollowRedirects = true
            headers(client, hwid).forEach { (k, v) -> connection.setRequestProperty(k, v) }
            val code = connection.responseCode
            val responseHeaders = connection.headerFields.filterKeys { it != null }.mapValues { it.value.lastOrNull().orEmpty() }
            if (code == 304) throw SubscriptionException("Подписка не изменилась с прошлого обновления.", notModified = true)
            checkDeviceHeaders(responseHeaders)
            if (code !in 200..299) throw SubscriptionException("Провайдер вернул HTTP $code. Проверьте доступность и срок действия подписки.")
            val metadata = parseMetadata(responseHeaders)
            val body = readLimited(connection.inputStream)
            return Download(decompress(body, connection.contentEncoding.orEmpty()), metadata)
        } catch (e: SubscriptionException) {
            throw e
        } catch (_: SocketTimeoutException) {
            throw SubscriptionException("Сервер подписки не ответил за 25 секунд. Проверьте сеть и повторите обновление.")
        } catch (_: java.io.IOException) {
            throw SubscriptionException("Не удалось загрузить подписку: ошибка сети, DNS или TLS. Проверьте доступность сервиса.")
        } finally {
            connection.disconnect()
        }
    }

    private fun readLimited(stream: InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        stream.use {
            while (true) {
                val n = it.read(buffer)
                if (n < 0) break
                out.write(buffer, 0, n)
                if (out.size() > MAX_BYTES) throw SubscriptionException("Подписка превышает допустимый размер 8 МБ.")
            }
        }
        return out.toByteArray()
    }

    /** Некоторые панели сжимают ответ, даже если клиент не просил. */
    fun decompress(body: ByteArray, encoding: String): ByteArray {
        val enc = encoding.lowercase().trim()
        val gzip = body.size >= 2 && body[0] == 0x1F.toByte() && body[1] == 0x8B.toByte()
        val stream = when {
            enc == "gzip" || gzip -> GZIPInputStream(body.inputStream())
            enc == "deflate" -> InflaterInputStream(body.inputStream())
            else -> return body
        }
        return try {
            readLimited(stream)
        } catch (e: SubscriptionException) {
            throw e
        } catch (_: java.io.IOException) {
            throw SubscriptionException("Ответ провайдера повреждён: не удалось распаковать сжатые данные.")
        }
    }

    fun decode(body: ByteArray): String {
        var raw = String(body, Charsets.UTF_8).removePrefix("﻿").trim()
        val compact = raw.filterNot { it.isWhitespace() }
        if (compact.isNotEmpty() && Regex("[A-Za-z0-9+/=_-]+").matches(compact)) {
            runCatching { String(lenientBase64(compact), Charsets.UTF_8).removePrefix("﻿").trim() }
                .getOrNull()?.takeIf { it.isNotEmpty() && '�' !in it }?.let { raw = it }
        }
        if (raw.lowercase().startsWith("<!doctype html") || raw.lowercase().startsWith("<html")) {
            throw SubscriptionException("Вместо подписки получена веб-страница. Нужна ссылка для импорта в VPN-клиент, а не страница личного кабинета.")
        }
        return raw
    }

    fun noServersError(raw: String): SubscriptionException =
        if (Regex("(?m)^proxies:\\s*\\[\\]").containsMatchIn(raw)) {
            SubscriptionException("Провайдер вернул пустой список серверов (proxies: []). Проверьте подписку и поддержку клиента у провайдера; текущие серверы сохранены.")
        } else {
            SubscriptionException("В ответе нет поддерживаемых серверов. Нужен список ссылок VLESS/SS/Trojan/Hysteria2 либо Clash YAML. Текущие серверы сохранены.")
        }

    data class Result(val servers: List<Server>, val metadata: Map<String, Any?>)

    /** Разобрать уже скачанный текст подписки. */
    fun parse(raw: String, metadata: MutableMap<String, Any?>): Result {
        var servers: MutableList<Server> = mutableListOf()
        val rejected = mutableListOf<Map<String, String>>()
        var received = 0
        if (Links.looksLikeLinks(raw)) {
            val parsed = Links.parseShareLinks(raw)
            servers = parsed.servers; rejected += parsed.rejected; received = parsed.received
        } else if ("proxies:" in raw || raw.trimStart().startsWith("{")) {
            servers = Transports.parseClashNodes(raw, rejected)
            received = servers.size + rejected.size
        }
        metadata["received"] = received
        metadata["accepted"] = servers.size
        metadata["rejected"] = rejected.take(50)
        if (servers.isEmpty()) {
            if (rejected.isEmpty()) throw noServersError(raw)
            throw SubscriptionException("Ни один сервер подписки не поддерживается: " +
                rejected.take(3).joinToString("; ") { "${it["name"]} — ${it["reason"]}" } + ". Текущие серверы сохранены.")
        }
        return Result(servers, metadata)
    }

    fun fetch(url: String, client: ClientInfo, hwid: String): Result {
        val download = download(url, client, hwid)
        return parse(decode(download.body), download.metadata)
    }
}
