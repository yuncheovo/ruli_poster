@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=slim"

set "VENV=%~dp0.venv\Scripts"
set "PY=%VENV%\python.exe"
set "VER=2.4.17"

if /I "%MODE%"=="full" (
  set "OUT=release\RuliPoster_v%VER%_full"
  set "ZIP=release\RuliPoster_v%VER%_full_win64.zip"
) else (
  set "OUT=release\RuliPoster_v%VER%"
  set "ZIP=release\RuliPoster_v%VER%_win64.zip"
)

echo ========================================
echo  RuliPoster release build v%VER% [%MODE%]
echo ========================================
echo.

if not exist "%PY%" (
  echo [!] Missing .venv — run: python -m venv .venv
  exit /b 1
)

echo [1/4] Install build deps...
"%VENV%\pip.exe" install -q -r requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1

echo [2/4] PyInstaller...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%VENV%\pyinstaller.exe" --noconfirm --clean RuliPoster.spec
if errorlevel 1 (
  echo [!] PyInstaller failed
  exit /b 1
)

if /I "%MODE%"=="full" (
  echo [3/4] Install bundled Chromium ^(offline, ~350MB^)...
  set "PLAYWRIGHT_BROWSERS_PATH=%~dp0dist\RuliPoster\ms-playwright"
  "%PY%" -m playwright install chromium
  if errorlevel 1 (
    echo [!] playwright install chromium failed
    exit /b 1
  )
) else (
  echo [3/4] Skip Chromium — uses system Edge/Chrome on user PC
)

echo [4/4] Assemble release folder...
"%PY%" "%~dp0scripts\assemble_release.py" --ver "%VER%" --mode "%MODE%"
if errorlevel 1 exit /b 1

echo [5/5] 跳过压缩包（按规则不生成 zip）
echo.
echo ========================================
echo  Done [%MODE%]
echo  Folder: %OUT%
echo ========================================
endlocal
