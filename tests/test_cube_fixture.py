import json
import stat

import pytest

from evaluations.cube_fixture import CUBE_IMAGE, POSTGRES_IMAGE, prepare


@pytest.mark.parametrize("company", ["retail", "saas", "marketplace"])
def test_real_semantic_fixture_uses_raw_rows_and_versioned_models(tmp_path, company):
    root = tmp_path / company
    report = prepare(root, company)
    model = json.loads((root / "model/revenue.yml").read_text())
    sql = (root / "seed.sql").read_text()
    assert report["raw_rows"] == 96 and len(model["cubes"]) == 6
    assert CUBE_IMAGE.endswith("5a728f42924051b9499016fb1ac9d1695ab544084d57221c0dd173e4c730730a")
    assert "@sha256:" in POSTGRES_IMAGE
    assert "default_transaction_read_only=on" in sql
    assert "GRANT SELECT" in sql and "GRANT ALL" not in sql
    assert "CREATE TABLE period_coverage" in sql
    assert "LEFT JOIN period_coverage" in sql
    assert sql.count("INSERT INTO transactions VALUES") == 96
    assert all(cube["title"] == "Revenue" for cube in model["cubes"])
    for cube in model["cubes"]:
        assert cube["sql_table"] == "public.cube_transactions"
        measures = {row["name"]: row for row in cube["measures"]}
        assert measures["amount"]["type"] == "sum"
        assert measures["expected_records"]["type"] == "max"
        assert "::numeric" in measures["amount"]["sql"]
        assert measures["amount"]["meta"]["revision"]
    assert stat.S_IMODE((root / "private.env").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "seed.sql").stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        prepare(root, company)


def test_fixture_rejects_privileged_ports_before_writing(tmp_path):
    with pytest.raises(ValueError, match="unprivileged"):
        prepare(tmp_path / "bad", "retail", port=80)
    assert not (tmp_path / "bad").exists()
