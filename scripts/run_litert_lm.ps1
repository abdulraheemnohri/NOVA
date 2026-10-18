$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Cli = Join-Path $Root ".venv\Scripts\litert-lm.exe"
if (-not (Test-Path $Cli)) {
    $Command = Get-Command "litert-lm" -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        Write-Error "LiteRT-LM CLI is not installed. Run: py scripts/install_optional_runtimes.py --litert-lm"
        exit 2
    }
    $Cli = $Command.Source
}
Write-Host "Starting LiteRT-LM on loopback 127.0.0.1:9379. Stop with Ctrl+C."
Write-Host "This explicit command runs in the foreground; NOVA does not start it automatically."
& $Cli serve --host 127.0.0.1 --port 9379
exit $LASTEXITCODE
