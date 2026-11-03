@echo off
rem Collect ARAM Mayhem games from your League client (no API key), then rebuild the stats.
rem Keep the League client open and logged in while this runs.
cd /d "%~dp0"
set PY=.venv\Scripts\python
if not exist %PY%.exe (where py >nul 2>nul && (set PY=py -3) || (set PY=python))
if not exist data\gamedata.json %PY% -m augur update
%PY% -m augur collect-client --games 500
%PY% -m augur build
%PY% -m augur info
echo.
echo Done. Run start.bat to see the grades with your games.
pause
