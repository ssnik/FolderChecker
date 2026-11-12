@echo off
REM Запуск FolderChecker без окна консоли
cd /d "%~dp0"
start "" pythonw.exe folder_monitor.py
