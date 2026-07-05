Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$w = $screen.Bounds.Width
$h = $screen.Bounds.Height
Write-Output "Screen: ${w}x${h}"

$bitmap = New-Object System.Drawing.Bitmap($w, $h)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Bounds.Location, (New-Object System.Drawing.Point(0,0)), $screen.Bounds.Size)
$bitmap.Save("D:\work2026\caps-writer-tauri\screenshots\fullscreen.png", [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Output "Screenshot saved"
