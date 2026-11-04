param(
    [string[]]$PytestArgs = @('tests', '--ci')
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv/Scripts/python.exe'
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
Push-Location $repoRoot
try {
    $testTemp = Join-Path $repoRoot '.pytest_cache/tmp'
    New-Item -ItemType Directory -Force $testTemp | Out-Null
    $env:TEMP = $testTemp
    $env:TMP = $testTemp
    & $python -m ruff check
    if ($LASTEXITCODE) { throw 'Ruff check failed' }
    & $python -m ruff format --check
    if ($LASTEXITCODE) { throw 'Ruff format failed' }
    & $python -m pyright --pythonpath $python
    if ($LASTEXITCODE) { throw 'Pyright failed' }
    & $python -m pytest @PytestArgs
    if ($LASTEXITCODE) { throw 'Pytest failed' }
}
finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    Pop-Location
}
