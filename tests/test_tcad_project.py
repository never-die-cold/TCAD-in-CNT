import json
import re
from pathlib import Path

import pytest

from cnt_tid.tcad_project import render_tcad_project


def test_incomplete_cntfet_config_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="REQUIRED values"):
        render_tcad_project("configs/tcad/cntfet_topgate.toml", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_complete_config_renders_all_templates_with_provenance(tmp_path: Path) -> None:
    source = Path("configs/tcad/cntfet_topgate.toml").read_text(encoding="utf-8")
    completed = re.sub(r'"REQUIRED[^\"]*"', "1.0", source)
    config = tmp_path / "completed.toml"
    config.write_text(completed, encoding="utf-8")

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
    metadata = json.loads(
        (result.output_dir / "tcad_project_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "prepared_not_run"
    assert metadata["calibration_status"] == "awaiting_user_digitization_and_assumptions"
    assert "idvg_raw.csv" in metadata["source_files_sha256"]
    assert "sdevice_des.cmd.in" in metadata["template_sha256"]
