import json
from pathlib import Path

import pandas as pd
import pytest

from cnt_tid.tcad_io import (
    export_sdevice_idvg,
    prepare_literature_idvg,
    read_dfise_plt,
)


def test_verified_literature_curve_preserves_sign_conversion(tmp_path: Path) -> None:
    raw = pd.DataFrame(
        [
            {
                "source": "Cui2023",
                "device_id": "cnt_network_p",
                "polarity": "p",
                "dose_value": 0,
                "dose_unit": "krad(Si)",
                "bias_condition": "floating",
                "temperature_k": 300,
                "vgs_signed_v": -1.0,
                "vds_signed_v": -0.1,
                "id_signed_a": -1e-6,
                "source_location": "Figure 2 page 4",
                "scan_direction": "not_reported",
                "extraction_method": "manual_test",
                "quality": "verified",
            }
        ]
    )
    raw.loc[1] = raw.loc[0]
    raw.loc[1, "vgs_signed_v"] = 0.5
    source = tmp_path / "raw.csv"
    raw.to_csv(source, index=False)

    result = prepare_literature_idvg(source, tmp_path / "prepared.csv")
    converted = pd.read_csv(result.output_path)

    assert result.input_rows == 2
    assert result.output_rows == 1
    assert result.dropped_positive_vgs_rows == 1
    assert converted.loc[0, "vgs_v"] == 1.0
    assert converted.loc[0, "vds_v"] == 0.1
    assert converted.loc[0, "id_a"] == 1e-6
    assert converted.loc[0, "dose_unit"] == "krad(Si)"


def test_unverified_literature_curve_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "raw.csv"
    source.write_text(
        "source,device_id,polarity,dose_value,dose_unit,bias_condition,temperature_k,"
        "vgs_signed_v,vds_signed_v,id_signed_a,source_location,scan_direction,"
        "extraction_method,quality\n"
        "Cui2023,d,p,0,krad(Si),floating,300,-1,-0.1,-1e-6,Figure 2,"
        "not_reported,manual,pending\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="verified"):
        prepare_literature_idvg(source, tmp_path / "prepared.csv")


def test_dfise_export_handles_wrapped_data_and_checksum(tmp_path: Path) -> None:
    source = tmp_path / "curve.plt"
    source.write_text(
        'DF-ISE text\nInfo {\n datasets = [ "time" "gate OuterVoltage"\n'
        ' "drain OuterVoltage" "drain TotalCurrent" ]\n}\n'
        "Data {\n 0 0.5 -0.1 -1e-9\n 0.5 0 -0.1 -2e-9\n 1 -2 -0.1 -3e-9\n}\n",
        encoding="utf-8",
    )
    frame = read_dfise_plt(source)
    assert len(frame) == 3
    assert list(frame.columns) == [
        "time",
        "gate OuterVoltage",
        "drain OuterVoltage",
        "drain TotalCurrent",
    ]

    csv_path, metadata_path = export_sdevice_idvg(source, tmp_path / "curve.csv")
    exported = pd.read_csv(csv_path)
    assert exported["vgs_signed_v"].tolist() == [0.5, 0.0, -2.0]
    assert exported["id_signed_a"].tolist() == [-1e-9, -2e-9, -3e-9]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert len(metadata["source_plt_sha256"]) == 64
    assert metadata["row_count"] == 3


def test_invalid_dfise_data_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad.plt"
    source.write_text(
        'DF-ISE text\nInfo { datasets = [ "time" "gate OuterVoltage" ] }\n'
        "Data { 0 0.5 1 }\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a multiple"):
        read_dfise_plt(source)
