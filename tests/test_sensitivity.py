from pathlib import Path

import pandas as pd
import pytest

from cnt_tid.config import SimulationConfig
from cnt_tid.sensitivity import PARAMETERS, run_sensitivity


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    output = tmp_path_factory.mktemp("sensitivity")
    config = SimulationConfig(doses_krad=(0.0, 100.0), inverter_points=201)
    return run_sensitivity(
        config,
        output,
        magnitude=0.1,
        parameters=("n.qot_slope", "n.threshold_v", "p.qot_slope"),
    )


def test_sensitivity_writes_artifacts(result) -> None:
    expected = {
        "sensitivity.csv",
        "sensitivity_baseline.csv",
        "sensitivity_tornado.png",
        "sensitivity_metadata.json",
    }
    assert expected == {path.name for path in result.output_dir.iterdir()}
    assert not result.table.empty


def test_sensitivity_table_has_expected_columns(result) -> None:
    assert set(result.table["parameter"]) == {"n.qot_slope", "n.threshold_v", "p.qot_slope"}
    assert set(result.table["direction"]) == {"plus", "minus"}
    for metric in ("vm_v", "nml_v", "nmh_v", "n_threshold_shift_v"):
        assert metric in set(result.table["metric"])


def test_threshold_sensitivity_has_expected_sign(result) -> None:
    table = result.table
    n_threshold = table[
        (table["parameter"] == "n.threshold_v")
        & (table["metric"] == "vm_v")
        & (table["direction"] == "plus")
    ]
    # Raising the nFET threshold moves the switching threshold up.
    assert n_threshold["sensitivity_per_unit"].iloc[0] > 0


def test_baseline_matches_direct_metric_frame(result) -> None:
    baseline = pd.read_csv(result.output_dir / "sensitivity_baseline.csv")
    assert baseline["dose_krad"].tolist() == [0.0, 100.0]
    assert (baseline["nml_v"] > 0).all()
    assert (baseline["nmh_v"] > 0).all()


def test_unknown_parameter_is_rejected(tmp_path: Path) -> None:
    config = SimulationConfig(doses_krad=(0.0,), inverter_points=201)
    with pytest.raises(ValueError, match="Unknown sensitivity parameters"):
        run_sensitivity(config, tmp_path, parameters=("n.bogus",))


def test_invalid_magnitude_is_rejected(tmp_path: Path) -> None:
    config = SimulationConfig(doses_krad=(0.0,), inverter_points=201)
    with pytest.raises(ValueError, match="magnitude"):
        run_sensitivity(config, tmp_path, magnitude=1.5)


def test_default_parameter_set_covers_both_devices() -> None:
    assert any(name.startswith("n.") for name in PARAMETERS)
    assert any(name.startswith("p.") for name in PARAMETERS)
