#requires -version 5
<#
Build standalone executables for this tool.
PyInstaller is required: py -3 -m pip install pyinstaller

Usage:
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -ConsoleOnly
#>

param(
    [switch]$ConsoleOnly
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Resolve-Python {
    foreach ($candidate in @("py", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }
    throw "Python 3.9 or newer was not found."
}

$python = Resolve-Python

& $python -3 -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller was not found. Run:" -ForegroundColor Yellow
    Write-Host "    $python -3 -m pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}

$iconPng = Join-Path $PSScriptRoot "image\appIcon.png"
$iconIco = Join-Path $PSScriptRoot "image\appIcon.ico"
$syncVersion = Join-Path $PSScriptRoot "tools\sync_version.py"
$versionMain = Join-Path $PSScriptRoot "packaging\version_main.txt"
$versionClean = Join-Path $PSScriptRoot "packaging\version_clean.txt"
$versionCli = Join-Path $PSScriptRoot "packaging\version_cli.txt"

if (-not (Test-Path -LiteralPath $iconPng)) {
    throw "Icon file not found: $iconPng"
}
if (-not (Test-Path -LiteralPath $iconIco)) {
    throw "Windows icon file not found: $iconIco"
}
foreach ($versionFile in @($versionMain, $versionClean, $versionCli)) {
    if (-not (Test-Path -LiteralPath $versionFile)) {
        throw "Version resource file not found: $versionFile"
    }
}

# 版本号只在 edge_ie_manager\version.py 里维护，打包前先同步到版本资源和
# version.json，避免各处版本号对不上导致“检查更新”判断错误。
Write-Host "Syncing version metadata ..." -ForegroundColor Cyan
& $python -3 $syncVersion
if ($LASTEXITCODE -ne 0) {
    throw "Version sync failed."
}

$common = @(
    "-3", "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onefile",
    "--distpath", "dist",
    "--workpath", "build",
    "--specpath", "build"
)

if ($ConsoleOnly) {
    Write-Host "Building command-line executable ..." -ForegroundColor Cyan
    & $python @common `
        --name "EdgeIEManager-CLI" `
        --icon $iconIco `
        --version-file $versionCli `
        run_cli.py
} else {
    Write-Host "Building GUI executable (no console window) ..." -ForegroundColor Cyan
    & $python @common `
        --name "EdgeIEManager" `
        --windowed `
        --icon $iconIco `
        --version-file $versionMain `
        --add-data "$iconPng;image" `
        --add-data "$iconIco;image" `
        run_gui.py
    if ($LASTEXITCODE -ne 0) {
        throw "GUI build failed. Check the PyInstaller output above."
    }

    # 把主程序 exe 的 sha256 和大小写进 version.json，更新器下载后可以校验完整性，
    # 上传 Release 时用这份 version.json 即可。
    & $python -3 $syncVersion --artifact (Join-Path $PSScriptRoot "dist\EdgeIEManager.exe")
    if ($LASTEXITCODE -ne 0) {
        throw "Version metadata sync (checksum) failed."
    }

    Write-Host "Building clean portable GUI executable ..." -ForegroundColor Cyan
    & $python @common `
        --name "EdgeIEManager-Clean" `
        --windowed `
        --icon $iconIco `
        --version-file $versionClean `
        --add-data "$iconPng;image" `
        --add-data "$iconIco;image" `
        run_gui_clean.py
    if ($LASTEXITCODE -ne 0) {
        throw "Clean GUI build failed. Check the PyInstaller output above."
    }

    Write-Host "Building command-line executable ..." -ForegroundColor Cyan
    & $python @common `
        --name "EdgeIEManager-CLI" `
        --icon $iconIco `
        --version-file $versionCli `
        run_cli.py
}

if ($LASTEXITCODE -ne 0) {
    throw "Build failed. Check the PyInstaller output above."
}

Write-Host ""
Write-Host "Done. Executables are in the dist directory." -ForegroundColor Green
