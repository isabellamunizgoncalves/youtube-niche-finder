#!/usr/bin/env bash
# Runs once, when the codespace is created: prepares .env and builds the image.
set -euo pipefail
cd "$(dirname "$0")/.."

for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done

[ -f .env ] || cp .env.example .env
if [ -n "${YOUTUBE_API_KEY:-}" ]; then
  # Put the Codespaces secret into .env (the file is in .gitignore, it never goes to GitHub).
  sed -i "s|^YOUTUBE_API_KEY=.*|YOUTUBE_API_KEY=${YOUTUBE_API_KEY}|" .env
fi

docker compose build
