$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonExecutable = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonExecutable)) { throw 'Prepare the project venv first.' }
& $pythonExecutable -m PyInstaller --noconfirm --onedir --console --name HeyGPTCodex --distpath artifacts/plugin-build --workpath artifacts/pyinstaller/codex --specpath artifacts/pyinstaller --collect-all vosk --collect-all sounddevice --collect-all comtypes codex_plugin.py
if ($LASTEXITCODE) { throw 'Codex plugin runtime build failed.' }
$pluginRoot = Join-Path (Get-Location) 'plugins/hey-gpt-codex'
$runtimeRoot = Join-Path $pluginRoot 'runtime/HeyGPTCodex'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
Get-ChildItem -LiteralPath 'artifacts/plugin-build/HeyGPTCodex' -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $runtimeRoot -Recurse -Force
}
Copy-Item -LiteralPath 'LICENSE','THIRD_PARTY.md','docs/DEPENDENCY_LICENSES.txt' -Destination $pluginRoot -Force
& $pythonExecutable scripts/package_codex_plugin.py
if ($LASTEXITCODE) { throw 'Codex plugin packaging failed.' }
