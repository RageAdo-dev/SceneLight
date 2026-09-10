param(
    [string]$RequestPath = "$env:USERPROFILE\SceneLight-Remote\tests\ui-request.json"
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

if (-not ("SceneLightRemote.NativeMethods" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace SceneLightRemote {
    public static class NativeMethods {
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll")]
        public static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

        [DllImport("user32.dll")]
        public static extern int GetWindowTextLength(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr hWnd, int command);

        [DllImport("user32.dll")]
        public static extern bool SetCursorPos(int x, int y);

        [DllImport("user32.dll")]
        public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
    }
}
"@
}

function Get-SceneLightWindows {
    $windows = New-Object System.Collections.Generic.List[object]
    $callback = [SceneLightRemote.NativeMethods+EnumWindowsProc] {
        param([IntPtr]$handle, [IntPtr]$parameter)

        if (-not [SceneLightRemote.NativeMethods]::IsWindowVisible($handle)) {
            return $true
        }

        $length = [SceneLightRemote.NativeMethods]::GetWindowTextLength($handle)
        if ($length -le 0) {
            return $true
        }

        $text = New-Object System.Text.StringBuilder ($length + 1)
        [void][SceneLightRemote.NativeMethods]::GetWindowText($handle, $text, $text.Capacity)
        [uint32]$processId = 0
        [void][SceneLightRemote.NativeMethods]::GetWindowThreadProcessId($handle, [ref]$processId)
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue

        $windows.Add([pscustomobject]@{
            Handle = $handle.ToInt64()
            ProcessId = [int]$processId
            ProcessName = if ($process) { $process.ProcessName } else { $null }
            Title = $text.ToString()
        })
        return $true
    }

    [void][SceneLightRemote.NativeMethods]::EnumWindows($callback, [IntPtr]::Zero)
    return @($windows | Sort-Object ProcessName, Title)
}

function Save-SceneLightScreenshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)

    try {
        $graphics.CopyFromScreen(
            $bounds.Left,
            $bounds.Top,
            0,
            0,
            $bitmap.Size,
            [System.Drawing.CopyPixelOperation]::SourceCopy
        )
        $bitmap.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }

    return [pscustomobject]@{
        Path = $Destination
        Left = $bounds.Left
        Top = $bounds.Top
        Width = $bounds.Width
        Height = $bounds.Height
    }
}

function Select-SceneLightWindow {
    param($Request)

    $windows = @(Get-SceneLightWindows)
    if ($Request.ProcessId) {
        return $windows | Where-Object { $_.ProcessId -eq [int]$Request.ProcessId } | Select-Object -First 1
    }
    if ($Request.TitleContains) {
        $needle = [string]$Request.TitleContains
        return $windows | Where-Object { $_.Title.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0 } | Select-Object -First 1
    }
    return $null
}

$root = Join-Path $env:USERPROFILE "SceneLight-Remote"
$screenshots = Join-Path $root "screenshots"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $screenshots, $logs | Out-Null

$request = $null
$result = [ordered]@{
    Id = $null
    Action = $null
    Success = $false
    Timestamp = (Get-Date).ToString("o")
    Message = $null
    ProcessId = $null
    Screenshot = $null
    Windows = @()
}

try {
    if (-not (Test-Path -LiteralPath $RequestPath)) {
        throw "UI request was not found: $RequestPath"
    }

    $requestText = [System.IO.File]::ReadAllText($RequestPath)
    $request = $requestText | ConvertFrom-Json
    $result.Id = [string]$request.Id
    $result.Action = [string]$request.Action

    switch ([string]$request.Action) {
        "snapshot" {
            $result.Message = "Desktop captured."
        }
        "activate" {
            $window = Select-SceneLightWindow $request
            if (-not $window) {
                throw "Requested window was not found."
            }
            [void][SceneLightRemote.NativeMethods]::ShowWindowAsync([IntPtr]$window.Handle, 9)
            [void][SceneLightRemote.NativeMethods]::SetForegroundWindow([IntPtr]$window.Handle)
            Start-Sleep -Milliseconds 400
            $result.ProcessId = $window.ProcessId
            $result.Message = "Window activated: $($window.Title)"
        }
        "click" {
            if ($null -eq $request.X -or $null -eq $request.Y) {
                throw "Click requests require X and Y coordinates."
            }
            if ($request.ProcessId -or $request.TitleContains) {
                $window = Select-SceneLightWindow $request
                if (-not $window) {
                    throw "Requested click target window was not found."
                }
                [void][SceneLightRemote.NativeMethods]::ShowWindowAsync([IntPtr]$window.Handle, 9)
                [void][SceneLightRemote.NativeMethods]::SetForegroundWindow([IntPtr]$window.Handle)
                Start-Sleep -Milliseconds 300
                $result.ProcessId = $window.ProcessId
            }
            [void][SceneLightRemote.NativeMethods]::SetCursorPos([int]$request.X, [int]$request.Y)
            [SceneLightRemote.NativeMethods]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
            [SceneLightRemote.NativeMethods]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
            Start-Sleep -Milliseconds 600
            $result.Message = "Clicked $($request.X),$($request.Y)."
        }
        "keys" {
            $window = Select-SceneLightWindow $request
            if ($window) {
                [void][SceneLightRemote.NativeMethods]::ShowWindowAsync([IntPtr]$window.Handle, 9)
                [void][SceneLightRemote.NativeMethods]::SetForegroundWindow([IntPtr]$window.Handle)
                Start-Sleep -Milliseconds 300
                $result.ProcessId = $window.ProcessId
            }
            [System.Windows.Forms.SendKeys]::SendWait([string]$request.Keys)
            Start-Sleep -Milliseconds 600
            $result.Message = "Keys sent."
        }
        "launch" {
            $path = [string]$request.Path
            if (-not [System.IO.Path]::IsPathRooted($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
                throw "Launch path is not an existing absolute file: $path"
            }
            $startArguments = @{
                FilePath = $path
                PassThru = $true
            }
            if ($request.Arguments) {
                $startArguments.ArgumentList = [string]$request.Arguments
            }
            if ($request.WorkingDirectory) {
                $startArguments.WorkingDirectory = [string]$request.WorkingDirectory
            }
            $process = Start-Process @startArguments
            $result.ProcessId = $process.Id
            $waitMilliseconds = if ($request.WaitMilliseconds) { [int]$request.WaitMilliseconds } else { 1500 }
            Start-Sleep -Milliseconds $waitMilliseconds
            $result.Message = "Process launched: $path"
        }
        default {
            throw "Unsupported UI action: $($request.Action)"
        }
    }

    $safeId = if ($result.Id -match "^[A-Za-z0-9_.-]+$") { $result.Id } else { (Get-Date -Format "yyyyMMdd-HHmmss-fff") }
    $screenshotPath = Join-Path $screenshots ("{0}-{1}.png" -f $safeId, $result.Action)
    $result.Screenshot = Save-SceneLightScreenshot -Destination $screenshotPath
    $result.Windows = @(Get-SceneLightWindows)
    $result.Success = $true
}
catch {
    $result.Message = $_.Exception.Message
}
finally {
    $result.Timestamp = (Get-Date).ToString("o")
    $resultName = if ($result.Id -and $result.Id -match "^[A-Za-z0-9_.-]+$") {
        "ui-result-$($result.Id).json"
    }
    else {
        "ui-result-error.json"
    }
    $resultPath = Join-Path $logs $resultName
    $json = $result | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($resultPath, $json, (New-Object System.Text.UTF8Encoding($false)))
}
