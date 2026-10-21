// Peek & Grep Portable launcher (C# 5, .NET Framework 4.x, compiled with the csc.exe that ships with Windows).
//
// Plain build: sits inside the PeekGrep folder and starts runtime\pythonw.exe app\desktop_app.py.
// Self-extracting build: carries the folder as an embedded zip. On the first start (or when the
// embedded version is newer) it unpacks runtime\ and app\ into a "PeekGrep" folder next to itself,
// keeps data\ as it is, and then starts the app.

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Peek & Grep Portable")]
[assembly: AssemblyProduct("Peek & Grep Portable")]
[assembly: AssemblyDescription("Folder-scoped desktop search with Quick Look")]
[assembly: AssemblyVersion("3.0.0.0")]
[assembly: AssemblyFileVersion("3.0.0.0")]

static class Program
{
    const string Title = "Peek & Grep";
    const string PayloadName = "payload.zip";
    const string VersionName = "payload.version";

    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string version = ReadResourceText(VersionName);
        string home;

        if (version == null)
        {
            // Plain launcher: inside the folder, or next to it
            home = Directory.Exists(Path.Combine(exeDir, "runtime")) ? exeDir : Path.Combine(exeDir, "PeekGrep");
        }
        else
        {
            home = Path.Combine(exeDir, "PeekGrep");
            if (!IsCurrent(home, version) && !Unpack(home, version))
            {
                return 1;
            }
        }

        string pythonw = Path.Combine(home, "runtime", "pythonw.exe");
        string script = Path.Combine(home, "app", "desktop_app.py");
        if (!File.Exists(pythonw) || !File.Exists(script))
        {
            MessageBox.Show("Some files are missing:\n" + pythonw + "\n" + script +
                "\n\nCopy the complete Peek & Grep folder again.", Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        var psi = new ProcessStartInfo(pythonw);
        psi.Arguments = Quote(script) + (args.Length > 0 ? " " + string.Join(" ", Array.ConvertAll(args, Quote)) : "");
        psi.WorkingDirectory = home;
        psi.UseShellExecute = false;
        psi.EnvironmentVariables["PEEK_GREP_HOME"] = home;
        // The bundled runtime must not pick up another Python installation
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Peek & Grep could not start:\n" + ex.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }

    static string Quote(string s)
    {
        return "\"" + s.Replace("\"", "\\\"") + "\"";
    }

    static string ReadResourceText(string name)
    {
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        {
            if (s == null) return null;
            using (var reader = new StreamReader(s)) return reader.ReadToEnd().Trim();
        }
    }

    static bool IsCurrent(string home, string version)
    {
        string marker = Path.Combine(home, "version.txt");
        return File.Exists(marker)
            && File.ReadAllText(marker).Trim() == version
            && File.Exists(Path.Combine(home, "runtime", "pythonw.exe"))
            && File.Exists(Path.Combine(home, "app", "desktop_app.py"));
    }

    static bool Unpack(string home, string version)
    {
        var form = new UnpackForm();
        Exception error = null;
        var worker = new Thread(() =>
        {
            try
            {
                Extract(home, version, form);
            }
            catch (Exception ex)
            {
                error = ex;
            }
            form.Done();
        });
        worker.IsBackground = true;
        form.Shown += (sender, e) => worker.Start();
        Application.Run(form);
        worker.Join();

        if (error != null)
        {
            string hint = error is IOException || error is UnauthorizedAccessException
                ? "\n\nIf Peek & Grep is running, quit it from the tray icon and start again. " +
                  "If this folder is read-only, move PeekGrep.exe to a folder where you can write files."
                : "";
            MessageBox.Show("Peek & Grep could not unpack its files:\n" + error.Message + hint, Title,
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        return true;
    }

    static void Extract(string home, string version, UnpackForm form)
    {
        Directory.CreateDirectory(home);
        string staging = Path.Combine(home, ".unpack-" + Guid.NewGuid().ToString("N").Substring(0, 8));
        string stagingRoot = Path.GetFullPath(staging) + Path.DirectorySeparatorChar;
        Directory.CreateDirectory(staging);
        try
        {
            using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream(PayloadName))
            using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
            {
                long total = 0, done = 0;
                foreach (ZipArchiveEntry entry in zip.Entries) total += entry.Length;
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    string dest = Path.GetFullPath(Path.Combine(staging, entry.FullName.Replace('/', '\\')));
                    if (!dest.StartsWith(stagingRoot, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("Bad path in package: " + entry.FullName);
                    if (entry.Name.Length == 0)
                    {
                        Directory.CreateDirectory(dest);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(dest));
                    entry.ExtractToFile(dest, true);
                    done += entry.Length;
                    form.Progress(total == 0 ? 100 : (int)(done * 100 / total));
                }
            }

            // Replace the program parts; the user's data folder stays as it is
            foreach (string part in new[] { "runtime", "app" })
            {
                string target = Path.Combine(home, part);
                if (Directory.Exists(target)) Directory.Delete(target, true);
                Directory.Move(Path.Combine(staging, part), target);
            }
            string readme = Path.Combine(staging, "README.txt");
            if (File.Exists(readme)) File.Copy(readme, Path.Combine(home, "README.txt"), true);
            File.WriteAllText(Path.Combine(home, "version.txt"), version);
        }
        finally
        {
            try { if (Directory.Exists(staging)) Directory.Delete(staging, true); } catch (IOException) { }
        }
    }
}

sealed class UnpackForm : Form
{
    readonly ProgressBar bar;

    public UnpackForm()
    {
        Text = "Peek & Grep";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(380, 96);
        BackColor = Color.FromArgb(21, 21, 27);
        ForeColor = Color.FromArgb(236, 236, 242);
        Font = new Font("Segoe UI", 9.5f);
        try { Icon = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location); } catch (Exception) { }

        var label = new Label();
        label.Text = "Unpacking Peek & Grep. This happens only on the first start.";
        label.AutoSize = false;
        label.SetBounds(18, 16, 344, 36);
        Controls.Add(label);

        bar = new ProgressBar();
        bar.SetBounds(18, 58, 344, 14);
        bar.Minimum = 0;
        bar.Maximum = 100;
        Controls.Add(bar);
    }

    public void Progress(int percent)
    {
        if (!IsHandleCreated) return;
        BeginInvoke((MethodInvoker)(() => bar.Value = Math.Max(0, Math.Min(100, percent))));
    }

    public void Done()
    {
        if (!IsHandleCreated) return;
        BeginInvoke((MethodInvoker)Close);
    }
}
