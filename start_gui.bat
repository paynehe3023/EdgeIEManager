@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0run_gui.py"
    exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0run_gui.py"
    exit /b %errorlevel%
)

python "%~dp0run_gui.py"
exit /b %errorlevel%
