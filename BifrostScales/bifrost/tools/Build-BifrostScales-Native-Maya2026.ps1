param(
    [string]$BifrostLocation = "",
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [string]$Toolset = "v142",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Add-BifrostCandidate {
    param(
        [System.Collections.Generic.List[object]]$Candidates,
        [string]$Path,
        [string]$Source
    )
    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        $Candidates.Add([pscustomobject]@{
            Path = $Path
            Source = $Source
        })
    }
}

function Resolve-BifrostLocation {
    param([string]$ExplicitLocation)

    if ($ExplicitLocation -match '[<>]') {
        throw (
            "-BifrostLocation contains a literal placeholder. " +
            "Replace <BIFROST_VERSION> with the installed numeric version " +
            "(for example 2.15.0.0), or omit -BifrostLocation to use auto-detection."
        )
    }

    $candidates = New-Object 'System.Collections.Generic.List[object]'
    if ($ExplicitLocation) {
        Add-BifrostCandidate $candidates $ExplicitLocation "explicit"
        Add-BifrostCandidate $candidates (Join-Path $ExplicitLocation "bifrost") "explicit"
    }
    if ($env:BIFROST_LOCATION) {
        Add-BifrostCandidate $candidates $env:BIFROST_LOCATION "environment"
        Add-BifrostCandidate $candidates (Join-Path $env:BIFROST_LOCATION "bifrost") "environment"
    }

    $mayaRoot = "C:\Program Files\Autodesk\Bifrost\Maya2026"
    if (Test-Path $mayaRoot) {
        $versionDirectories = Get-ChildItem -Path $mayaRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object -Property @{
                Expression = {
                    try { [version]$_.Name }
                    catch { [version]"0.0" }
                }
                Descending = $true
            }
        foreach ($directory in $versionDirectories) {
            Add-BifrostCandidate $candidates (Join-Path $directory.FullName "bifrost") "auto"
            Add-BifrostCandidate $candidates $directory.FullName "auto"
        }
    }

    foreach ($candidate in $candidates) {
        $candidatePath = [string]$candidate.Path
        try {
            $resolved = [System.IO.Path]::GetFullPath($candidatePath)
        } catch {
            if ($candidate.Source -eq "explicit") {
                throw "Invalid -BifrostLocation path '$candidatePath': $($_.Exception.Message)"
            }
            continue
        }
        if (Test-Path (Join-Path $resolved "sdk\cmake\setup.cmake")) {
            return $resolved
        }
    }

    throw (
        "Bifrost SDK root was not found. Omit -BifrostLocation for auto-detection, " +
        "or pass the real path ending in \\bifrost, for example " +
        "C:\Program Files\Autodesk\Bifrost\Maya2026\2.15.0.0\bifrost."
    )
}

function Get-CMakeCacheValue {
    param(
        [string]$CacheFile,
        [string]$Name
    )
    if (-not (Test-Path $CacheFile)) {
        return $null
    }
    $escapedName = [regex]::Escape($Name)
    foreach ($line in Get-Content -Path $CacheFile) {
        if ($line -match "^${escapedName}:[^=]+=(.*)$") {
            return $Matches[1]
        }
    }
    return $null
}

