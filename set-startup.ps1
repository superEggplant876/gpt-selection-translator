param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'GPTSelectionTranslator.lnk'
if ($Disable) {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
    Write-Output 'Automatic startup disabled.'
    exit
}
$python = Join-Path $PSScriptRoot 'runtime/pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $PSScriptRoot '.venv/Scripts/pythonw.exe' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.ps1 first.' }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'desktop.py') + '" --background'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'GPT Selection Translator'
$shortcut.Save()
Write-Output 'Automatic startup enabled for the current Windows user.'
