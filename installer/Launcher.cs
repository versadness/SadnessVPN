using System;
using System.IO;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;
using System.Windows.Forms;
using System.Reflection;

[assembly: AssemblyTitle("Sadness VPN Launcher")]
[assembly: AssemblyProduct("Sadness VPN")]
[assembly: AssemblyCompany("Sadness VPN")]
[assembly: AssemblyVersion("2.0.24.0")]
[assembly: AssemblyFileVersion("2.0.24.0")]

internal static class Launcher {
    static string root = AppDomain.CurrentDomain.BaseDirectory;
    static string logDir;
    static bool quiet;
    static void Log(string text) {
        try { File.AppendAllText(Path.Combine(logDir, "launcher.log"), DateTime.Now.ToString("s") + " " + text + Environment.NewLine); }
        catch { /* The error dialog still identifies a logging failure. */ }
    }
    static void InitLog() {
        foreach (string dir in new [] {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SadnessVPN", "data", "diagnostics"),
            Path.Combine(Path.GetTempPath(), "SadnessVPN-diagnostics")}) {
            try {
                Directory.CreateDirectory(dir);
                string file = Path.Combine(dir, "launcher.log");
                if (File.Exists(file) && new FileInfo(file).Length > 2097152) {
                    File.Copy(file, file + ".previous", true);
                    File.WriteAllText(file, "");
                }
                File.AppendAllText(file, DateTime.Now.ToString("s") + " Launcher " + Assembly.GetExecutingAssembly().GetName().Version.ToString(3) + " started\r\n");
                logDir = dir; return;
            } catch { }
        }
        throw new IOException("Не удалось создать журнал запуска ни в профиле пользователя, ни в TEMP.");
    }
    static int Fail(string reason) {
        Log("FAILED: " + reason);
        if (!quiet) {
            string message = reason + "\n\nЖурналы: " + (logDir ?? "недоступны") +
                "\n\nПовторный запуск установщика позволяет восстановить компоненты. Защиту Windows отключать не нужно.";
            if (logDir != null && MessageBox.Show(message + "\n\nОткрыть папку журналов?", "Sadness VPN — диагностика", MessageBoxButtons.YesNo, MessageBoxIcon.Error) == DialogResult.Yes)
                Process.Start(new ProcessStartInfo(logDir) { UseShellExecute = true });
            else if (logDir == null) MessageBox.Show(message, "Sadness VPN", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        return 1;
    }
    static string[] required = {
        "runtime/SadnessVPN.exe", "runtime/_internal/python311.dll", "runtime/_internal/base_library.zip",
        "runtime/_internal/ui/templates/index.html",
        "runtime/_internal/bin/sing-box.exe", "runtime/_internal/bin/mihomo.exe",
        "runtime/_internal/bin/wintun.dll",
        "electron/Sadness VPN.exe", "electron/resources/app.asar"
    };
    static void CheckFiles(bool full) {
        foreach (string relative in required) {
            string file = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
            if (!File.Exists(file) || new FileInfo(file).Length == 0)
                throw new FileNotFoundException("Отсутствует или пуст компонент: " + relative + ". Он не установлен, повреждён или был удалён защитой.");
        }
        if (!full) return;
        int count = 0;
        foreach (string line in File.ReadAllLines(Path.Combine(root, "files.sha256"))) {
            if (String.IsNullOrWhiteSpace(line)) continue;
            if (line.Length < 67 || line.Substring(64, 2) != "  ") throw new IOException("Повреждён files.sha256");
            string relative = line.Substring(66);
            string file = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!file.StartsWith(Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase)) throw new IOException("Неверный путь в files.sha256");
            if (!File.Exists(file)) throw new FileNotFoundException("Не найден компонент: " + relative);
            using (var hash = SHA256.Create()) using (var stream = File.OpenRead(file)) {
                string actual = BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                if (actual != line.Substring(0, 64)) throw new IOException("Повреждён компонент: " + relative);
            }
            count++;
        }
        if (count < required.Length) throw new IOException("Неполный манифест компонентов");
        Log("Full integrity check passed: " + count + " files");
    }
    [STAThread]
    static int Main(string[] args) {
        quiet = Array.IndexOf(args, "--quiet") >= 0;
        try {
            InitLog();
            Log("OS=" + Environment.OSVersion + "; 64-bit OS=" + Environment.Is64BitOperatingSystem + "; CLR=" + Environment.Version);
            if (!Environment.Is64BitOperatingSystem) return Fail("Нужна Windows 10/11 x64.");
            bool diagnostics = Array.IndexOf(args, "--diagnostics") >= 0;
            bool check = Array.IndexOf(args, "--check") >= 0;
            CheckFiles(diagnostics || check);
            if (diagnostics || check) {
                if (diagnostics && !quiet) {
                    MessageBox.Show("Проверка компонентов пройдена. Результат записан в launcher.log.\n\n" + logDir, "Sadness VPN");
                    Process.Start(new ProcessStartInfo(logDir) { UseShellExecute = true });
                }
                return 0;
            }
            string eventName = "Local\\SadnessVPN.Startup." + Guid.NewGuid().ToString("N");
            var security = new EventWaitHandleSecurity();
            security.AddAccessRule(new EventWaitHandleAccessRule(WindowsIdentity.GetCurrent().User,
                EventWaitHandleRights.FullControl, AccessControlType.Allow));
            security.AddAccessRule(new EventWaitHandleAccessRule(new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null),
                EventWaitHandleRights.Modify | EventWaitHandleRights.Synchronize, AccessControlType.Allow));
            bool created;
            using (var ready = new EventWaitHandle(false, EventResetMode.ManualReset, eventName, out created, security)) {
                // Оболочка Electron поднимает окно и сама запускает Python-бэкенд
                // (runtime/SadnessVPN.exe --headless). Готовность подтверждает она же.
                var info = new ProcessStartInfo(Path.Combine(root, "electron", "Sadness VPN.exe")) {
                    WorkingDirectory = Path.Combine(root, "electron"), UseShellExecute = true, Verb = "runas",
                    Arguments = "--startup-event=" + eventName + (Array.IndexOf(args, "--autostart") >= 0 ? " --autostart" : " --show")
                };
                using (var child = Process.Start(info)) {
                    if (child == null) return Fail("Windows не вернула процесс приложения.");
                    Log("Electron shell started; PID=" + child.Id);
                    for (int i = 0; i < 240; i++) {
                        if (ready.WaitOne(250)) { Log("UI ready / existing instance activated"); return 0; }
                        if (child.HasExited) {
                            if (ready.WaitOne(0)) { Log("Existing instance activated"); return 0; }
                            return Fail("Приложение завершилось до готовности интерфейса. Код: 0x" + child.ExitCode.ToString("X8") +
                                ". Подробности: startup-python.log и application.log.");
                        }
                    }
                    return Fail("Интерфейс не подтвердил готовность за 60 секунд. Процесс не завершён принудительно. Проверьте журналы и окно приложения.");
                }
            }
        } catch (System.ComponentModel.Win32Exception ex) {
            if (ex.NativeErrorCode == 1223) { Log("Administrator prompt cancelled by user"); return 1223; }
            return Fail("Windows не смогла запустить компонент (" + ex.NativeErrorCode + "): " + ex.Message);
        } catch (Exception ex) { return Fail(ex.GetType().Name + ": " + ex.Message); }
    }
}
