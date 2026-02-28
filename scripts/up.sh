#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo '.env not found. Creating from .env.example...'
    cp .env.example .env
  else
    echo '.env and .env.example are both missing.' >&2
    exit 1
  fi
fi

if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker CLI not found. Install Docker Engine/Desktop first.' >&2
  exit 1
fi

if [ "${FORCE_RESET_PROXY:-0}" = "1" ]; then
  echo 'Force-resetting proxy container...'
  docker compose rm -s -f proxy >/dev/null 2>&1 || true
fi

echo 'Starting stack with rebuild...'
if [ "${COMPOSE_FORCE_RECREATE:-0}" = "1" ]; then
  docker compose up -d --build --remove-orphans --force-recreate
else
  docker compose up -d --build --remove-orphans
fi

echo 'Current services:'
docker compose ps

echo 'Health endpoint check (proxy):'
if command -v curl >/dev/null 2>&1; then
  if curl -fsS http://127.0.0.1/api/health >/dev/null 2>&1; then
    echo 'OK: http://127.0.0.1/api/health'
  else
    echo 'Warning: health check failed via localhost proxy. Check docker compose logs proxy backend.'
  fi
else
  echo 'curl not found, skip health check.'
fi

echo 'Done.'
