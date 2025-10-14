@echo off
echo ========================================
echo   TireShop - Building Executable
echo ========================================
echo.

echo Step 1: Installing PyInstaller...
pip install pyinstaller
if %errorlevel% neq 0 (
    echo ERROR: Failed to install PyInstaller
    pause
    exit /b 1
)

echo.
echo Step 2: Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo Step 3: Building executable...
pyinstaller --clean tire_shop.spec
if %errorlevel% neq 0 (
    echo ERROR: Failed to build executable
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
echo The executable is located at:
echo   dist\TireShop.exe
echo.
echo You can now distribute this file to users.
echo They can run it without installing Python or any libraries.
echo.
pause
