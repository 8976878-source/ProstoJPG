@echo off
setlocal
echo ProstoJPG: opening the official installation page in Chrome and Yandex.
echo Confirm Add extension in each browser. No hidden installation is performed.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0setup\install.ps1" -ExtensionOnly
set "ProstoJpgExit=%ERRORLEVEL%"
if not "%ProstoJpgExit%"=="0" echo Setup failed. See the error above.
pause
exit /b %ProstoJpgExit%
