.PHONY: seed api-client

seed:
	docker compose --profile tools run --rm --build seed

api-client:
	uv run --frozen python -m scripts.export_openapi web/openapi.json
	npm --prefix web run api:generate
