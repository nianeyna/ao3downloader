#!/bin/bash
set -euo pipefail

get_new_version() {
    local api_url="$1"
    local version_format="^([0-9]{4})\.([0-9]{1,2})\.([0-9]+)"

    echo "Getting current repository version"
    local version=$(uv version --short)
    
    if [[ ! "$version" =~ ${version_format} ]]; then
        echo "ERROR: Unexpected repository version format $version"
        exit 1
    fi

    echo "Checking for existing package version at $api_url"

    local api_response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$api_url")
    local api_response_body=$(echo "$api_response" | sed -e 's/HTTPSTATUS\:.*//g')
    local api_response_status=$(echo "$api_response" | tr -d '\n' | sed -e 's/.*HTTPSTATUS://')

    local api_version
    if [ "$api_response_status" -eq 200 ]; then
        api_version=$(echo "$api_response_body" | jq -r '.info.version')
        echo "Found existing package version: $api_version"
    elif [ "$api_response_status" -eq 404 ]; then
        api_version="0.0.0"
        echo "No existing package version found"
    else
        echo "ERROR: Status code when fetching package version from api was $api_response_status"
        exit 1
    fi

    if [[ ! "$api_version" =~ ${version_format} ]]; then
        echo "ERROR: Unexpected existing package version format $api_version"
        exit 1
    fi

    echo "Comparing current repository version ($version) with existing package version ($api_version)"
    
    local max_version=$(echo -e "$version\n$api_version" | sort -V | tail -n1)
    echo "Maximum existing version is $max_version"

    IFS='.' read -r max_year max_month max_patch <<< "$max_version"
    local max_version_prefix="${max_year}.${max_month}"
    echo "Maximum existing version date is $max_version_prefix"

    local new_version_prefix=$(date -u +%Y.%-m)
    echo "The current UTC date is $new_version_prefix"

    local new_version
    if [[ "${max_version_prefix}" > "${new_version_prefix}" ]]; then
        echo "ERROR: The current UTC date (${new_version_prefix}) is less " \
            "than the maximum existing version date (${max_version_prefix})"
        exit 1
    elif [[ "${max_version_prefix}" == "${new_version_prefix}" ]]; then
        echo "The current UTC date (${new_version_prefix}) is equal to " \
            "the maximum existing version date (${max_version_prefix})"
        echo "Incrementing the patch version"
        new_version="${new_version_prefix}.$((10#$max_patch + 1))"
    else
        echo "The current UTC date (${new_version_prefix}) is greater than " \
            "the maximum existing version date (${max_version_prefix})"
        echo "Setting the patch version to 0"
        new_version="${new_version_prefix}.0"
    fi

    echo "$new_version"
}

tag_prefix="$1"
tag_message="$2"
branch_name="$3"
is_test="$4"

if [ "$is_test" = "true" ]; then
    api_url="https://test.pypi.org/pypi/ao3downloader/json"
else
    api_url="https://pypi.org/pypi/ao3downloader/json"
fi

new_version=$(get_new_version "$api_url")
uv version "$new_version"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add pyproject.toml
git commit -m "Bump version to $new_version"

git push origin HEAD:"$branch_name"
git pull origin "$branch_name"

tag_name="${tag_prefix}${new_version}"
git tag -a "$tag_name" -m "$tag_message"
git push origin "$tag_name"

uv build
if [ "$is_test" = "true" ]; then
    uv publish --index testpypi
else
    uv publish
fi
