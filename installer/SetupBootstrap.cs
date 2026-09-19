using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
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

    [DllImport("msi.dll", CharSet = CharSet.Unicode)]
    private static extern int MsiQueryProductState(string product);

    [STAThread]
    private static int Main(string[] args) {
        string temporaryDirectory = Path.Combine(Path.GetTempPath(), "SadnessVPN-Setup-" + Guid.NewGuid().ToString("N"));
        string extractedMsi = Path.Combine(temporaryDirectory, MsiName);
        try {
            Directory.CreateDirectory(temporaryDirectory);
            ExtractAndVerify(Application.ExecutablePath, extractedMsi);
            if (args.Length == 1 && args[0] == "--verify") return 0;

            string arguments = "/i \"" + extractedMsi + "\"";
            if (MsiQueryProductState(ProductCode) >= 1)
                arguments += " REINSTALL=ALL REINSTALLMODE=vomus";
            ProcessStartInfo start = new ProcessStartInfo("msiexec.exe", arguments);
            start.UseShellExecute = true;
            start.Verb = "runas";
            Process installer = Process.Start(start);
            installer.WaitForExit();
            return installer.ExitCode;
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
        finally {
            try { Directory.Delete(temporaryDirectory, true); } catch { }
        }
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
