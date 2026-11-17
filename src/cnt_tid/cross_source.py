"""Cross-source comparison of measured threshold drift versus TID.

The P0 compact model fits a single device family.  This module puts that fit in
context: it fits the same power law to every device variant that the two anchor
papers report, and quantifies how far a law fitted on one architecture is from
another.  The point is not to average the sources but to show that the dose law
is a property of the structure, so it must be fitted per structure.

Sources
-------
* Cui 2023 (top-gate CNT-network p-FET, 0-3000 krad) - digitized Figure 3.
* Kanhaiya 2021 (ACS Nano, four CNFET geometries, 0-10 Mrad) - digitized
  Figure 3e and Figure 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

MIN_USABLE_SHIFT_MV = 30.0
MIN_POINTS = 4


@dataclass(frozen=True)
class DoseLawFit:
    source: str
    device_id: str
    geometry: str
    eot_nm: float
    points: int
    dose_min_krad: float
    dose_max_krad: float
    coefficient_mv_per_krad_p: float
    exponent: float
    r_squared: float
    max_residual_mv: float
    usable: bool


def load_vt_shift(paths: list[Path]) -> pd.DataFrame:
    """Load and concatenate digitized threshold-shift tables."""

    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        required = {"source", "device_id", "geometry", "dose_value", "dose_unit", "value"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        if frame["dose_unit"].nunique() != 1 or frame["dose_unit"].iloc[0] != "krad(Si)":
            raise ValueError(f"{path}: expected a single krad(Si) dose axis")
        if (frame["dose_value"] < 0).any():
            raise ValueError(f"{path}: negative dose")
        frame = frame.copy()
        frame["eot_nm"] = pd.to_numeric(frame.get("eot_nm"), errors="coerce")
        frames.append(frame[["source", "device_id", "geometry", "eot_nm", "dose_value", "value"]])
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.rename(columns={"dose_value": "dose_krad", "value": "vt_shift_mv"})
    return combined.sort_values(["device_id", "dose_krad"]).reset_index(drop=True)


def cui_shift_frame(
    metrics: pd.DataFrame, oxide_thickness_nm: float, oxide_relative_permittivity: float
) -> pd.DataFrame:
    """Build a threshold-shift table from the digitized Cui metrics."""

    subset = metrics[metrics["metric"] == "vth_v"].sort_values("dose_value")
    if subset.empty:
        raise ValueError("digitized metrics contain no threshold column")
    magnitude = subset["value"].abs().to_numpy(dtype=float)
    eot_nm = oxide_thickness_nm * 3.9 / oxide_relative_permittivity
    return pd.DataFrame(
        {
            "source": "Cui2023",
            "device_id": "cui2023_top_gate",
            "geometry": "top-gate CNT network (Cui 2023)",
            "eot_nm": eot_nm,
            "dose_krad": subset["dose_value"].to_numpy(dtype=float),
            "vt_shift_mv": 1000.0 * (magnitude - magnitude[0]),
        }
    )


def _fit_one(doses: np.ndarray, values: np.ndarray) -> tuple[float, float, float, float]:
    mask = doses > 0
    dose = doses[mask]
    shift = np.maximum(values[mask], 0.0)
    if dose.size < 2:
        raise ValueError("need at least two non-zero doses")

    def model(x, coefficient, exponent):
        return coefficient * x**exponent

    initial = [max(shift[-1], 1e-6) / dose[-1] ** 0.6, 0.6]
    parameters, _ = curve_fit(
        model, dose, shift, p0=initial, bounds=([0.0, 0.05], [np.inf, 5.0]), maxfev=20000
    )
    predicted = model(dose, *parameters)
    ss_res = float(np.sum((shift - predicted) ** 2))
    ss_tot = float(np.sum((shift - shift.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return (
        float(parameters[0]),
        float(parameters[1]),
        r_squared,
        float(np.max(np.abs(shift - predicted))),
    )


def fit_dose_laws(frame: pd.DataFrame) -> pd.DataFrame:
    """Fit Q-style power laws per device variant and flag trustworthy fits."""

    rows = []
    for device_id, group in frame.groupby("device_id"):
        group = group.sort_values("dose_krad")
        doses = group["dose_krad"].to_numpy(dtype=float)
        values = group["vt_shift_mv"].to_numpy(dtype=float)
        coefficient, exponent, r_squared, residual = _fit_one(doses, values)
        nonzero = values[doses > 0]
        peak = float(np.nanmax(nonzero))
        if group.shape[0] < MIN_POINTS:
            regime = "too_few_points"
        elif peak < MIN_USABLE_SHIFT_MV:
            regime = "below_noise_floor"
        elif not 0.12 <= exponent <= 1.6:
            regime = "knee_not_a_power_law"
        elif residual > 0.2 * peak:
            regime = "poor_power_law_fit"
        else:
            regime = "power_law"
        usable = regime == "power_law"
        rows.append(
            {
                "source": group["source"].iloc[0],
                "device_id": device_id,
                "geometry": group["geometry"].iloc[0],
                "eot_nm": group["eot_nm"].iloc[0],
                "points": int(group.shape[0]),
                "dose_min_krad": float(doses[doses > 0].min()),
                "dose_max_krad": float(doses.max()),
                "coefficient_mv_per_krad_p": coefficient,
                "exponent": exponent,
                "r_squared": r_squared,
                "max_residual_mv": residual,
                "peak_shift_mv": peak,
                "regime": regime,
                "usable": usable,
            }
        )
    return pd.DataFrame(rows).sort_values("device_id").reset_index(drop=True)


def transfer_error(
    frame: pd.DataFrame, fits: pd.DataFrame, reference_device: str
) -> pd.DataFrame:
    """How far off is a law fitted on one architecture when used on another?

    The reference law is rescaled to pass through the target variant's first
    measured point above 10 mV, which is the most favourable transfer a user
    could hope for (they still hold one measured point).  What remains is the
    shape error of the dose law alone.
    """

    reference = fits.loc[fits["device_id"] == reference_device].iloc[0]
    rows = []
    for device_id, group in frame.groupby("device_id"):
        group = group.sort_values("dose_krad")
        positive = group[(group["dose_krad"] > 0) & (group["vt_shift_mv"] > 10.0)]
        if positive.shape[0] < 2:
            rows.append(
                {
                    "device_id": device_id,
                    "reference": reference_device,
                    "reference_exponent": reference["exponent"],
                    "anchor_dose_krad": float("nan"),
                    "max_dose_krad": float(positive["dose_krad"].max()) if not positive.empty else float("nan"),
                    "measured_end_mv": float(positive["vt_shift_mv"].iloc[-1]) if not positive.empty else float("nan"),
                    "predicted_end_mv": float("nan"),
                    "relative_error_end": float("nan"),
                    "rmse_mv": float("nan"),
                    "n_points": int(positive.shape[0]),
                }
            )
            continue
        anchor = positive.iloc[0]
        law = reference["coefficient_mv_per_krad_p"] * anchor["dose_krad"] ** reference["exponent"]
        scale = anchor["vt_shift_mv"] / law
        predicted = (
            reference["coefficient_mv_per_krad_p"]
            * scale
            * positive["dose_krad"].to_numpy(dtype=float) ** reference["exponent"]
        )
        measured = positive["vt_shift_mv"].to_numpy(dtype=float)
        rows.append(
            {
                "device_id": device_id,
                "reference": reference_device,
                "reference_exponent": reference["exponent"],
                "anchor_dose_krad": float(anchor["dose_krad"]),
                "max_dose_krad": float(positive["dose_krad"].max()),
                "measured_end_mv": float(measured[-1]),
                "predicted_end_mv": float(predicted[-1]),
                "relative_error_end": float(predicted[-1] / measured[-1] - 1.0),
                "rmse_mv": float(np.sqrt(np.mean((predicted - measured) ** 2))),
                "n_points": int(positive.shape[0]),
            }
        )
    return pd.DataFrame(rows).sort_values("device_id").reset_index(drop=True)
