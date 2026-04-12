#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_DIR}"

COMPOSE_IMPL=""

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
  COMPOSE_IMPL="plugin"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
  COMPOSE_IMPL="legacy"
else
  echo "Docker Compose is not installed. Please install docker compose plugin or docker-compose." >&2
  exit 1
fi

if [[ "${COMPOSE_IMPL}" == "legacy" ]]; then
  echo "Legacy docker-compose detected; applying compatibility cleanup before deploy..."
  "${COMPOSE_CMD[@]}" -f docker-compose.prod.yml down --remove-orphans || true
  docker rm -f telegramsellbot-postgres telegramsellbot-redis telegramsellbot-api telegramsellbot-bot telegramsellbot-worker >/dev/null 2>&1 || true
fi

"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml up -d --build postgres redis

DB_BOOTSTRAP_EXIT_CODE=0
if [[ -f "alembic.ini" && -d "migrations" ]]; then
  "${COMPOSE_CMD[@]}" -f docker-compose.prod.yml run --rm api python -m alembic upgrade head || DB_BOOTSTRAP_EXIT_CODE=$?
else
  "${COMPOSE_CMD[@]}" -f docker-compose.prod.yml run --rm api python -c "import asyncio; import models; from core.database import init_database; asyncio.run(init_database())" || DB_BOOTSTRAP_EXIT_CODE=$?
fi

if [[ "${DB_BOOTSTRAP_EXIT_CODE}" -ne 0 ]]; then
  if docker volume ls --format '{{.Name}}' | grep -q '^telegramsellbot_postgres_data$'; then
    echo
    echo "Database bootstrap failed while an existing PostgreSQL volume is present."
    echo "Most likely cause: POSTGRES_PASSWORD in .env no longer matches the password stored in the existing database volume."
    echo
    echo "If this is a fresh install and you do NOT need old data, run:"
    echo "  docker volume rm telegramsellbot_postgres_data"
    echo "Then rerun the installer."
    echo
    echo "If you need the old data, restore the original POSTGRES_PASSWORD and DATABASE_URL values in .env, then deploy again."
    echo
  fi
  exit "${DB_BOOTSTRAP_EXIT_CODE}"
fi

"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml up -d --build api bot worker
