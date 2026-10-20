@echo off
rem First-run setup for Riven Reroll Helper, used by "Riven Helper.bat".
rem Creates the Python environment in .venv and installs everything in requirements.txt.
rem After a successful install it keeps a copy of requirements.txt in .venv, so later runs start
rem straight away, and it installs again if requirements.txt changes or an install didn't finish.
setlocal
cd /d "%~dp0"
set "MARKER=.venv\requirements.installed"

if exist .venv\Scripts\python.exe goto :have_venv

rem --- find Python 3.10+ (the "py" launcher first, then "python") ---------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo Python 3.10 or newer was not found.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
    echo then run this again.
    exit /b 1
)
echo First run: creating the Python environment ^(.venv^)...
%PY% -m venv .venv || (echo Could not create .venv. & exit /b 1)

:have_venv
if exist "%MARKER%" (
    fc /b requirements.txt "%MARKER%" >nul 2>&1 && exit /b 0
)
echo Installing requirements (first run or requirements.txt changed). This can take a few minutes...
.venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installing the requirements failed - check your internet connection and run this again.
    exit /b 1
)
.venv\Scripts\python -c "import mss, PIL, numpy, cv2, winrt.windows.media.ocr" || (
    echo The requirements installed but can't be loaded - run this again, or delete the .venv folder and retry.
    exit /b 1
)
copy /y requirements.txt "%MARKER%" >nul
echo Setup complete.
exit /b 0
