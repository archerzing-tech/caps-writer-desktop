Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Full screen capture approach - capture the entire screen
$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$bounds = $screen.Bounds

Write-Output "Screen: $($screen.DeviceName) Bounds=$($bounds.Width)x$($bounds.Height) Location=$($bounds.X),$($bounds.Y)"

# Find CapsWriter and bring it to front
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinAPI3 {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$hwnd = [WinAPI3]::FindWindow($null, "CapsWriter · 语音输入")
if ($hwnd -ne [IntPtr]::Zero) {
    Write-Output "Found window handle: $hwnd"
    [WinAPI3]::ShowWindow($hwnd, 9) | Out-Null
    Start-Sleep -Milliseconds 200
    [WinAPI3]::SetForegroundWindow($hwnd) | Out-Null
    Start-Sleep -Milliseconds 500
    
    $rect = New-Object WinAPI3+RECT
    [WinAPI3]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
    Write-Output "Window rect: L=$($rect.Left) T=$($rect.Top) R=$($rect.Right) B=$($rect.Bottom) W=$($($rect.Right-$rect.Left)) H=$($($rect.Bottom-$rect.Top))"
    
    # Capture the area around the window (with some padding)
    $captureX = [Math]::Max(0, $rect.Left)
    $captureY = [Math]::Max(0, $rect.Top)
    $captureW = [Math]::Min(800, $bounds.Right - $captureX)
    $captureH = [Math]::Min(660, $bounds.Bottom - $captureY)
    
    Write-Output "Capturing area: X=$captureX Y=$captureY W=$captureW H=$captureH"
    
    $bitmap = New-Object System.Drawing.Bitmap($captureW, $captureH)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($captureX, $captureY, 0, 0, (New-Object System.Drawing.Size($captureW, $captureH)))
    
    $outputPath = "D:\work2026\caps-writer-tauri\screenshots\main-record-view.png"
    $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    
    Write-Output "Screenshot saved: $outputPath ($captureW x $captureH)"
} else {
    Write-Output "Window not found by title. Trying full screen capture..."
    
    $bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
    
    $outputPath = "D:\work2026\caps-writer-tauri\screenshots\main-record-view.png"
    $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    
    Write-Output "Full screen screenshot saved: $outputPath"
}
