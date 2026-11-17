import json
from pathlib import Path

from cnt_tid.config import SimulationConfig
from cnt_tid.workflow import run_simulation


def test_workflow_writes_complete_artifacts(tmp_path: Path) -> None:
    config = SimulationConfig(
        doses_krad=(0.0, 100.0), transfer_points=30, inverter_points=201
    )
    artifacts = run_simulation(config, tmp_path)
    expected = {
        "device_transfer.csv",
        "inverter_vtc.csv",
        "summary.csv",
        "metadata.json",
        "device_transfer.png",
        "inverter_vtc.png",
        "degradation_metrics.png",
    }
    assert expected == {path.name for path in tmp_path.iterdir()}
    assert len(artifacts.summary) == 2
    assert (artifacts.summary["nml_v"] > 0).all()
    assert (artifacts.summary["nmh_v"] > 0).all()
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["calibration_status"] == "illustrative_uncalibrated"
    assert len(metadata["config_sha256"]) == 64
