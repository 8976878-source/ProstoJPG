@echo off
setlocal
echo ProstoJPG: installing the Codex plugin and its skills.
echo The extension store will open in installed Chrome and Yandex browsers.
echo Confirm Add extension in each browser.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0setup\install.ps1"
set "ProstoJpgExit=%ERRORLEVEL%"
if not "%ProstoJpgExit%"=="0" echo Setup failed. See the error above.
pause
exit /b %ProstoJpgExit%
