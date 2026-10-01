$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$version = (Get-Content -LiteralPath (Join-Path $sourceRoot '.codex-plugin/plugin.json') -Raw | ConvertFrom-Json).version
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$') { throw 'Invalid plugin version.' }
if (!(Test-Path -LiteralPath (Join-Path $sourceRoot 'runtime/HeyGPTCodex/HeyGPTCodex.exe'))) {
    throw 'The Windows runtime is missing. Use the complete Windows plugin ZIP.'
}
$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
$codexExecutable = if ($codexCommand) { $codexCommand.Source } else { $null }
if (!$codexExecutable) {
    $binRoot = Join-Path $env:LOCALAPPDATA 'OpenAI/Codex/bin'
    if (Test-Path -LiteralPath $binRoot) {
        $codexExecutable = Get-ChildItem -LiteralPath $binRoot -Directory |
            ForEach-Object { Get-Item -LiteralPath (Join-Path $_.FullName 'codex.exe') -ErrorAction SilentlyContinue } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
}
if (!$codexExecutable) { throw 'Codex CLI was not found. Install or update the Codex desktop app first.' }
$installRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'HeyGPT/CodexPlugin'))
$pluginDestination = [IO.Path]::GetFullPath((Join-Path $installRoot ('plugins/hey-gpt-codex/' + $version)))
if (!$pluginDestination.StartsWith($installRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The plugin destination is outside the installation directory.'
}
New-Item -ItemType Directory -Path $pluginDestination -Force | Out-Null
if (![String]::Equals($sourceRoot, $pluginDestination, [StringComparison]::OrdinalIgnoreCase)) {
    Get-ChildItem -LiteralPath $sourceRoot -Force | Where-Object { $_.Name -ne 'plugin.json' } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $pluginDestination -Recurse -Force
    }
}
# Codex 0.159.2 ignores lifecycle hooks for Agent Plugins manifests. Its
# documented compatibility manifest loads both hooks and stdio MCP correctly.
# Keep the portable identity for inspection, without selecting it at runtime.
$portableManifest = Join-Path $sourceRoot 'plugin.json'
if (Test-Path -LiteralPath $portableManifest) {
    Copy-Item -LiteralPath $portableManifest -Destination (Join-Path $pluginDestination 'plugin.portable.json') -Force
}
$selectedPortableManifest = Join-Path $pluginDestination 'plugin.json'
if (Test-Path -LiteralPath $selectedPortableManifest) {
    Remove-Item -LiteralPath $selectedPortableManifest
}
$catalogFolder = Join-Path $installRoot '.agents/plugins'
New-Item -ItemType Directory -Path $catalogFolder -Force | Out-Null
$catalog = @{
    name = 'hey-gpt-local'
    interface = @{ displayName = 'Hey GPT local' }
    plugins = @(@{
        name = 'hey-gpt-codex'
        source = @{ source = 'local'; path = './plugins/hey-gpt-codex/' + $version }
        policy = @{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
        category = 'Productivity'
    })
}
$utf8 = New-Object Text.UTF8Encoding($false)
# Compatibility MCP does not expand PLUGIN_ROOT in executable names. Resolve
# this install's own durable runtime, without editing Codex's version cache.
$installedMcp = @{ mcpServers = @{ 'hey-gpt' = @{
    command = Join-Path $pluginDestination 'runtime/HeyGPTCodex/HeyGPTCodex.exe'
    args = @('mcp')
    cwd = $pluginDestination
} } }
[IO.File]::WriteAllText((Join-Path $pluginDestination '.mcp.json'), ($installedMcp | ConvertTo-Json -Depth 10), $utf8)
[IO.File]::WriteAllText((Join-Path $catalogFolder 'marketplace.json'), ($catalog | ConvertTo-Json -Depth 10), $utf8)
& $codexExecutable plugin marketplace add $installRoot --json
if ($LASTEXITCODE) { throw 'Codex could not register the local marketplace.' }
& $codexExecutable plugin add 'hey-gpt-codex@hey-gpt-local' --json
if ($LASTEXITCODE) { throw 'Codex could not install the plugin.' }
Write-Output 'Installed Hey GPT for Codex. Enable or inspect voice mode in your chosen task.'
