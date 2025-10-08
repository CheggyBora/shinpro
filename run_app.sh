#!/bin/bash

# Запускаем x11vnc с автоматическим созданием X дисплея
x11vnc -forever -nopw -rfbport 5900 -shared -create &

# Ждём пока создастся X дисплей
sleep 3

# Ждём создания X display и автоматически определяем его
# Ищем последний (самый свежий) Xvfb созданный x11vnc
for i in {1..10}; do
  XVFB_INFO=$(ps aux | grep 'Xvfb.*-auth' | grep -v grep | tail -1)
  if [ -n "$XVFB_INFO" ]; then
    DISPLAY_NUM=$(echo "$XVFB_INFO" | grep -o 'Xvfb :[0-9]*' | grep -o ':[0-9]*')
    AUTH_FILE=$(echo "$XVFB_INFO" | grep -o '\-auth [^ ]*' | cut -d' ' -f2)
    if [ -n "$DISPLAY_NUM" ] && [ -n "$AUTH_FILE" ]; then
      export DISPLAY=$DISPLAY_NUM
      export XAUTHORITY=$AUTH_FILE
      break
    fi
  fi
  sleep 0.5
done

echo "Using DISPLAY: $DISPLAY"
echo "Using XAUTHORITY: $XAUTHORITY"

# Запускаем window manager
fluxbox 2>&1 | grep -v "Failed to read" &

# Ждём запуска window manager  
sleep 2

# Запускаем приложение с полным логированием
echo "Starting Python application..."
python -u /home/runner/workspace/main.py 2>&1
