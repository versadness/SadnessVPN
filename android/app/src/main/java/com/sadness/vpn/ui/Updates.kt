package com.sadness.vpn.ui

import android.content.Context
import android.os.Build
import com.sadness.vpn.BuildConfig
import org.json.JSONArray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Обновление из GitHub Releases. Подделку Android не поставит сам: подпись нового
 * APK обязана совпасть с подписью установленного. Дополнительно сверяется
 * SHA-256, который GitHub показывает для файла, — чтобы не ставить битую загрузку.
 */
object Updates {
    private const val API = "https://api.github.com/repos/versadness/SadnessVPN/releases?per_page=30"

    /** Суффикс файла для архитектуры телефона; null — для неё APK не выпускается. */
    private fun abiSuffix(): String? = when (Build.SUPPORTED_ABIS.firstOrNull()) {
        "arm64-v8a" -> "arm64"
        "armeabi-v7a" -> "armv7"
        else -> null
    }

    fun newer(candidate: String, current: String): Boolean {
        fun parts(v: String) = v.substringBefore('-').split('.').map { it.toIntOrNull() ?: 0 }
        val a = parts(candidate); val b = parts(current)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }; val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    /** Самый новый Android-выпуск новее установленного или null. */
    fun latest(): UpdateInfo? {
        val suffix = abiSuffix() ?: return null
        val connection = (URL(API).openConnection() as HttpURLConnection).apply {
            connectTimeout = 10_000; readTimeout = 15_000
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", "SadnessVPN-Android/${BuildConfig.VERSION_NAME}")
        }
        val body = try { connection.inputStream.bufferedReader().readText() } finally { connection.disconnect() }
        return parse(body, suffix, BuildConfig.VERSION_NAME.removeSuffix("-debug"))
    }

    /** Разбор ответа GitHub API: самый новый android-v* новее current с APK для suffix. */
    fun parse(body: String, suffix: String, current: String): UpdateInfo? {
        val releases = JSONArray(body)
        var best: UpdateInfo? = null
        for (i in 0 until releases.length()) {
            val release = releases.getJSONObject(i)
            val tag = release.optString("tag_name")
            if (!tag.startsWith("android-v") || release.optBoolean("draft")) continue
            val version = tag.removePrefix("android-v").substringBefore("-")
            if (!newer(version, current)) continue
            if (best != null && !newer(version, best.version)) continue
            val assets = release.optJSONArray("assets") ?: continue
            val asset = (0 until assets.length()).map { assets.getJSONObject(it) }
                .firstOrNull { it.optString("name").endsWith("-$suffix.apk") } ?: continue
            best = UpdateInfo(
                version = version,
                notes = notes(release.optString("body")),
                url = asset.optString("browser_download_url"),
                size = asset.optLong("size"),
                sha256 = asset.optString("digest").removePrefix("sha256:"),
                name = asset.optString("name"),
            )
        }
        return best
    }

    /** Пункты из раздела «Что нового» описания выпуска — без markdown. */
    private fun notes(body: String): List<String> = body.lines()
        .dropWhile { !it.startsWith("## Что нового") && !it.startsWith("## What") }.drop(1)
        .takeWhile { !it.startsWith("## ") }
        .filter { it.trimStart().startsWith("- ") }
        .map { line -> line.trim().removePrefix("- ").replace(Regex("\\*\\*([^*]+)\\*\\*"), "$1").replace("`", "").substringBefore(". ").take(90) }
        .take(6)

    fun download(context: Context, info: UpdateInfo, onProgress: (Int) -> Unit): File {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val file = File(dir, info.name.replace(Regex("[^A-Za-z0-9._-]"), "_"))
        val connection = (URL(info.url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000; readTimeout = 30_000; instanceFollowRedirects = true
            setRequestProperty("User-Agent", "SadnessVPN-Android/${BuildConfig.VERSION_NAME}")
        }
        val digest = MessageDigest.getInstance("SHA-256")
        try {
            connection.inputStream.use { input ->
                file.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var done = 0L
                    var last = -1
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n); digest.update(buffer, 0, n)
                        done += n
                        val percent = if (info.size > 0) (done * 100 / info.size).toInt() else 0
                        if (percent != last) { last = percent; onProgress(percent) }
                    }
                }
            }
        } finally {
            connection.disconnect()
        }
        val actual = digest.digest().joinToString("") { "%02x".format(it) }
        if (info.sha256.isNotEmpty() && !actual.equals(info.sha256, ignoreCase = true)) {
            file.delete()
            throw IllegalStateException(L.t("Файл обновления повреждён при загрузке. Попробуйте ещё раз."))
        }
        return file
    }
}
