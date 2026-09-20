param(
    [ValidateRange(0,65535)][int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$SetupOnly,
    [switch]$SelfTest,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeDir = Join-Path $projectDir '.runtime'
$setupLock = $null

function Test-Checksum([string]$Path, [string]$Expected) {
    if (-not [IO.File]::Exists($Path)) { return $false }
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $actual = [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '')
        return $actual -eq $Expected
    } finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Get-VerifiedAsset([string]$Url, [string]$Target, [string]$Sha256) {
    if (Test-Checksum $Target $Sha256) { return }
    if ($Offline) { throw "Offline mode: required asset is missing or corrupt: $Target" }
    $uri = [Uri]$Url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin @('www.python.org','raw.githubusercontent.com')) {
        throw "Unexpected dependency source: $Url"
    }
    Write-Host "Downloading $([IO.Path]::GetFileName($Target)) ..."
    $partialFile = $Target + '.partial-' + [guid]::NewGuid().ToString('N')
    try {
        $downloaded = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $partialFile -TimeoutSec 180
                $downloaded = $true
                break
            } catch {
                if ($attempt -eq 3) { throw "Download failed: $Url. Check your connection/proxy and run the launcher again. $($_.Exception.Message)" }
                Start-Sleep -Seconds 1
            }
        }
        if (-not $downloaded -or -not (Test-Checksum $partialFile $Sha256)) {
            throw "SHA-256 mismatch: $Url. The downloaded code will not be executed."
        }
        Move-Item -LiteralPath $partialFile -Destination $Target -Force
    } finally {
        if (Test-Path -LiteralPath $partialFile) { Remove-Item -LiteralPath $partialFile -Force }
    }
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'This package requires 64-bit Windows 10/11.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $locked = Get-Content -LiteralPath (Join-Path $projectDir 'packaging/runtime-lock.json') -Raw | ConvertFrom-Json
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    try {
        $setupLock = [IO.File]::Open((Join-Path $runtimeDir 'setup.lock'), [IO.FileMode]::OpenOrCreate,
                                    [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch { throw 'Another launcher is preparing the runtime. Wait a moment and try again.' }

    $pythonDir = Join-Path $runtimeDir $locked.python.directory
    $pythonExe = Join-Path $pythonDir 'python.exe'
    $pythonValid = $true
    foreach ($entry in $locked.python.files.PSObject.Properties) {
        if (-not (Test-Checksum (Join-Path $pythonDir $entry.Name) $entry.Value)) {
            $pythonValid = $false
            break
        }
    }
    if (-not $pythonValid) {
        $downloadsDir = Join-Path $runtimeDir 'downloads'
        New-Item -ItemType Directory -Force -Path $downloadsDir | Out-Null
        $pythonZip = Join-Path $downloadsDir ([IO.Path]::GetFileName(([Uri]$locked.python.url).AbsolutePath))
        Get-VerifiedAsset $locked.python.url $pythonZip $locked.python.sha256
        Write-Host 'Preparing isolated Python runtime ...'
        New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($pythonZip)
        try {
            foreach ($zipEntry in $archive.Entries) {
                $destination = [IO.Path]::GetFullPath((Join-Path $pythonDir $zipEntry.FullName))
                if (-not $destination.StartsWith($pythonDir + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'Archive entry escapes the runtime directory.'
                }
                if ($zipEntry.Name -eq '') {
                    [IO.Directory]::CreateDirectory($destination) | Out-Null
                } else {
                    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($zipEntry, $destination, $true)
                }
            }
        } finally { $archive.Dispose() }
        foreach ($entry in $locked.python.files.PSObject.Properties) {
            if (-not (Test-Checksum (Join-Path $pythonDir $entry.Name) $entry.Value)) {
                throw "Python extraction failed verification: $($entry.Name). Close other project windows and retry."
            }
        }
    }
    # _pth keeps this runtime isolated from installed Python, pip, and PYTHONPATH.
    # The project is two parents above .runtime/python-<version>-win64.
    [IO.File]::WriteAllText((Join-Path $pythonDir $locked.python.pth), "python313.zip`r`n.`r`n..\..`r`n", [Text.Encoding]::ASCII)
    $rapidDir = Join-Path $runtimeDir 'rapidchiplet'
    New-Item -ItemType Directory -Force -Path $rapidDir | Out-Null
    foreach ($asset in $locked.rapidchiplet.files) {
        Get-VerifiedAsset $asset.url (Join-Path $rapidDir $asset.name) $asset.sha256
    }
    Write-Host "Ready: Python $($locked.python.version), official RapidChiplet $($locked.rapidchiplet.commit.Substring(0,12))."
    $setupLock.Dispose()
    $setupLock = $null

    if ($SelfTest) {
        & $pythonExe -X utf8 (Join-Path $projectDir 'tools/portable_smoke.py')
    } elseif ($SetupOnly) {
        & $pythonExe -X utf8 -c 'import sys; import simple_rapidchiplet; print(sys.executable)'
    } else {
        $guiArgs = @('-X','utf8',(Join-Path $projectDir 'gui.py'),'--port',"$Port")
        if ($NoBrowser) { $guiArgs += '--no-browser' }
        & $pythonExe @guiArgs
    }
    if ($LASTEXITCODE -ne 0) { throw "Application exited with code $LASTEXITCODE. See the message above." }
} catch {
    Write-Host ''
    Write-Host ('Chiplet Lab could not start: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $setupLock) { $setupLock.Dispose() }
}
exit 0
