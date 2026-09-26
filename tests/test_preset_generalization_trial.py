from evaluations.preset_generalization_trial import run_trial


def test_generated_preset_shapes_do_not_depend_on_named_fixture_values():
    report = run_trial(seed=17, workspace_count=4, charts_per_workspace=8)

    assert report["passed"] is True
    assert report["chart_count"] == 32
    assert set(report["case_coverage"]) == {
        "ambiguous_numeric",
        "dict_metric",
        "empty",
        "explicit",
        "implicit_count",
        "missing_metric",
        "non_numeric_metric",
        "provider_error",
    }
    assert set(report["envelope_coverage"]) == {
        "columnar",
        "data",
        "records",
        "rows",
        "values",
    }
