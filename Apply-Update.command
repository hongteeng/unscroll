#!/bin/bash
set -euo pipefail
trap 'echo; read -r -p "Press Return to close."' EXIT
update_root="$(cd "$(dirname "$0")" && pwd)"
install_root=/Applications/unscroll
if [ ! -x "$install_root/.venv/bin/python" ]; then
  echo "Could not find the installed app at /Applications/unscroll. No files changed."
  exit 1
fi
if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "First stop Unscroll: open its running Terminal window and press Control+C."
  echo "Then open Apply-Update.command again. No files changed."
  exit 1
fi
for folder in unscroll extension; do
  if [ ! -d "$update_root/$folder" ]; then
    echo "Keep this command together with the unscroll and extension folders from the ZIP."
    exit 1
  fi
done
if [ "$update_root" != "$install_root" ]; then
  cp -R "$update_root/unscroll/." "$install_root/unscroll/"
  cp -R "$update_root/extension/." "$install_root/extension/"
  cp "$update_root/requirements.txt" "$install_root/requirements.txt"
fi
"$install_root/.venv/bin/python" -m pip install -r "$install_root/requirements.txt"
"$install_root/.venv/bin/python" -m pip check
echo "Update installed. Your .env, library database, and downloads were preserved."
echo "Open /Applications/unscroll/Start.command, then reload Unscroll at chrome://extensions."
echo "In Unscroll: Processing > Pause; wait for active work to finish."
echo "Then Settings > Clear accidental imports > Remove all unprocessed posts."
