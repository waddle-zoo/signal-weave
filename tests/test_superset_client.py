from semantic_monitor.superset_client import SupersetClient


def test_metadata_mapping_is_read_only_and_safe():
    snapshot = SupersetClient.metadata_to_snapshot(
        {"id": 42, "dashboard_title": "Revenue", "owners": [{"username": "alice"}]}
    )
    assert snapshot.id == "42"
    assert snapshot.title == "Revenue"
    assert snapshot.owners == ["alice"]
    assert snapshot.charts == []
