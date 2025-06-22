if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv is required but is not installed. installing uv..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
}

$current_version = (& uv tool list | Select-String 'ao3downloader v' | ForEach-Object {
    ($_ -split '\s+')[1] -replace '[^0-9\.]', ''
})

$latest_version = (Invoke-RestMethod -Uri "https://pypi.org/pypi/ao3downloader/json").info.version

if (-not $current_version) {
    Write-Host "ao3downloader is not installed. installing latest version..."
    uv tool install --python 3.12 --force ao3downloader@latest
} elseif ($latest_version -and ($current_version -ne $latest_version)) {
    $choice = Read-Host "a new version of ao3downloader is available ($latest_version, you have $current_version). install the latest version? (y/n)"
    if ($choice -match '^[Yy]$') {
        uv tool install --python 3.12 --force ao3downloader@latest
    }
}

uv run ao3downloader

if ($LASTEXITCODE -ne 0) {
    Write-Host "could not start ao3downloader"
    Read-Host "press any key to exit"
}
