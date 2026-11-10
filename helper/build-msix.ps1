param([Parameter(Mandatory=$true)][string]$IdentityFile)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
$python = Join-Path $root '.helper-build\Scripts\python.exe'
$output = Join-Path $root 'data\connector-candidates\msix-3.7.1'
# Validate identity before installing dependencies or building anything.
& $python -c 'import json,sys; from helper.msix_manifest import manifest; manifest(json.load(open(sys.argv[1],encoding="utf-8")))' $IdentityFile
if ($LASTEXITCODE -ne 0) { throw 'Verified Partner Center metadata missing; MSIX withheld' }
$sdk = Get-ChildItem -LiteralPath "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Directory |
    Sort-Object Name -Descending | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'x64\makeappx.exe') } |
    Select-Object -First 1
if (-not $sdk) { throw 'Windows SDK MakeAppx required; no package built' }
& $python -m pip install -r "$PSScriptRoot\requirements-msix.txt"
if ($LASTEXITCODE -ne 0) { throw 'MSIX dependency installation failed' }
$bundleOutput = & $python "$root\scripts\bundle_tally_mcp.py"
if ($LASTEXITCODE -ne 0) { throw 'Pinned Node/MCP payload incomplete' }
$bundleLine = @($bundleOutput | Where-Object { $_ -like 'MCP_BUNDLE=*' })
if ($bundleLine.Count -ne 1) { throw 'MCP payload path missing' }
$bundle = $bundleLine[0].Substring(11)
$payload = Join-Path $output 'payload'
$runtimeJson = & $python -m helper.build_evidence --runtime-data
if ($LASTEXITCODE -ne 0) { throw 'Required SSL runtime resource unavailable' }
$runtimeOptions = @()
foreach ($entry in @($runtimeJson | ConvertFrom-Json)) { $runtimeOptions += @('--add-data', "$($entry.source);$($entry.destination)") }
& $python -m PyInstaller --clean --noconfirm --onedir --windowed --name PhilixaConnect --runtime-hook "$PSScriptRoot\boot.py" --paths $root --collect-all certifi --collect-all winrt @runtimeOptions --add-data "$root\app\services\tally_mcp_registry.json;app\services" --add-data "$bundle;mcp_bundle" --distpath "$output\dist" --workpath "$output\work" --specpath $output "$PSScriptRoot\connect.py"
if ($LASTEXITCODE -ne 0) { throw 'MSIX onedir build failed' }
New-Item -ItemType Directory -Force -Path $payload | Out-Null
if (Test-Path -LiteralPath (Join-Path $payload 'app')) { throw 'Use a fresh candidate directory; existing payload preserved' }
Copy-Item -LiteralPath "$output\dist\PhilixaConnect" -Destination "$payload\app" -Recurse
& $python -m helper.msix_manifest $IdentityFile "$payload\AppxManifest.xml"
if ($LASTEXITCODE -ne 0) { throw 'Manifest validation failed' }
& $python -m helper.msix_assets "$payload\Assets"
if ($LASTEXITCODE -ne 0) { throw 'Package asset generation failed' }
& $python -m helper.msix_licenses "$payload\Licences"
if ($LASTEXITCODE -ne 0) { throw 'Dependency licence collection failed' }
$makeappx = Join-Path $sdk.FullName 'x64\makeappx.exe'
& $makeappx pack /d $payload /p "$output\PhilixaConnect-3.7.1.msix" /o
if ($LASTEXITCODE -ne 0) { throw 'MakeAppx validation failed; release withheld' }
$files = Get-ChildItem -LiteralPath $payload -File -Recurse | ForEach-Object {
    @{path=$_.FullName.Substring($payload.Length+1);sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
$dependencies = & $python -m pip freeze
@{version='3.7.1';protocol=10;published=$false;signed=$false;runtime_acceptance='pending';files=@($files);dependencies=@($dependencies);package_sha256=(Get-FileHash -LiteralPath "$output\PhilixaConnect-3.7.1.msix" -Algorithm SHA256).Hash} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$output\build-evidence.json"
Write-Output 'Unsigned Store submission candidate only. Store signing and Windows matrix acceptance remain required.'
} finally { Pop-Location }
