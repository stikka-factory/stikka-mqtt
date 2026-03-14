#!/bin/bash

# Script: GitHubFileDownloader.sh
# Author: electblake <https://github.com/electblake>
# Version: 1.0
# Description: This script converts a GitHub repository file URL to its GitHub API URL for file contents, checks if the user is logged into GitHub CLI, and downloads the file.
# Source: https://gist.github.com/electblake/7ef3a63e20b3c8db67d9d66f7021d727
# Credits:
# - Inspired by answers on: https://stackoverflow.com/questions/9159894/download-specific-files-from-github-in-command-line-not-clone-the-entire-repo
# - Used "Bash Script" GPT by Widenex for script creation assistance.
#
# MIT License
# Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted.
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
# Requires: jq, curl, and GitHub CLI (gh) installed and configured.
#
# **Installation:**
# 1. Download this file using the old fashioned way: Click the download icon on github.com
# 2. Make script executable: chmod +x ./GitHubFileDownloader.sh
# 3. Place this script in a directory included in your $PATH, e.g., /usr/local/bin (macOS El Capitan or newer) or $HOME/bin.
#
# *Bonus Alternative* step is to rename to command `gh-dl` and place in $PATH like:
#
# ```bash
# mv ./GithubFileDownloader.sh $HOME/bin/gh-dl
# 
# # or for macOS  users:
# mv ./GithubFileDownloader.sh /usr/local/bin/gh-dl
# ````
#
# **Example Usage**
# - You must be logged into the GitHub CLI. If not, the script will initiate the login flow.
#
# ```console
# 
# $ GithubFileDownloader.sh https://github.com/github/docs/blob/main/README.md
# File downloaded successfully: README.md
#
# $ cat README.md | head -2
# # GitHub Docs <!-- omit in toc -->
# [![Build GitHub Docs On Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new/?repo=github)
# 
# ```
#


# Function to check if the user is logged into the GitHub CLI
check_gh_cli_login() {
  if ! gh auth status &> /dev/null; then
    printf "You are not logged into the GitHub CLI. Starting login flow...\n"
    if ! gh auth login --web; then
      printf "GitHub CLI login failed.\n" >&2
      return 1
    fi
  fi
}

# Function to convert a GitHub file URL to its corresponding GitHub API URL
convert_url_to_api() {
  local input_url="$1"
  local regex='https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)'
  
  if [[ $input_url =~ $regex ]]; then
    local user="${BASH_REMATCH[1]}"
    local repo="${BASH_REMATCH[2]}"
    local branch="${BASH_REMATCH[3]}"
    local path="${BASH_REMATCH[4]}"
    printf "https://api.github.com/repos/%s/%s/contents/%s?ref=%s\n" "$user" "$repo" "$path" "$branch"
  else
    printf "Invalid URL format.\n" >&2
    return 1
  fi
}

# Function to download the file using GitHub API URL
download_file_using_api() {
  local api_url="$1"
  local original_file_name=$(basename "$2")
  
  # Ensure jq and curl are installed
  if ! command -v jq &> /dev/null || ! command -v curl &> /dev/null; then
    printf "Error: jq and curl are required.\n" >&2
    return 1
  fi
  
  # Fetch the download URL using GitHub CLI and jq
  local download_url
  if ! download_url=$(gh api "$api_url" --jq .download_url); then
    printf "Failed to fetch download URL.\n" >&2
    return 1
  fi
  
  # Download the file
  if ! curl -sL "$download_url" -o "$original_file_name"; then
    printf "Failed to download the file.\n" >&2
    return 1
  fi
  
  printf "File downloaded successfully: %s\n" "$original_file_name"
}

main() {
  local url="$1"

  if [[ -z $url ]]; then
    printf "Usage: $0 <github file URL>\nExample: $0 https://github.com/github/docs/blob/main/README.md\n" >&2
    return 1
  fi
  
  # Check if the user is logged into GitHub CLI
  if ! check_gh_cli_login; then
    return 1
  fi

  local api_url
  if ! api_url=$(convert_url_to_api "$url"); then
    printf "Failed to convert URL to API URL.\n" >&2
    return 1
  fi

  download_file_using_api "$api_url" "$url"
}

main "$@"
