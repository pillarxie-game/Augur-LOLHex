#!/bin/sh
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up screen reading (about 1 minute)..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements-screen.txt || echo "Screen reading could not be installed. Everything else still works."
fi
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
[ -f data/gamedata.json ] || $PY -m augur update
$PY -m augur build
$PY -m augur serve
