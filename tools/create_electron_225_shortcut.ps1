$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath 'Sadness VPN 2.0.25.lnk'
$launcherPath = 'C:\Program Files\Sadness VPN\SadnessVPN.exe'
if (-not (Test-Path -LiteralPath $launcherPath)) { throw 'Launcher not installed' }
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.TargetPath -ne $launcherPath) { throw 'Existing shortcut points to another application' }
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = 'C:\Program Files\Sadness VPN'
$shortcut.Arguments = '--show'
$shortcut.Description = 'Sadness VPN 2.0.25 Beta — Electron'
$shortcut.IconLocation = "$launcherPath,0"
$shortcut.Save()
Write-Output $shortcutPath
