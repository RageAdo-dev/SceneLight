param(
    [string]$ManifestPath = (Join-Path $PSScriptRoot "..\online-release.json"),
    [string]$CacheRoot = $(if ($env:SCENELIGHT_INSTALL_ROOT) { $env:SCENELIGHT_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "SceneLight\installed" }),
    [switch]$Headless,
    [switch]$InstallOnly
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Read-ReleaseManifest {
    param([string]$Path)
    $record = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $uri = [Uri]$record.url
    if (-not $uri.IsAbsoluteUri -or ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.IsLoopback))) {
        throw "The release download must use HTTPS."
    }
    if ($record.sha256 -notmatch '^[a-f0-9]{64}$' -or
        $record.package_root -notmatch '^SceneLight-[0-9][A-Za-z0-9._-]*$' -or
        $record.archive -notmatch '^SceneLight-[A-Za-z0-9._-]+\.zip$' -or
        [long]$record.bytes -le 0 -or [long]$record.bytes -gt 2GB) {
        throw "The online installer manifest is invalid."
    }
    return $record
}

function Test-ReleaseArchive {
    param([string]$Path, $Record)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne [long]$Record.bytes) { return $false }
    $hash = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try {
        return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() -eq $Record.sha256
    } finally { $stream.Dispose(); $hash.Dispose() }
}

function Expand-VerifiedRelease {
    param([string]$Archive, [string]$Destination, $Record)
    if (-not (Test-ReleaseArchive $Archive $Record)) { throw "Release checksum verification failed. Nothing was installed." }
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $total = 0L
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if (($name.TrimEnd('/') -ne $Record.package_root -and -not $name.StartsWith($Record.package_root + '/', [StringComparison]::Ordinal)) -or
                $name -match '(^|/)(\.|\.\.)(/|$)|:' -or
                (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {
                throw "Unsafe path in the release archive."
            }
            $total += $entry.Length
            if ($total -gt 4GB) { throw "Release expands beyond its allowed size." }
        }
    } finally { $zip.Dispose() }
    # Windows tar handles Qt's long asset names; .NET Framework extraction does not.
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path -LiteralPath $tar)) { throw "Windows tar.exe is missing. Use the offline ZIP and extract it manually." }
    & $tar -xf $Archive -C $Destination
    if ($LASTEXITCODE -ne 0) { throw "Release extraction failed. Reopen this installer to retry." }
    $app = Join-Path $Destination $Record.package_root
    foreach ($relative in @('SceneLight.exe', '_scenelight\python\pythonw.exe', '_scenelight\python\scenelight-runtime.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $app $relative) -PathType Leaf)) {
            throw "The release is incomplete: $relative"
        }
    }
}

