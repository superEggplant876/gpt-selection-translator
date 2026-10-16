$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv/Scripts/python.exe'))) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 for Windows, including Tcl/Tk, then run setup again.' }
}
& (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Output 'Setup complete. Open the launch VBS file, then sign in with your own ChatGPT account.'
