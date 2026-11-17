"""Structure-transfer predictor: |Vt shift|(dose) with an architecture-class band.

The cross-source fits show the dose-law exponent is a property of the
structure (0.23-0.85 across the measured variants).  This module turns that
finding into an engineering tool:

* a variant with its own usable power-law fit is predicted by that fit;
* any other variant is predicted by the reference law rescaled through its
  first measured point (the single-point anchor, the most favourable
  transfer a user can hope for);
* every prediction carries the **class envelope**: the minimum and maximum
  of all usable fitted laws rescaled through the same anchor point.  It is
  the honest answer to "I only know it is a CNT FET and I measured one
  point" -- the shape uncertainty of the dose law alone spans a factor of
  several, which is exactly why parameters must be fitted per structure.

Predictions outside a variant's measured dose range are flagged as
extrapolations, not hidden.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .cross_source import (
    MIN_USABLE_SHIFT_MV,
    cui_shift_frame,
    fit_dose_laws,
    load_vt_shift,
)

REFERENCE_DEVICE = "cui2023_top_gate"


@dataclass(frozen=True)
class Prediction:
    device_id: str
    strategy: str
    anchor_dose_krad: float
    anchor_shift_mv: float
    dose_min_krad: float
    dose_max_krad: float
    exponent: float
    table: pd.DataFrame


def _anchor_point(group: pd.DataFrame) -> tuple[float, float] | None:
    positive = group[(group["dose_krad"] > 0) & (group["vt_shift_mv"] > MIN_USABLE_SHIFT_MV)]
    if positive.empty:
        return None
    first = positive.sort_values("dose_krad").iloc[0]
    return float(first["dose_krad"]), float(first["vt_shift_mv"])


def _class_exponent_bounds(fits: pd.DataFrame) -> tuple[float, float]:
    usable = fits[fits["usable"]]
    if usable.empty:
        raise ValueError("no usable power-law fit defines the architecture class")
    return float(usable["exponent"].min()), float(usable["exponent"].max())


def predict_architecture(
    frame: pd.DataFrame,
    fits: pd.DataFrame,
    device_id: str,
    dose_grid: np.ndarray,
) -> Prediction:
    """Predict |Vt shift| for one variant across a dose grid."""

    group = frame[frame["device_id"] == device_id].sort_values("dose_krad")
    if group.empty:
        raise ValueError(f"unknown device_id: {device_id}")
    fit = fits.loc[fits["device_id"] == device_id].iloc[0]
    anchor = _anchor_point(group)
    dose_grid = np.asarray(dose_grid, dtype=float)
    if dose_grid.size == 0 or np.any(dose_grid <= 0):
        raise ValueError("dose_grid must contain positive doses")

    p_low, p_high = _class_exponent_bounds(fits)
    doses = group["dose_krad"].to_numpy(dtype=float)
    measured_min = float(doses[doses > 0].min()) if np.any(doses > 0) else float("nan")
    measured_max = float(doses.max())

    if anchor is None:
        table = pd.DataFrame(
            {
                "dose_krad": dose_grid,
                "predicted_mv": np.nan,
                "band_low_mv": np.nan,
                "band_high_mv": np.nan,
                "extrapolated": [True] * dose_grid.size,
            }
        )
        return Prediction(
            device_id=device_id,
            strategy="below_noise_floor",
            anchor_dose_krad=float("nan"),
            anchor_shift_mv=float("nan"),
            dose_min_krad=measured_min,
            dose_max_krad=measured_max,
            exponent=float("nan"),
            table=table,
        )

    anchor_dose, anchor_shift = anchor
    ratio = dose_grid / anchor_dose

    if bool(fit["usable"]):
        strategy = "own_power_law"
        exponent = float(fit["exponent"])
        predicted = anchor_shift * ratio**exponent
    else:
        strategy = "anchored_reference"
        reference = fits.loc[fits["device_id"] == REFERENCE_DEVICE].iloc[0]
        exponent = float(reference["exponent"])
        predicted = anchor_shift * ratio**exponent

    low_edge = anchor_shift * ratio**p_low
    high_edge = anchor_shift * ratio**p_high
    band_low = np.minimum(low_edge, high_edge)
    band_high = np.maximum(low_edge, high_edge)
    table = pd.DataFrame(
        {
            "dose_krad": dose_grid,
            "predicted_mv": predicted,
            "band_low_mv": band_low,
            "band_high_mv": band_high,
            "extrapolated": (dose_grid < measured_min) | (dose_grid > measured_max),
        }
    )
    return Prediction(
        device_id=device_id,
        strategy=strategy,
        anchor_dose_krad=anchor_dose,
        anchor_shift_mv=anchor_shift,
        dose_min_krad=measured_min,
        dose_max_krad=measured_max,
        exponent=exponent,
        table=table,
    )


def predict_all(
    vt_shift_paths: list[Path],
    metrics: pd.DataFrame,
    oxide_thickness_nm: float,
    oxide_relative_permittivity: float,
    dose_grid: np.ndarray,
) -> tuple[pd.DataFrame, dict]:
    """Build the cross-source frame and predict every variant on the grid."""

    frame = pd.concat(
        [
            cui_shift_frame(metrics, oxide_thickness_nm, oxide_relative_permittivity),
            load_vt_shift(vt_shift_paths),
        ],
        ignore_index=True,
    )
    fits = fit_dose_laws(frame)
    tables = []
    manifest = []
    for device_id in sorted(frame["device_id"].unique()):
        prediction = predict_architecture(frame, fits, device_id, dose_grid)
        tables.append(prediction.table.assign(device_id=device_id))
        manifest.append(
            {
                "device_id": device_id,
                "strategy": prediction.strategy,
                "anchor_dose_krad": prediction.anchor_dose_krad,
                "exponent": prediction.exponent,
                "measured_dose_min_krad": prediction.dose_min_krad,
                "measured_dose_max_krad": prediction.dose_max_krad,
            }
        )
    table = pd.concat(tables, ignore_index=True)
    return table, {"variants": manifest}


def plot_prediction_bands(
    frame: pd.DataFrame,
    table: pd.DataFrame,
    manifest: dict,
    path: Path,
) -> None:
    """Small-multiple prediction chart: data, prediction line, class band."""

    from .p0_plots import _style  # package-internal: keep the figure style identical

    _style()
    import matplotlib.pyplot as plt

    devices = sorted(table["device_id"].unique())
    columns = 4
    rows = int(np.ceil(len(devices) / columns))
    fig, axes = plt.subplots(
        rows, columns, figsize=(3.1 * columns, 2.6 * rows), constrained_layout=True
    )
    axes = np.atleast_1d(axes).ravel()
    strategies = {item["device_id"]: item["strategy"] for item in manifest["variants"]}
    for axis, device_id in zip(axes, devices, strict=False):
        group = frame[frame["device_id"] == device_id].sort_values("dose_krad")
        subset = table[table["device_id"] == device_id].sort_values("dose_krad")
        usable = bool(group["vt_shift_mv"].max() > MIN_USABLE_SHIFT_MV)
        if usable:
            axis.loglog(
                group["dose_krad"].replace(0, np.nan),
                group["vt_shift_mv"],
                "s",
                color="black",
                markersize=3.5,
                label="measured",
            )
        if subset["predicted_mv"].notna().any():
            axis.loglog(
                subset["dose_krad"],
                subset["predicted_mv"],
                "-",
                color="#b22222",
                linewidth=1.3,
                label="prediction",
            )
            axis.fill_between(
                subset["dose_krad"],
                subset["band_low_mv"],
                subset["band_high_mv"],
                color="#b22222",
                alpha=0.18,
                label="class band",
            )
        strategy = strategies.get(device_id, "")
        axis.set_title(device_id, fontsize=7)
        axis.text(
            0.03,
            0.06,
            strategy.replace("_", " "),
            transform=axis.transAxes,
            fontsize=6,
            color="#1b7837" if strategy == "own_power_law" else "#555555",
        )
        axis.grid(True, which="both", alpha=0.18)
        axis.tick_params(labelsize=6)
    for axis in axes[len(devices):]:
        axis.axis("off")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7, loc="outside upper right", ncol=3)
    fig.suptitle("Structure-transfer prediction: one anchor point + architecture-class band")
    fig.text(
        0.006,
        0.004,
        "cnt-tid predict | fig9 | band = envelope of all usable fitted laws "
        "(exponent 0.23-0.85) rescaled through the variant's first measured point",
        fontsize=6.5,
        color="#555555",
    )
    fig.savefig(path)
    plt.close(fig)


def write_prediction_artifacts(
    vt_shift_paths: list[Path],
    metrics: pd.DataFrame,
    oxide_thickness_nm: float,
    oxide_relative_permittivity: float,
    dose_grid: np.ndarray,
    output_dir: str | Path,
    figure_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Predict every variant and write the table + manifest (and figure)."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    table, manifest = predict_all(
        vt_shift_paths,
        metrics,
        oxide_thickness_nm,
        oxide_relative_permittivity,
        dose_grid,
    )
    table.to_csv(destination / "prediction_table.csv", index=False)
    payload = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "reference_device": REFERENCE_DEVICE,
        "dose_grid_krad": [float(d) for d in dose_grid],
        **manifest,
    }
    (destination / "prediction_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if figure_path is not None:
        frame = pd.concat(
            [
                cui_shift_frame(metrics, oxide_thickness_nm, oxide_relative_permittivity),
                load_vt_shift(vt_shift_paths),
            ],
            ignore_index=True,
        )
        plot_prediction_bands(frame, table, manifest, Path(figure_path))
    return destination / "prediction_table.csv", destination / "prediction_manifest.json"
