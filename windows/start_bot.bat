@echo off
rem Starts the Anvil Helper bot and restarts it automatically if it stops.
rem First run: creates the Python environment and installs everything it needs.
setlocal
cd /d "%~dp0.."

if not exist ".env" (
    echo No .env file found. Copy .env.example to .env and put your bot token in it.
    exit /b 2
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Could not find Python. Install Python 3.10+ from python.org ^(tick "Add to PATH"^).
        exit /b 2
    )
)

echo Installing / updating requirements...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

:loop
echo [%date% %time%] Starting Anvil Helper...
".venv\Scripts\python.exe" -m anvilhelper
set CODE=%errorlevel%
if "%CODE%"=="2" (
    echo Configuration problem - see logs\bot.log. Not restarting.
    exit /b 2
)
echo [%date% %time%] Bot stopped with code %CODE%. Restarting in 15 seconds...
rem ping works as a delay even without a console window (timeout does not)
ping -n 16 127.0.0.1 >nul
goto loop
