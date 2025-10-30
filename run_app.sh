#!/bin/bash

# Создаём X дисплей без авторизации
export X11VNC_CREATE_XAUTH_FILE=/tmp/xauth_file
x11vnc -forever -nopw -rfbport 5900 -shared -create -env X11VNC_CREATE_GEOM=1280x1024x24 &

# Ждём пока создастся X дисплей
sleep 5

# Ждём создания X display и автоматически определяем его
# Ищем Xvfb процесс созданный x11vnc
for i in {1..15}; do
  XVFB_INFO=$(ps aux | grep '[X]vfb' | tail -1)
  if [ -n "$XVFB_INFO" ]; then
    # Извлекаем номер дисплея (например, :20)
    DISPLAY_NUM=$(echo "$XVFB_INFO" | grep -oP 'Xvfb\s+:\d+' | grep -oP ':\d+')
    # Извлекаем auth файл если есть
    AUTH_FILE=$(echo "$XVFB_INFO" | grep -oP '\-auth\s+\S+' | awk '{print $2}')
    
    if [ -n "$DISPLAY_NUM" ]; then
      export DISPLAY=$DISPLAY_NUM
      if [ -n "$AUTH_FILE" ]; then
        export XAUTHORITY=$AUTH_FILE
      fi
      echo "Found X server on display: $DISPLAY_NUM"
      break
    fi
  fi
  sleep 0.5
done

echo "Using DISPLAY: $DISPLAY"
echo "Using XAUTHORITY: $XAUTHORITY"

# Разрешаем доступ к X серверу через XAUTHORITY файл
if [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
  chmod 644 "$XAUTHORITY" 2>/dev/null || true
fi

# Запускаем window manager
fluxbox 2>&1 | grep -v "Failed to read" &

# Ждём запуска window manager  
sleep 2

# Запускаем приложение с полным логированием
echo "Starting Python application..."
DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY python -u /home/runner/workspace/main.py 2>&1
