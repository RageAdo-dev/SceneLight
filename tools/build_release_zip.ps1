param(
    [string]$PythonInstaller,
    [string]$Wheelhouse,
    [string]$CompatibilityRuntime,
    [switch]$Source
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$version = (& python -c "import sys; sys.path.insert(0, 'src'); import scenelight; print(scenelight.__version__)").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the SceneLight version."
}

$offline = -not [string]::IsNullOrWhiteSpace($PythonInstaller) -or
    -not [string]::IsNullOrWhiteSpace($Wheelhouse)
$resolvedInstaller = $null
$resolvedWheelhouse = $null
$resolvedCompatibilityRuntime = $null
if ($offline) {
    if ([string]::IsNullOrWhiteSpace($PythonInstaller) -or
        [string]::IsNullOrWhiteSpace($Wheelhouse)) {
        throw "Offline releases require both -PythonInstaller and -Wheelhouse."
    }
    if ([string]::IsNullOrWhiteSpace($CompatibilityRuntime)) {
        throw "Offline releases require -CompatibilityRuntime for legacy Ren'Py games."
    }
    $resolvedInstaller = (Resolve-Path -LiteralPath $PythonInstaller).Path
    $resolvedWheelhouse = (Resolve-Path -LiteralPath $Wheelhouse).Path
    if (-not (Test-Path -LiteralPath $resolvedWheelhouse -PathType Container)) {
        throw "Wheelhouse is not a directory: $resolvedWheelhouse"
    }
    if (-not (Get-ChildItem -LiteralPath $resolvedWheelhouse -Filter "*.whl" -File)) {
        throw "Wheelhouse contains no .whl packages: $resolvedWheelhouse"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $resolvedInstaller
    if ($signature.Status -ne "Valid" -or
        $signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        throw "Python installer is not validly signed by the Python Software Foundation."
    }
}

if (-not [string]::IsNullOrWhiteSpace($CompatibilityRuntime)) {
    $requestedRuntime = (Resolve-Path -LiteralPath $CompatibilityRuntime).Path
    $resolvedCompatibilityRuntime = if (
        Test-Path -LiteralPath $requestedRuntime -PathType Leaf
    ) {
        Split-Path -Parent $requestedRuntime
    } else {
        $requestedRuntime
    }
    $runtimeExecutable = Join-Path $resolvedCompatibilityRuntime "renpy.exe"
    $runtimeVersionSource = Join-Path $resolvedCompatibilityRuntime "renpy\__init__.py"
    $runtimeLicense = Join-Path $resolvedCompatibilityRuntime "LICENSE.txt"
    if (-not (Test-Path -LiteralPath $runtimeExecutable -PathType Leaf) -or
        -not (Test-Path -LiteralPath $runtimeVersionSource -PathType Leaf) -or
        -not (Test-Path -LiteralPath $runtimeLicense -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $resolvedCompatibilityRuntime "lib") -PathType Container) -or
        -not (Test-Path -LiteralPath (Join-Path $resolvedCompatibilityRuntime "module") -PathType Container)) {
        throw "Compatibility runtime is incomplete; expected an unpacked Ren'Py 7 runtime with renpy.exe, lib, module, renpy, and LICENSE.txt."
    }
    $runtimeVersionText = [IO.File]::ReadAllText($runtimeVersionSource)
    $runtimeBuildVersion = Join-Path $resolvedCompatibilityRuntime "renpy\vc_version.py"
    if (Test-Path -LiteralPath $runtimeBuildVersion -PathType Leaf) {
        $runtimeVersionText += "`n" + [IO.File]::ReadAllText($runtimeBuildVersion)
    }
    if ($runtimeVersionText -notmatch 'version_tuple\s*=\s*\(\s*7\s*,' -and
        $runtimeVersionText -notmatch '(?m)^\s*version\s*=\s*[uU]?[''"]7\.') {
        throw "Compatibility runtime must be Ren'Py 7 so it can run legacy Python 2 games."
    }
    if ($runtimeVersionText -match 'version_tuple\s*=\s*\(\s*7\s*,\s*8\s*,\s*7\s*[,)]' -or
        $runtimeVersionText -match '(?m)^\s*version\s*=\s*[uU]?[''"]7\.8\.7(?:\.|[''"])') {
        throw "Ren'Py 7.8.7 is disqualified because its graphics textures leak. Use the verified 7.7.1 compatibility runtime."
    }
}

$staging = Join-Path ([IO.Path]::GetTempPath()) "scenelight-release-$([guid]::NewGuid())"
$packageRoot = Join-Path $staging "SceneLight-$version"
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

