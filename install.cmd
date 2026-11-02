@echo off
rem Starts the graphical installer. Needs Python 3 from python.org (with tkinter, default option).
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw installer.pyw & exit /b)
where pythonw >nul 2>nul && (start "" pythonw installer.pyw & exit /b)
echo Python 3 was not found. Please install it from https://www.python.org/downloads/
echo or follow the manual installation in docs\MANUAL_INSTALL.md.
pause
