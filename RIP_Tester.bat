@echo off
REM Launch the SAI RIP/CMS Tester GUI (no CLI needed)
cd /d "%~dp0"
python "%~dp0rip_tester.py"
if errorlevel 1 pause
