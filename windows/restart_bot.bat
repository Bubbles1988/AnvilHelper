@echo off
rem Restarts the scheduled-task bot (e.g. after update_data.bat). Run as administrator.
schtasks /End /TN "AnvilHelper Discord Bot" >nul 2>&1
rem Ending the task stops cmd.exe; also stop the Python process it started.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%-m anvilhelper%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
schtasks /Run /TN "AnvilHelper Discord Bot"
echo Bot restarted.
