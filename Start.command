#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -d /opt/homebrew/bin ]; then export PATH="/opt/homebrew/bin:$PATH"; fi
if [ ! -x .venv/bin/python ]; then
  echo 'Run Setup.command first.'
  read -r -p 'Press Enter to close.'
  exit 1
fi
echo 'Unscroll local helper is starting. Open your library from the Chrome extension.'
echo 'Keep this Terminal open for manual operation, or enable automatic startup.'
exec .venv/bin/python -m uvicorn unscroll.server:app --host 127.0.0.1 --port 8765
