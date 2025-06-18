if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
    $choice = Read-Host "uv is required to run this script, but is not currently installed. do you want to install it? (y/n)"
    if ($choice -match '^[Yy]$') {
        Write-Host "installing uv..."
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    } else {
        exit 1
    }
}

$current_version = (& uv tool list | Select-String 'ao3downloader v' | ForEach-Object {
    ($_ -split '\s+')[1] -replace '[^0-9\.]', ''
})

$latest_version = (Invoke-RestMethod -Uri "https://test.pypi.org/pypi/ao3downloader/json").info.version

if (-not $current_version) {
    Write-Host "ao3downloader is not installed. installing latest version..."
    uv tool install --index "https://test.pypi.org/simple/" --index-strategy unsafe-best-match ao3downloader@latest
} elseif ($latest_version -and ($current_version -ne $latest_version)) {
    $choice = Read-Host "a new version of ao3downloader is available ($latest_version, you have $current_version). install the latest version? (y/n)"
    if ($choice -match '^[Yy]$') {
        uv tool install --index "https://test.pypi.org/simple/" --index-strategy unsafe-best-match ao3downloader@latest
    }
}

uv run ao3downloader

if ($LASTEXITCODE -ne 0) {
    Write-Host "could not start ao3downloader"
    Read-Host "press any key to exit"
}
