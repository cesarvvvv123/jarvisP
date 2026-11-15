@echo off
rem Jalankan Jarvis.
rem   jarvis.bat         tanpa jendela konsol (seperti shortcut Desktop)
rem   jarvis.bat debug   dengan konsol, error Python terlihat
cd /d "%~dp0"

set "PYW=pythonw"
set "PYC=python"
set "PYDIR=%LOCALAPPDATA%\Programs\Python\Python312"
if exist "%PYDIR%\pythonw.exe" (
  set "PYW=%PYDIR%\pythonw.exe"
  set "PYC=%PYDIR%\python.exe"
)

rem Cegah dua Jarvis sekaligus (rebutan mikrofon)
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'jarvis\.py' }) { exit 1 }"
if errorlevel 1 (
  echo Jarvis sudah berjalan.
  ping -n 4 127.0.0.1 >nul
  exit /b 0
)

if /i "%~1"=="debug" (
  "%PYC%" jarvis.py
  pause
  exit /b
)

start "" "%PYW%" jarvis.py
