#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -d /opt/homebrew/bin ]; then export PATH="/opt/homebrew/bin:$PATH"; fi
if [ ! -x .venv/bin/python ]; then
  echo 'Run Setup.command first.'
  read -r -p 'Press Enter to close.'
  exit 1
fi
# Restart-safe: stop a helper that is already running so this script always starts the latest code.
OLD=$(lsof -ti tcp:8765 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$OLD" ] && ps -o command= -p $OLD | grep -q 'unscroll.server'; then
  echo 'Stopping the running helper...'
  kill $OLD
  for i in 1 2 3 4 5 6 7 8 9 10; do
    lsof -ti tcp:8765 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
fi
echo 'Unscroll local helper is starting. Open your library from the Chrome extension.'
echo 'Keep this Terminal open for manual operation, or enable automatic startup.'
exec .venv/bin/python -m uvicorn unscroll.server:app --host 127.0.0.1 --port 8765
