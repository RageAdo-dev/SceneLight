param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA "SceneLight\bootstrap-python"),
    [string]$InstallerPath = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$expectedHash = "5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde"
$downloads = Join-Path $env:LOCALAPPDATA "SceneLight\downloads"
$cachedInstaller = Join-Path $downloads "python-3.11.9-amd64.exe"
$installer = if ($InstallerPath) {
    [IO.Path]::GetFullPath($InstallerPath)
} else {
    $cachedInstaller
}

function Test-OfficialInstaller {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $actualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) { return $false }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    return $signature.Status -eq "Valid" -and
        $signature.SignerCertificate.Subject -match "Python Software Foundation"
}

if ($InstallerPath -and -not (Test-OfficialInstaller -Path $installer)) {
    throw "The bundled Python installer failed its SHA-256 or publisher verification."
}

if (-not $InstallerPath -and -not (Test-OfficialInstaller -Path $installer)) {
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    $partial = "$installer.download"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    Write-Host "Downloading Python 3.11.9 runtime..."
    Invoke-WebRequest -Uri $url -OutFile $partial -UseBasicParsing
    if (-not (Test-OfficialInstaller -Path $partial)) {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        throw "The downloaded Python installer failed its SHA-256 or publisher verification."
    }
    Move-Item -LiteralPath $partial -Destination $installer -Force
}

Write-Host "Installing SceneLight runtime under $Destination ..."
$process = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
    "/passive",
    "InstallAllUsers=0",
    "TargetDir=`"$Destination`"",
    "Include_launcher=0",
    "AssociateFiles=0",
    "Shortcuts=0",
    "PrependPath=0",
    "Include_test=0",
    "Include_doc=0",
    "Include_tcltk=1",
    "Include_pip=1"
)
if ($process.ExitCode -ne 0) {
    throw "The Python installer exited with code $($process.ExitCode)."
}
if (-not (Test-Path -LiteralPath (Join-Path $Destination "pythonw.exe") -PathType Leaf)) {
    $installKey = "HKCU:\Software\Python\PythonCore\3.11\InstallPath"
    $registered = if (Test-Path -LiteralPath $installKey) {
        (Get-ItemProperty -LiteralPath $installKey)."(default)"
    } else {
        $null
    }
    $expectedPath = [IO.Path]::GetFullPath($Destination).TrimEnd([char[]]@(92, 47))
    $registeredPath = if ($registered) {
        [IO.Path]::GetFullPath([string]$registered).TrimEnd([char[]]@(92, 47))
    } else {
        ""
    }
    if (-not [string]::Equals(
        $registeredPath,
        $expectedPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Python finished without creating the SceneLight runtime."
    }

    # A user may have deleted SceneLight's files without first removing the
    # registered per-user Python runtime. The installer then enters Modify mode
    # and returns success without restoring missing files. Repair only when the
    # registered target is exactly SceneLight's own directory.
    Write-Host "Repairing SceneLight runtime..."
    $repair = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        "/repair",
        "/passive"
    )
    if ($repair.ExitCode -ne 0) {
        throw "The SceneLight runtime repair exited with code $($repair.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Destination "pythonw.exe") -PathType Leaf)) {
        throw "Python repair finished without restoring the SceneLight runtime."
    }
}
