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

rem Ambil versi terbaru dari GitHub (branch main), lihat update.ps1. Kalau ada pembaruan, file ini
rem dijalankan ulang dari awal (cmd membaca .bat sepotong-sepotong, jadi jangan lanjut di file yang sudah berubah).
rem Satu blok ( ) dibaca utuh oleh cmd sebelum dijalankan, jadi aman walau jarvis.bat ikut berubah.
(
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
  if errorlevel 2 (
    call "%~f0" %*
    exit /b
  )
)

if /i "%~1"=="debug" (
  "%PYC%" jarvis.py
  pause
  exit /b
)

start "" "%PYW%" jarvis.py
