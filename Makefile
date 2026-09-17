.PHONY: install test lint prove docker-up docker-down

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check .

prove:
	uv run semantic-monitor prove

docker-up:
	docker compose up --build

docker-down:
	docker compose down
