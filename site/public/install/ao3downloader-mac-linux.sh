#!/bin/bash

install_package() {
    if command -v "$1" &>/dev/null; then
        return
    fi
    echo "$1 is required but is not installed. attempting to install $1 automatically..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y "$1"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "$1"
    else
        echo "could not install $1 automatically."
        echo "please install $1 manually and try again."
        exit 1
    fi
}

install_package curl

if ! command -v uv &>/dev/null; then
    echo "uv is required but is not installed. installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

install_package jq

current_version=$(uv tool list | grep 'ao3downloader v' | awk '{print $2}' | sed 's/[^0-9.]*//g')
latest_version=$(curl -s https://pypi.org/pypi/ao3downloader/json | jq -r '.info.version')

if [[ -z "$current_version" ]]; then
    echo "ao3downloader is not installed. installing latest version..."
    uv tool install --python 3.12 --force ao3downloader@latest
elif [[ "$current_version" != "$latest_version" ]]; then
    read -p "a new version of ao3downloader is available ($latest_version, you have $current_version). install the latest version? (y/n): " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        uv tool install --python 3.12 --force ao3downloader@latest
    fi
fi

uv run ao3downloader

if [[ $? -ne 0 ]]; then
    echo "could not start ao3downloader"
    read -p "press any key to exit" -n1 -s
fi
