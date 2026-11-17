"""One-command deliverable rebuild: p0 -> Monte Carlo -> predictor -> annealing.

``cnt-tid all`` chains every deliverable stage and writes a master manifest
that links the sub-artifacts by hash, so a single JSON pins the whole
closing package: the calibrated pipeline, the uncertainty bands, the
structure-transfer predictions and the annealing scenarios.  Runtime is
dominated by the Monte-Carlo draws (~1.3 s each).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .annealing import write_annealing_artifacts
from .metric_calibration import load_digitized_metrics
from .monte_carlo import run_monte_carlo
from .p0 import run_p0
from .registry import load_registry, number
from .structure_transfer import predict_all

DEFAULT_SECOND_SOURCE = Path("data/literature/kanhaiya2021/vt_shift_vs_tid.csv")
DEFAULT_DOSE_GRID = (100.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0, 10000.0)
DEFAULT_TIMES_S = (0.0, 3600.0, 86400.0, 604800.0, 2592000.0)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_deliverable(
    registry_path: str | Path,
    metrics_path: str | Path,
    output_dir: str | Path,
    *,
    draws: int = 200,
    seed: int = 20261118,
    second_source: str | Path = DEFAULT_SECOND_SOURCE,
    dose_grid: tuple[float, ...] = DEFAULT_DOSE_GRID,
    times_s: tuple[float, ...] = DEFAULT_TIMES_S,
    publish_dir: str | Path | None = None,
) -> Path:
    """Rebuild every deliverable artifact and the master manifest."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    registry = load_registry(registry_path)
    metrics = load_digitized_metrics(metrics_path)

    print("[1/5] p0 pipeline (calibrate, sweep, sensitivity, figures)")
    p0_result = run_p0(registry_path, metrics_path, destination / "p0", publish_dir)

    print(f"[2/5] Monte Carlo ({draws} draws)")
    mc = run_monte_carlo(
        registry_path, metrics_path, draws=draws, seed=seed, output_dir=destination / "mc"
    )

    print("[3/5] structure-transfer predictions")
    table, manifest = predict_all(
        [Path(second_source)],
        metrics,
        oxide_thickness_nm=number(registry, "dev.oxide_thickness_nm"),
        oxide_relative_permittivity=number(registry, "dev.oxide_relative_permittivity"),
        dose_grid=np.asarray(dose_grid, dtype=float),
    )
    table.to_csv(destination / "prediction_table.csv", index=False)
    (destination / "prediction_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("[4/5] annealing scenarios")
    fraction = number(registry, "assume.annealed_charge_fraction")
    tau_s = number(registry, "assume.annealing_time_constant_s")
    anneal_path, anneal_metadata = write_annealing_artifacts(
        p0_result.config, fraction, tau_s, times_s, destination / "anneal"
    )

    print("[5/5] master manifest")
    manifest = {
        "schema_version": "1.0",
        "software_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            str(registry_path).replace("\\", "/"): _sha256(Path(registry_path)),
            str(metrics_path).replace("\\", "/"): _sha256(Path(metrics_path)),
        },
        "stages": {
            "p0": {
                "manifest": "p0/manifest.json",
                "sha256": _sha256(destination / "p0" / "manifest.json"),
                "key_numbers": p0_result.key_numbers,
            },
            "monte_carlo": {
                "summary": "mc/mc_summary.json",
                "sha256": _sha256(destination / "mc" / "mc_summary.json"),
                "draws_completed": mc.metadata["draws_completed"],
                "draws_failed": mc.metadata["draws_failed"],
                "seed": seed,
            },
            "prediction": {
                "manifest": "prediction_manifest.json",
                "sha256": _sha256(destination / "prediction_manifest.json"),
                "variants": len(manifest["variants"]),
            },
            "annealing": {
                "metadata": "anneal/annealing_metadata.json",
                "sha256": _sha256(destination / "anneal" / "annealing_metadata.json"),
                "fraction": fraction,
                "tau_s": tau_s,
            },
        },
        "scan_frames": {
            "mc_scan_rows": int(len(mc.scan)),
            "prediction_table_rows": int(len(table)),
            "annealing_scan_rows": int(len(pd.read_csv(anneal_path))),
        },
    }
    (destination / "deliverable_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Deliverable complete: {destination.resolve()}")
    return destination
