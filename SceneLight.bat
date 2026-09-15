@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0SceneLight.exe" (
  start "" "%~dp0SceneLight.exe"
  exit /b 0
)

set "SCENELIGHT_APP=%~dp0_scenelight"
if not exist "%SCENELIGHT_APP%\scenelight_setup.pyw" set "SCENELIGHT_APP=%~dp0"

set "SCENELIGHT_PRIVATE_PYTHON=%LOCALAPPDATA%\SceneLight\bootstrap-python\pythonw.exe"
if exist "%SCENELIGHT_PRIVATE_PYTHON%" (
  start "" "%SCENELIGHT_PRIVATE_PYTHON%" "%SCENELIGHT_APP%\scenelight_setup.pyw"
  exit /b 0
)

where pyw >nul 2>nul
if %errorlevel%==0 (
  pyw -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
  if not errorlevel 1 (
    start "" pyw -3 "%SCENELIGHT_APP%\scenelight_setup.pyw"
    exit /b 0
  )
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
  pythonw -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
  if not errorlevel 1 (
    start "" pythonw "%SCENELIGHT_APP%\scenelight_setup.pyw"
    exit /b 0
  )
)

set "SCENELIGHT_INSTALLER="
for %%I in ("%SCENELIGHT_APP%\runtime-installer\python-*-amd64.exe") do if exist "%%~fI" set "SCENELIGHT_INSTALLER=%%~fI"
if not defined SCENELIGHT_INSTALLER goto :online_python

echo SceneLight needs its bundled Python runtime to open.
choice /M "Install it for this Windows account now"
if errorlevel 2 exit /b 1

powershell.exe -NoProfile -Command "$s=Get-AuthenticodeSignature -LiteralPath $env:SCENELIGHT_INSTALLER; if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'Python Software Foundation'){exit 0}; Write-Error 'The bundled Python installer does not have a valid Python Software Foundation signature.'; exit 1"
if errorlevel 1 (
  echo SceneLight refused to run an unverified runtime installer.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCENELIGHT_APP%\tools\bootstrap_python.ps1" -InstallerPath "%SCENELIGHT_INSTALLER%"
if errorlevel 1 (
  echo The SceneLight runtime was not installed.
  pause
  exit /b 1
)
if not exist "%SCENELIGHT_PRIVATE_PYTHON%" (
  echo Python finished without creating the expected SceneLight runtime.
  pause
  exit /b 1
)
start "" "%SCENELIGHT_PRIVATE_PYTHON%" "%SCENELIGHT_APP%\scenelight_setup.pyw"
exit /b 0

:online_python
echo SceneLight needs its runtime on this computer.
echo.
echo SceneLight will download Python 3.11.9 from python.org, verify its exact
echo SHA-256 checksum and Python Software Foundation signature, then install it
echo only under:
echo   %LOCALAPPDATA%\SceneLight\bootstrap-python
echo.
echo It will not be added to PATH, associated with files, or installed for
echo other users.
choice /M "Download and install SceneLight runtime now"
if errorlevel 2 exit /b 1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCENELIGHT_APP%\tools\bootstrap_python.ps1"
if errorlevel 1 (
  echo SceneLight could not install its runtime.
  pause
  exit /b 1
)
if not exist "%SCENELIGHT_PRIVATE_PYTHON%" (
  echo Python finished without creating the expected SceneLight runtime.
  pause
  exit /b 1
)
start "" "%SCENELIGHT_PRIVATE_PYTHON%" "%SCENELIGHT_APP%\scenelight_setup.pyw"
exit /b 0
