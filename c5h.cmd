@echo off
rem c5h from a checkout without installing anything: python -m civ5headless with python\ on PYTHONPATH.
rem C5H_PYTHON names the Python to use (default: python on PATH).
setlocal
if not defined C5H_PYTHON set "C5H_PYTHON=python"
set "PYTHONPATH=%~dp0python;%PYTHONPATH%"
"%C5H_PYTHON%" -m civ5headless %*
exit /b %ERRORLEVEL%
