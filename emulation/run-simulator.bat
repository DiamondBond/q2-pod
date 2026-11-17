@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 is required. Install Python from https://www.python.org/downloads/
    echo Enable "Add python.exe to PATH" and Tcl/Tk during installation.
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

%PYTHON% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo Python's Tkinter is missing. Install Python with Tcl/Tk enabled.
  pause
  exit /b 1
)

if not exist "emulation\.venv-simulator\Scripts\python.exe" (
  echo Creating simulator virtual environment...
  %PYTHON% -m venv "emulation\.venv-simulator"
  if errorlevel 1 goto :failed
)

"emulation\.venv-simulator\Scripts\python.exe" -c "import PIL, mutagen, fontTools, unicorn, elftools" >nul 2>nul
if errorlevel 1 (
  echo Installing simulator Python dependencies...
  "emulation\.venv-simulator\Scripts\python.exe" -m pip install -r emulation\requirements-simulator.txt
  if errorlevel 1 goto :failed
)
"emulation\.venv-simulator\Scripts\python.exe" emulation\simulator.py %*
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Simulator could not start. Check the error above.
pause
exit /b 1
