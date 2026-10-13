param([switch]$WithMcp)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.helper-build\Scripts\python.exe'
& $pythonPath -m pip install 'httpx==0.28.1' 'psutil==7.0.0' 'pystray==0.19.5' 'Pillow==11.3.0' 'pyinstaller==6.16.0' 'tzdata==2025.2' 'jsonschema==4.25.1'
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
$runtimeRoot = & $pythonPath -c 'import sys; print(sys.base_prefix)'
$tclPath = Join-Path $runtimeRoot 'tcl\tcl8.6'
$tkPath = Join-Path $runtimeRoot 'tcl\tk8.6'
if (Test-Path -LiteralPath $tclPath) { $env:TCL_LIBRARY = $tclPath.Replace('\','/') }
if (Test-Path -LiteralPath $tkPath) { $env:TK_LIBRARY = $tkPath.Replace('\','/') }
& $pythonPath -c 'import tkinter; root=tkinter.Tk(); root.withdraw(); root.destroy()'
if ($LASTEXITCODE -ne 0) { throw 'Working Tcl/Tk runtime required for helper packaging' }
$connectorVersion = & $pythonPath -c 'from helper.runtime import VERSION; print(VERSION)'
$packageName = "PhilixaTallyConnectorSetup-$connectorVersion"
$mcpOptions = @('--add-data', "$projectRoot\app\services\tally_mcp_registry.json;app\services")
if ($WithMcp) {
    $bundleOutput = & $pythonPath "$projectRoot\scripts\bundle_tally_mcp.py"
    if ($LASTEXITCODE -ne 0) { throw 'MCP bundle incomplete; do not publish installer' }
    $bundleLine = @($bundleOutput | Where-Object { $_ -like 'MCP_BUNDLE=*' })
    if ($bundleLine.Count -ne 1) { throw 'MCP payload path missing' }
    $bundlePath = $bundleLine[0].Substring(11)
    $mcpOptions += @('--add-data', "$bundlePath;mcp_bundle")
    $packageName += '-mcp-candidate'
}
& $pythonPath -m PyInstaller --clean --noconfirm --onefile --windowed --name $packageName --runtime-hook "$PSScriptRoot\boot.py" --paths $projectRoot --distpath "$projectRoot\data\downloads" --workpath "$projectRoot\.helper-build\build" --specpath "$projectRoot\.helper-build" @mcpOptions "$PSScriptRoot\connect.py"
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
Get-FileHash -LiteralPath "$projectRoot\data\downloads\$packageName.exe" -Algorithm SHA256
