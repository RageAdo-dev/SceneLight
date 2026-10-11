param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$Config,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$RenPy,
    [Parameter(Mandatory = $true)][string]$ResultPath,
    [Parameter(Mandatory = $true)][string]$LogPath
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = $SourceRoot
$started = [DateTimeOffset]::Now
$exitCode = 1
$errorText = $null
try {
    & $Python -m scenelight install `
        --project $Project `
        --config $Config `
        --renpy-sdk $RenPy `
        --analyzer cpu 2>&1 |
        Tee-Object -FilePath $LogPath | Out-Null
    $exitCode = $LASTEXITCODE
}
catch {
    $errorText = $_.Exception.ToString()
}
$finished = [DateTimeOffset]::Now
$payload = @{
    started = $started.ToString("o")
    finished = $finished.ToString("o")
    elapsed_seconds = ($finished - $started).TotalSeconds
    exit_code = $exitCode
    error = $errorText
}
$json = $payload | ConvertTo-Json
[IO.File]::WriteAllText($ResultPath, $json, (New-Object Text.UTF8Encoding($false)))
