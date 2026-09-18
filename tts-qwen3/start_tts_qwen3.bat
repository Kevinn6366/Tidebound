@echo off
chcp 65001 >nul
title GWC Built-in TTS (Qwen3-TTS)
setlocal

rem ==========================================================
rem GWC Qwen3-TTS launcher.
rem Uses a CLONED runtime (tts-qwen3\env, copied from backend\runtime
rem by the one-click installer), so users do NOT need to install Python.
rem Override with:  set GWC_QWEN_TTS_RUNTIME=D:\path\to\python.exe
rem Default model: Qwen/Qwen3-TTS-12Hz-1.7B-Base (set GWC_QWEN_TTS_MODEL for 0.6B)
rem NOTE: keep this file CRLF + ASCII, cmd.exe misparses LF batch files.
rem ==========================================================

set "TTS_ROOT=%~dp0"
set "SERVER_DIR=%TTS_ROOT%server"

rem ---- Python runtime (cloned from backend\runtime, python.exe at env root) ----
if not defined GWC_QWEN_TTS_RUNTIME (
    set "GWC_QWEN_TTS_RUNTIME=%TTS_ROOT%env\python.exe"
)

rem ---- model id ----
if not defined GWC_QWEN_TTS_MODEL (
    set "GWC_QWEN_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-Base"
)

if not exist "%GWC_QWEN_TTS_RUNTIME%" (
    echo [ERROR] Python runtime not found:
    echo         %GWC_QWEN_TTS_RUNTIME%
    echo.
    echo The Qwen3-TTS environment is created by the one-click installer
    echo in GWC settings (Sound tab - select Qwen3-TTS - one-click install).
    echo It clones the bundled backend\runtime, so no external Python is needed.
    echo.
    echo Or set GWC_QWEN_TTS_RUNTIME to an existing python.exe with qwen-tts installed.
    echo.
    pause
    exit /b 1
)

if not exist "%SERVER_DIR%\api.py" (
    echo [ERROR] TTS server files missing: %SERVER_DIR%\api.py
    pause
    exit /b 1
)

echo =========================================
echo    GWC Qwen3-TTS  (port 9881)
echo =========================================
echo Runtime: %GWC_QWEN_TTS_RUNTIME%
echo Model  : %GWC_QWEN_TTS_MODEL%
echo Server : %SERVER_DIR%
echo.

cd /d "%SERVER_DIR%"
"%GWC_QWEN_TTS_RUNTIME%" api.py -a 127.0.0.1 -p 9881 --model "%GWC_QWEN_TTS_MODEL%"

echo.
echo [Qwen3-TTS stopped]
pause