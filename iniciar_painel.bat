@echo off
cd /d "%~dp0"
python painel_cbo.py
if errorlevel 1 pause
