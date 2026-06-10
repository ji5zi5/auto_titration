using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class AutoTitrationLauncher
{
    [STAThread]
    private static int Main()
    {
        try
        {
            string root = FindProjectRoot(AppDomain.CurrentDomain.BaseDirectory);
            string batPath = Path.Combine(root, "launchers", "windows", "21_open_dashboard_server.bat");

            if (!File.Exists(batPath))
            {
                MessageBox.Show(
                    "실행 파일 위치에서 launchers\\windows\\21_open_dashboard_server.bat 파일을 찾지 못했습니다.\n\n" +
                    "AutoTitration.exe를 배포 ZIP의 최상위 폴더에 둔 상태로 실행하세요.",
                    "Auto Titration",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return 1;
            }

            var startInfo = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c \"" + batPath + "\"",
                WorkingDirectory = root,
                UseShellExecute = true,
                WindowStyle = ProcessWindowStyle.Normal
            };

            Process.Start(startInfo);
            return 0;
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Auto Titration 실행 중 오류가 발생했습니다.\n\n" + ex.Message,
                "Auto Titration",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string FindProjectRoot(string startDir)
    {
        var current = new DirectoryInfo(startDir);
        while (current != null)
        {
            string candidate = Path.Combine(current.FullName, "launchers", "windows", "21_open_dashboard_server.bat");
            if (File.Exists(candidate))
            {
                return current.FullName;
            }
            current = current.Parent;
        }
        return startDir;
    }
}
