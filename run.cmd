@echo off
rem Double-click to refresh the class action report. Extra args pass through, e.g.:  run.cmd --match
rem pushd: works from any start folder (Task Scheduler starts in System32).
pushd "%~dp0"
".venv\Scripts\python.exe" -m caf run %*
set rc=%errorlevel%
popd
exit /b %rc%
