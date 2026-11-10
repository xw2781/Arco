// Arco Add-in Setup: registers the Arco.xlam that sits beside this program as
// an Excel add-in for the current Windows user.
//
// It writes Excel's own per-user add-in list in the registry and never starts
// Excel or runs a macro, so it works whatever the user's macro settings are.
// Built by excel-addin/tools/build_addin_setup.ps1 with the C# 5 compiler that
// ships with Windows, so keep the code to C# 5.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

namespace ArcoAddinSetup
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            string addInPath = Path.Combine(
                Path.GetDirectoryName(Application.ExecutablePath), AddInRegistration.AddInFileName);

            // "/silent" installs without a window; the exit code is the result.
            if (args.Length == 1 && string.Equals(args[0], "/silent", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    AddInRegistration.Install(addInPath);
                    return 0;
                }
                catch (InvalidOperationException)
                {
                    return 1;
                }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm(addInPath));
            return 0;
        }
    }

    internal static class AddInRegistration
    {
        public const string AddInFileName = "Arco.xlam";

        // Registrations this install replaces. The add-in was ArcRho.xlam until
        // 2026-11-09; that registration points at a file that no longer exists.
        private static readonly string[] ReplacedFileNames = { AddInFileName, "ArcRho.xlam" };

        public static bool IsInstalled(string addInPath)
        {
            string optionsPath = ExcelKeyPath("Options");
            if (optionsPath == null)
            {
                return false;
            }
            using (RegistryKey options = Registry.CurrentUser.OpenSubKey(optionsPath))
            {
                if (options == null)
                {
                    return false;
                }
                foreach (string value in ReadOpenValues(options))
                {
                    if (string.Equals(value.Trim().Trim('"'), addInPath, StringComparison.OrdinalIgnoreCase))
                    {
                        return true;
                    }
                }
            }
            return false;
        }

        public static void Install(string addInPath)
        {
            if (!File.Exists(addInPath))
            {
                throw new InvalidOperationException(AddInFileName + " was not found beside this program.");
            }
            string optionsPath = ExcelKeyPath("Options");
            if (optionsPath == null)
            {
                throw new InvalidOperationException("Excel was not found on this PC.");
            }
            // Excel rewrites its add-in list when it closes, which would undo this.
            if (ExcelIsRunning())
            {
                throw new InvalidOperationException("Close Excel, then click Install.");
            }

            // Excel loads the values OPEN, OPEN1, OPEN2 ... and stops at the first gap.
            using (RegistryKey options = Registry.CurrentUser.CreateSubKey(optionsPath))
            {
                List<string> existing = ReadOpenValues(options);
                List<string> kept = new List<string>();
                foreach (string value in existing)
                {
                    if (!PointsAtReplacedFile(value))
                    {
                        kept.Add(value);
                    }
                }
                kept.Add("\"" + addInPath + "\"");

                for (int index = 0; index < existing.Count; index++)
                {
                    options.DeleteValue(OpenValueName(index), false);
                }
                for (int index = 0; index < kept.Count; index++)
                {
                    options.SetValue(OpenValueName(index), kept[index], RegistryValueKind.String);
                }
            }

            // Excel lists switched-off add-ins here by path; one left behind
            // would show the add-in a second time, unticked.
            using (RegistryKey manager = Registry.CurrentUser.OpenSubKey(ExcelKeyPath("Add-in Manager"), true))
            {
                if (manager != null)
                {
                    foreach (string name in manager.GetValueNames())
                    {
                        if (PointsAtReplacedFile(name))
                        {
                            manager.DeleteValue(name, false);
                        }
                    }
                }
            }
        }

        // "Software\Microsoft\Office\16.0\Excel\<leaf>" for the installed Excel.
        private static string ExcelKeyPath(string leaf)
        {
            using (RegistryKey current = Registry.ClassesRoot.OpenSubKey(@"Excel.Application\CurVer"))
            {
                string progId = current == null ? null : current.GetValue(null) as string;
                if (string.IsNullOrEmpty(progId))
                {
                    return null;
                }
                string major = progId.Substring(progId.LastIndexOf('.') + 1);
                return @"Software\Microsoft\Office\" + major + @".0\Excel\" + leaf;
            }
        }

        private static string OpenValueName(int index)
        {
            return index == 0 ? "OPEN" : "OPEN" + index;
        }

        private static List<string> ReadOpenValues(RegistryKey options)
        {
            List<string> values = new List<string>();
            while (true)
            {
                string value = options.GetValue(OpenValueName(values.Count)) as string;
                if (value == null)
                {
                    return values;
                }
                values.Add(value);
            }
        }

        private static bool PointsAtReplacedFile(string registeredPath)
        {
            string path = registeredPath.Trim().TrimEnd('"');
            foreach (string fileName in ReplacedFileNames)
            {
                if (path.EndsWith("\\" + fileName, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            return false;
        }

        // Only this user's desktop session: a shared server runs other users' Excel too.
        // Only an Excel with a window: a hidden one started by another program
        // leaves the add-in list alone when it closes, and the user cannot close it.
        private static bool ExcelIsRunning()
        {
            int session = Process.GetCurrentProcess().SessionId;
            foreach (Process process in Process.GetProcessesByName("EXCEL"))
            {
                if (process.SessionId == session && process.MainWindowHandle != IntPtr.Zero)
                {
                    return true;
                }
            }
            return false;
        }
    }

    internal sealed class SetupForm : Form
    {
        private readonly string addInPath;
        private readonly Label status;
        private readonly Button install;

        public SetupForm(string addInPath)
        {
            this.addInPath = addInPath;

            Text = "Arco Excel Add-in Setup";
            Font = SystemFonts.MessageBoxFont;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowIcon = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(480, 150);

            Label path = new Label();
            path.Text = addInPath;
            path.AutoEllipsis = true;
            path.SetBounds(16, 18, 448, 20);

            status = new Label();
            status.SetBounds(16, 48, 448, 40);

            install = new Button();
            install.Text = "Install";
            install.SetBounds(292, 108, 82, 28);
            install.Click += OnInstall;

            Button close = new Button();
            close.Text = "Close";
            close.SetBounds(382, 108, 82, 28);
            close.Click += delegate { Close(); };

            Controls.AddRange(new Control[] { path, status, install, close });
            AcceptButton = install;
            CancelButton = close;

            if (!File.Exists(addInPath))
            {
                ShowStatus(AddInRegistration.AddInFileName + " was not found beside this program.", true);
                install.Enabled = false;
            }
            else if (AddInRegistration.IsInstalled(addInPath))
            {
                ShowStatus("Already installed for this user.", false);
            }
        }

        private void OnInstall(object sender, EventArgs e)
        {
            try
            {
                AddInRegistration.Install(addInPath);
                ShowStatus("Installed. Start Excel to use Arco.", false);
            }
            catch (InvalidOperationException error)
            {
                ShowStatus(error.Message, true);
            }
        }

        private void ShowStatus(string message, bool isError)
        {
            status.ForeColor = isError ? Color.Firebrick : SystemColors.ControlText;
            status.Text = message;
        }
    }
}
