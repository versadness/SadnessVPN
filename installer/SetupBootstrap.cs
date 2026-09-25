using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: AssemblyTitle("Sadness VPN Setup")]
[assembly: AssemblyProduct("Sadness VPN")]
[assembly: AssemblyCompany("Sadness VPN")]
[assembly: AssemblyVersion("__APP_VERSION__.0")]
[assembly: AssemblyFileVersion("__APP_VERSION__.0")]

internal static class SetupBootstrap {
    private const string ProductCode = "__PRODUCT_CODE__";
    private const string MsiName = "__MSI_NAME__";
    private const string ExpectedSha256 = "__MSI_SHA256__";
    private static readonly byte[] Magic = Encoding.ASCII.GetBytes("SADNESSVPNMSI01");

    // Каталог и правило именования те же, что у встроенного апдейтера
    // (installer/updater_main.py, installer/msi_source.py). Расходиться им нельзя:
    // Windows Installer предъявляет к обоим одинаковые требования.
    private const string StagingRoot = "SadnessVPN-Update";
    private const string ProtectedDacl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)";
    private const string ElevatedUpgradeFlag = "--elevated-upgrade";

    [DllImport("msi.dll", CharSet = CharSet.Unicode)]
    private static extern int MsiQueryProductState(string product);

    [DllImport("msi.dll", CharSet = CharSet.Unicode)]
    private static extern int MsiSourceListGetInfoW(string product, string patchCode,
                                                    int context, int options,
                                                    string property, StringBuilder value,
                                                    ref int size);

    [STAThread]
    private static int Main(string[] args) {
        try {
            bool verifyOnly = args.Length == 1 && args[0] == "--verify";
            bool elevatedUpgrade = args.Length == 1 && args[0] == ElevatedUpgradeFlag;
            // Обновление поверх установленного продукта Windows Installer проводит
            // через secure repair. Тот берёт пакет только из каталога, доступного на
            // запись исключительно администраторам, и только под именем, записанным
            // в SourceList\PackageName при первой установке. Распаковка в %TEMP% под
            // собственным именем не выполняет ни одного условия — установка падала с 1603.
            bool upgrade = elevatedUpgrade || (!verifyOnly && MsiQueryProductState(ProductCode) >= 1);

            if (upgrade && !elevatedUpgrade && !IsElevated())
                return RelaunchElevated();

            return upgrade ? RunUpgrade() : RunPlainInstall(verifyOnly);
        }
        catch (Win32Exception error) {
            if (error.NativeErrorCode == 1223) return 1223;
            ShowError(error.Message);
            return 1;
        }
        catch (Exception error) {
            ShowError(error.Message);
            return 1;
        }
    }

    // Чистая установка и --verify: прежнее поведение, менять его незачем.
    private static int RunPlainInstall(bool verifyOnly) {
        string directory = Path.Combine(Path.GetTempPath(), "SadnessVPN-Setup-" + Guid.NewGuid().ToString("N"));
        try {
            Directory.CreateDirectory(directory);
            string staged = Path.Combine(directory, MsiName);
            ExtractAndVerify(Application.ExecutablePath, staged);
            if (verifyOnly) return 0;
            return RunInstaller("/i \"" + staged + "\"", true);
        }
        finally {
            try { Directory.Delete(directory, true); } catch { }
        }
    }

    private static int RunUpgrade() {
        string directory = CreateProtectedDirectory();
        try {
            string staged = Path.Combine(directory, RegisteredPackageName());
            ExtractAndVerify(Application.ExecutablePath, staged);
            return RunInstaller("/i \"" + staged + "\" REINSTALL=ALL REINSTALLMODE=vomus", false);
        }
        finally {
            try { Directory.Delete(directory, true); } catch { }
        }
    }

    private static int RunInstaller(string arguments, bool elevate) {
        ProcessStartInfo start = new ProcessStartInfo("msiexec.exe", arguments);
        start.UseShellExecute = true;
        if (elevate) start.Verb = "runas";
        Process installer = Process.Start(start);
        installer.WaitForExit();
        return installer.ExitCode;
    }

    private static bool IsElevated() {
        using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
            return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
    }

    private static int RelaunchElevated() {
        ProcessStartInfo start = new ProcessStartInfo(Application.ExecutablePath, ElevatedUpgradeFlag);
        start.UseShellExecute = true;
        start.Verb = "runas";
        Process elevated = Process.Start(start);
        elevated.WaitForExit();
        return elevated.ExitCode;
    }

    private static string CreateProtectedDirectory() {
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), StagingRoot);
        string directory = Path.Combine(root, "setup-" + Guid.NewGuid().ToString("N"));
        DirectorySecurity security = new DirectorySecurity();
        security.SetSecurityDescriptorSddlForm(ProtectedDacl, AccessControlSections.Access);
        if (!Directory.Exists(root)) Directory.CreateDirectory(root, security);
        Directory.CreateDirectory(directory, security);
        DirectoryInfo info = new DirectoryInfo(directory);
        if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Небезопасный каталог подготовки пакета.");
        return directory;
    }

    // Имя берётся только из локальной регистрации Windows Installer, поэтому
    // проверяется так же строго, как в installer/msi_source.py.
    private static string RegisteredPackageName() {
        StringBuilder value = new StringBuilder(1024);
        int size = value.Capacity;
        const int MSIINSTALLCONTEXT_MACHINE = 4;
        int code = MsiSourceListGetInfoW(ProductCode, null, MSIINSTALLCONTEXT_MACHINE, 0, "PackageName", value, ref size);
        if (code != 0) return MsiName;
        string name = value.ToString();
        if (name.Contains("..") || !Regex.IsMatch(name, @"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,190}\.msi$", RegexOptions.IgnoreCase))
            return MsiName;
        return name;
    }

    private static void ExtractAndVerify(string executable, string destination) {
        using (FileStream source = File.OpenRead(executable)) {
            long trailerSize = Magic.Length + sizeof(long);
            if (source.Length <= trailerSize) throw new InvalidDataException("В установщике отсутствует пакет MSI.");
            source.Seek(-trailerSize, SeekOrigin.End);
            byte[] marker = ReadExact(source, Magic.Length);
            if (!Equal(marker, Magic)) throw new InvalidDataException("Повреждена структура установщика.");
            long payloadLength = BitConverter.ToInt64(ReadExact(source, sizeof(long)), 0);
            long payloadStart = source.Length - trailerSize - payloadLength;
            if (payloadLength <= 0 || payloadStart < 0) throw new InvalidDataException("Некорректный размер пакета MSI.");
            source.Position = payloadStart;
            using (FileStream target = File.Create(destination)) {
                byte[] buffer = new byte[1024 * 1024];
                long remaining = payloadLength;
                while (remaining > 0) {
                    int read = source.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                    if (read <= 0) throw new EndOfStreamException("Пакет MSI прочитан не полностью.");
                    target.Write(buffer, 0, read);
                    remaining -= read;
                }
            }
        }
        using (SHA256 sha = SHA256.Create())
        using (FileStream file = File.OpenRead(destination)) {
            string actual = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
            if (actual != ExpectedSha256) throw new InvalidDataException("Контрольная сумма встроенного MSI не совпала.");
        }
    }

    private static byte[] ReadExact(Stream stream, int count) {
        byte[] result = new byte[count];
        int offset = 0;
        while (offset < count) {
            int read = stream.Read(result, offset, count - offset);
            if (read <= 0) throw new EndOfStreamException();
            offset += read;
        }
        return result;
    }

    private static bool Equal(byte[] left, byte[] right) {
        if (left.Length != right.Length) return false;
        for (int i = 0; i < left.Length; i++) if (left[i] != right[i]) return false;
        return true;
    }

    private static void ShowError(string message) {
        MessageBox.Show("Не удалось запустить установку Sadness VPN.\n\n" + message,
                        "Sadness VPN Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}
