# check_napcat_compat.ps1
# ---------------------------------------------------------------------------
# Verify that the QQ build installed on this machine is supported by the
# NapCat build sitting in <root>\NapCat.Shell.
#
# Why this exists: NapCat injects into QQ via hard-coded hook offsets keyed by
# the QQ buildId. QQ silently hot-updates in the background; when it lands on a
# build NapCat has never seen, injection fails and the bot goes deaf with no
# obvious error. This script turns that silent failure into an explicit check.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File check_napcat_compat.ps1
#   powershell ... -File check_napcat_compat.ps1 -Root "C:\path\to\project" -Quiet
#
# Exit codes:
#   0 = compatible
#   1 = QQ build NOT supported by this NapCat (needs update)
#   2 = NapCat not installed at all
#   3 = QQ installation not found
# ---------------------------------------------------------------------------
param(
    [string]$Root = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

if (-not $Root -or $Root.Trim().Length -eq 0) {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$Root = $Root.TrimEnd('\')

function Write-Info($msg) { if (-not $Quiet) { Write-Host $msg } }

# ---------------------------------------------------------------- locate QQ
function Get-QqBuildId {
    $candidates = @(
        "C:\Program Files\Tencent\QQNT\versions\config.json",
        "C:\Program Files (x86)\Tencent\QQNT\versions\config.json"
    )
    foreach ($cfg in $candidates) {
        if (Test-Path $cfg) {
            try {
                $json = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($json.curVersion) { return [string]$json.curVersion }
            } catch {
                # fall through to directory scan
            }
        }
    }
    # Fallback: newest build directory name under any QQNT versions folder
    $roots = @(
        "C:\Program Files\Tencent\QQNT\versions",
        "C:\Program Files (x86)\Tencent\QQNT\versions"
    )
    foreach ($r in $roots) {
        if (Test-Path $r) {
            $dirs = Get-ChildItem $r -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^\d+\.\d+\.\d+-\d+$' }
            if ($dirs) {
                return ($dirs | Sort-Object LastWriteTime -Descending | Select-Object -First 1).Name
            }
        }
    }
    return ""
}

# ------------------------------------------------------------- locate NapCat
function Get-NapCatMainFile {
    $shell = Join-Path $Root "NapCat.Shell"
    if (-not (Test-Path $shell)) { return "" }
    $hit = Get-ChildItem $shell -Recurse -Filter "napcat.mjs" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return ""
}

# --------------------------------------------------- extract supported builds
function Get-SupportedBuilds($mainFile) {
    $text = Get-Content $mainFile -Raw -Encoding UTF8
    # QQ build ids look like 9.9.30-48517; NapCat's own versions look like 4.18.38
    $m = [regex]::Matches($text, '9\.9\.\d{1,2}-\d{4,6}')
    $set = @{}
    foreach ($x in $m) { $set[$x.Value] = $true }
    return $set.Keys
}

# ------------------------------------------------------------------ run check
$qqBuild = Get-QqBuildId
if (-not $qqBuild) {
    Write-Host "RESULT=NO_QQ"
    Write-Host "QQ installation not found. Install official QQ NT first."
    exit 3
}

$mainFile = Get-NapCatMainFile
if (-not $mainFile) {
    Write-Host "RESULT=NO_NAPCAT"
    Write-Host ("NapCat is not installed under " + $Root + "\NapCat.Shell")
    Write-Host "Run setup_napcat_shell.ps1 to download it."
    exit 2
}

$supported = @(Get-SupportedBuilds $mainFile)
if ($supported.Count -eq 0) {
    # Cannot parse the list: do not block the user, just warn.
    Write-Host "RESULT=UNKNOWN"
    Write-Host ("Could not read the supported-build list from " + $mainFile)
    exit 0
}

$maxBuild = ($supported | Sort-Object { [int](($_ -split '-')[1]) } | Select-Object -Last 1)

if ($supported -contains $qqBuild) {
    Write-Host "RESULT=OK"
    Write-Host ("QQ build " + $qqBuild + " is supported by this NapCat (" + $supported.Count + " builds known).")
    exit 0
}

Write-Host "RESULT=UNSUPPORTED"
Write-Host ("QQ build " + $qqBuild + " is NOT supported by this NapCat.")
Write-Host ("Highest build this NapCat knows: " + $maxBuild)
Write-Host ("NapCat file: " + $mainFile)
Write-Host "Fix: update NapCat (re-run setup_napcat_shell.ps1 with -Force, or grab"
Write-Host "     NapCat.Shell.Windows.Node.zip from https://github.com/NapNeko/NapCatQQ/releases/latest )"
exit 1
