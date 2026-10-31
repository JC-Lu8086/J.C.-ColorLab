@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failure
  .venv\Scripts\python.exe -m pip install .
  if errorlevel 1 goto :failure
)
.venv\Scripts\python.exe -m jc_colorlab
if errorlevel 1 goto :failure
exit /b 0
:failure
echo JC ColorLab could not start. Please read the error above.
pause
exit /b 1
