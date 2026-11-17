"""Traceable dose-by-geometry experiment matrix."""

from __future__ import annotations

import json
import traceback
import warnings
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from . import __version__
from .config import SimulationConfig, config_sha256
from .workflow import run_simulation


@dataclass(frozen=True)
class MatrixResult:
    output_dir: Path
    summary: pd.DataFrame
    manifest: pd.DataFrame

    @property
    def failed_count(self) -> int:
        return int((self.manifest["status"] != "passed").sum())


def _validate_scales(name: str, values: tuple[float, ...]) -> None:
    if not values or not np.isfinite(values).all() or any(value <= 0 for value in values):
        raise ValueError(f"{name} must contain finite positive values")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")


def _scenario_id(oxide_scale: float, length_scale: float) -> str:
    oxide = f"{oxide_scale:g}".replace(".", "p")
    length = f"{length_scale:g}".replace(".", "p")
    return f"oxide-{oxide}_length-{length}"


def _scaled_config(
    config: SimulationConfig, oxide_scale: float, length_scale: float
) -> SimulationConfig:
    def scale_device(device):
        return replace(
            device,
            oxide_thickness_nm=device.oxide_thickness_nm * oxide_scale,
            length_nm=device.length_nm * length_scale,
        )

    return replace(
        config,
        n_device=scale_device(config.n_device),
        p_device=scale_device(config.p_device),
    )


def run_matrix(
    config: SimulationConfig,
    output_dir: str | Path,
    oxide_scales: tuple[float, ...] = (0.8, 1.0, 1.2),
    length_scales: tuple[float, ...] = (0.8, 1.0, 1.2),
) -> MatrixResult:
    """Run independent geometry scenarios and retain failures in a manifest."""

    _validate_scales("oxide_scales", oxide_scales)
    _validate_scales("length_scales", length_scales)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary_frames: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, object]] = []

    for oxide_scale, length_scale in product(oxide_scales, length_scales):
        scenario_id = _scenario_id(oxide_scale, length_scale)
        scenario_dir = destination / "runs" / scenario_id
        row: dict[str, object] = {
            "scenario_id": scenario_id,
            "oxide_scale": oxide_scale,
            "length_scale": length_scale,
            "run_path": str(Path("runs") / scenario_id),
            "status": "failed",
            "error": "",
            "warnings_path": "",
        }
        try:
            trial = _scaled_config(config, oxide_scale, length_scale)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                artifacts = run_simulation(trial, scenario_dir)
            if caught:
                warning_text = "\n".join(
                    f"{item.category.__name__}: {item.message}" for item in caught
                )
                warning_path = scenario_dir / "warnings.txt"
                warning_path.write_text(warning_text + "\n", encoding="utf-8")
                row["warnings_path"] = str(warning_path.relative_to(destination))
            metric_columns = ("vm_v", "vil_v", "vih_v", "nml_v", "nmh_v")
            metric_values = artifacts.summary.loc[:, metric_columns].to_numpy(dtype=float)
            if not np.isfinite(metric_values).all():
                raise ValueError("non-finite inverter metrics; inspect warnings and VTC output")
            summary = artifacts.summary.copy()
            summary.insert(0, "scenario_id", scenario_id)
            summary.insert(1, "oxide_scale", oxide_scale)
            summary.insert(2, "length_scale", length_scale)
            summary.insert(3, "oxide_thickness_nm", trial.n_device.oxide_thickness_nm)
            summary.insert(4, "length_nm", trial.n_device.length_nm)
            summary_frames.append(summary)
            row["status"] = "passed"
        except Exception as error:
            scenario_dir.mkdir(parents=True, exist_ok=True)
            (scenario_dir / "failure.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            row["error"] = f"{type(error).__name__}: {error}"
        manifest_rows.append(row)

    summary_frame = (
        pd.concat(summary_frames, ignore_index=True)
        if summary_frames
        else pd.DataFrame(
            columns=["scenario_id", "oxide_scale", "length_scale", "dose_krad"]
        )
    )
    manifest = pd.DataFrame(manifest_rows)
    summary_frame.to_csv(destination / "matrix_summary.csv", index=False)
    manifest.to_csv(destination / "matrix_manifest.csv", index=False)
    _plot_matrix_metrics(
        summary_frame,
        oxide_scales,
        length_scales,
        max(config.doses_krad),
        destination / "matrix_metrics.png",
    )

    failed_count = int((manifest["status"] != "passed").sum())
    metadata = {
        "schema_version": "1.0",
        "software_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(),
        "model_type": "compact_equivalent_tid",
        "calibration_status": config.calibration_status,
        "dose_unit": config.dose_unit,
        "oxide_scales": list(oxide_scales),
        "length_scales": list(length_scales),
        "scenario_count": len(manifest),
        "passed_count": len(manifest) - failed_count,
        "failed_count": failed_count,
        "config_sha256": config_sha256(config),
        "base_config": config.to_dict(),
    }
    with (destination / "matrix_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    return MatrixResult(destination, summary_frame, manifest)


def _plot_matrix_metrics(
    summary: pd.DataFrame,
    oxide_scales: tuple[float, ...],
    length_scales: tuple[float, ...],
    max_dose: float,
    path: Path,
) -> None:
    metrics = (("vm_v", "VM"), ("nml_v", "NML"), ("nmh_v", "NMH"))
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    at_max_dose = (
        summary[np.isclose(summary["dose_krad"], max_dose)]
        if not summary.empty
        else summary
    )
    for axis, (metric, label) in zip(axes, metrics, strict=True):
        if at_max_dose.empty:
            values = np.full((len(oxide_scales), len(length_scales)), np.nan)
        else:
            values = (
                at_max_dose.pivot(
                    index="oxide_scale", columns="length_scale", values=metric
                )
                .reindex(index=oxide_scales, columns=length_scales)
                .to_numpy(dtype=float)
            )
        image = axis.imshow(values, origin="lower", cmap="viridis", aspect="auto")
        axis.set_xticks(range(len(length_scales)), [f"{value:g}" for value in length_scales])
        axis.set_yticks(range(len(oxide_scales)), [f"{value:g}" for value in oxide_scales])
        axis.set_xlabel("Gate length scale")
        axis.set_ylabel("Oxide thickness scale")
        axis.set_title(f"{label} @ {max_dose:g} krad")
        for row in range(values.shape[0]):
            for column in range(values.shape[1]):
                value = values[row, column]
                text = f"{value:.3f}" if np.isfinite(value) else "failed"
                axis.text(column, row, text, ha="center", va="center", fontsize=8)
        fig.colorbar(image, ax=axis, label="V")
    fig.savefig(path)
    plt.close(fig)
