# Start LFC monitor + ngrok. Ctrl+C stops both.
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
Set-Location $Root

$HandoffPort = if ($env:LFC_HANDOFF_PORT) { $env:LFC_HANDOFF_PORT } else { "8765" }
$NgrokProc = $null

function Stop-Ngrok {
    if ($null -ne $NgrokProc -and -not $NgrokProc.HasExited) {
        Write-Host ""
        Write-Host "Stopping ngrok (pid $($NgrokProc.Id))..."
        Stop-Process -Id $NgrokProc.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    $NgrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($NgrokCmd) {
        Write-Host "Starting ngrok http $HandoffPort..."
        $NgrokProc = Start-Process -FilePath "ngrok" -ArgumentList "http", $HandoffPort -PassThru -WindowStyle Hidden
        for ($i = 0; $i -lt 20; $i++) {
            try {
                Invoke-WebRequest -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 1 -UseBasicParsing | Out-Null
                Write-Host "ngrok ready (local API on :4040)"
                break
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
    } else {
        Write-Host "WARN: ngrok not in PATH - set lfc_checkout_public_url in .env or install ngrok"
    }

    Write-Host 'Starting monitor (Ctrl+C stops monitor and ngrok)...'
    python -m lfc.monitor @args
} finally {
    Stop-Ngrok
}
