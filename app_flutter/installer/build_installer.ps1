# Builds the Flutter Windows release and packs it into dist\SentinelAI-Setup-<version>.exe with Inno Setup 6.
# usage (from app_flutter\):  powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1
$ErrorActionPreference = 'Stop'
$app = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $app -Parent

$version = (Select-String -Path "$app\pubspec.yaml" -Pattern '^version:\s*([0-9.]+)').Matches[0].Groups[1].Value
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found (winget install JRSoftware.InnoSetup).' }

Push-Location $app
try {
  flutter build windows --release
  if ($LASTEXITCODE -ne 0) { throw 'flutter build failed' }
  & $iscc "/DAppVersion=$version" "/DBackendDefault=$repo\backend" "$PSScriptRoot\sentinelai.iss"
  if ($LASTEXITCODE -ne 0) { throw 'ISCC failed' }
} finally { Pop-Location }
Get-Item "$repo\dist\SentinelAI-Setup-$version.exe"
