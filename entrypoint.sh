#!/bin/bash
set -eu
umask 077
ulimit -c 0
mkdir -p "$HOME/.vnc" /tmp/runtime-wechat /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
export XDG_RUNTIME_DIR=/tmp/runtime-wechat
chmod 700 "$XDG_RUNTIME_DIR"
Xvfb :99 -screen 0 1600x1000x24 -dpi 96 -nolisten tcp &
for i in $(seq 1 50); do xdpyinfo -display :99 >/dev/null 2>&1 && break; sleep .2; done
xdpyinfo -display :99 >/dev/null
openbox >/tmp/openbox.log 2>&1 &
x11vnc -storepasswd "$(cat /run/secrets/vnc_password)" "$HOME/.vnc/passwd" >/dev/null
x11vnc -display :99 -rfbauth "$HOME/.vnc/passwd" -forever -shared -localhost -rfbport 5900 >/tmp/vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
/opt/wechat/wechat --no-sandbox --disable-gpu >>"$HOME/wechat-runtime.log" 2>&1 &
WECHAT_PID=$!
# The bridge is restarted on its own, so updating it never takes WeChat (and its login) down.
( set +e; while true; do /usr/bin/python3 /app/transport.py; sleep 1; done ) &
BRIDGE_PID=$!
trap 'kill "$WECHAT_PID" "$BRIDGE_PID" 2>/dev/null || true' EXIT TERM INT
wait -n "$WECHAT_PID"
exit 1
