#!/bin/bash
cd "$(dirname "$0")"
echo "A arrancar bots..."
.venv/bin/python bot_agent.py --name claude &
.venv/bin/python bot_agent.py --name codex &
wait
