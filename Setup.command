#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -x /opt/homebrew/bin/brew ]; then export PATH="/opt/homebrew/bin:$PATH"; fi
if ! command -v brew >/dev/null 2>&1; then
  echo 'Install Homebrew from https://brew.sh, then double-click Setup.command again.'
  read -r -p 'Press Enter to close.'
  exit 1
fi
brew install python@3.12 ffmpeg tesseract
UNSCROLL_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
"$UNSCROLL_PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python configure.py
.venv/bin/python build_extension.py
.venv/bin/python -c 'from unscroll import db; db.init(); print("\nLocal pairing token (paste into the Unscroll extension):\n" + db.setting("token"))'
echo ''
echo 'Setup finished. Start.command runs the local helper.'
echo 'Load the extension folder at chrome://extensions, then choose Open your library.'
echo 'For automatic helper startup, run Enable-Automatic-Helper.command once.'
read -r -p 'Press Enter to close.'
