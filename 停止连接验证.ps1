$ErrorActionPreference = 'Stop'
$statePath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'data/server.json'))
if (Test-Path -LiteralPath $statePath) {
    $serverInfo = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $target = Get-CimInstance Win32_Process -Filter "ProcessId = $($serverInfo.pid)"
    $expectedScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'verify_connection.py'))
    if ($target -and $target.CommandLine.Replace('/', '\').IndexOf($expectedScript, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        Stop-Process -Id $target.ProcessId
        Write-Host 'Connection verifier stopped.'
    } else {
        Write-Host 'Connection verifier is not running.'
    }
}
