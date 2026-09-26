.PHONY: install test lint prove benchmark daily-trial enterprise-trial discovery-trial bundle-trial query-trial retrieval-explanation-trial preset-trial preset-bootstrap-check preset-provider-smoke preset-live-trial verify docker-up docker-down

install:
	uv sync --extra dev

test:
	uv run python -m pytest

lint:
	uv run ruff check .

prove:
	uv run python -m evaluations.cli prove

daily-trial:
	PUSH_WEBHOOK_TOKEN=$${PUSH_WEBHOOK_TOKEN:?set a trial webhook token} TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -m evaluations.daily_monitor_trial --output artifacts/daily-monitor-trial.json

benchmark:
	uv run python -m evaluations.cli benchmark --systems jev --repeats 5

enterprise-trial:
	uv run python -m evaluations.enterprise_mcp_cli generate --config evaluations/data/enterprise-portfolio.json --output artifacts/enterprise/portfolio-fixture.json
	uv run python -m evaluations.enterprise_runner --fixture artifacts/enterprise/portfolio-fixture.json --store artifacts/enterprise/portfolio-research-cards.json --trace artifacts/enterprise/portfolio-research-trace.jsonl --report artifacts/enterprise/portfolio-research-report.json --markdown artifacts/enterprise/portfolio-research-report.md --evaluator research --run-id portfolio-research

discovery-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -c 'import asyncio, json; from pathlib import Path; from evaluations.discovery_trial import run_trial; print(json.dumps(asyncio.run(run_trial(48, Path("artifacts/discovery-trial-48.json"))), indent=2))'

bundle-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -c 'import asyncio, json; from pathlib import Path; from evaluations.bundle_trial import run_trial; print(json.dumps(asyncio.run(run_trial(48, Path("artifacts/bundle-trial-48.json"))), indent=2))'

query-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python -c 'import asyncio, json; from pathlib import Path; from evaluations.query_trial import run_trial; print(json.dumps(asyncio.run(run_trial(24, Path("artifacts/query-trial-24.json"))), indent=2))'

retrieval-explanation-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} uv run python evaluations/retrieval_explanation_trial.py --output artifacts/retrieval-explanation-trial.json

preset-trial:
	uv run python evaluations/preset_hosted_trial.py --output artifacts/preset-hosted-trial.json

preset-bootstrap-check:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a TypeSafe key file} \
	uv run python scripts/preset_bootstrap_check.py \
		--output artifacts/preset-bootstrap-check.json

preset-provider-smoke:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a TypeSafe key file} \
	uv run python scripts/preset_bootstrap_check.py \
		--dashboard-id "$${PRESET_BOOTSTRAP_DASHBOARD_ID:?set a dashboard id}" \
		--chart-id "$${PRESET_BOOTSTRAP_CHART_ID:?set a chart id}" \
		--output artifacts/preset-provider-smoke.json

preset-live-trial:
	TYPESAFE_API_KEY_FILE=$${TYPESAFE_API_KEY_FILE:?set a live TypeSafe key file} \
	uv run python evaluations/preset_live_onboarding_trial.py \
		--goal "$${PRESET_TRIAL_GOAL:?set a human monitoring goal}" \
		--why "$${PRESET_TRIAL_WHY:?set why the goal matters}" \
		--destination "$${PRESET_TRIAL_DESTINATION:-slack://shadow-review}" \
		--approve \
		--output artifacts/preset-live-onboarding-shadow.json

verify:
	uv run ruff check .
	uv run python -m pytest

docker-up:
	docker compose up --build

docker-down:
	docker compose down
