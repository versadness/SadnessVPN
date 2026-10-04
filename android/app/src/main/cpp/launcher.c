// Запуск ядра Mihomo с переданным ему туннелем VPN.
//
// Java/Kotlin не умеют передать дочернему процессу открытый дескриптор:
// ProcessBuilder закрывает всё, кроме stdin/stdout/stderr. Туннель же
// существует только как открытый дескриптор от VpnService. Поэтому запуск —
// здесь: fork, снять с туннеля флаг закрытия при exec, закрыть всё лишнее,
// exec ядра. Ядро остаётся отдельной программой (граница GPL сохраняется).
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void close_other_fds(int keep, int log_fd) {
    struct rlimit limit;
    long max = 4096;
    if (getrlimit(RLIMIT_NOFILE, &limit) == 0 && limit.rlim_cur != RLIM_INFINITY && limit.rlim_cur < 65536)
        max = (long) limit.rlim_cur;
    for (long fd = 3; fd < max; fd++) {
        if (fd != keep && fd != log_fd) close((int) fd);
    }
}

JNIEXPORT jint JNICALL
Java_com_sadness_vpn_vpn_CoreLauncher_nativeStart(JNIEnv *env, jclass clazz, jstring jexe,
                                                  jobjectArray jargs, jint tun_fd, jstring jlog) {
    (void) clazz;
    // Всё, что требует памяти, готовится до fork: после fork в многопоточном
    // процессе допустимы только простейшие системные вызовы.
    jsize argc = (*env)->GetArrayLength(env, jargs);
    char **argv = calloc((size_t) argc + 2, sizeof(char *));
    if (!argv) return -ENOMEM;
    const char *exe_utf = (*env)->GetStringUTFChars(env, jexe, NULL);
    char *exe = strdup(exe_utf);
    (*env)->ReleaseStringUTFChars(env, jexe, exe_utf);
    argv[0] = exe;
    for (jsize i = 0; i < argc; i++) {
        jstring item = (jstring) (*env)->GetObjectArrayElement(env, jargs, i);
        const char *utf = (*env)->GetStringUTFChars(env, item, NULL);
        argv[i + 1] = strdup(utf);
        (*env)->ReleaseStringUTFChars(env, item, utf);
        (*env)->DeleteLocalRef(env, item);
    }
    argv[argc + 1] = NULL;
    const char *log_utf = (*env)->GetStringUTFChars(env, jlog, NULL);
    int log_fd = open(log_utf, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    (*env)->ReleaseStringUTFChars(env, jlog, log_utf);
    int null_fd = open("/dev/null", O_RDONLY | O_CLOEXEC);

    pid_t pid = fork();
    if (pid == 0) {
        if (tun_fd >= 0) {
            int flags = fcntl(tun_fd, F_GETFD);
            if (flags >= 0) fcntl(tun_fd, F_SETFD, flags & ~FD_CLOEXEC);
        }
        if (null_fd >= 0) dup2(null_fd, 0);
        if (log_fd >= 0) {
            dup2(log_fd, 1);
            dup2(log_fd, 2);
        }
        close_other_fds(tun_fd, -1);
        // Ядро не должно жить дольше приложения, если то убито системой.
        signal(SIGPIPE, SIG_DFL);
        execv(exe, argv);
        _exit(127);
    }
    int saved = errno;
    if (log_fd >= 0) close(log_fd);
    if (null_fd >= 0) close(null_fd);
    for (jsize i = 0; i <= argc; i++) free(argv[i]);
    free(argv);
    return pid > 0 ? (jint) pid : -saved;
}

// 1 — работает, 0 — завершился (статус забран), -1 — ошибка.
JNIEXPORT jint JNICALL
Java_com_sadness_vpn_vpn_CoreLauncher_nativeAlive(JNIEnv *env, jclass clazz, jint pid) {
    (void) env; (void) clazz;
    int status = 0;
    pid_t result = waitpid((pid_t) pid, &status, WNOHANG);
    if (result == 0) return 1;
    return result == pid ? 0 : -1;
}

// Мягкая остановка: SIGTERM, до timeout_ms ожидания, затем SIGKILL.
JNIEXPORT void JNICALL
Java_com_sadness_vpn_vpn_CoreLauncher_nativeStop(JNIEnv *env, jclass clazz, jint pid, jint timeout_ms) {
    (void) env; (void) clazz;
    if (pid <= 0) return;
    kill((pid_t) pid, SIGTERM);
    struct timespec step = {0, 50 * 1000 * 1000};
    for (int waited = 0; waited < timeout_ms; waited += 50) {
        int status = 0;
        pid_t result = waitpid((pid_t) pid, &status, WNOHANG);
        if (result == pid || (result < 0 && errno == ECHILD)) return;
        nanosleep(&step, NULL);
    }
    kill((pid_t) pid, SIGKILL);
    int status = 0;
    waitpid((pid_t) pid, &status, 0);
}
