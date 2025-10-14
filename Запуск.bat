@echo off
echo ========================================
echo   Tire Shop Management System
echo ========================================
echo.
echo Starting application...
echo.

python main.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to start application!
    echo.
    echo Possible reasons:
    echo 1. Python is not installed
    echo 2. Libraries not installed (run: pip install -r requirements.txt)
    echo.
    pause
    exit /b %errorlevel%
)

pause
