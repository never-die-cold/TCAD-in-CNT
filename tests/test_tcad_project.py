import json
import tomllib
from pathlib import Path

import pytest

from cnt_tid.tcad_project import render_tcad_project


def test_incomplete_cntfet_config_is_rejected(tmp_path: Path) -> None:
    # The repository config is complete since v0.7.1; regress one field to a
    # REQUIRED placeholder to keep the hard-stop behaviour covered.
    source = Path("configs/tcad/cntfet_topgate.toml").read_text(encoding="utf-8")
    incomplete = source.replace(
        "gate_length_um = 4.0", 'gate_length_um = "REQUIRED: test"'
    )
    assert incomplete != source
    config = tmp_path / "incomplete.toml"
    config.write_text(incomplete, encoding="utf-8")
    with pytest.raises(ValueError, match="REQUIRED values"):
        render_tcad_project(config, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_complete_config_renders_all_templates_with_provenance(tmp_path: Path) -> None:
    # The repository config itself is complete; it renders as-is.
    config = Path("configs/tcad/cntfet_topgate.toml")
    expected_status = tomllib.loads(config.read_text(encoding="utf-8"))["calibration_status"]

    result = render_tcad_project(config, tmp_path / "output")

    assert {path.name for path in result.generated_files} == {
        "sde_dvs.cmd",
        "sdevice_des.cmd",
        "sdevice.par",
        "datexcodes.txt",
    }
    for path in result.generated_files:
        assert path.is_file()
    assert "@GEOMETRY_" not in (result.output_dir / "sde_dvs.cmd").read_text(
        encoding="utf-8"
    )
    assert "@RUN_INTERFACE_DIT_CM2EV@" not in (
        result.output_dir / "sdevice_des.cmd"
    ).read_text(encoding="utf-8")
    metadata = json.loads(
        (result.output_dir / "tcad_project_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "prepared_not_run"
    assert metadata["calibration_status"] == expected_status
    assert "idvg_raw.csv" in metadata["source_files_sha256"]
    assert "sdevice_des.cmd.in" in metadata["template_sha256"]
