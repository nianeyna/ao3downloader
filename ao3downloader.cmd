@echo off

if not exist "venv\" (set firstrun="true") else (set firstrun="false")

if %firstrun%=="true" python -m venv venv

call venv\Scripts\activate

if %firstrun%=="true" python -m pip install --upgrade pip & pip install -r requirements.txt

python ao3downloader.py
