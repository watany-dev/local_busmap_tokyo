$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$ProjectDir = $RootDir
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$VenvDir = Join-Path $ProjectDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

& $Python -c "import sys; assert sys.version_info >= (3, 11), f'Python 3.11以上が必要です: {sys.version.split()[0]}'; print('Python:', sys.version.split()[0])"

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv $VenvDir
}

$env:PYTHONPATH = Join-Path $ProjectDir "src"
Push-Location $ProjectDir
try {
    & $VenvPython (Join-Path $ScriptDir "verify_repo.py")
    & $VenvPython -m tokyo_local_bus validate-config
    & $VenvPython -m unittest discover -s tests -v

    $SampleDir = Join-Path $ProjectDir "data\sample-run"
    if (Test-Path $SampleDir) {
        Remove-Item -Recurse -Force $SampleDir
    }

    & $VenvPython -m tokyo_local_bus ingest `
        --config tests/fixtures/test-feeds.json `
        --data-dir data/sample-run `
        --date 2026-08-22 `
        --local-zip TEST=tests/fixtures/minimal_gtfs.zip
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "セットアップとオフライン検証が完了しました。"
Write-Host "サンプル地図:"
Write-Host ('  $env:PYTHONPATH = "{0}\src"' -f $ProjectDir)
Write-Host ('  & "{0}" -m tokyo_local_bus serve --data-dir "{1}\data\sample-run" --web-dir "{1}\web" --host 127.0.0.1 --port 8000' -f $VenvPython, $ProjectDir)
