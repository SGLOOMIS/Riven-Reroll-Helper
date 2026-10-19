@echo off
rem Start the Riven Reroll Helper overlay. The first run sets up Python and installs the requirements.
cd /d "%~dp0"
call setup.bat || goto :error
.venv\Scripts\python -m riven_helper %*
goto :eof
:error
echo.
echo Setup didn't finish, so the overlay can't start yet.
pause
