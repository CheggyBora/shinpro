#!/bin/bash

echo "========================================"
echo "  Шиномонтаж - Система учёта"
echo "========================================"
echo ""
echo "Запуск приложения..."
echo ""

python3 main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "ОШИБКА: Не удалось запустить приложение!"
    echo ""
    echo "Возможные причины:"
    echo "1. Python 3 не установлен"
    echo "2. Не установлены библиотеки (выполните: pip3 install -r requirements.txt)"
    echo ""
    read -p "Нажмите Enter для выхода..."
    exit 1
fi
