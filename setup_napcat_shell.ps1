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

Write-Host "[INFO] Project: $Root"
$QQExe = Find-InstalledQQ
Write-Host "[OK] Installed QQNT: $QQExe"

if (-not (Test-Path $ShellDir)) {
    New-Item -ItemType Directory -Path $ShellDir | Out-Null
}

$Launcher = Get-ChildItem -Path $ShellDir -Recurse -Filter "launcher.bat" -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $Launcher) {
    Write-Host "[INFO] Downloading NapCat Shell Windows Node package..."
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

    Write-Host "[INFO] Extracting NapCat Shell..."
    if (Test-Path $ShellDir) {
        Remove-Item -Path $ShellDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ShellDir | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ShellDir -Force
    Remove-Item -Path $ZipPath -Force

    $Launcher = Get-ChildItem -Path $ShellDir -Recurse -Filter "launcher.bat" -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not $Launcher) {
    throw "launcher.bat was not found after extracting NapCat Shell."
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
