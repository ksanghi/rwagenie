@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM  RWAGenie — Windows packaging build
REM
REM  Pipeline:
REM    1. Nuitka --standalone compiles main.py + every package it imports
REM       to a real Windows binary in build\output\main.dist\. AG's core/
REM       and ui/ modules come from the sibling Aiccounting/ folder via
REM       PYTHONPATH (set below); Nuitka traces them as if they were
REM       in-tree and bakes them into the binary, so the installer is
REM       self-contained — the customer machine does NOT need AccGenie
REM       installed.
REM    2. Inno Setup 6 wraps that folder into a single
REM       RWAGenie-Setup-X.Y.Z.exe.
REM
REM  Prerequisites (one-time, same as AccGenie's build):
REM    • pip install nuitka pyside6 (the runtime deps RWAGenie inherits
REM      from AG: pdfplumber / openpyxl / python-docx / requests / razorpay)
REM    • Inno Setup 6  (https://jrsoftware.org/isdl.php)
REM    • C compiler — Nuitka prompts to download MinGW on first run.
REM    • The Aiccounting repo cloned as a SIBLING:
REM         eclipse-workspace\
REM             ├── Aiccounting\     <- AG engine
REM             └── rwagenie\        <- this repo (you run build from here)
REM
REM  Run from this repo's root:    build\build.bat
REM ──────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

set APP_NAME=RWAGenie
set VERSION=0.1.2
set OUTPUT_DIR=build\output
set DIST_DIR=build\dist

REM Locate the sibling AccGenie repo — main.py expects ..\Aiccounting.
REM ACCGENIE_PATH env-var override lets CI / non-standard checkouts point
REM at the engine wherever it lives.
if defined ACCGENIE_PATH (
    set "AG_PATH=%ACCGENIE_PATH%"
) else (
    set "AG_PATH=%~dp0..\..\Aiccounting"
)

if not exist "!AG_PATH!\core\models.py" (
    echo *** AccGenie engine not found at !AG_PATH!
    echo     Expected the Aiccounting repo as a sibling folder, or set
    echo     ACCGENIE_PATH to its root.
    exit /b 1
)
echo === AccGenie engine source: !AG_PATH!

REM Put AG on PYTHONPATH so Nuitka resolves 'from core.*' / 'from ui.*'
REM during its import-tracing pass. Same mechanism main.py uses at
REM runtime in dev mode.
set "PYTHONPATH=!AG_PATH!;%~dp0..;%PYTHONPATH%"

echo.
echo === [1/2]  Compiling with Nuitka  (5-15 minutes) ===
echo.

python -m nuitka ^
    --standalone ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=core.migration ^
    --include-package=ui ^
    --include-package=ai ^
    --include-package=app ^
    --include-package=app.pages ^
    --include-package=app.services ^
    --include-data-files="!AG_PATH!/ui/AccGenie final logo.png=ui/AccGenie final logo.png" ^
    --windows-console-mode=disable ^
    --output-dir=%OUTPUT_DIR% ^
    --output-filename=%APP_NAME%.exe ^
    --remove-output ^
    --assume-yes-for-downloads ^
    --product-name=%APP_NAME% ^
    --product-version=%VERSION% ^
    --file-version=%VERSION% ^
    --file-description="RWAGenie - Resident Welfare Association management" ^
    --copyright="(c) 2026 Aiccounting" ^
    main.py

if errorlevel 1 (
    echo.
    echo *** Nuitka build failed. See output above. ***
    exit /b 1
)

echo.
echo === [2/2]  Building installer with Inno Setup ===
echo.

set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"      set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if "!ISCC!"=="" (
    where iscc.exe >nul 2>&1
    if not errorlevel 1 set ISCC=iscc.exe
)

if "!ISCC!"=="" (
    echo *** ISCC.exe not found. Install Inno Setup 6 from
    echo     https://jrsoftware.org/isdl.php  and re-run.
    exit /b 1
)

if not exist %DIST_DIR% mkdir %DIST_DIR%

!ISCC! /Qp ^
    "/DAppName=%APP_NAME%" ^
    "/DAppVersion=%VERSION%" ^
    build\installer.iss

if errorlevel 1 (
    echo *** Inno Setup build failed. ***
    exit /b 1
)

echo.
echo === Done. Installer at:  %DIST_DIR%\%APP_NAME%-Setup-%VERSION%.exe ===
echo.

REM Best-effort WhatsApp ping — silent no-op if CallMeBot env vars unset.
REM Re-uses the AccGenie tools/ script via the AG sibling folder.
if exist "!AG_PATH!\tools\wa_notify.py" (
    python "!AG_PATH!\tools\wa_notify.py" "RWAGenie %VERSION% built. %DIST_DIR%\%APP_NAME%-Setup-%VERSION%.exe is ready." 2>nul
)

endlocal
