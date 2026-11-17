"""Literature-data preparation and DF-ISE current-file conversion."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAW_IDVG_COLUMNS = (
    "source",
    "device_id",
    "polarity",
    "dose_value",
    "dose_unit",
    "bias_condition",
    "temperature_k",
    "vgs_signed_v",
    "vds_signed_v",
    "id_signed_a",
    "source_location",
    "scan_direction",
    "extraction_method",
    "quality",
)


@dataclass(frozen=True)
class LiteraturePreparationResult:
    output_path: Path
    input_rows: int
    output_rows: int
    dropped_positive_vgs_rows: int


def prepare_literature_idvg(
    input_path: str | Path, output_path: str | Path
) -> LiteraturePreparationResult:
    """Convert verified signed p-FET data to positive terminal magnitudes."""

    source = Path(input_path)
    frame = pd.read_csv(source)
    missing = [name for name in RAW_IDVG_COLUMNS if name not in frame.columns]
    if missing:
        raise ValueError(f"Literature Id-Vg data missing columns: {missing}")
    if frame.empty:
        raise ValueError("Literature Id-Vg data is empty; digitize and verify Figure 2 first")
    if set(frame["polarity"]) != {"p"}:
        raise ValueError("This converter expects only the Cui 2023 p-FET polarity")
    if set(frame["quality"]) != {"verified"}:
        raise ValueError("Every literature data row must have quality='verified'")
    numeric_columns = (
        "dose_value",
        "temperature_k",
        "vgs_signed_v",
        "vds_signed_v",
        "id_signed_a",
    )
    numeric = frame.loc[:, numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("Literature Id-Vg data contains NaN or infinite values")
    if (frame["dose_value"] < 0).any() or (frame["temperature_k"] <= 0).any():
        raise ValueError("Dose must be non-negative and temperature positive")
    if (frame["vds_signed_v"] >= 0).any() or (frame["id_signed_a"] >= 0).any():
        raise ValueError("Cui p-FET VDS and IDS must be negative; omit zero-current points")
    if frame["dose_unit"].nunique() != 1:
        raise ValueError("dose_unit must be consistent within one literature data file")

    forward_gate = frame["vgs_signed_v"] > 0
    retained = frame.loc[~forward_gate].copy()
    if retained.empty:
        raise ValueError("No rows remain with VGS <= 0 for positive-magnitude conversion")
    retained["vgs_v"] = -retained["vgs_signed_v"]
    retained["vds_v"] = -retained["vds_signed_v"]
    retained["id_a"] = -retained["id_signed_a"]
    output_columns = [
        "source",
        "device_id",
        "polarity",
        "dose_value",
        "dose_unit",
        "bias_condition",
        "temperature_k",
        "vgs_v",
        "vds_v",
        "id_a",
        "source_location",
        "scan_direction",
        "extraction_method",
        "quality",
    ]
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    retained.loc[:, output_columns].to_csv(destination, index=False)
    return LiteraturePreparationResult(
        destination,
        len(frame),
        len(retained),
        int(forward_gate.sum()),
    )


def read_dfise_plt(path: str | Path) -> pd.DataFrame:
    """Read a text DF-ISE .plt file with arbitrary line wrapping."""

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if "DF-ISE text" not in text:
        raise ValueError("Only text DF-ISE .plt files are supported")
    dataset_match = re.search(r"datasets\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
    data_match = re.search(r"\bData\s*\{(.*?)\}", text, flags=re.DOTALL)
    if not dataset_match or not data_match:
        raise ValueError("Invalid DF-ISE file: datasets or Data block is missing")
    columns = re.findall(r'"([^"]+)"', dataset_match.group(1))
    if not columns:
        raise ValueError("Invalid DF-ISE file: no datasets declared")
    values = np.fromstring(data_match.group(1), sep=" ", dtype=float)
    if values.size == 0 or values.size % len(columns):
        raise ValueError(
            f"DF-ISE data has {values.size} values, not a multiple of {len(columns)} columns"
        )
    return pd.DataFrame(values.reshape(-1, len(columns)), columns=columns)


def export_sdevice_idvg(
    input_path: str | Path,
    output_path: str | Path,
    gate_contact: str = "gate",
    drain_contact: str = "drain",
) -> tuple[Path, Path]:
    """Export signed gate/drain data and a source-checksummed metadata JSON."""

    source = Path(input_path).resolve()
    frame = read_dfise_plt(source)
    required = (
        f"{gate_contact} OuterVoltage",
        f"{drain_contact} OuterVoltage",
        f"{drain_contact} TotalCurrent",
    )
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"SDevice current file missing datasets: {missing}")
    exported = frame.loc[:, required].rename(
        columns={
            required[0]: "vgs_signed_v",
            required[1]: "vds_signed_v",
            required[2]: "id_signed_a",
        }
    )
    if not np.isfinite(exported.to_numpy(dtype=float)).all():
        raise ValueError("SDevice current file contains NaN or infinite values")
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    exported.to_csv(destination, index=False)
    metadata = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "source_plt": source.name,
        "source_plt_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "gate_contact": gate_contact,
        "drain_contact": drain_contact,
        "row_count": len(exported),
        "sign_convention": "signed SDevice terminal values; no magnitude conversion",
    }
    metadata_path = destination.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destination, metadata_path
