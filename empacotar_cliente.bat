@echo off
cd /d "%~dp0"
python empacotar_cliente.py
if errorlevel 1 (echo FALHOU) else (echo OK)
pause
