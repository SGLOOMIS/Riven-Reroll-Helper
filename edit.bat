@echo off
rem Open the roll-file editor. The first run sets up Python and installs the requirements.
cd /d "%~dp0"
call setup.bat || goto :error
start "" .venv\Scripts\pythonw -m riven_helper --edit %*
goto :eof
:error
echo.
echo Setup didn't finish, so the editor can't start yet.
pause
