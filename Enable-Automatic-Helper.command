#!/bin/bash
set -e
cd "$(dirname "$0")"
.venv/bin/python helper_service.py install
echo 'Keep this project folder in place. Unscroll can now connect from Chrome.'
read -r -p 'Press Enter to close.'
