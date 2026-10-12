param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ShellDir = Join-Path $Root "NapCat.Shell"
$ZipPath = Join-Path $Root "NapCat.Shell.Windows.Node.zip"
$DownloadUrl = "https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.Windows.Node.zip"
$QQ = "100000000"

function Find-InstalledQQ {
    $Candidates = @(
        "C:\Program Files\Tencent\QQNT\QQ.exe",
        "C:\Program Files (x86)\Tencent\QQNT\QQ.exe"
    )

    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            return $Candidate
        }
    }

    $Found = Get-ChildItem -Path "C:\Program Files", "C:\Program Files (x86)" -Recurse -Filter "QQ.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*QQNT*" } |
        Select-Object -First 1

    if ($Found) {
        return $Found.FullName
    }

    throw "Installed QQNT was not found. Install official QQ first."
}

function Write-OneBotConfig($ConfigDir) {
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }

    $Config = @{
        network = @{
            httpServers = @()
            httpClients = @()
            websocketServers = @()
            websocketClients = @(
                @{
                    name = "JMComicBot"
                    enable = $true
                    url = "ws://127.0.0.1:8081/onebot/v11/ws"
                    messagePostFormat = "array"
                    reportSelfMessage = $false
                    reconnectInterval = 5000
                    token = ""
                    debug = $false
                    heartInterval = 30000
                }
            )
        }
        musicSignUrl = ""
        enableLocalFile2Url = $false
        parseMultMsg = $false
    }

    $Path = Join-Path $ConfigDir "onebot11_$QQ.json"
    $Config | ConvertTo-Json -Depth 10 | Set-Content -Path $Path -Encoding UTF8
    Write-Host "[OK] Wrote OneBot config: $Path"
}

# ---------------------------------------------------------------------------
# Compatibility gate.
# NapCat injects into QQ through hook offsets keyed by the QQ buildId. QQ
# hot-updates silently in the background, so a NapCat that worked last week can
# stop working today with no visible error. So "the folder exists" is no longer
# treated as "it works" -- we ask check_napcat_compat.ps1 instead.
#
# Returns: "ok" | "missing" | "incompatible" | "unknown"
# ---------------------------------------------------------------------------
function Test-NapCatCompatibility {
    if (-not (Test-Path $ShellDir)) { return "missing" }

    $checker = Join-Path $Root "check_napcat_compat.ps1"
    if (-not (Test-Path $checker)) { return "unknown" }

    # Run as a separate process on purpose: the checker uses `exit <code>`,
    # which must not terminate this script.
    $null = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checker -Root $Root -Quiet
    $code = $LASTEXITCODE

    if ($code -eq 0) { return "ok" }
    if ($code -eq 1) { return "incompatible" }
    if ($code -eq 2) { return "missing" }
    return "unknown"
}

function Backup-NapCatConfig {
    # Keep user config (OneBot endpoint, WebUI token, plugins) across updates.
    $backup = Join-Path $Root ".napcat-config-backup"
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null

    $dirs = @(Get-ChildItem -Path $ShellDir -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "config" })
    $i = 0
    foreach ($d in $dirs) {
        Copy-Item $d.FullName (Join-Path $backup ("cfg" + $i)) -Recurse -Force
        $i++
    }

    # Preserve files this project added on top of the official package; they are
    # NOT in the release zip and would otherwise be destroyed by the wipe below.
    $customNames = @("launcher-noadmin.bat")
    $customDir = Join-Path $backup "custom"
    New-Item -ItemType Directory -Path $customDir -Force | Out-Null
    $kept = 0
    foreach ($name in $customNames) {
        $hit = Get-ChildItem -Path $ShellDir -Recurse -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) {
            Copy-Item $hit.FullName (Join-Path $customDir $name) -Force
            $kept++
        }
    }

    Write-Host "[OK] Backed up $i config folder(s) and $kept custom file(s) to $backup"
    return $backup
}

