$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Установите Python 3.11 или новее с python.org и повторите запуск.' }
    & $pythonExe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Host 'Квартирный AI: http://127.0.0.1:8000 (Ctrl+C — остановить)'
& $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
