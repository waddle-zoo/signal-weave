.PHONY: install test lint prove benchmark verify docker-up docker-down

install:
	uv sync --extra dev

test:
	uv run python -m pytest

lint:
	uv run ruff check .

prove:
	uv run python -m evaluations.cli prove

benchmark:
	uv run python -m evaluations.cli benchmark --systems jev --repeats 5

verify:
	uv run ruff check .
	uv run python -m pytest

docker-up:
	docker compose up --build

docker-down:
	docker compose down
