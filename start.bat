@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv\Scripts\python.exe (
  echo First run: setting up screen reading ^(about 1 minute^)...
  %PY% -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements-screen.txt || echo Screen reading could not be installed. Everything else still works.
)
set PY=.venv\Scripts\python
if not exist data\gamedata.json %PY% -m augur update
%PY% -m augur build
%PY% -m augur serve
pause
