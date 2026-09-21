from evaluations.mass_analytical_trial import (
    DEFAULT_CONFIG,
    load_mass_config,
    model_economics,
)


def test_mass_trial_population_and_scenarios_are_consistent():
    config = load_mass_config(DEFAULT_CONFIG)

    assert config["population"] == 10_000
    assert len(config["scenarios"]) == 7
    assert sum(item["count"] for item in config["scenarios"]) == 10_000


def test_mass_trial_shows_query_deduplication_and_agent_reduction():
    config = load_mass_config(DEFAULT_CONFIG)
    economics = model_economics(config)

    assert economics["baseline"]["expensive_query_executions"] == 11_900
    assert economics["signalweave"]["deduplicated_query_groups"] == 82
    assert economics["reductions"]["expensive_query_execution_reduction_pct"] > 99
    assert economics["reductions"]["general_agent_run_reduction_pct"] == 53.0
    assert economics["reductions"]["modeled_total_cost_reduction_pct"] > 95


def test_mass_trial_query_work_accounts_for_batch_scan_multiplier():
    config = load_mass_config(DEFAULT_CONFIG)
    economics = model_economics(config)

    assert economics["signalweave"]["query_work_units"] == 114.8
    assert economics["reductions"]["query_work_reduction_pct"] > 99
