#!/bin/bash
set -euo pipefail

get_new_version() {
    local api_url="$1"
    local version_format="^([0-9]{1,4})\.([0-9]{1,2})\.([0-9]+)"

    echo "Getting current repository version" >&2
    local version=$(uv version --short)
    
    if [[ ! "$version" =~ ${version_format} ]]; then
        echo "ERROR: Unexpected repository version format $version" >&2
        exit 1
    fi

    echo "Checking for existing package version at $api_url" >&2

    local api_response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$api_url")
    local api_response_body=$(echo "$api_response" | sed -e 's/HTTPSTATUS\:.*//g')
    local api_response_status=$(echo "$api_response" | tr -d '\n' | sed -e 's/.*HTTPSTATUS://')

    local api_version
    if [ "$api_response_status" -eq 200 ]; then
        api_version=$(echo "$api_response_body" | jq -r '.info.version')
        echo "Found existing package version: $api_version" >&2
    elif [ "$api_response_status" -eq 404 ]; then
        api_version="0.0.0"
        echo "No existing package version found" >&2
    else
        echo "ERROR: Status code when fetching package version from api was $api_response_status" >&2
        exit 1
    fi

    if [[ ! "$api_version" =~ ${version_format} ]]; then
        echo "ERROR: Unexpected existing package version format $api_version" >&2
        exit 1
    fi

    echo "Comparing current repository version ($version) with existing package version ($api_version)" >&2
    
    local max_version=$(echo -e "$version\n$api_version" | sort -V | tail -n1)
    echo "Maximum existing version is $max_version" >&2

    IFS='.' read -r max_year max_month max_patch <<< "$max_version"
    local max_version_prefix="${max_year}.${max_month}"
    echo "Maximum existing version date is $max_version_prefix" >&2

    local new_version_prefix=$(date -u +%Y.%-m)
    echo "The current UTC date is $new_version_prefix" >&2

    local new_version
    if [[ "${max_version_prefix}" > "${new_version_prefix}" ]]; then
        echo "ERROR: The current UTC date (${new_version_prefix}) is less" \
             "than the maximum existing version date (${max_version_prefix})" >&2
        exit 1
    elif [[ "${max_version_prefix}" == "${new_version_prefix}" ]]; then
        echo "The current UTC date (${new_version_prefix}) is equal to" \
             "the maximum existing version date (${max_version_prefix})" >&2
        echo "Incrementing the patch version" >&2
        new_version="${new_version_prefix}.$((10#$max_patch + 1))"
    else
        echo "The current UTC date (${new_version_prefix}) is greater than" \
             "the maximum existing version date (${max_version_prefix})" >&2
        echo "Setting the patch version to 0" >&2
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
echo "Setting version to $new_version"
uv version "$new_version"

echo "Committing version bump to branch $branch_name"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add pyproject.toml
git add uv.lock
git commit -m "Bump version to $new_version"

remote_url=$(git remote get-url origin)
if [[ "$remote_url" =~ ^https:// ]]; then
    cleaned_url=$(echo "$remote_url" | sed -E 's#https://[^/@]+@#https://#')
    authed_url=$(echo "$cleaned_url" | sed -E "s#https://#https://x-access-token:${GITHUB_TOKEN}@#")
    git remote set-url origin "$authed_url"
fi

git push origin HEAD:"$branch_name"
git pull origin "$branch_name"

echo "Creating tag for version $new_version"
tag_name="${tag_prefix}${new_version}"
git tag -a "$tag_name" -m "$tag_message"
git push origin "$tag_name"

echo "Building and publishing package"
uv build
if [ "$is_test" = "true" ]; then
    uv publish --index testpypi
else
    uv publish
fi
