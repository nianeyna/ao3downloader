[array] $dependencies = Get-Content .\requirements.txt

if (!(Test-Path -Path .\venv\)) {
    Write-Host 'Venv Path not found, starting first run items'
    python -m venv venv
    call .\venv\Scripts\activate
    python -m pip install --upgrade pip
    foreach ($depend in $dependencies) {
        python install $depend
    }
} else {
    call .\venv\Scripts\activate
}

Start-Process python.exe ".\ao3downloader.py"