function Assert-PathInside {
    param(
        [string]$Child,
        [string]$Parent,
        [string]$Label
    )
    $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $prefix = $parentFull + [System.IO.Path]::DirectorySeparatorChar
    if (
        -not $childFull.Equals($parentFull, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $childFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "$Label resolved outside the module pack directory: $childFull"
    }
}

$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$moduleRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceNativeRoot = Join-Path $sourceRoot "native"
$installedNativeRoot = Join-Path $moduleRoot "bifrost\native"
if (Test-Path $sourceNativeRoot) {
    $nativeRoot = $sourceNativeRoot
} elseif (Test-Path $installedNativeRoot) {
    $nativeRoot = $installedNativeRoot
} else {
    throw "Native source directory is missing. Checked: $sourceNativeRoot and $installedNativeRoot"
}

$packContainer = Join-Path $moduleRoot "bifrost\pack"
$buildRoot = Join-Path $moduleRoot ("bifrost\out\maya2026-" + $Configuration.ToLowerInvariant())
$modFile = Join-Path (Split-Path $moduleRoot -Parent) "BifrostScales.mod"
$bifrostRoot = Resolve-BifrostLocation $BifrostLocation

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake was not found on PATH."
}
if (-not (Test-Path $nativeRoot)) {
    throw "Native source directory is missing: $nativeRoot"
}
$nodeHeader = Join-Path $nativeRoot "operator\src\bifrost_scales_nodedef.hpp"
if (-not (Test-Path $nodeHeader)) {
    throw "Bifrost operator header is missing: $nodeHeader"
}
if (Select-String -Path $nodeHeader -Pattern "name=BifrostScales::generate_scale_mesh_payload_arrays" -Quiet) {
    throw (
        "The operator header repeats the C++ namespace in the Amino name annotation. " +
        "This registers BifrostScales::BifrostScales and is incompatible with the v3 graph."
    )
}
if ($Clean -and (Test-Path $buildRoot)) {
    Remove-Item -Path $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $packContainer -Force | Out-Null

Write-Host "Bifrost SDK : $bifrostRoot"
Write-Host "Native source: $nativeRoot"
Write-Host "MSVC toolset : $Toolset"
Write-Host "Pack container: $packContainer"

& cmake `
    -S $nativeRoot `
    -B $buildRoot `
    -G "Visual Studio 17 2022" `
    -A x64 `
    -T $Toolset `
    "-DBIFROST_LOCATION=$bifrostRoot" `
    "-DBIFROST_SCALES_BUILD_BIFROST_OPERATOR=ON" `
    "-DBIFROST_SCALES_STATIC_GRAPH_DIR=$(Join-Path $moduleRoot 'bifrost\compounds')" `
    "-DBUILD_TESTING=ON" `
    "-DCMAKE_INSTALL_PREFIX=$packContainer"
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed." }

$cacheFile = Join-Path $buildRoot "CMakeCache.txt"
$cachedInstallPrefix = Get-CMakeCacheValue $cacheFile "CMAKE_INSTALL_PREFIX"
if (-not $cachedInstallPrefix) {
    throw "CMAKE_INSTALL_PREFIX was not found in $cacheFile"
}
$installRoot = [System.IO.Path]::GetFullPath($cachedInstallPrefix)
Assert-PathInside $installRoot $packContainer "CMake install root"
Write-Host "CMake install root: $installRoot"

if ($Clean -and (Test-Path $installRoot)) {
    $installRootFull = [System.IO.Path]::GetFullPath($installRoot).TrimEnd('\', '/')
    $packContainerFull = [System.IO.Path]::GetFullPath($packContainer).TrimEnd('\', '/')
    $installLeaf = Split-Path $installRootFull -Leaf
    if ($installRootFull.Equals($packContainerFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean the shared pack container itself: $installRootFull"
    }
    if ($installLeaf -ne "BifrostScalesCore-0.10.6") {
        throw "Refusing to clean an unexpected install root: $installRootFull"
    }
    Remove-Item -Path $installRootFull -Recurse -Force
    Write-Host "Removed previous 0.10.6 install root: $installRootFull"
}

& cmake --build $buildRoot --config $Configuration --target install
if ($LASTEXITCODE -ne 0) { throw "Native operator build/install failed." }

& ctest --test-dir $buildRoot -C $Configuration --output-on-failure
if ($LASTEXITCODE -ne 0) { throw "Native core tests failed." }

$packConfig = Join-Path $installRoot "BifrostScalesPackConfig.json"
$operatorDll = Get-Item -Path (Join-Path $installRoot "lib\BifrostScalesOps.dll") -ErrorAction SilentlyContinue
$nodeDefinition = Join-Path $installRoot "json\BifrostScales\operators\bifrost_scales_nodedef.json"
$staticGraph = Join-Path $installRoot "json\BifrostScales\graphs\BifrostScales_native_scales_v4_graph.json"
$metadataManifest = Join-Path $installRoot "metadata\manifest.bifrost-scales.json"
$parityDump = Join-Path $installRoot "tools\bifrost_scales_parity_dump.exe"
$performanceBenchmark = Join-Path $installRoot "tools\bifrost_scales_performance_benchmark.exe"
$gpuPreviewBenchmark = Join-Path $installRoot "tools\bifrost_scales_gpu_preview_benchmark.exe"
$boundaryDensityBenchmark = Join-Path $installRoot "tools\bifrost_scales_open_boundary_density_benchmark.exe"
$stageCacheBenchmark = Join-Path $installRoot "tools\bifrost_scales_stage_cache_benchmark.exe"
$distributionBenchmark = Join-Path $installRoot "tools\bifrost_scales_interactive_distribution_benchmark.exe"

if (-not (Test-Path $packConfig)) {
    throw "PackConfig was not installed at the CMake install root: $packConfig"
}
if (-not $operatorDll) {
    throw "BifrostScalesOps.dll was not installed at: $(Join-Path $installRoot 'lib')"
}
if (-not (Test-Path $nodeDefinition)) {
    throw "Generated node definition JSON was not installed at: $nodeDefinition"
}
if (-not (Select-String -Path $nodeDefinition -Pattern "generate_scale_mesh_payload_arrays" -Quiet)) {
    throw "Generated node definition does not contain the expected operator function: $nodeDefinition"
}
if (Select-String -Path $nodeDefinition -Pattern "BifrostScales::BifrostScales" -Quiet) {
    throw (
        "Generated node definition contains the invalid doubled namespace " +
        "BifrostScales::BifrostScales. Verify the 0.10.6 header source and rebuild with -Clean."
    )
}
try {
    $nodeDefinitionData = Get-Content -Path $nodeDefinition -Raw | ConvertFrom-Json
} catch {
    throw "Generated node definition is not valid JSON: $nodeDefinition ($($_.Exception.Message))"
}
$operatorDefinitionEntry = @(
    $nodeDefinitionData.operators | Where-Object {
        [string]$_.name -eq 'BifrostScales::generate_scale_mesh_payload_arrays'
    }
) | Select-Object -First 1
if (-not $operatorDefinitionEntry) {
    throw (
        "Generated node definition does not contain the exact operator " +
        "BifrostScales::generate_scale_mesh_payload_arrays: $nodeDefinition"
    )
}
$operatorPortTypes = @{}
foreach ($operatorPortEntry in @($operatorDefinitionEntry.ports)) {
    $operatorPortName = [string]$operatorPortEntry.portName
    if (-not [string]::IsNullOrWhiteSpace($operatorPortName)) {
        $operatorPortTypes[$operatorPortName] = [string]$operatorPortEntry.portType
    }
}
$requiredTopologyPortTypes = @{
    source_face_offset = 'array<uint>'
    source_face_vertex = 'array<uint>'
    face_offset = 'array<uint>'
    face_vertex = 'array<uint>'
    profile_json = 'string'
}
foreach ($requiredTopologyPortName in $requiredTopologyPortTypes.Keys) {
    $actualTopologyPortType = [string]$operatorPortTypes[$requiredTopologyPortName]
    $expectedTopologyPortType = [string]$requiredTopologyPortTypes[$requiredTopologyPortName]
    if ($actualTopologyPortType -ne $expectedTopologyPortType) {
        throw (
            "Generated operator port '$requiredTopologyPortName' has type " +
            "'$actualTopologyPortType'; expected '$expectedTopologyPortType'. " +
            "Geometry::Mesh::construct_mesh requires array<uint> topology. " +
            "Verify the 0.10.6 Native source and rebuild with -Clean."
        )
    }
}
if (-not (Test-Path $staticGraph)) {
    throw "Static Published Graph was not installed at: $staticGraph"
}
try {
    $staticGraphData = Get-Content -Path $staticGraph -Raw | ConvertFrom-Json
} catch {
    throw "Static Published Graph is not valid JSON: $staticGraph ($($_.Exception.Message))"
}
$staticGraphCompounds = @($staticGraphData.compounds)
if ($staticGraphCompounds.Count -ne 1) {
    throw "Static Published Graph must contain exactly one top-level graph definition: $staticGraph"
}
$staticGraphCompound = $staticGraphCompounds[0]
if ([string]$staticGraphCompound.name -ne 'Graphs::BifrostScales::native_scales_v4') {
    throw "Static Published Graph has an unexpected definition name: $($staticGraphCompound.name)"
}
$compoundIsGraphEntry = @(
    $staticGraphCompound.metadata | Where-Object {
        [string]$_.metaName -eq 'compoundIsGraph'
    }
) | Select-Object -First 1
if (-not $compoundIsGraphEntry -or ([string]$compoundIsGraphEntry.metaValue).ToLowerInvariant() -ne 'true') {
    throw "Static Published Graph is not marked compoundIsGraph=true. Maya cannot expose the top-level source_mesh input on an ordinary compound."
}
$sourceMeshPort = @(
    $staticGraphCompound.ports | Where-Object {
        [string]$_.portName -eq 'source_mesh'
    }
) | Select-Object -First 1
if (-not $sourceMeshPort -or [string]$sourceMeshPort.portType -ne 'Object') {
    throw "Static Published Graph source_mesh must be a top-level Object input."
}
$sourcePathInfo = @(
    $sourceMeshPort.metadata | Where-Object {
        [string]$_.metaName -eq 'pathinfo'
    }
) | Select-Object -First 1
if (-not $sourcePathInfo) {
    throw "Static Published Graph source_mesh is missing pathinfo metadata."
}
$requiredPathInfo = @{
    path = ''
    setOperation = '+'
    active = 'true'
}
foreach ($pathInfoName in $requiredPathInfo.Keys) {
    $pathInfoEntry = @(
        $sourcePathInfo.metadata | Where-Object {
            [string]$_.metaName -eq [string]$pathInfoName
        }
    ) | Select-Object -First 1
    if (-not $pathInfoEntry -or [string]$pathInfoEntry.metaType -ne 'string') {
        throw "Static Published Graph source_mesh pathinfo '$pathInfoName' must have metaType=string."
    }
    if ([string]$pathInfoEntry.metaValue -ne [string]$requiredPathInfo[$pathInfoName]) {
        throw "Static Published Graph source_mesh pathinfo '$pathInfoName' has an unexpected value."
    }
}
$sourceMeshConnectionFound = $false
foreach ($connectionEntry in @($staticGraphCompound.connections)) {
    if (
        [string]$connectionEntry.source -eq '.source_mesh' -and
        [string]$connectionEntry.target -eq 'get_mesh_structure.mesh'
    ) {
        $sourceMeshConnectionFound = $true
        break
    }
}
if (-not $sourceMeshConnectionFound) {
    throw "Static Published Graph does not connect .source_mesh to get_mesh_structure.mesh."
}
$profileJsonPort = @(
    $staticGraphCompound.ports | Where-Object {
        [string]$_.portName -eq 'profile_json'
    }
) | Select-Object -First 1
if (-not $profileJsonPort -or [string]$profileJsonPort.portType -ne 'string') {
    throw "Static Published Graph profile_json must be a top-level string output."
}
$profileJsonConnectionFound = $false
foreach ($connectionEntry in @($staticGraphCompound.connections)) {
    if (
        [string]$connectionEntry.source -eq 'generate_scale_mesh_payload_arrays.profile_json' -and
        [string]$connectionEntry.target -eq '.profile_json'
    ) {
        $profileJsonConnectionFound = $true
        break
    }
}
if (-not $profileJsonConnectionFound) {
    throw "Static Published Graph does not publish the Native profile_json output."
}
$payloadJsonPort = @(
    $staticGraphCompound.ports | Where-Object {
        [string]$_.portName -eq 'payload_json'
    }
) | Select-Object -First 1
if (-not $payloadJsonPort) {
    throw "Static Published Graph is missing payload_json."
}
try {
    $payloadDefaultData = ([string]$payloadJsonPort.portDefault) | ConvertFrom-Json
} catch {
    throw "Static Published Graph payload_json default is not valid JSON."
}
if ([string]$payloadDefaultData.schema -ne 'bifrost-scales/native-payload/10') {
    throw "Static Published Graph payload schema must be bifrost-scales/native-payload/10."
}
if (-not (Test-Path $metadataManifest)) {
    throw "Native metadata manifest was not installed outside jsonLibs: $metadataManifest"
}
try {
    $metadataManifestData = Get-Content -Path $metadataManifest -Raw | ConvertFrom-Json
} catch {
    throw "Native metadata manifest is not valid JSON: $metadataManifest ($($_.Exception.Message))"
}
if ([string]$metadataManifestData.native_payload_schema -ne 'bifrost-scales/native-payload/10') {
    throw "Native metadata manifest payload schema must be bifrost-scales/native-payload/10."
}
if ([string]$metadataManifestData.native_behavior_contract -ne 'bifrost-scales/native-core/0.10.6-cell-hot-path-1') {
    throw (
        "Native metadata manifest behavior contract must be " +
        "bifrost-scales/native-core/0.10.6-cell-hot-path-1."
    )
}
if ([string]$metadataManifestData.native_profile_schema -ne 'bifrost-scales/native-profile/9') {
    throw "Native metadata manifest profile schema must be bifrost-scales/native-profile/9."
}
if (-not (Test-Path $parityDump)) {
    throw "Host-independent parity dump executable was not installed at: $parityDump"
}
if (-not (Test-Path $performanceBenchmark)) {
    throw "Native performance benchmark executable was not installed at: $performanceBenchmark"
}
if (-not (Test-Path $gpuPreviewBenchmark)) {
    throw "GPU Preview benchmark executable was not installed at: $gpuPreviewBenchmark"
}
if (-not (Test-Path $boundaryDensityBenchmark)) {
    throw "Open-boundary Density benchmark executable was not installed at: $boundaryDensityBenchmark"
}
if (-not (Test-Path $stageCacheBenchmark)) {
    throw "Cross-worker Stage Cache benchmark executable was not installed at: $stageCacheBenchmark"
}
if (-not (Test-Path $distributionBenchmark)) {
    throw "Interactive Distribution benchmark executable was not installed at: $distributionBenchmark"
}

& $stageCacheBenchmark 2000
if ($LASTEXITCODE -ne 0) {
    throw "Cross-worker Stage Cache benchmark failed."
}

try {
    $packData = Get-Content -Path $packConfig -Raw | ConvertFrom-Json
} catch {
    throw "PackConfig is not valid JSON: $packConfig ($($_.Exception.Message))"
}
$operatorLibraryFound = $false
$graphLibraryFound = $false
$aminoConfigurationEntries = @($packData.AminoConfigurations)
foreach ($aminoConfigurationEntry in $aminoConfigurationEntries) {
    foreach ($jsonLibraryEntry in @($aminoConfigurationEntry.jsonLibs)) {
        $libraryPath = ([string]$jsonLibraryEntry.path).Replace('\', '/').TrimEnd('/')
        $libraryFiles = @($jsonLibraryEntry.files | ForEach-Object { [string]$_ })
        if (
            ($libraryPath -eq './json/BifrostScales/operators' -or $libraryPath -eq 'json/BifrostScales/operators') -and
            ($libraryFiles -contains 'bifrost_scales_nodedef.json')
        ) {
            $operatorLibraryFound = $true
        }
        if (
            ($libraryPath -eq './json/BifrostScales/graphs' -or $libraryPath -eq 'json/BifrostScales/graphs') -and
            ($libraryFiles -contains 'BifrostScales_native_scales_v4_graph.json')
        ) {
            $graphLibraryFound = $true
        }
    }
}
if (-not $operatorLibraryFound) {
    throw (
        "PackConfig does not explicitly register the operator definition before the graph: " +
        "$packConfig"
    )
}
if (-not $graphLibraryFound) {
    throw "PackConfig does not explicitly register the static graph: $packConfig"
}

$legacyJsonRoot = Join-Path $installRoot "json\BifrostScales"
foreach ($unexpected in @(
    (Join-Path $legacyJsonRoot "bifrost_scales_nodedef.json"),
    (Join-Path $legacyJsonRoot "BifrostScales_native_scales_v4_graph.json"),
    (Join-Path $legacyJsonRoot "manifest.bifrost-scales.json")
)) {
    if (Test-Path $unexpected) {
        throw "A legacy JSON resource remains in the scanned parent directory: $unexpected"
    }
}

$modulePathText = $moduleRoot.Replace('\', '/')
$packConfigText = $packConfig.Replace('\', '/')
$moduleText = @"
+ BifrostScales 0.10.6 $modulePathText
PYTHONPATH +:= scripts
BIFROST_LIB_CONFIG_FILES += $packConfigText
"@
[System.IO.File]::WriteAllText($modFile, $moduleText, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "Native Bifrost Scales pack built successfully." -ForegroundColor Green
Write-Host "Install root: $installRoot"
Write-Host "Operator : $($operatorDll.FullName)"
Write-Host "Node JSON : $nodeDefinition"
Write-Host "Graph     : $staticGraph"
Write-Host "PackConfig: $packConfig"
Write-Host "Parity CLI: $parityDump"
Write-Host "Benchmark : $performanceBenchmark"
Write-Host "GPU Bench : $gpuPreviewBenchmark"
Write-Host "Edge Bench: $boundaryDensityBenchmark"
Write-Host "Cache Bench: $stageCacheBenchmark"
Write-Host "Distribution Bench: $distributionBenchmark"
Write-Host "Module    : $modFile"
Write-Host ""
Write-Host "Bifrost Scales 0.10.6 uses Payload Schema 10 / Operator Contract 18 / Profile Schema 9, the exact Cell Hot Path, process-shared Stage Cache, and OpenCL GPU Preview; do not reuse a pre-0.10.6 DLL." -ForegroundColor Yellow
Write-Host "Completely restart Maya before running the native smoke test." -ForegroundColor Yellow
