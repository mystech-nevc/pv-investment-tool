@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title GuangXiaoZhiSuan V1.0

set "ROOT=%~dp0"
set "APPDIR="
if exist "%ROOT%main.py" set "APPDIR=%ROOT%"
for /d %%D in ("%ROOT%*") do if exist "%%D\main.py" set "APPDIR=%%D\"
if not defined APPDIR goto NOAPP
cd /d "%APPDIR%"

echo ============================================
echo    GuangXiaoZhiSuan V1.0
echo ============================================
echo App folder : %APPDIR%
echo.

set "PYOUT="
for /f "delims=" %%P in ('python -c "print(12345)" 2^>nul') do set "PYOUT=%%P"
if not "!PYOUT!"=="12345" goto NOPYTHON

if exist ".venv\Scripts\python.exe" goto CHECK_PKG

echo [1/4] Creating virtual environment .venv ...
python -m venv .venv
if errorlevel 1 goto VENV_FAIL

:CHECK_PKG
".venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
if not errorlevel 1 goto RUN

echo [2/4] Installing dependencies, first run 2-5 minutes ...
echo       Please keep this window open.
".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto PIP_FAIL
".venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
if errorlevel 1 goto PIP_FAIL

:RUN
set "CRED=%USERPROFILE%\.streamlit\credentials.toml"
if exist "%CRED%" goto CRED_OK
if exist "%USERPROFILE%\.streamlit" goto MAKE_CRED
mkdir "%USERPROFILE%\.streamlit" >nul 2>nul
:MAKE_CRED
echo [general]> "%CRED%"
echo email = "">> "%CRED%"
:CRED_OK
echo [3/4] Environment ready.
echo [4/4] Starting software, browser will open http://localhost:8501
echo       Press Ctrl + C to stop.
echo.
".venv\Scripts\python.exe" -m streamlit run main.py --browser.gatherUsageStats false

echo.
echo Software stopped.
pause
exit /b 0

:NOAPP
echo [ERROR] main.py not found. Checked: %ROOT%
echo Put this bat in the same folder as main.py.
pause
exit /b 1

:NOPYTHON
echo [ERROR] Python is not available on this computer.
echo.
echo Install it with one of these:
echo   1) winget install -e --id Python.Python.3.12 --source winget
echo   2) https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
echo      During setup CHECK "Add python.exe to PATH".
echo.
echo After install, CLOSE this window, open a NEW cmd, run: python --version
echo If it prints Python 3.12.x, double click this bat again.
echo.
pause
exit /b 1

:VENV_FAIL
echo [ERROR] Failed to create .venv
echo Python may be the Microsoft Store stub. Run: python --version
echo If it says "not found", install real Python first.
pause
exit /b 1

:PIP_FAIL
echo [ERROR] Failed to install dependencies.
echo Try another mirror source:
echo   ".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.mirrors.ustc.edu.cn/simple
echo.
pause
exit /b 1
