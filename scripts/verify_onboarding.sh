#!/usr/bin/env bash
# Disposable real-service acceptance. Never points migrations at a shared database.
set -euo pipefail
project="${COMPOSE_PROJECT_NAME:-duth154-acceptance-$$}"
export POSTGRES_PORT="${POSTGRES_PORT:-25454}"
export RABBITMQ_PORT="${RABBITMQ_PORT:-26454}"
export RABBITMQ_MANAGEMENT_PORT="${RABBITMQ_MANAGEMENT_PORT:-25455}"
export KEYCLOAK_PORT="${KEYCLOAK_PORT:-28454}"
export MAILPIT_PORT="${MAILPIT_PORT:-28054}"
cleanup() { docker compose -p "$project" down -v --remove-orphans; }
trap cleanup EXIT
# Build the same runtime image for both changed services.
docker compose -p "$project" build onboarding-worker hris-stub
docker compose -p "$project" up -d --wait --wait-timeout 600 postgres rabbitmq keycloak mailpit hris-stub
hris_container="$(docker compose -p "$project" ps -q hris-stub)"
mail_container="$(docker compose -p "$project" ps -q mailpit)"
hris_ip="$(docker inspect "$hris_container" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
mail_ip="$(docker inspect "$mail_container" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
vhost="onboarding-$$"
docker compose -p "$project" exec -T rabbitmq rabbitmqctl add_vhost "$vhost"
docker compose -p "$project" exec -T rabbitmq rabbitmqctl set_permissions -p "$vhost" talentflow '.*' '.*' '.*'
export ONBOARDING_TEST_DATABASE_URL="postgresql+psycopg://talentflow:talentflow@localhost:${POSTGRES_PORT}/talentflow"
export ONBOARDING_TEST_RABBITMQ_URL="amqp://talentflow:talentflow@localhost:${RABBITMQ_PORT}/${vhost}"
export ONBOARDING_TEST_KEYCLOAK_URL="http://localhost:${KEYCLOAK_PORT}"
export ONBOARDING_TEST_HRIS_URL="http://${hris_ip}:8090"
export ONBOARDING_TEST_MAILPIT_URL="http://localhost:${MAILPIT_PORT}"
export ONBOARDING_TEST_SMTP_HOST="$mail_ip"
export DATABASE_URL="$ONBOARDING_TEST_DATABASE_URL"
uv run alembic upgrade head
# Smoke-test the composition root against the migrated public schema.
docker compose -p "$project" up -d --no-deps --wait --wait-timeout 60 onboarding-worker
# No shared test database or queue is used by the service fixtures.
if [[ "${ONBOARDING_VERIFY_FULL:-0}" == "1" ]]; then
  export DUTH59_TEST_POSTGRES_URL="$ONBOARDING_TEST_DATABASE_URL"
  export DUTH59_TEST_RABBITMQ_URL="$ONBOARDING_TEST_RABBITMQ_URL"
  uv run python -m pytest
else
  uv run python -m pytest tests/integration/test_onboarding*.py tests/unit/test_onboarding*.py tests/architecture --no-cov
fi