function Remove-VerifiedStagingTree {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
        [IO.Path]::DirectorySeparatorChar
    )
    $expectedPrefix = $temporaryRoot + [IO.Path]::DirectorySeparatorChar + "scenelight-release-"
    if (-not $resolved.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove an unexpected staging path: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

try {
if ($Source) {
    $items = @(
        ".github", "docs", "examples", "runtime-installer", "src", "tests",
        "tools", ".gitattributes", ".gitignore", "CHANGELOG.md",
        "CONTRIBUTING.md", "SceneLight.bat", "scenelight.sh", "LICENSE",
        "pyproject.toml", "README.md", "requirements.txt",
        "requirements-preview.txt", "SECURITY.md", "scenelight_sdk.py",
        "scenelight_setup.pyw", "scenelight_preview.pyw",
        "THIRD_PARTY_NOTICES.md", "VALIDATION.md", "VALIDATION_RESULTS.md"
    )
    foreach ($item in $items) {
        Copy-Item -LiteralPath (Join-Path $root $item) `
            -Destination $packageRoot -Recurse -Force
    }
    $payloadRoot = $packageRoot
} else {
    foreach ($item in @(
        "SceneLight.bat", "scenelight.sh", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"
    )) {
        Copy-Item -LiteralPath (Join-Path $root $item) -Destination $packageRoot -Force
    }
    $payloadRoot = Join-Path $packageRoot "_scenelight"
    New-Item -ItemType Directory -Path $payloadRoot -Force | Out-Null
    foreach ($item in @("src", "runtime-installer")) {
        Copy-Item -LiteralPath (Join-Path $root $item) `
            -Destination $payloadRoot -Recurse -Force
    }
    foreach ($item in @(
        "scenelight_setup.pyw", "scenelight_preview.pyw", "scenelight_sdk.py",
        "requirements.txt", "requirements-preview.txt"
    )) {
        Copy-Item -LiteralPath (Join-Path $root $item) -Destination $payloadRoot -Force
    }
    $payloadTools = Join-Path $payloadRoot "tools"
    New-Item -ItemType Directory -Path $payloadTools -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root "tools\bootstrap_python.ps1") `
        -Destination $payloadTools -Force
}

if ($offline) {
    Copy-Item -LiteralPath $resolvedInstaller `
        -Destination (Join-Path $payloadRoot "runtime-installer") -Force
    Copy-Item -LiteralPath $resolvedWheelhouse `
        -Destination (Join-Path $payloadRoot "wheelhouse") -Recurse -Force
}

if ($null -ne $resolvedCompatibilityRuntime) {
    Copy-Item -LiteralPath $resolvedCompatibilityRuntime `
        -Destination (Join-Path $payloadRoot "compatibility-runtime") -Recurse -Force
}

# Keep Windows launchers conventional even when the source checkout uses LF.
$utf8NoBom = [Text.UTF8Encoding]::new($false)
foreach ($batch in @(Get-ChildItem -LiteralPath $packageRoot -Filter "*.bat" -File -Recurse)) {
    $batchText = [IO.File]::ReadAllText($batch.FullName)
    $batchText = $batchText -replace "`r?`n", "`r`n"
    [IO.File]::WriteAllText($batch.FullName, $batchText, $utf8NoBom)
}

$packagedCompatibilityRoot = Join-Path $payloadRoot "compatibility-runtime"
$packagedCompatibilityPrefix = $packagedCompatibilityRoot.TrimEnd(
    [IO.Path]::DirectorySeparatorChar
) + [IO.Path]::DirectorySeparatorChar
Get-ChildItem -LiteralPath $packageRoot -Recurse -Directory -Force |
    Where-Object {
        -not $_.FullName.StartsWith(
            $packagedCompatibilityPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -and (
            $_.Name -in @("__pycache__", ".pytest_cache", ".ruff_cache") -or
            $_.Name -like "*.egg-info"
        )
    } |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $packageRoot -Recurse -File -Force |
    Where-Object {
        -not $_.FullName.StartsWith(
            $packagedCompatibilityPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -and $_.Extension -in @(".pyc", ".pyo", ".rpyc")
    } |
    Remove-Item -Force

$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$suffix = if ($offline) { "-offline" } elseif ($Source) { "-source" } else { "" }
$archive = Join-Path $dist "SceneLight-v$version-Windows$suffix.zip"
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -LiteralPath $packageRoot -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($archive))" | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-VerifiedStagingTree -Path $staging
    }
}
Write-Output $archive
Write-Output "$archive.sha256"
