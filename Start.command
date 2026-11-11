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
  # Wait for the old process itself to exit (not just its port): it holds app.lock until it is gone.
  for i in $(seq 1 15); do
    kill -0 $OLD 2>/dev/null || break
    sleep 1
  done
  # Still alive after 15s (finishing a job)? Force it; unfinished jobs go back to the queue on next start.
  if kill -0 $OLD 2>/dev/null; then kill -9 $OLD; sleep 1; fi
fi
echo 'Unscroll local helper is starting. Open your library from the Chrome extension.'
echo 'Keep this Terminal open for manual operation, or enable automatic startup.'
exec .venv/bin/python -m uvicorn unscroll.server:app --host 127.0.0.1 --port 8765
