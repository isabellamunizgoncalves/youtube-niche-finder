#!/usr/bin/env bash
# Runs every time the codespace starts: brings the dashboard up.
set -euo pipefail
cd "$(dirname "$0")/.."

for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
docker image inspect niche-finder:latest >/dev/null 2>&1 || docker compose build

key="${YOUTUBE_API_KEY:-$(grep -E '^YOUTUBE_API_KEY=' .env 2>/dev/null | cut -d= -f2- || true)}"
if [ -n "$key" ]; then
  docker compose up -d web worker
  echo "Painel com a sua chave: abra a aba PORTS e clique no globo da porta 8080."
else
  # No key yet: show the demo data so the dashboard is not empty.
  docker compose up -d postgres
  for i in $(seq 1 30); do docker compose exec -T postgres pg_isready -U niches >/dev/null 2>&1 && break; sleep 2; done
  if [ ! -f .devcontainer/.demo-seeded ]; then
    docker run --rm --network niche-finder_default -e POSTGRES_HOST=postgres niche-finder:latest python tests/seed_demo.py && touch .devcontainer/.demo-seeded
  fi
  docker compose up -d web
  echo "Sem chave do YouTube: o painel abre com dados de demonstração. Veja COMECE-AQUI.md para pôr a sua chave."
fi
