"""Full-chain Monte-Carlo uncertainty propagation for the P0 deliverable.

The OAT sensitivity (fig4) perturbs one parameter at a time around the
calibrated point, and the assumption sweep (fig5) checks three values of two
documented assumptions.  Neither answers "what is the confidence interval of
the deliverable numbers".  This module draws the *entire* documented
uncertainty at once and pushes each draw through calibration -> device sweep
-> inverter -> ring oscillator:

* the four registry assumptions are drawn from triangular distributions over
  their registered ranges (low, nominal, high) -- more mass near the nominal,
  which is the honest shape for "nominal +/- stated range";
* every digitized metric point is drawn from a normal with the digitized
  error bar as sigma, so figure-reading uncertainty propagates too;
* a draw that fails a physicality check (e.g. interface charge exceeding the
  total under an unlucky combination) is recorded as failed and skipped, and
  the failure count is reported instead of silently dropped.

Same seed -> identical artifacts; the metadata records every input hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .metric_calibration import calibrate_from_metrics, load_digitized_metrics
from .p0 import _inverter_metrics
from .registry import ParameterRecord, build_simulation_config, load_registry, number
from .ringosc import run_ring_oscillator_scan

#: (low, nominal, high) per registry id; the guard below ties these to the
#: registry so the sampling spec cannot drift away from the documented ranges.
ASSUMPTION_RANGES = {
    "dev.oxide_relative_permittivity": (12.0, 15.0, 20.0),
    "assume.n_p_dose_response_ratio": (0.5, 1.0, 1.5),
    "sim.vdd_v": (1.5, 2.0, 2.5),
    "sim.temperature_k": (295.0, 300.0, 305.0),
}
SUMMARY_KEYS = (
    "dose_exponent",
    "q_tot_at_max_dose_c_cm2",
    "vth_shift_at_max_dose_v",
    "vm_at_max_dose_v",
    "nml_at_max_dose_v",
    "nmh_at_max_dose_v",
    "frequency_hz_at_zero_dose",
    "frequency_hz_at_max_dose",
    "frequency_degradation_factor",
    "static_power_w_at_zero_dose",
    "static_power_w_at_max_dose",
    "total_power_w_at_max_dose",
)
QUANTILES = (0.05, 0.16, 0.5, 0.84, 0.95)


@dataclass(frozen=True)
class MonteCarloArtifacts:
    output_dir: Path
    draws: pd.DataFrame
    scan: pd.DataFrame
    summary: dict
    metadata: dict


def _perturb_metrics(
    metrics: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """Draw every digitized metric point within its digitized error bar."""

    perturbed = metrics.copy()
    error_columns = [name for name in ("err_minus", "err_plus") if name in perturbed.columns]
    if not error_columns:
        raise ValueError("digitized metrics need error bars for MC propagation")
    sigma = 0.5 * sum(
        perturbed[name].to_numpy(dtype=float) for name in error_columns
    )
    values = perturbed["value"].to_numpy(dtype=float) + rng.normal(
        0.0, 1.0, size=sigma.size
    ) * sigma
    # Gm and SS must stay positive; pull offending points back to the data
    # value instead of discarding the whole draw.
    non_negative_metric = perturbed["metric"].to_numpy() != "vth_v"
    bad = non_negative_metric & (values <= 0)
    values[bad] = perturbed["value"].to_numpy(dtype=float)[bad]
    perturbed["value"] = values
    return perturbed


def _validate_sampling_ranges(registry: dict[str, ParameterRecord]) -> None:
    """Tie the sampling spec to the registry before any draw runs."""

    for param_id, bounds in ASSUMPTION_RANGES.items():
        nominal = bounds[1]
        registered = number(registry, param_id)
        if abs(registered - nominal) > 1e-9:
            raise ValueError(
                f"{param_id}: registry value {registered:g} does not match the "
                f"MC sampling nominal {nominal:g}; update ASSUMPTION_RANGES"
            )


def _draw_registry(
    registry: dict[str, ParameterRecord], rng: np.random.Generator
) -> dict[str, ParameterRecord]:
    drawn = dict(registry)
    for param_id, (low, nominal, high) in ASSUMPTION_RANGES.items():
        value = rng.triangular(low, nominal, high)
        drawn[param_id] = replace(registry[param_id], value=f"{value:.17g}")
    return drawn


def _one_draw(
    index: int,
    metrics: pd.DataFrame,
    registry: dict[str, ParameterRecord],
    rng: np.random.Generator,
) -> tuple[dict | None, pd.DataFrame | None]:
    """Run one full-chain draw; return (row, scan_frame) or (None, None)."""

    try:
        perturbed = _perturb_metrics(metrics, rng)
        drawn_registry = _draw_registry(registry, rng)
        calibration = calibrate_from_metrics(
            perturbed,
            oxide_thickness_nm=number(drawn_registry, "dev.oxide_thickness_nm"),
            oxide_relative_permittivity=number(
                drawn_registry, "dev.oxide_relative_permittivity"
            ),
            width_um=number(drawn_registry, "dev.width_um"),
            length_nm=number(drawn_registry, "dev.length_nm"),
            temperature_k=number(drawn_registry, "sim.temperature_k"),
        )
        config = build_simulation_config(
            drawn_registry,
            vth0_mag_v=calibration.vth0_mag_v,
            mobility_m2_vs=calibration.mobility_m2_vs,
            slope_factor0=calibration.slope_factor0,
            q_ot_c_cm2_per_krad=calibration.q_ot_c_cm2_per_krad,
            q_it_c_cm2_per_krad=calibration.q_it_c_cm2_per_krad,
            mobility_degradation_per_krad=calibration.mobility_degradation_per_krad,
            dose_exponent=calibration.dose_exponent,
            qit_density_slope_c_cm2_per_krad=calibration.qit_density_slope_c_cm2_per_krad,
            qit_anneal_c_cm2=calibration.qit_anneal_c_cm2,
            qit_anneal_dose_krad=calibration.qit_anneal_dose_krad,
        )
        inverter = _inverter_metrics(config)
        ring = run_ring_oscillator_scan(config)
    except (ValueError, RuntimeError):
        return None, None

    doses = inverter["dose_krad"].to_numpy(dtype=float)
    max_index = int(np.argmax(doses))
    row = {
        "draw": index,
        "eps_r": number(drawn_registry, "dev.oxide_relative_permittivity"),
        "n_over_p_ratio": number(drawn_registry, "assume.n_p_dose_response_ratio"),
        "vdd_v": number(drawn_registry, "sim.vdd_v"),
        "temperature_k": number(drawn_registry, "sim.temperature_k"),
        "dose_exponent": calibration.dose_exponent,
        "q_tot_at_max_dose_c_cm2": calibration.total_charge_slope_c_cm2_per_krad
        * doses[max_index] ** calibration.dose_exponent,
        "vth_shift_at_max_dose_v": calibration.total_charge_slope_c_cm2_per_krad
        * doses[max_index] ** calibration.dose_exponent
        / calibration.cox_f_cm2,
        "ss0_mv_dec": calibration.ss0_mv_dec,
        "mu0_cm2_vs": calibration.mobility_m2_vs * 1e4,
        "qit_anneal_c_cm2": calibration.qit_anneal_c_cm2,
        "qit_anneal_dose_krad": calibration.qit_anneal_dose_krad,
        "vm_at_max_dose_v": float(inverter["vm_v"].iloc[max_index]),
        "nml_at_max_dose_v": float(inverter["nml_v"].iloc[max_index]),
        "nmh_at_max_dose_v": float(inverter["nmh_v"].iloc[max_index]),
        "frequency_hz_at_zero_dose": float(ring["frequency_hz"].iloc[0]),
        "frequency_hz_at_max_dose": float(ring["frequency_hz"].iloc[max_index]),
        "frequency_degradation_factor": float(
            ring["frequency_hz"].iloc[0] / ring["frequency_hz"].iloc[max_index]
        ),
        "static_power_w_at_zero_dose": float(ring["static_power_w"].iloc[0]),
        "static_power_w_at_max_dose": float(ring["static_power_w"].iloc[max_index]),
        "total_power_w_at_max_dose": float(ring["total_power_w"].iloc[max_index]),
    }
    scan = pd.DataFrame(
        {
            "draw": index,
            "dose_krad": doses,
            "vm_v": inverter["vm_v"].to_numpy(dtype=float),
            "nml_v": inverter["nml_v"].to_numpy(dtype=float),
            "nmh_v": inverter["nmh_v"].to_numpy(dtype=float),
            "frequency_hz": ring["frequency_hz"].to_numpy(dtype=float),
            "static_power_w": ring["static_power_w"].to_numpy(dtype=float),
        }
    )
    return row, scan


def run_monte_carlo(
    registry_path: str | Path,
    metrics_path: str | Path,
    draws: int = 200,
    seed: int = 20261118,
    output_dir: str | Path = "results/mc",
    progress_every: int = 25,
) -> MonteCarloArtifacts:
    """Propagate the documented uncertainty through the whole P0 chain."""

    if draws < 2:
        raise ValueError("draws must be at least 2")
    registry_file = Path(registry_path)
    metrics_file = Path(metrics_path)
    registry = load_registry(registry_file)
    metrics = load_digitized_metrics(metrics_file)
    _validate_sampling_ranges(registry)
    rng = np.random.default_rng(seed)

    rows: list[dict] = []
    scans: list[pd.DataFrame] = []
    failed = 0
    for index in range(draws):
        row, scan = _one_draw(index, metrics, registry, rng)
        if row is None:
            failed += 1
            continue
        rows.append(row)
        scans.append(scan)
        if progress_every and (index + 1) % progress_every == 0:
            print(f"  mc draw {index + 1}/{draws} ({failed} failed so far)")

    if len(rows) < 2:
        raise RuntimeError(
            f"only {len(rows)}/{draws} draws survived the physicality checks; "
            "the uncertainty ranges and the physicality constraints are incompatible"
        )
    draws_frame = pd.DataFrame(rows)
    scan_frame = pd.concat(scans, ignore_index=True)

    summary: dict[str, dict[str, float]] = {}
    for key in SUMMARY_KEYS:
        values = draws_frame[key].to_numpy(dtype=float)
        finite = np.isfinite(values)
        # NaN entries are information, not garbage: a NaN noise margin means
        # the VIL/VIH crossing does not exist at that dose for that draw.
        # Quantiles are taken over the finite draws and the fraction that
        # survives is reported next to them.
        summary[key] = {
            "finite_fraction": float(finite.mean()),
            "median": float(np.nanquantile(values, 0.5)),
            "mean": float(np.nanmean(values)),
            "std": float(np.nanstd(values)),
            **{f"p{int(q * 100)}": float(np.nanquantile(values, q)) for q in QUANTILES},
        }

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    draws_frame.to_csv(destination / "mc_draws.csv", index=False)
    scan_frame.to_csv(destination / "mc_scan.csv", index=False)
    metadata = {
        "schema_version": "1.0",
        "software_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(),
        "draws_requested": draws,
        "draws_completed": len(rows),
        "draws_failed": failed,
        "seed": seed,
        "sampling": {
            "assumptions": "triangular(low, nominal, high) per registry range",
            "metric_points": "normal(sigma = digitized error bar)",
            **{param_id: list(range_) for param_id, range_ in ASSUMPTION_RANGES.items()},
        },
        "registry_sha256": hashlib.sha256(registry_file.read_bytes()).hexdigest(),
        "metrics_sha256": hashlib.sha256(metrics_file.read_bytes()).hexdigest(),
        "note": "config hash of the median-draw pipeline is meaningless; "
        "each draw carries its own sampled values in mc_draws.csv",
    }
    (destination / "mc_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary_path = {
        "schema_version": "1.0",
        "seed": seed,
        "draws_completed": len(rows),
        "draws_failed": failed,
        "metrics": summary,
    }
    (destination / "mc_summary.json").write_text(
        json.dumps(summary_path, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return MonteCarloArtifacts(destination, draws_frame, scan_frame, summary, metadata)


def plot_monte_carlo(scan: pd.DataFrame, path: Path) -> None:
    """Confidence bands of the inverter switching point and the ring frequency."""

    from .p0_plots import _style  # package-internal: keep the figure style identical

    _style()
    import matplotlib.pyplot as plt

    doses = np.sort(scan["dose_krad"].unique())
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.2), constrained_layout=True)
    for axis, column, label, color in (
        (left, "vm_v", "Switching threshold VM (V)", "#7b3294"),
        (right, "frequency_hz", "Ring frequency (Hz)", "#4c78a8"),
    ):
        per_dose = [
            scan.loc[scan["dose_krad"] == dose, column].to_numpy(dtype=float)
            for dose in doses
        ]
        median = np.array([np.nanquantile(values, 0.5) for values in per_dose])
        low = np.array([np.nanquantile(values, 0.05) for values in per_dose])
        high = np.array([np.nanquantile(values, 0.95) for values in per_dose])
        axis.fill_between(doses, low, high, color=color, alpha=0.22, label="5-95 %")
        axis.fill_between(doses, np.array([np.nanquantile(v, 0.16) for v in per_dose]),
                          np.array([np.nanquantile(v, 0.84) for v in per_dose]),
                          color=color, alpha=0.40, label="16-84 %")
        axis.plot(doses, median, "-", color=color, linewidth=1.6, label="median")
        axis.set(xlabel="Dose (krad(Si))", ylabel=label)
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=7, loc="best")
    right.set_yscale("log")
    fig.text(
        0.006,
        0.004,
        "cnt-tid mc | fig8 | full-chain Monte Carlo over registry ranges + "
        "digitized error bars | bands = per-dose quantiles across draws",
        fontsize=6.5,
        color="#555555",
    )
    fig.savefig(path)
    plt.close(fig)
