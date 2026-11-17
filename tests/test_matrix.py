import json
from pathlib import Path

import pytest

from cnt_tid.config import SimulationConfig, config_sha256
from cnt_tid.matrix import run_matrix


def test_matrix_writes_traceable_scenarios(tmp_path: Path) -> None:
    config = SimulationConfig(
        doses_krad=(0.0, 100.0), transfer_points=30, inverter_points=201
    )
    result = run_matrix(
        config,
        tmp_path,
        oxide_scales=(0.8, 1.0),
        length_scales=(1.0,),
    )
    expected = {
        "matrix_summary.csv",
        "matrix_manifest.csv",
        "matrix_metadata.json",
        "matrix_metrics.png",
        "runs",
    }
    assert expected == {path.name for path in tmp_path.iterdir()}
    assert result.failed_count == 0
    assert len(result.manifest) == 2
    assert len(result.summary) == 4
    assert set(result.summary["oxide_thickness_nm"]) == {8.0, 10.0}

    nominal_dir = tmp_path / "runs" / "oxide-1_length-1"
    metadata = json.loads((nominal_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["config_sha256"] == config_sha256(config)
    matrix_metadata = json.loads(
        (tmp_path / "matrix_metadata.json").read_text(encoding="utf-8")
    )
    assert matrix_metadata["scenario_count"] == 2
    assert matrix_metadata["config_sha256"] == config_sha256(config)


def test_matrix_records_failure_and_runs_remaining_scenarios(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = SimulationConfig(doses_krad=(0.0,), inverter_points=201)

    def fail_short_channel(trial, output_dir):
        if trial.n_device.length_nm < config.n_device.length_nm:
            raise RuntimeError("synthetic convergence failure")
        from cnt_tid.workflow import run_simulation

        return run_simulation(trial, output_dir)

    monkeypatch.setattr("cnt_tid.matrix.run_simulation", fail_short_channel)
    result = run_matrix(config, tmp_path, oxide_scales=(1.0,), length_scales=(0.8, 1.0))

    assert result.failed_count == 1
    assert len(result.summary) == 1
    failed = result.manifest[result.manifest["status"] == "failed"].iloc[0]
    assert "synthetic convergence failure" in failed["error"]
    failure_log = tmp_path / "runs" / failed["scenario_id"] / "failure.txt"
    assert failure_log.is_file()
    assert (tmp_path / "runs" / "oxide-1_length-1" / "summary.csv").is_file()


@pytest.mark.parametrize(
    ("oxide_scales", "length_scales"),
    [
        ((), (1.0,)),
        ((0.0,), (1.0,)),
        ((float("nan"),), (1.0,)),
        ((1.0, 1.0), (1.0,)),
        ((1.0,), (-0.8,)),
    ],
)
def test_matrix_rejects_invalid_scales(
    tmp_path: Path, oxide_scales: tuple[float, ...], length_scales: tuple[float, ...]
) -> None:
    with pytest.raises(ValueError):
        run_matrix(
            SimulationConfig(),
            tmp_path,
            oxide_scales=oxide_scales,
            length_scales=length_scales,
        )
