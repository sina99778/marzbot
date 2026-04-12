#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_DIR}"

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is not installed. Please install docker compose plugin or docker-compose." >&2
  exit 1
fi

if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  git pull --ff-only
fi

"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml up -d postgres redis --build
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml run --rm api python -m alembic upgrade head
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml up -d --build api bot worker
