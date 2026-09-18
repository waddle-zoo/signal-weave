.PHONY: install test lint prove benchmark daily-trial enterprise-trial discovery-trial query-trial verify docker-up docker-down

install:
	uv sync --extra dev

test:
	uv run python -m pytest

lint:
	uv run ruff check .

prove:
	uv run python -m evaluations.cli prove

daily-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -m evaluations.daily_monitor_trial --output artifacts/daily-monitor-trial.json

benchmark:
	uv run python -m evaluations.cli benchmark --systems jev --repeats 5

enterprise-trial:
	uv run python -m evaluations.enterprise_mcp_cli generate --config evaluations/data/enterprise-portfolio.json --output artifacts/enterprise/portfolio-fixture.json
	uv run python -m evaluations.enterprise_runner --fixture artifacts/enterprise/portfolio-fixture.json --store artifacts/enterprise/portfolio-research-cards.json --trace artifacts/enterprise/portfolio-research-trace.jsonl --report artifacts/enterprise/portfolio-research-report.json --markdown artifacts/enterprise/portfolio-research-report.md --evaluator research --run-id portfolio-research

discovery-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -c 'import asyncio, json; from pathlib import Path; from evaluations.discovery_trial import run_trial; print(json.dumps(asyncio.run(run_trial(48, Path("artifacts/discovery-trial-48.json"))), indent=2))'

query-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -c 'import asyncio, json; from pathlib import Path; from evaluations.query_trial import run_trial; print(json.dumps(asyncio.run(run_trial(24, Path("artifacts/query-trial-24.json"))), indent=2))'

verify:
	uv run ruff check .
	uv run python -m pytest

docker-up:
	docker compose up --build

docker-down:
	docker compose down
