param(
    [string]$ServerAlias = "openclaw-server",
    [string]$RemoteBackupPath = "/home/guagua/apps/kline/shared/backups",
    [string]$LocalBackupPath = "D:\kline-backups"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ServerAlias -notmatch '^[A-Za-z0-9_.@-]+$') {
    throw "Invalid server alias"
}
if ($RemoteBackupPath -notmatch '^/[A-Za-z0-9_./-]+$') {
    throw "Invalid remote backup path"
}

New-Item -ItemType Directory -Force -Path $LocalBackupPath | Out-Null
$remoteNames = @(
    & ssh $ServerAlias "find '$RemoteBackupPath' -maxdepth 1 -type f -name 'kline-data-*.tar.gz' -printf '%f\n' | sort"
)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to list remote backups"
}

$remoteNames = @($remoteNames | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($remoteNames.Count -eq 0) {
    Write-Host "No remote backups are waiting for transfer."
    exit 0
}

foreach ($archiveName in $remoteNames) {
    if ($archiveName -notmatch '^kline-data-[0-9]{8}T[0-9]{6}Z\.tar\.gz$') {
        throw "Unexpected remote backup name: $archiveName"
    }
    $checksumName = $archiveName -replace '\.gz$', '.sha256'
    $remoteArchive = "$RemoteBackupPath/$archiveName"
    $remoteChecksum = "$RemoteBackupPath/$checksumName"
    $localArchive = Join-Path $LocalBackupPath $archiveName
    $localChecksum = Join-Path $LocalBackupPath $checksumName
    $partialArchive = "$localArchive.partial"

    & scp "${ServerAlias}:$remoteChecksum" $localChecksum
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to download checksum for $archiveName"
    }
    $expected = ((Get-Content -LiteralPath $localChecksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()

    $needsDownload = $true
    if (Test-Path -LiteralPath $localArchive) {
        $existingHash = (Get-FileHash -LiteralPath $localArchive -Algorithm SHA256).Hash.ToLowerInvariant()
        $needsDownload = $existingHash -ne $expected
    }
    if ($needsDownload) {
        if (Test-Path -LiteralPath $partialArchive) {
            Remove-Item -LiteralPath $partialArchive -Force
        }
        & scp "${ServerAlias}:$remoteArchive" $partialArchive
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to download $archiveName"
        }
        $actual = (Get-FileHash -LiteralPath $partialArchive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "SHA-256 mismatch for $archiveName; remote copy was retained"
        }
        Move-Item -LiteralPath $partialArchive -Destination $localArchive -Force
    }

    $actual = (Get-FileHash -LiteralPath $localArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "Local verification failed for $archiveName; remote copy was retained"
    }

    & ssh $ServerAlias "rm -- '$remoteArchive' '$remoteChecksum'"
    if ($LASTEXITCODE -ne 0) {
        throw "Local backup is valid, but remote cleanup failed for $archiveName"
    }
    $receipt = [ordered]@{
        archive = $archiveName
        size = (Get-Item -LiteralPath $localArchive).Length
        sha256 = $actual
        server = $ServerAlias
        remoteDeleted = $true
        transferredAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    $receiptPath = Join-Path $LocalBackupPath "$archiveName.receipt.json"
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8
    Write-Host "Verified locally and removed from VPS: $localArchive"
}
