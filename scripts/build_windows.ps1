$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run Run.cmd once before building.' }
& $python -m pip install 'pyinstaller==6.22.3'
if ($LASTEXITCODE) { throw 'Build dependency installation failed.' }
& $python scripts/collect_licenses.py
if ($LASTEXITCODE) { throw 'License collection failed.' }
& $python -m PyInstaller --noconfirm --onedir --console --name HeyGPTVoice --distpath artifacts/build_0_4_0 --workpath artifacts/pyinstaller/voice --specpath artifacts/pyinstaller --collect-all vosk --collect-all sounddevice voice_entry.py
if ($LASTEXITCODE) { throw 'Voice worker build failed.' }
& $python -m PyInstaller --noconfirm --onedir --windowed --name HeyGPT --distpath artifacts/build_0_4_0 --workpath artifacts/pyinstaller/app --specpath artifacts/pyinstaller --collect-all customtkinter --collect-all comtypes --collect-all uiautomation launch.py
if ($LASTEXITCODE) { throw 'Application build failed.' }
$bundle = Join-Path (Get-Location) 'artifacts/build_0_4_0/HeyGPT'
New-Item -ItemType Directory -Path (Join-Path $bundle 'voice') -Force | Out-Null
Copy-Item -Path 'artifacts/build_0_4_0/HeyGPTVoice/*' -Destination (Join-Path $bundle 'voice') -Recurse -Force
Copy-Item -LiteralPath 'LICENSE','THIRD_PARTY.md','START_HERE_RU.md' -Destination $bundle -Force
if (Test-Path -LiteralPath 'docs/DEPENDENCY_LICENSES.txt') { Copy-Item -LiteralPath 'docs/DEPENDENCY_LICENSES.txt' -Destination $bundle -Force }
Compress-Archive -Path "$bundle/*" -DestinationPath 'artifacts/Hey_GPT_v0_4_0_Windows.zip' -Force
Write-Output 'Built artifacts/Hey_GPT_v0_4_0_Windows.zip; extract the whole folder, then run HeyGPT.exe.'
