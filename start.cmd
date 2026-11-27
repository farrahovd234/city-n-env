@echo off
setlocal

where uv.exe >nul 2>nul
if errorlevel 1 (
    echo uv is required. Install uv and rerun start.cmd. 1>&2
    exit /b 1
)

set "extra="
for %%A in (%*) do if "%%~A"=="--gigachat" set "extra=--extra gigachat"

pushd "%~dp0backend" || exit /b 1
if defined extra if not exist "gpt2giga.env" (
    echo Create backend/gpt2giga.env from backend/gpt2giga.env.example first. 1>&2
    popd
    exit /b 1
)
uv run --locked %extra% python -m web_backend %*
set "result=%errorlevel%"
popd
exit /b %result%
