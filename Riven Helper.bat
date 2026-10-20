@echo off
rem Riven Reroll Helper: the roll editor, with the overlay running while it is open.
rem The first run sets up Python and installs the requirements (see setup.bat).
cd /d "%~dp0"
call setup.bat || goto :error
start "" .venv\Scripts\pythonw -m riven_helper %*
goto :eof
:error
echo.
echo Setup didn't finish, so Riven Helper can't start yet.
pause