function Restore-NapCatConfig($backup) {
    if (-not $backup -or -not (Test-Path $backup)) { return }

    # 1) config folders
    $target = Get-ChildItem -Path $ShellDir -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "config" } |
        Select-Object -First 1
    if (-not $target) {
        Write-Host "[WARN] No config folder in the new NapCat; backup kept at $backup"
    } else {
        Get-ChildItem $backup -Directory | Where-Object { $_.Name -like "cfg*" } | ForEach-Object {
            Copy-Item (Join-Path $_.FullName "*") $target.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Host "[OK] Restored previous config into $($target.FullName)"
    }

    # 2) custom launcher files, placed next to the official launchers
    $customDir = Join-Path $backup "custom"
    if (Test-Path $customDir) {
        $official = Get-ChildItem -Path $ShellDir -Recurse -Filter "launcher.bat" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($official) {
            $n = 0
            Get-ChildItem $customDir -File | ForEach-Object {
                Copy-Item $_.FullName (Join-Path $official.Directory.FullName $_.Name) -Force
                $n++
            }
            if ($n -gt 0) { Write-Host "[OK] Restored $n custom launcher file(s) next to the official ones" }
        }
    }
}

function Install-NapCatShell($reason) {
    Write-Host "[INFO] Updating NapCat Shell. Reason: $reason"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath
    } catch {
        Write-Host "[WARN] PowerShell download failed. Trying curl.exe..."
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if (-not $curl) {
            throw "Download failed and curl.exe was not found. Download manually: $DownloadUrl"
        }
        & $curl.Source -L $DownloadUrl -o $ZipPath
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ZipPath)) {
            throw "Download failed. Download manually: $DownloadUrl"
        }
    }

    $backup = Backup-NapCatConfig

    Write-Host "[INFO] Extracting NapCat Shell..."
    if (Test-Path $ShellDir) {
        Remove-Item -Path $ShellDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ShellDir | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ShellDir -Force
    Remove-Item -Path $ZipPath -Force

    Restore-NapCatConfig $backup

    Write-Host "[OK] NapCat Shell updated."
}

Write-Host "[INFO] Project: $Root"
$QQExe = Find-InstalledQQ
Write-Host "[OK] Installed QQNT: $QQExe"

if (-not (Test-Path $ShellDir)) {
    New-Item -ItemType Directory -Path $ShellDir | Out-Null
}

# ---- decide whether we actually need to (re)install ----------------------
$status = Test-NapCatCompatibility
Write-Host "[INFO] NapCat compatibility status: $status"

$shouldInstall = $false
$reason = ""

if ($Force) {
    $shouldInstall = $true
    $reason = "forced re-install requested (-Force)"
} elseif ($status -eq "missing") {
    $shouldInstall = $true
    $reason = "NapCat Shell is not installed"
} elseif ($status -eq "incompatible") {
    $shouldInstall = $true
    $reason = "installed QQ build is NOT supported by the current NapCat (the silent-failure case)"
} elseif ($status -eq "ok") {
    Write-Host "[OK] Existing NapCat Shell is compatible with the installed QQ. Skipping download."
    Write-Host "[INFO] Use -Force to reinstall anyway."
} else {
    Write-Host "[WARN] Compatibility could not be determined. Keeping the existing NapCat Shell."
}

if ($shouldInstall) {
    Install-NapCatShell $reason
}

$Launcher = Get-ChildItem -Path $ShellDir -Recurse -Filter "launcher.bat" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Launcher) {
    throw "launcher.bat was not found after extracting NapCat Shell."
}

# ---- report the final state ----------------------------------------------
$finalStatus = Test-NapCatCompatibility
if ($finalStatus -eq "ok") {
    Write-Host "[OK] NapCat is compatible with the installed QQ build."
} elseif ($finalStatus -eq "incompatible") {
    Write-Host "[WARN] Still incompatible after update. QQ may be newer than any released NapCat."
    Write-Host "[WARN] Check https://github.com/NapNeko/NapCatQQ/releases and wait for support,"
    Write-Host "[WARN] or install an older QQ build that this NapCat supports."
}

$RunDir = $Launcher.Directory.FullName
$ConfigDirs = @(
    (Join-Path $RunDir "config"),
    (Join-Path $ShellDir "config")
)

Get-ChildItem -Path $ShellDir -Directory -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "config" } |
    ForEach-Object { $ConfigDirs += $_.FullName }

$ConfigDirs | Select-Object -Unique | ForEach-Object { Write-OneBotConfig $_ }

Write-Host "[OK] NapCat Shell launcher: $($Launcher.FullName)"
Write-Host "[OK] NapCat will connect to ws://127.0.0.1:8081/onebot/v11/ws"
