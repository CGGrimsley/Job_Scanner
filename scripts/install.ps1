# Job Scanner one-click installer for Windows. Run "Install Job Scanner.bat" (it calls this).
# Installs what's missing (Python, Node.js 22+, Claude Code), turns on Start with Windows, adds a desktop
# shortcut and opens the app. Safe to run again: anything already installed is left alone.
# Kept plain ASCII for Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Say($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function WingetInstall($id, $what) {
  if (-not (Have "winget")) {
    Write-Host "winget isn't available. Install $what yourself, then run this again." -ForegroundColor Yellow
    return $false
  }
  Write-Host "Installing $what..."
  winget install -e --id $id --accept-source-agreements --accept-package-agreements
  RefreshPath
  return $true
}

Say "Python"
function Py { if (Have "py") { & py -3 @args } else { & python @args } }
if (-not ((Have "py") -or (Have "python"))) { WingetInstall "Python.Python.3.12" "Python 3.12" | Out-Null }
if (-not ((Have "py") -or (Have "python"))) { Write-Host "Python still isn't found. Install it from python.org and run this again." -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }
Py --version

Say "Node.js (Claude Code needs version 22 or newer)"
$nodeOk = $false
if (Have "node") {
  $v = (node -v) -replace "^v", ""
  $nodeOk = ([int]($v.Split(".")[0]) -ge 22)
  Write-Host "Found Node $v"
}
if (-not $nodeOk) { WingetInstall "OpenJS.NodeJS.LTS" "Node.js LTS" | Out-Null }

Say "Claude Code"
if ((Have "claude.cmd") -or (Have "claude")) {
  Write-Host "Claude Code is installed."
} elseif (Have "npm.cmd") {
  npm.cmd install -g @anthropic-ai/claude-code
  RefreshPath
} else {
  Write-Host "npm isn't found yet. Close this window, open a new one and run the installer again." -ForegroundColor Yellow
}

Say "Settings"
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env" }

Say "Start with Windows"
Py -m job_scanner startup on

Say "Desktop shortcut"
try {
  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "Job Scanner.lnk"))
  $link.TargetPath = Join-Path $repo "start.bat"
  $link.WorkingDirectory = $repo
  $icon = Join-Path $repo "job_scanner\static\favicon.ico"
  if (Test-Path $icon) { $link.IconLocation = $icon }
  $link.Save()
  Write-Host "Added Job Scanner to your desktop."
} catch { Write-Host "Couldn't add the shortcut: $_" -ForegroundColor Yellow }

Say "Starting Job Scanner"
$vbs = [IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs\Startup\Job Scanner.vbs")
if (Test-Path $vbs) { Start-Process "wscript.exe" -ArgumentList "`"$vbs`"" } else { Start-Process (Join-Path $repo "start.bat") }
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:8766/"

Write-Host ""
Write-Host "Done. Job Scanner is open in your browser, and its guide walks you through the rest." -ForegroundColor Green
Write-Host "If Claude isn't signed in yet: open Command Prompt, type  claude  and choose your Claude subscription."
Write-Host ""
Read-Host "Press Enter to close"
