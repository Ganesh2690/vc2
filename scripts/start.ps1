# Start Voice Agent - opens LiveKit local server then launches the agent
# Usage: .\scripts\start.ps1

param(
    [string]$Env = "dev"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

# Verify .env exists
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Write-Error ".env not found. Copy .env.example to .env and fill in OPENAI_API_KEY."
    exit 1
}

$lines   = Get-Content $envFile
$keyLine = $lines | Where-Object { $_ -like 'OPENAI_API_KEY=*' } | Select-Object -First 1
$apiKey  = if ($keyLine) { ($keyLine -split '=', 2)[1].Trim() } else { '' }
if (-not $apiKey -or $apiKey -eq 'sk-...') {
    Write-Warning "OPENAI_API_KEY looks like a placeholder - edit .env before continuing."
    $ans = Read-Host "Continue anyway? (y/N)"
    if ($ans -ne 'y' -and $ans -ne 'Y') { exit 1 }
}

# Start LiveKit server (background)
$lkBin = Join-Path $Root "bin\livekit-server.exe"
if (-not (Test-Path $lkBin)) {
    Write-Error "LiveKit binary not found at $lkBin. Run: uv run python scripts/download_models.py"
    exit 1
}

Write-Host "`n[1/2] Starting LiveKit local server on port 7880 ..." -ForegroundColor Cyan
$nodeIp = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $nodeIp) { $nodeIp = "127.0.0.1" }

$lkArgs = @(
    "--dev",
    "--bind", "127.0.0.1",
    "--node-ip", $nodeIp,
    "--port", "7880",
    "--udp-port", "7882",
    "--rtc.tcp_port", "7881",
    "--rtc.allow_tcp_fallback",
    "--rtc.use_mdns",
    "--turn.enabled",
    "--turn.udp_port", "3478",
    "--turn.domain", "127.0.0.1",
    "--turn.relay_range_start", "50100",
    "--turn.relay_range_end", "50110"
)
if ($nodeIp -eq "127.0.0.1") {
    $lkArgs += "--rtc.enable_loopback_candidate"
}

$lkJob = Start-Process -FilePath $lkBin `
    -ArgumentList $lkArgs `
    -PassThru -WindowStyle Hidden

Write-Host "      LiveKit PID: $($lkJob.Id)" -ForegroundColor Gray
Write-Host "      LiveKit media IP: $nodeIp" -ForegroundColor Gray
Start-Sleep -Milliseconds 1500   # give it a moment to bind

# Start voice agent
Write-Host "[2/2] Starting Voice Agent at http://localhost:7860 ..." -ForegroundColor Cyan
Write-Host "      Open http://localhost:7860 in your browser.`n" -ForegroundColor Green

try {
    Set-Location $Root
    $env:PYTHONPATH = Join-Path $Root "src"
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        & $venvPython -m voice_agent start
    }
    else {
        uv run voice-agent start
    }
}
finally {
    # Cleanup LiveKit when agent exits
    if (-not $lkJob.HasExited) {
        Write-Host "`nStopping LiveKit server ..." -ForegroundColor Gray
        Stop-Process -Id $lkJob.Id -ErrorAction SilentlyContinue
    }
}
