#!/bin/bash
set -e
cd "$(dirname "$0")"
.venv/bin/python helper_service.py remove
read -r -p 'Press Enter to close.'
