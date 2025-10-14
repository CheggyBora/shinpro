@echo off
chcp 65001 >nul
echo ========================================
echo   Шиномонтаж - Система учёта
echo ========================================
echo.
echo Запуск приложения...
echo.

python main.py

if %errorlevel% neq 0 (
    echo.
    echo ОШИБКА: Не удалось запустить приложение!
    echo.
    echo Возможные причины:
    echo 1. Python не установлен
    echo 2. Не установлены библиотеки (выполните: pip install -r requirements.txt)
    echo.
    pause
    exit /b %errorlevel%
)

pause
