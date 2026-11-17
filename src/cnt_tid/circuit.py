"""Static complementary CNTFET inverter analysis."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq

from .device import DeviceState, drain_current


@dataclass(frozen=True)
class InverterResult:
    vin_v: NDArray[np.float64]
    vout_v: NDArray[np.float64]
    vil_v: float
    vih_v: float
    vol_v: float
    voh_v: float
    vm_v: float
    nml_v: float
    nmh_v: float


def _crossing(x: NDArray[np.float64], y: NDArray[np.float64], level: float) -> float:
    sign = y - level
    indices = np.flatnonzero(sign[:-1] * sign[1:] <= 0)
    if indices.size == 0:
        return float("nan")
    index = int(indices[0])
    x0, x1 = float(x[index]), float(x[index + 1])
    y0, y1 = float(sign[index]), float(sign[index + 1])
    if y0 == 0:
        return x0
    return x0 + (x1 - x0) * (-y0) / (y1 - y0)


def _last_crossing(
    x: NDArray[np.float64], y: NDArray[np.float64], level: float
) -> float:
    sign = y - level
    indices = np.flatnonzero(sign[:-1] * sign[1:] <= 0)
    if indices.size == 0:
        return float("nan")
    index = int(indices[-1])
    x0, x1 = float(x[index]), float(x[index + 1])
    y0, y1 = float(sign[index]), float(sign[index + 1])
    if y0 == 0:
        return x0
    return x0 + (x1 - x0) * (-y0) / (y1 - y0)


def _current_balance(
    output_v: float,
    input_v: float,
    n_state: DeviceState,
    p_state: DeviceState,
    vdd_v: float,
) -> float:
    n_current = float(drain_current(n_state, input_v, output_v))
    p_current = float(drain_current(p_state, vdd_v - input_v, vdd_v - output_v))
    return n_current - p_current


def solve_inverter(
    n_state: DeviceState,
    p_state: DeviceState,
    vdd_v: float,
    points: int = 1001,
) -> InverterResult:
    """Solve Id,n(Vin,Vout) = Id,p(Vdd-Vin,Vdd-Vout) at each input."""

    if vdd_v <= 0 or points < 100:
        raise ValueError("vdd_v must be positive and points >= 100")
    vin = np.linspace(0.0, vdd_v, points)
    vout = np.empty_like(vin)
    for index, input_v in enumerate(vin):
        vout[index] = brentq(
            _current_balance,
            0.0,
            vdd_v,
            args=(input_v, n_state, p_state, vdd_v),
            xtol=1e-12,
        )

    gain = np.gradient(vout, vin)
    gain_error = np.abs(gain) - 1.0
    vil = _crossing(vin, gain_error, 0.0)
    vih = _last_crossing(vin, gain_error, 0.0)
    vm = _crossing(vin, vout - vin, 0.0)
    vol = float(vout[-1])  # Output low when the input is high.
    voh = float(vout[0])  # Output high when the input is low.
    return InverterResult(
        vin_v=vin,
        vout_v=vout,
        vil_v=vil,
        vih_v=vih,
        vol_v=vol,
        voh_v=voh,
        vm_v=vm,
        nml_v=vil - vol,
        nmh_v=voh - vih,
    )
