#!/bin/bash

# Запускаем x11vnc с автоматическим созданием X дисплея
x11vnc -forever -nopw -rfbport 5900 -shared -create &

# Ждём пока создастся X дисплей
sleep 3

# Ждём создания X display и автоматически определяем его
# Ищем последний (самый свежий) Xvfb созданный x11vnc
for i in {1..10}; do
  DISPLAY_NUM=$(ps aux | grep 'Xvfb.*-auth' | grep -v grep | grep -o 'Xvfb :[0-9]*' | grep -o ':[0-9]*' | tail -1)
  if [ -n "$DISPLAY_NUM" ]; then
    export DISPLAY=$DISPLAY_NUM
    break
  fi
  sleep 0.5
done

echo "Using DISPLAY: $DISPLAY"

# Запускаем window manager
fluxbox 2>&1 | grep -v "Failed to read" &

# Ждём запуска window manager  
sleep 2

# Запускаем приложение с полным логированием
echo "Starting Python application..."
python -u /home/runner/workspace/main.py 2>&1
