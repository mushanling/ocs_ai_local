$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 virtual environment creation failed' }
    & .venv/Scripts/python.exe -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & .venv/Scripts/python.exe -m pip install -e . --no-deps
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
if (-not (Test-Path -LiteralPath '.env')) {
    & .venv/Scripts/python.exe -c "from pathlib import Path; import secrets; p=Path('.env.example'); Path('.env').write_text(p.read_text(encoding='utf-8').replace('replace-with-a-random-token',secrets.token_urlsafe(32)),encoding='utf-8')"
}
& .venv/Scripts/python.exe run.py
