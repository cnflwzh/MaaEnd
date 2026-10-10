$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
$appDir = Join-Path $root 'build-cloudweb-full/MaaEnd-CloudWeb'
$evidence = Join-Path $root 'build-cloudweb-full/verification'
New-Item -ItemType Directory -Force $evidence | Out-Null
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class CloudWebCapture {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    public class Window { public IntPtr Handle; public string Title; public int Width; public int Height; }
    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr param);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr handle, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr handle, uint message, IntPtr wParam, IntPtr lParam);
    public static Window[] Find(uint processId) {
        var result = new List<Window>();
        EnumWindows((handle, param) => {
            uint owner; GetWindowThreadProcessId(handle, out owner);
            Rect bounds;
            var title = new StringBuilder(512);
            GetWindowText(handle, title, title.Capacity);
            if (owner == processId && IsWindowVisible(handle) && GetWindowRect(handle, out bounds)
                && title.ToString().IndexOf("MaaEnd", StringComparison.OrdinalIgnoreCase) >= 0
                && bounds.Right - bounds.Left >= 800 && bounds.Bottom - bounds.Top >= 600) {
                result.Add(new Window { Handle = handle, Title = title.ToString(), Width = bounds.Right - bounds.Left, Height = bounds.Bottom - bounds.Top });
            }
            return true;
        }, IntPtr.Zero);
        return result.ToArray();
    }
}
'@
$process = Start-Process (Join-Path $appDir 'MaaEnd.exe') -WorkingDirectory $appDir -PassThru
$window = $null
try {
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "MaaEnd exited before its full UI appeared ($($process.ExitCode))" }
        $window = [CloudWebCapture]::Find($process.Id) | Sort-Object { $_.Width * $_.Height } -Descending | Select-Object -First 1
        $frontendReady = $false
        $frontendLogs = Get-ChildItem (Join-Path $appDir 'debug') -Filter '*.log' -ErrorAction SilentlyContinue
        foreach ($log in $frontendLogs) {
            if (Select-String -Path $log.FullName -SimpleMatch '窗口已显示' -Quiet) { $frontendReady = $true; break }
        }
        if ($null -ne $window -and $frontendReady) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $window -or -not $frontendReady) { throw 'Full titled MaaEnd window and frontend-ready log were not observed' }
    [CloudWebCapture]::SetForegroundWindow($window.Handle) | Out-Null
    Start-Sleep -Seconds 2
    # Re-enumerate after rendering; never retain an early tray/helper handle.
    $window = [CloudWebCapture]::Find($process.Id) | Sort-Object { $_.Width * $_.Height } -Descending | Select-Object -First 1
    if ($null -eq $window) { throw 'The full MaaEnd window disappeared before capture' }
    $rect = New-Object CloudWebCapture+Rect
    if (-not [CloudWebCapture]::GetWindowRect($window.Handle, [ref]$rect)) { throw 'GetWindowRect failed' }
    if (($rect.Right - $rect.Left) -lt 800 -or ($rect.Bottom - $rect.Top) -lt 600) { throw 'Window changed to an invalid capture size' }
    $bitmap = New-Object System.Drawing.Bitmap ($rect.Right - $rect.Left), ($rect.Bottom - $rect.Top)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    try {
        if (-not [CloudWebCapture]::PrintWindow($window.Handle, $dc, 2)) { throw 'PrintWindow failed' }
    } finally { $graphics.ReleaseHdc($dc) }
    try { $bitmap.Save((Join-Path $evidence 'MaaEnd-window.png'), [System.Drawing.Imaging.ImageFormat]::Png) }
    finally { $graphics.Dispose(); $bitmap.Dispose() }
    @{ processId = $process.Id; windowTitle = $window.Title; width = $window.Width; height = $window.Height; nativeWindowHandle = $window.Handle.ToInt64(); frontendReady = $true; tasksStarted = $false; verification = 'Visible titled full MaaEnd window captured after frontend initialization; inspect image for UI acceptance' } |
        ConvertTo-Json | Set-Content (Join-Path $evidence 'ui-capture.json') -Encoding utf8NoBOM
} finally {
    if (-not $process.HasExited) {
        if ($null -ne $window) { [CloudWebCapture]::PostMessage($window.Handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
        if (-not $process.WaitForExit(10000)) { & taskkill /PID $process.Id /T /F | Out-Null }
    }
    if (Test-Path (Join-Path $appDir 'debug')) {
        Copy-Item (Join-Path $appDir 'debug') (Join-Path $evidence 'ui-debug') -Recurse -Force
    }
    Copy-Item (Join-Path $appDir 'config/mxu-MaaEnd.json') (Join-Path $evidence 'ui-test-config.json') -Force
}
