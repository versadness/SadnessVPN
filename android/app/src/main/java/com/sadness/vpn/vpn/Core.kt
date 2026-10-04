package com.sadness.vpn.vpn

import android.content.Context
import com.sadness.vpn.core.Failover
import com.sadness.vpn.core.Json
import com.sadness.vpn.core.MihomoConfig
import com.sadness.vpn.core.Server
import java.io.File
import java.net.ServerSocket
import java.security.SecureRandom

/** Запущенное ядро Mihomo: процесс, API и имена серверов в нём. */
class Core private constructor(
    val pid: Int,
    val api: ClashApi,
    val live: Map<String, Server>,
    /** Есть ли у выбранного сервера запасные (группа backup в ядре). */
    val hasBackup: Boolean,
    private val log: File,
    /** Внутренний вход для проверки соединения (только при туннеле). */
    val check: MihomoConfig.CheckProxy? = null,
    val autoBest: Boolean = false,
) {
    fun alive() = CoreLauncher.alive(pid)

    fun stop() = CoreLauncher.stop(pid)

    /** Последние строки журнала ядра — для понятной ошибки, без секретов конфигурации. */
    fun tail(lines: Int = 12): String = Core.tail(log, lines)

    /** Текст последней ошибки ядра (уровень error/fatal) или пустая строка. */
    fun lastError(): String = errorMessage(tail(30)).orEmpty()

    companion object {
        /**
         * Запустить ядро. tunFd < 0 — режим проверки серверов без туннеля.
         * Бросает IllegalStateException с понятной причиной.
         */
        fun newCheckProxy() = MihomoConfig.CheckProxy(freePort(), "check",
            ByteArray(16).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) })

        /** Наборы правил из assets → rules/ рядом с конфигом ядра (если изменились). */
        private fun copyRules(context: Context, dir: File) {
            val target = File(dir, "rules").apply { mkdirs() }
            for (name in MihomoConfig.RULE_FILES) {
                val bytes = runCatching { context.assets.open("rules/$name.mrs").use { it.readBytes() } }.getOrNull() ?: continue
                val file = File(target, "$name.mrs")
                if (!file.isFile || file.length() != bytes.size.toLong()) file.writeBytes(bytes)
            }
        }

        fun start(context: Context, selected: Server, groups: List<Failover.Group>, settings: MihomoConfig.Settings,
                  failover: Boolean, tunFd: Int, tag: String, autoBest: Boolean = false): Core {
            val dir = File(context.filesDir, "core-$tag").apply { mkdirs() }
            copyRules(context, dir)
            val log = File(context.cacheDir, "core-$tag.log")
            val port = freePort()
            val secret = ByteArray(24).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) }
            val config = MihomoConfig.assemble(MihomoConfig.proxy(selected), settings, "127.0.0.1:$port", secret, tunFd)
            val live = Failover.applyServerGroups(config, selected, groups, failover = failover, mux = settings.mux, autoBest = autoBest)
            val configFile = File(dir, "config.json")
            configFile.writeText(Json.encode(config))
            configFile.setReadable(false, false); configFile.setReadable(true, true)

            val exe = File(context.applicationInfo.nativeLibraryDir, "libmihomo.so")
            if (!exe.canExecute()) throw IllegalStateException("Ядро VPN не найдено в установке. Переустановите приложение.")
            val pid = CoreLauncher.start(exe.path, listOf("-d", dir.path, "-f", configFile.path), tunFd, log.path)
            if (pid <= 0) throw IllegalStateException("Не удалось запустить ядро VPN (код ${-pid}).")
            val api = ClashApi(port, secret)
            val deadline = System.currentTimeMillis() + 15_000
            while (System.currentTimeMillis() < deadline) {
                if (!CoreLauncher.alive(pid)) {
                    throw IllegalStateException("Ядро VPN завершилось при запуске: " + reason(tail(log, 20)))
                }
                if (api.ready()) {
                    val backup = (config["proxy-groups"] as? List<*>).orEmpty().any { (it as? Map<*, *>)?.get("name") == Failover.BACKUP_GROUP }
                    return Core(pid, api, live, backup || autoBest, log, settings.checkProxy?.takeIf { tunFd >= 0 }, autoBest)
                }
                Thread.sleep(100)
            }
            CoreLauncher.stop(pid)
            throw IllegalStateException("Ядро VPN не ответило за 15 секунд: " + reason(tail(log, 20)))
        }

        private fun freePort(): Int = ServerSocket(0).use { it.localPort }

        fun tail(log: File, lines: Int): String =
            runCatching { log.readLines().takeLast(lines).joinToString("\n") }.getOrDefault("")

        /** Причина из журнала ядра для пользователя, без адресов и ключей. */
        private fun reason(tail: String): String = errorMessage(tail)
            ?: tail.lines().lastOrNull { it.isNotBlank() }?.let(::clean) ?: "журнал пуст"

        /** Последняя строка уровня error/fatal или null. */
        fun errorMessage(tail: String): String? =
            tail.lines().lastOrNull { "level=error" in it || "level=fatal" in it || "Parse config error" in it }?.let(::clean)

        private fun clean(line: String): String {
            val msg = Regex("""msg="?([^"]+)"?""").find(line)?.groupValues?.get(1) ?: line
            return msg.replace(Regex("""\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b"""), "<адрес>").take(240)
        }
    }
}
