@echo off
rem First-run setup for Riven Reroll Helper, used by "Riven Helper.bat".
rem Finds Python 3.10+ (offering to install it if there is none), creates the Python environment in
rem .venv and installs everything in requirements.txt. After a successful install it keeps a copy of
rem requirements.txt in .venv, so later runs start straight away, and it installs again if
rem requirements.txt changes or an install didn't finish.
setlocal
cd /d "%~dp0"
set "MARKER=.venv\requirements.installed"

if exist .venv\Scripts\python.exe goto :have_venv

call :find_python
if not defined PY call :install_python
if not defined PY exit /b 1
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


rem --- Python 3.10+: the "py" launcher, "python", or a per-user install not on PATH yet ----------
:find_python
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && (set "PY=py -3" & exit /b 0)
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && (set "PY=python" & exit /b 0)
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" "%%D\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set PY="%%D\python.exe"
)
exit /b 0

rem --- no Python: offer to install it with winget (built into Windows 10 and 11) -----------------
:install_python
echo Riven Helper needs Python 3.10 or newer, which isn't installed.
where winget >nul 2>&1 || goto :install_by_hand
echo.
echo It can install Python 3.12 for you now: free, from python.org, just for your Windows user
echo (no administrator rights needed). This accepts Python's license terms.
choice /c YN /m "Install Python now"
if errorlevel 2 goto :install_by_hand
winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY exit /b 0
echo.
echo Python was installed, but this window can't see it yet. Close it and start Riven Helper again.
exit /b 0

:install_by_hand
echo.
echo Install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then start Riven Helper again.
exit /b 0
