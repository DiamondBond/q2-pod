@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (set "PYTHON=py -3") else (set "PYTHON=python")
if not exist ".venv-simulator\Scripts\python.exe" (
  %PYTHON% -m venv ".venv-simulator"
  if errorlevel 1 goto :failed
)
".venv-simulator\Scripts\python.exe" -c "import PIL, unicorn" >nul 2>nul
if errorlevel 1 (
  ".venv-simulator\Scripts\python.exe" -m pip install -r requirements-simulator.txt
  if errorlevel 1 goto :failed
)
".venv-simulator\Scripts\python.exe" tools\arcade_emulator.py %*
if errorlevel 1 goto :failed
exit /b 0
:failed
echo Emulator could not start. Check Python, LLVM clang, ld.lld and readelf.
pause
exit /b 1
