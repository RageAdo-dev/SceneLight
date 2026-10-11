param([switch]$RequireSigning)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($env:SCENELIGHT_CERT_PFX)) {
    if ($RequireSigning) { throw 'Signing is required but WINDOWS_CERT_PFX is missing.' }
    Write-Output 'Building unsigned launchers.'
    exit 0
}

$pfx = Join-Path ([IO.Path]::GetTempPath()) ("scenelight-signing-" + [guid]::NewGuid() + '.pfx')
$cert = $null
try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SCENELIGHT_CERT_PFX))
    $password = ConvertTo-SecureString -String $env:SCENELIGHT_CERT_PASSWORD -Force -AsPlainText
    $cert = Import-PfxCertificate -FilePath $pfx -CertStoreLocation Cert:\CurrentUser\My -Password $password
    foreach ($name in @('scenelight-desktop.exe', 'scenelight-launcher.exe')) {
        $exe = Join-Path $root "src\scenelight\assets\$name"
        $signature = Set-AuthenticodeSignature -LiteralPath $exe -Certificate $cert `
            -HashAlgorithm SHA256 -TimestampServer 'http://timestamp.digicert.com'
        if ($signature.Status -ne 'Valid') { throw "Signing failed for $name ($($signature.Status))" }
        Write-Output "Signed $name"
    }
} finally {
    if (Test-Path -LiteralPath $pfx) { Remove-Item -LiteralPath $pfx -Force }
    if ($null -ne $cert) { Remove-Item -LiteralPath ("Cert:\CurrentUser\My\" + $cert.Thumbprint) -Force }
}
