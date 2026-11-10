param([switch]$WithMcp, [switch]$Publish, [switch]$ValidateOnly, [switch]$BuildOnly, [string]$CachedMcpBundle, [switch]$Offline)
$ErrorActionPreference = 'Stop'
if ($BuildOnly -and ($Publish -or $ValidateOnly)) { throw 'BuildOnly cannot validate or publish a release' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.helper-build\Scripts\python.exe'
if ($Offline) {
    & $pythonPath -m helper.build_evidence --dependencies
} else {
    & $pythonPath -m pip install 'httpx==0.28.1' 'psutil==7.0.0' 'pystray==0.19.5' 'Pillow==11.3.0' 'pyinstaller==6.16.0' 'tzdata==2025.2' 'jsonschema==4.25.1'
}
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
$runtimeRoot = & $pythonPath -c 'import sys; print(sys.base_prefix)'
$tclPath = Join-Path $runtimeRoot 'tcl\tcl8.6'
$tkPath = Join-Path $runtimeRoot 'tcl\tk8.6'
if (Test-Path -LiteralPath $tclPath) { $env:TCL_LIBRARY = $tclPath.Replace('\','/') }
if (Test-Path -LiteralPath $tkPath) { $env:TK_LIBRARY = $tkPath.Replace('\','/') }
& $pythonPath -c 'import tkinter; root=tkinter.Tk(); root.withdraw(); root.destroy()'
if ($LASTEXITCODE -ne 0) { throw 'Working Tcl/Tk runtime required for helper packaging' }
$connectorVersion = & $pythonPath -c 'from helper.runtime import VERSION; print(VERSION)'
$runtimeDataJson = & $pythonPath -m helper.build_evidence --runtime-data
if ($LASTEXITCODE -ne 0) { throw 'Required SSL runtime resource unavailable' }
$runtimeData = @($runtimeDataJson | ConvertFrom-Json)
$runtimeOptions = @()
foreach ($entry in $runtimeData) { $runtimeOptions += @('--add-data', "$($entry.source);$($entry.destination)") }
$packageName = "PhilixaTallyConnectorSetup-$connectorVersion"
$candidateDir = Join-Path $projectRoot 'data\connector-candidates'
$mcpOptions = @('--add-data', "$projectRoot\app\services\tally_mcp_registry.json;app\services")
if ($WithMcp) {
    if ($CachedMcpBundle) {
        $bundlePath = (Resolve-Path -LiteralPath $CachedMcpBundle).Path
        & $pythonPath -c 'from helper.build_evidence import validate_mcp; import sys; validate_mcp(sys.argv[1])' $bundlePath
        if ($LASTEXITCODE -ne 0) { throw 'Cached MCP payload integrity failed' }
    } else {
    $bundleOutput = & $pythonPath "$projectRoot\scripts\bundle_tally_mcp.py"
    if ($LASTEXITCODE -ne 0) { throw 'MCP bundle incomplete; do not publish installer' }
    $bundleLine = @($bundleOutput | Where-Object { $_ -like 'MCP_BUNDLE=*' })
    if ($bundleLine.Count -ne 1) { throw 'MCP payload path missing' }
    $bundlePath = $bundleLine[0].Substring(11)
    }
    $mcpOptions += @('--add-data', "$bundlePath;mcp_bundle")
    $packageName += '-mcp-candidate'
}
else { $packageName += '-candidate' }
if (-not $ValidateOnly) {
    & $pythonPath -m PyInstaller --clean --noconfirm --onefile --windowed --name $packageName --runtime-hook "$PSScriptRoot\boot.py" --paths $projectRoot --distpath $candidateDir --workpath "$projectRoot\.helper-build\build" --specpath "$projectRoot\.helper-build" @runtimeOptions @mcpOptions "$PSScriptRoot\connect.py"
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
}
$candidatePath = Join-Path $candidateDir "$packageName.exe"
if ($BuildOnly) {
    $hash = Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256
    @{version=$connectorVersion;sha256=$hash.Hash;runtime_ssl_resources=@($runtimeData | Select-Object name,sha256);published=$false;executed=$false;runtime_acceptance='pending'} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $candidateDir "$packageName-build-only.json")
    Write-Output 'Candidate built only. No executable launched, installed or published.'
    $hash
    return
}
$checks = @('transport','history','invoice','receipt')
if ($WithMcp) { $checks += 'mcp' }
$evidence = @{}
foreach ($check in $checks) {
    $resultPath = Join-Path $candidateDir ("$packageName-"+$check+'-'+[guid]::NewGuid().ToString('N')+'.json')
    $arguments = '--{0}-self-test "{1}"' -f $check,$resultPath
    # Fail closed on Windows Application Control too; never promote an unrun build.
    $process = Start-Process -FilePath $candidatePath -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) { throw "Packaged $check check timed out; installer withheld" }
    $process.Refresh()
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $resultPath)) { throw "Packaged $check check failed; installer withheld" }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    $field = @{transport='client_ready';history='history_read';invoice='duplicate_blocked';receipt='receipt_codecs';mcp='stdio'}[$check]
    if ($result.$field -ne $true -or $result.error) { throw "Packaged $check result invalid; installer withheld" }
    if ($check -eq 'transport' -and (-not $result.async_client_ready -or -not $result.certificate_validation -or -not $result.ca_exists)) { throw 'Packaged async/TLS initialization unverified; installer withheld' }
    $evidence[$check] = $result
}
$hash = Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256
$proof = @{sha256=$hash.Hash;checks=$evidence;published=$false}
$proofPath = Join-Path $candidateDir "$packageName-acceptance.json"
$proof | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $proofPath
if ($Publish) {
    $signature = Get-AuthenticodeSignature -LiteralPath $candidatePath
    if ($signature.Status -ne 'Valid') { throw 'Trusted code signature required before public release; installer withheld' }
    Copy-Item -LiteralPath $candidatePath -Destination (Join-Path $projectRoot "data\downloads\PhilixaTallyConnectorSetup-$connectorVersion.exe")
    $proof.published=$true
    $proof | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $proofPath
}
$hash
