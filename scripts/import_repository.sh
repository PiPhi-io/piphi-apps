#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <source-repository-url> <destination-prefix>" >&2
  exit 2
fi

source_url=$1
destination=$2

if [[ -e "$destination" ]]; then
  echo "destination already exists: $destination" >&2
  exit 1
fi

default_branch=$(
  git ls-remote --symref "$source_url" HEAD |
    awk '/^ref:/ {sub("refs/heads/", "", $2); print $2; exit}'
)

if [[ -z "$default_branch" ]]; then
  echo "could not determine default branch for $source_url" >&2
  exit 1
fi

git subtree add --prefix "$destination" "$source_url" "$default_branch"
