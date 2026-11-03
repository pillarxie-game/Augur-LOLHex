@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist data\gamedata.json %PY% -m augur update
%PY% -m augur build
%PY% -m augur serve
pause
