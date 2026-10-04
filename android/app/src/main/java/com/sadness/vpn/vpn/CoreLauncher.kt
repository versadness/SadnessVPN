package com.sadness.vpn.vpn

/** JNI-обёртка над launcher.c: запуск ядра с открытым туннелем VPN. */
object CoreLauncher {
    init {
        System.loadLibrary("svpnlauncher")
    }

    /** PID процесса или отрицательный errno. tunFd < 0 — без туннеля. */
    fun start(exe: String, args: List<String>, tunFd: Int, logPath: String): Int =
        nativeStart(exe, args.toTypedArray(), tunFd, logPath)

    fun alive(pid: Int): Boolean = pid > 0 && nativeAlive(pid) == 1

    fun stop(pid: Int, timeoutMs: Int = 3000) {
        if (pid > 0) nativeStop(pid, timeoutMs)
    }

    @JvmStatic private external fun nativeStart(exe: String, args: Array<String>, tunFd: Int, logPath: String): Int
    @JvmStatic private external fun nativeAlive(pid: Int): Int
    @JvmStatic private external fun nativeStop(pid: Int, timeoutMs: Int)
}
