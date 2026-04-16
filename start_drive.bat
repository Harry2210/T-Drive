@echo off
:: ================================================================
::  T-Drive — Windows Auto-Start Script
::  Mounts the virtual drive and launches the app.
::
::  To auto-start on login, place a shortcut to this file in:
::    %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
:: ================================================================

title T-Drive — Telegram Cloud Drive

:: ---- Configuration ----
set DRIVE_LETTER=G
set LOCAL_FOLDER=C:\TelegramDrive
set SCRIPT_DIR=%~dp0

:: ---- Ensure folder exists ----
if not exist "%LOCAL_FOLDER%" mkdir "%LOCAL_FOLDER%"

:: ---- Mount the virtual drive ----
echo [*] Mounting %DRIVE_LETTER%: -^> %LOCAL_FOLDER% ...
subst %DRIVE_LETTER%: "%LOCAL_FOLDER%" 2>nul
echo [+] Drive %DRIVE_LETTER%: ready.

:: ---- Start the app ----
echo [*] Launching T-Drive ...
cd /d "%SCRIPT_DIR%"
python main.py

:: Keep window open on error
if errorlevel 1 (
    echo.
    echo [!] T-Drive exited with an error.
    pause
)
