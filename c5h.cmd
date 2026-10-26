@echo off
rem c5h without installing anything: python -m civ5headless with python\ on PYTHONPATH.
rem Works from a checkout and from an unpacked release kit. The Python used is the first of:
rem   C5H_PYTHON (a python.exe), the kit's own runtime\python.exe, python on PATH, the py launcher.
setlocal
set "C5H_PYARGS="
if not defined C5H_PYTHON if exist "%~dp0runtime\python.exe" set "C5H_PYTHON=%~dp0runtime\python.exe"
if not defined C5H_PYTHON (
    where python >nul 2>nul && set "C5H_PYTHON=python"
)
if not defined C5H_PYTHON (
    where py >nul 2>nul && set "C5H_PYTHON=py" && set "C5H_PYARGS=-3"
)
if not defined C5H_PYTHON (
    echo c5h: Python 3.11 or newer is needed: install it from python.org, or set C5H_PYTHON to a python.exe 1>&2
    exit /b 2
)
set "PYTHONPATH=%~dp0python;%PYTHONPATH%"
"%C5H_PYTHON%" %C5H_PYARGS% -m civ5headless %*
exit /b %ERRORLEVEL%
