#!/bin/sh
cd "$(dirname "$0")"
[ -f data/gamedata.json ] || python3 -m augur update
python3 -m augur build
python3 -m augur serve
