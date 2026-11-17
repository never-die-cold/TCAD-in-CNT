"""End-to-end device-to-inverter dose sweep with reproducible artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .circuit import solve_inverter
from .config import SimulationConfig, config_sha256
from .device import drain_current, state_at_dose
from .plotting import plot_all


@dataclass(frozen=True)
class SimulationArtifacts:
    output_dir: Path
    transfer: pd.DataFrame
    inverter: pd.DataFrame
    summary: pd.DataFrame


def run_simulation(config: SimulationConfig, output_dir: str | Path) -> SimulationArtifacts:
    """Run all dose points and write CSV, JSON and PNG artifacts."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    transfer_rows: list[pd.DataFrame] = []
    inverter_rows: list[pd.DataFrame] = []
    summaries: list[dict[str, float]] = []
    vgs = np.linspace(0.0, config.vdd_v, config.transfer_points)

    for dose in config.doses_krad:
        states = {
            "n": state_at_dose(config.n_device, dose, config.temperature_k),
            "p": state_at_dose(config.p_device, dose, config.temperature_k),
        }
        device_metrics: dict[str, float] = {}
        for polarity, state in states.items():
            current = drain_current(state, vgs, config.vdd_v)
            transfer_rows.append(
                pd.DataFrame(
                    {
                        "device": polarity,
                        "dose_krad": dose,
                        "vgs_v": vgs,
                        "id_a": current,
                    }
                )
            )
            gm = np.gradient(current, vgs)
            device_metrics[f"{polarity}_threshold_magnitude_v"] = state.threshold_v
            device_metrics[f"{polarity}_threshold_shift_v"] = state.delta_threshold_v
            device_metrics[f"{polarity}_qot_c_cm2"] = state.qot_c_cm2
            device_metrics[f"{polarity}_qit_c_cm2"] = state.qit_c_cm2
            device_metrics[f"{polarity}_mobility_m2_vs"] = state.mobility_m2_vs
            device_metrics[f"{polarity}_slope_factor"] = state.slope_factor
            device_metrics[f"{polarity}_ioff_a"] = float(current[0])
            device_metrics[f"{polarity}_ion_a"] = float(current[-1])
            device_metrics[f"{polarity}_gm_max_s"] = float(np.max(gm))

        inverter = solve_inverter(
            states["n"], states["p"], config.vdd_v, config.inverter_points
        )
        inverter_rows.append(
            pd.DataFrame(
                {
                    "dose_krad": dose,
                    "vin_v": inverter.vin_v,
                    "vout_v": inverter.vout_v,
                    "gain": np.gradient(inverter.vout_v, inverter.vin_v),
                }
            )
        )
        summaries.append(
            {
                "dose_krad": dose,
                **device_metrics,
                "vm_v": inverter.vm_v,
                "vil_v": inverter.vil_v,
                "vih_v": inverter.vih_v,
                "vol_v": inverter.vol_v,
                "voh_v": inverter.voh_v,
                "nml_v": inverter.nml_v,
                "nmh_v": inverter.nmh_v,
            }
        )

    transfer_frame = pd.concat(transfer_rows, ignore_index=True)
    inverter_frame = pd.concat(inverter_rows, ignore_index=True)
    summary_frame = pd.DataFrame(summaries).sort_values("dose_krad").reset_index(drop=True)
    transfer_frame.to_csv(destination / "device_transfer.csv", index=False)
    inverter_frame.to_csv(destination / "inverter_vtc.csv", index=False)
    summary_frame.to_csv(destination / "summary.csv", index=False)

    metadata = {
        "schema_version": "1.0",
        "software_version": __version__,
        "model_type": "compact_equivalent_tid",
        "calibration_status": config.calibration_status,
        "created_utc": datetime.now(UTC).isoformat(),
        "dose_unit": config.dose_unit,
        "warning": "Illustrative results are not device predictions until calibrated.",
        "config_sha256": config_sha256(config),
        "config": config.to_dict(),
    }
    with (destination / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    plot_all(transfer_frame, inverter_frame, summary_frame, config.vdd_v, destination)
    return SimulationArtifacts(destination, transfer_frame, inverter_frame, summary_frame)
