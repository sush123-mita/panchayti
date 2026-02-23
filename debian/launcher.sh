#!/bin/bash
# /usr/bin/localdiscord — installed launcher script.
#
# Activates the app's private virtual environment and starts the app.
# Using 'exec' replaces the shell process so the app runs with the
# correct PID (important for desktop session tracking).

VENV="/usr/lib/localdiscord/venv"
APP="/usr/lib/localdiscord/run.py"

if [ ! -f "$VENV/bin/python3" ]; then
    echo "Error: LocalDiscord virtual environment is missing." >&2
    echo "Try reinstalling:  sudo apt install --reinstall localdiscord" >&2
    exit 1
fi

if [ ! -f "$APP" ]; then
    echo "Error: LocalDiscord application files are missing at $APP" >&2
    exit 1
fi

exec "$VENV/bin/python3" "$APP" "$@"
