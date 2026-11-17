"""Ring-oscillator frequency and power degradation under TID (quasi-static).

The compact model has no transient solver, so the ring oscillator is treated
with a standard quasi-static first-order delay model:

* load capacitance = the gate capacitance of one identical next stage,
  C_L = Cox * W * L (wire and junction capacitance neglected);
* the 50 % propagation delay of one stage is the charge-deficit integral
  t_pd = C_L * (integral over half the rail of dV/I) averaged over the
  pull-down (input high) and pull-up (input low) transitions, with the
  drive currents taken from the *dose-shifted* compact device states;
* f_osc = 1 / (2 * N_stages * t_pd) for an N-stage inverter ring;
* dynamic power = N_stages * C_L * Vdd^2 * f_osc (each node swings once per
  period); static power = Vdd * mean through-current of a stage held at
  Vin = 0 and Vin = Vdd, where the through-current comes from the DC
  operating-point balance.

This is a trend model for the dose response of a ring, not a transient
circuit simulator; the assumptions are stated again in docs/modeling.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .circuit import static_operating_current
from .config import SimulationConfig, config_sha256
from .device import DeviceState, drain_current, state_at_dose

DELAY_POINTS = 101


@dataclass(frozen=True)
class RingOscillatorArtifacts:
    output_dir: Path
    scan: pd.DataFrame
    metadata: dict


def stage_load_capacitance(config: SimulationConfig) -> float:
    """Input gate capacitance of one identical next stage (farad)."""

    device = config.p_device
    return float(device.cox_f_m2 * device.width_m * device.length_m)


def _half_rail_transition_time(state: DeviceState, load_cap_f: float, vdd_v: float) -> float:
    """50 % delay contribution of one transition, in seconds.

    In the positive-magnitude convention both transitions integrate the same
    expression: the pull-down sees Vgs = Vdd with Vds falling from Vdd to
    Vdd/2, and the pull-up sees Vsg = Vdd with Vsd falling from Vdd to Vdd/2
    as the output rises.  The device states (threshold, mobility, swing)
    carry the asymmetry between the two transitions.
    """

    output_v = np.linspace(0.0, 0.5 * vdd_v, DELAY_POINTS)
    current = drain_current(state, vdd_v, vdd_v - output_v)
    if np.any(current <= 0):
        raise ValueError("drive current must stay positive over the half-rail window")
    return float(load_cap_f * np.trapezoid(1.0 / current, output_v))


def stage_delay(
    n_state: DeviceState,
    p_state: DeviceState,
    load_cap_f: float,
    vdd_v: float,
) -> float:
    """Quasi-static 50 % propagation delay of one loaded inverter (s)."""

    if load_cap_f <= 0:
        raise ValueError("load_cap_f must be positive")
    t_phl = _half_rail_transition_time(n_state, load_cap_f, vdd_v)
    t_plh = _half_rail_transition_time(p_state, load_cap_f, vdd_v)
    return 0.5 * (t_phl + t_plh)


def _stage_static_current(n_state: DeviceState, p_state: DeviceState, vdd_v: float) -> float:
    low_input = static_operating_current(n_state, p_state, vdd_v, 0.0)
    high_input = static_operating_current(n_state, p_state, vdd_v, vdd_v)
    return float(0.5 * (low_input + high_input))


def run_ring_oscillator_scan(config: SimulationConfig) -> pd.DataFrame:
    """Frequency and power of an N-stage ring at every registered dose."""

    if config.ro_stages < 3 or config.ro_stages % 2 == 0:
        raise ValueError("ro_stages must be an odd number >= 3")
    load_cap_f = stage_load_capacitance(config)
    stages = config.ro_stages
    rows = []
    for dose in config.doses_krad:
        n_state = state_at_dose(config.n_device, dose, config.temperature_k)
        p_state = state_at_dose(config.p_device, dose, config.temperature_k)
        delay_s = stage_delay(n_state, p_state, load_cap_f, config.vdd_v)
        frequency_hz = float(1.0 / (2.0 * stages * delay_s))
        static_current_a = _stage_static_current(n_state, p_state, config.vdd_v)
        dynamic_power_w = float(stages * load_cap_f * config.vdd_v**2 * frequency_hz)
        static_power_w = float(config.vdd_v * static_current_a)
        rows.append(
            {
                "dose_krad": dose,
                "load_cap_f": load_cap_f,
                "stage_delay_s": delay_s,
                "frequency_hz": frequency_hz,
                "static_current_a": static_current_a,
                "static_power_w": static_power_w,
                "dynamic_power_w": dynamic_power_w,
                "total_power_w": dynamic_power_w + static_power_w,
            }
        )
    return pd.DataFrame(rows).sort_values("dose_krad").reset_index(drop=True)


def write_ring_oscillator_artifacts(
    config: SimulationConfig, output_dir: str | Path
) -> RingOscillatorArtifacts:
    """Run the scan and write CSV + metadata (figures are handled by the caller)."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    scan = run_ring_oscillator_scan(config)
    scan.to_csv(destination / "ring_oscillator.csv", index=False)
    metadata = {
        "schema_version": "1.0",
        "software_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(),
        "model_type": "quasi_static_ring_oscillator",
        "ro_stages": config.ro_stages,
        "load_capacitance_f": stage_load_capacitance(config),
        "dose_unit": config.dose_unit,
        "calibration_status": config.calibration_status,
        "config_sha256": config_sha256(config),
        "assumptions": [
            "load = next-stage gate capacitance only (no wire/junction cap)",
            "50 % delay = C_L * integral dV/I over half the rail",
            "dynamic power = N * C_L * Vdd^2 * f (each node swings once per period)",
        ],
    }
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return RingOscillatorArtifacts(destination, scan, metadata)
