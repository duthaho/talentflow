.PHONY: seed

seed:
	docker compose --profile tools run --rm seed
