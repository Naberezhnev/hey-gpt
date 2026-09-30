# Compile the real embedded C# without starting microphone recording.
$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot '..\hey_gpt\listen.ps1'
$text = Get-Content $path -Raw
$match = [regex]::Match($text, "(?s)-TypeDefinition @'\r?\n(.*?)\r?\n'@")
if (-not $match.Success) { throw 'Embedded speech bridge source not found' }
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition $match.Groups[1].Value
Write-Output 'Speech bridge compiled. Microphone and live recognition were not tested.'
