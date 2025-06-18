#!/bin/bash

if ! command -v uv &> /dev/null; then
    read -p "uv is required to run this script, but is not currently installed. do you want to install it? (y/n): " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        echo "installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    else
        exit 1
    fi
fi

current_version=$(uv tool list | grep 'ao3downloader v' | awk '{print $2}' | sed 's/[^0-9.]*//g')
latest_version=$(curl -s https://test.pypi.org/pypi/ao3downloader/json | grep '"version":' | head -1 | sed -E 's/.*"([0-9\.]+)".*/\1/')

if [[ -z "$current_version" ]]; then
    echo "ao3downloader is not installed. installing latest version..."
    uv tool install --force --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match ao3downloader@latest
elif [[ "$current_version" != "$latest_version" ]]; then
    read -p "a new version of ao3downloader is available ($latest_version, you have $current_version). install the latest version? (y/n): " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        uv tool install --force --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match ao3downloader@latest
    fi
fi

uv run ao3downloader

if [[ $? -ne 0 ]]; then
    echo "could not start ao3downloader"
    read -p "press any key to exit" -n1 -s
fi