function Install-SceneLightRelease {
    param($Record, [string]$Root, [string]$ManifestDirectory, [switch]$Quiet)
    $Root = [IO.Path]::GetFullPath($Root)
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $target = Join-Path $Root $Record.sha256
    $app = Join-Path $target $Record.package_root
    $marker = Join-Path $target 'verified.sha256'
    if ((Test-Path -LiteralPath $marker) -and
        (Get-Content -LiteralPath $marker -Raw).Trim() -eq $Record.sha256 -and
        (Test-Path -LiteralPath (Join-Path $app 'SceneLight.exe')) -and
        (Test-Path -LiteralPath (Join-Path $app '_scenelight\python\pythonw.exe'))) { return $app }
    if (Test-Path -LiteralPath $target) {
        throw "This cached installation is incomplete. Use the offline ZIP, or move this folder aside and retry: $target"
    }
    $lock = $null
    $stage = $null
    $form = $null
    try {
        try { $lock = [IO.File]::Open((Join-Path $Root 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch { throw "Another SceneLight installer is running. Let it finish, then reopen SceneLight." }
        $stage = Join-Path $Root ('pending-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $stage | Out-Null
        $archive = Join-Path $stage 'release.zip'
        $sibling = Join-Path $ManifestDirectory $Record.archive
        if (-not $Quiet) {
            Add-Type -AssemblyName System.Windows.Forms
            $size = [math]::Ceiling([long]$Record.bytes / 1MB)
            $answer = [Windows.Forms.MessageBox]::Show(
                "Download SceneLight and its required components ($size MB)?`n`nThey stay in SceneLight's own folder. No system Python or administrator access is needed. Later launches reuse this download.",
                'SceneLight setup', 'YesNo', 'Information')
            if ($answer -ne 'Yes') { throw [OperationCanceledException]::new('Setup cancelled.') }
            $form = New-Object Windows.Forms.Form
            $form.Text = 'Setting up SceneLight'
            $form.ClientSize = New-Object Drawing.Size(480, 130)
            $form.StartPosition = 'CenterScreen'
            $form.FormBorderStyle = 'FixedDialog'
            $form.MaximizeBox = $false
            $form.BackColor = [Drawing.ColorTranslator]::FromHtml('#12161c')
            $form.ForeColor = [Drawing.Color]::White
            $label = New-Object Windows.Forms.Label
            $label.SetBounds(20, 20, 440, 35)
            $label.Text = 'Preparing download...'
            $progress = New-Object Windows.Forms.ProgressBar
            $progress.SetBounds(20, 65, 440, 20)
            $form.Controls.AddRange(@($label, $progress))
            $form.Show()
            [Windows.Forms.Application]::DoEvents()
        }
        if (Test-ReleaseArchive $sibling $Record) {
            Copy-Item -LiteralPath $sibling -Destination $archive
        } else {
            $client = New-Object Net.WebClient
            try {
                $client.Headers.Add('User-Agent', 'SceneLight-Installer')
                $download = $client.DownloadFileTaskAsync([Uri]$Record.url, $archive)
                $timer = [Diagnostics.Stopwatch]::StartNew()
                while (-not $download.IsCompleted) {
                    $received = if (Test-Path -LiteralPath $archive) { (Get-Item -LiteralPath $archive).Length } else { 0 }
                    if ($received -gt [long]$Record.bytes) { $client.CancelAsync() }
                    if ($form) {
                        [Windows.Forms.Application]::DoEvents()
                        if ($form.IsDisposed) { $client.CancelAsync() }
                        else {
                            $progress.Value = [math]::Min(100, [int](100 * $received / [long]$Record.bytes))
                            $label.Text = "Downloading components: $([math]::Floor($received / 1MB)) of $size MB"
                        }
                    }
                    if ($timer.Elapsed.TotalMinutes -gt 15) { $client.CancelAsync() }
                    Start-Sleep -Milliseconds 100
                }
                $download.GetAwaiter().GetResult()
            } finally { $client.Dispose() }
        }
        if ($form) {
            if ($form.IsDisposed) { throw [OperationCanceledException]::new('Setup cancelled.') }
            $label.Text = 'Verifying and unpacking SceneLight...'
            $form.ControlBox = $false
            [Windows.Forms.Application]::DoEvents()
        }
        Expand-VerifiedRelease $archive $stage $Record
        Remove-Item -LiteralPath $archive -Force
        [IO.File]::WriteAllText((Join-Path $stage 'verified.sha256'), $Record.sha256)
        # Publish only a complete, verified tree. Interrupted downloads leave no installed app.
        Move-Item -LiteralPath $stage -Destination $target
        $stage = $null
        return $app
    } finally {
        if ($form -and -not $form.IsDisposed) { $form.Dispose() }
        if ($stage -and (Test-Path -LiteralPath $stage)) {
            $resolved = (Resolve-Path -LiteralPath $stage).Path
            $prefix = $Root.TrimEnd('\') + '\pending-'
            if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected staging cleanup path.' }
            Remove-Item -LiteralPath ('\\?\' + $resolved) -Recurse -Force
        }
        if ($lock) { $lock.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $record = Read-ReleaseManifest $ManifestPath
        $app = Install-SceneLightRelease $record $CacheRoot (Split-Path -Parent ([IO.Path]::GetFullPath($ManifestPath))) -Quiet:$Headless
        if ($InstallOnly) { Write-Output $app }
        else {
            $start = @{ FilePath = (Join-Path $app 'SceneLight.exe'); WorkingDirectory = $app; Wait = $true; PassThru = $true }
            if ($env:SCENELIGHT_LAUNCH_ARGUMENTS) { $start.ArgumentList = $env:SCENELIGHT_LAUNCH_ARGUMENTS }
            # This is the interactive application requested by the user.
            $process = Start-Process @start
            exit $process.ExitCode
        }
    } catch [OperationCanceledException] {
        exit 0
    } catch {
        if (-not $Headless) {
            Add-Type -AssemblyName System.Windows.Forms
            [Windows.Forms.MessageBox]::Show("$($_.Exception.Message)`n`nReopen this installer to retry, or use the offline ZIP.", 'SceneLight setup', 'OK', 'Error') | Out-Null
        }
        Write-Error $_
        exit 1
    }
}
