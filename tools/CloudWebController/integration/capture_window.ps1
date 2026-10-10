$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
$appDir = Join-Path $root 'build-cloudweb-full/MaaEnd-CloudWeb'
$evidence = Join-Path $root 'build-cloudweb-full/verification'
New-Item -ItemType Directory -Force $evidence | Out-Null
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class CloudWebCapture {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr handle, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr handle);
}
'@
$process = Start-Process (Join-Path $appDir 'MaaEnd.exe') -WorkingDirectory $appDir -PassThru
try {
    $deadline = (Get-Date).AddSeconds(90)
    $handle = [IntPtr]::Zero
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "MaaEnd exited before its full UI appeared ($($process.ExitCode))" }
        $handle = $process.MainWindowHandle
        if ($handle -ne [IntPtr]::Zero) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($handle -eq [IntPtr]::Zero) { throw 'MaaEnd did not create a visible native window' }
    [CloudWebCapture]::SetForegroundWindow($handle) | Out-Null
    # A window handle precedes React's initial resource/config render.
    Start-Sleep -Seconds 8
    $rect = New-Object CloudWebCapture+Rect
    if (-not [CloudWebCapture]::GetWindowRect($handle, [ref]$rect)) { throw 'GetWindowRect failed' }
    $bitmap = New-Object System.Drawing.Bitmap ($rect.Right - $rect.Left), ($rect.Bottom - $rect.Top)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    try {
        if (-not [CloudWebCapture]::PrintWindow($handle, $dc, 2)) { throw 'PrintWindow failed' }
    } finally { $graphics.ReleaseHdc($dc) }
    try { $bitmap.Save((Join-Path $evidence 'MaaEnd-window.png'), [System.Drawing.Imaging.ImageFormat]::Png) }
    finally { $graphics.Dispose(); $bitmap.Dispose() }
    @{ processId = $process.Id; windowTitle = $process.MainWindowTitle; nativeWindowHandle = $handle.ToInt64(); tasksStarted = $false; verification = 'Full native MaaEnd window captured; inspect image for UI acceptance' } |
        ConvertTo-Json | Set-Content (Join-Path $evidence 'ui-capture.json') -Encoding utf8NoBOM
} finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        if (-not $process.WaitForExit(10000)) { & taskkill /PID $process.Id /T /F | Out-Null }
    }
    if (Test-Path (Join-Path $appDir 'debug')) {
        Copy-Item (Join-Path $appDir 'debug') (Join-Path $evidence 'ui-debug') -Recurse -Force
    }
}
