@echo off
REM Build HECTOR Desktop as a standalone Windows executable.
REM
REM Run from PowerShell or cmd (no conda activate, no bash, no exec policy):
REM     .\windows_app.cmd
REM
REM Calls the `sc` env's Python directly. Override with:
REM     set SC_PYTHON=C:\path\to\python.exe  &&  .\windows_app.cmd
REM
REM Output: dist\HECTOR Desktop\HECTOR Desktop.exe
REM
REM If it fails with PermissionError on ucrtbase.dll, that's 360 / AV blocking
REM PyInstaller. Whitelist this folder or pause real-time protection, then rerun.

setlocal
cd /d "%~dp0"

if "%SC_PYTHON%"=="" set "SC_PYTHON=%USERPROFILE%\miniforge3\envs\sc\python.exe"

echo ==^> Using Python: %SC_PYTHON%
if not exist "%SC_PYTHON%" (
    echo ERROR: Python not found at "%SC_PYTHON%".
    echo        Set SC_PYTHON to your 'sc' env python.exe and rerun.
    exit /b 1
)

"%SC_PYTHON%" -c "import PyInstaller" 1>nul 2>nul
if errorlevel 1 (
    echo ERROR: PyInstaller not installed in that env. Install build deps once:
    echo        "%SC_PYTHON%" -m pip install pyinstaller PySide6 pyqtgraph
    echo        "%SC_PYTHON%" -m pip install -e . -e ..\hector_package
    exit /b 1
)

echo ==^> Cleaning previous build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo ==^> Running PyInstaller (slow during COLLECT - be patient)...
"%SC_PYTHON%" -m PyInstaller --clean hector_desktop.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: Build failed. If you saw "PermissionError ... ucrtbase.dll",
    echo        it's 360 / antivirus. Whitelist this folder or pause protection,
    echo        then run .\windows_app.cmd again.
    exit /b 1
)

if not exist "dist\HECTOR Desktop\HECTOR Desktop.exe" (
    echo ERROR: Build finished but exe is missing - COLLECT likely blocked by AV.
    exit /b 1
)

REM Copy hector-sc resource files (parquets, etc.) into the bundle.
REM On macOS these are resolved from the editable install at runtime;
REM on Windows the bundled app cannot reach back to the source tree.
REM The __init__.py marker is needed so importlib.resources.files("hector")
REM resolves to this directory (the .py modules live in the PYZ archive).
set "HECTOR_RES=..\hector_package\hector\resources"
if exist "%HECTOR_RES%" (
    echo ==^> Copying hector-sc resources into bundle...
    xcopy "%HECTOR_RES%" "dist\HECTOR Desktop\_internal\hector\resources" /E /I /Q /Y >nul
    if not exist "dist\HECTOR Desktop\_internal\hector\__init__.py" (
        echo.> "dist\HECTOR Desktop\_internal\hector\__init__.py"
    )
)

echo ==^> Removing intermediate build folder...
if exist build rmdir /s /q build

echo.
echo ==^> Build complete!
echo     Executable: %CD%\dist\HECTOR Desktop\HECTOR Desktop.exe

REM Extract version from hector_package's pyproject.toml for the installer.
REM Uses findstr (not python -c) because cmd's `for /f ('cmd')` syntax mangles
REM embedded double quotes around %SC_PYTHON%, leaving APP_VERSION empty.
set "APP_VERSION="
set "HECTOR_PYPROJECT=..\hector_package\pyproject.toml"
if not exist "%HECTOR_PYPROJECT%" set "HECTOR_PYPROJECT=pyproject.toml"
for /f "usebackq tokens=3" %%v in (`findstr /B /C:"version = " "%HECTOR_PYPROJECT%"`) do set "APP_VERSION=%%v"
set APP_VERSION=%APP_VERSION:"=%
if "%APP_VERSION%"=="" (
    echo ERROR: Could not read version from "%HECTOR_PYPROJECT%". Skipping installer.
    goto :skip_installer
)
echo     Version:    %APP_VERSION%

set "INSTALLER=release\HECTOR-Desktop-%APP_VERSION%-Setup.exe"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo NOTE: Inno Setup not found. To build the installer:
    echo       1. Install Inno Setup: https://jrsoftware.org/isdl.php
    echo       2. Run: "%ISCC%" /DMyAppVersion=%APP_VERSION% installer.iss
    goto :skip_installer
)

echo.
echo ==^> Building Windows installer...
"%ISCC%" /DMyAppVersion=%APP_VERSION% installer.iss
if errorlevel 1 (
    echo ERROR: Installer build failed. Leaving dist\ in place for inspection.
    goto :skip_installer
)
if not exist "%INSTALLER%" (
    echo ERROR: ISCC reported success but "%INSTALLER%" is missing. Leaving dist\ in place.
    goto :skip_installer
)
echo     Installer: %CD%\%INSTALLER%

REM dist\ is now packed into the installer .exe, so it is no longer needed.
echo ==^> Removing dist\ folder (now bundled into the installer)...
if exist dist rmdir /s /q dist

echo.
echo Done. To test, run the installer:
echo     %CD%\%INSTALLER%
goto :end

:skip_installer
echo.
echo To test:
echo     ^& ".\dist\HECTOR Desktop\HECTOR Desktop.exe"

:end
endlocal
