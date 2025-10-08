#!/bin/bash

export DISPLAY=:99

xvfb-run -a -s "-screen 0 1280x800x24" fluxbox &
sleep 2

x11vnc -display :99 -forever -nopw -rfbport 5900 -shared -create &
sleep 2

DISPLAY=:99 python main.py
