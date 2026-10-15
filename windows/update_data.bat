@echo off
rem Re-reads data\source\Anvil_Helper.xlsx into the bot's data files.
rem Afterwards restart the bot (windows\restart_bot.bat) so it picks up the changes.
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" tools\import_xlsx.py %*
pause
