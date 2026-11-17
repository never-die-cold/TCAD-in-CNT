from pathlib import Path

import pytest

from cnt_tid.config import load_config


def test_baseline_config_loads() -> None:
    config = load_config(Path("configs/baseline.toml"))
    assert config.n_device.polarity == "n"
    assert config.p_device.polarity == "p"
    assert config.doses_krad[0] == 0.0


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("vdd=0.8\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown SimulationConfig fields"):
        load_config(path)


def test_negative_dose_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("doses_krad=[0, -1]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-negative"):
        load_config(path)
