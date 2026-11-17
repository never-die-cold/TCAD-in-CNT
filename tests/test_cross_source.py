"""Tests for the cross-source dose-law comparison."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cnt_tid.cross_source import (
    cui_shift_frame,
    fit_dose_laws,
    load_vt_shift,
    transfer_error,
)

ROOT = Path(__file__).resolve().parents[1]
KANHAIYA = ROOT / "data" / "literature" / "kanhaiya2021" / "vt_shift_vs_tid.csv"
CUI = ROOT / "data" / "literature" / "cui2023_topgate" / "fig3_metrics_digitized.csv"


def test_digitized_table_matches_the_published_endpoints():
    frame = load_vt_shift([KANHAIYA])
    assert frame["dose_unit" if "dose_unit" in frame else "dose_krad"].notna().all()
    by_device = frame.groupby("device_id")["vt_shift_mv"].max()
    # The paper quotes 441 and 341 mV at 10 Mrad for local bottom-gate and
    # dual-gate CNFETs with a 7 nm EOT gate stack.
    assert by_device["kanhaiya_local_bottom_gate_eot7"] == pytest.approx(441, abs=5)
    assert by_device["kanhaiya_dual_gate_eot7"] == pytest.approx(341.5, abs=5)
    assert by_device["kanhaiya_top_gate"] == pytest.approx(595, abs=10)
    assert by_device["kanhaiya_local_bottom_gate"] == pytest.approx(84, abs=5)


def test_dose_axis_is_in_krad_and_monotonic_per_device():
    frame = load_vt_shift([KANHAIYA])
    for _, group in frame.groupby("device_id"):
        assert group["dose_krad"].is_monotonic_increasing
    assert frame["dose_krad"].min() == 0.0
    assert frame["dose_krad"].max() == 10000.0


def test_cui_frame_reproduces_the_threshold_shift():
    metrics = pd.read_csv(CUI)
    frame = cui_shift_frame(metrics, oxide_thickness_nm=10.0, oxide_relative_permittivity=15.0)
    assert frame.iloc[0]["vt_shift_mv"] == pytest.approx(0.0, abs=1e-9)
    assert frame.iloc[-1]["vt_shift_mv"] == pytest.approx(1092.4, abs=1.0)
    assert frame.iloc[0]["eot_nm"] == pytest.approx(10.0 * 3.9 / 15.0)


def test_fit_recovers_a_known_power_law():
    doses = np.array([0, 100, 200, 500, 1000, 2000])
    values = 3.0 * doses**0.6
    synthetic = pd.DataFrame(
        {
            "source": "synthetic",
            "device_id": "synthetic",
            "geometry": "synthetic",
            "eot_nm": 5.0,
            "dose_value": doses,
            "dose_unit": "krad(Si)",
            "value": values,
            "geometry_ok": True,
        }
    )
    frame = synthetic.rename(columns={"dose_value": "dose_krad", "value": "vt_shift_mv"})
    fits = fit_dose_laws(frame)
    row = fits.iloc[0]
    assert row["coefficient_mv_per_krad_p"] == pytest.approx(3.0, rel=0.02)
    assert row["exponent"] == pytest.approx(0.6, abs=0.02)
    assert row["regime"] == "power_law"


def test_repository_fits_separate_architectures():
    frame = pd.concat(
        [
            cui_shift_frame(pd.read_csv(CUI), 10.0, 15.0),
            load_vt_shift([KANHAIYA]),
        ],
        ignore_index=True,
    )
    fits = fit_dose_laws(frame)
    usable = fits[fits["usable"]]
    assert usable.shape[0] >= 4
    assert usable["exponent"].min() == pytest.approx(0.233, abs=0.03)
    assert usable["exponent"].max() == pytest.approx(0.845, abs=0.03)
    # the dual-gate variants must not be sold as power laws
    assert set(fits.loc[fits["device_id"].str.startswith("kanhaiya_dual"), "regime"]) <= {
        "knee_not_a_power_law",
        "below_noise_floor",
    }


def test_transfer_of_one_law_to_another_structure_is_quantified():
    frame = pd.concat(
        [
            cui_shift_frame(pd.read_csv(CUI), 10.0, 15.0),
            load_vt_shift([KANHAIYA]),
        ],
        ignore_index=True,
    )
    fits = fit_dose_laws(frame)
    transfer = transfer_error(frame, fits, "cui2023_top_gate")
    row = transfer[transfer["device_id"] == "kanhaiya_local_bottom_gate_eot7"].iloc[0]
    assert row["measured_end_mv"] == pytest.approx(441, abs=5)
    assert row["relative_error_end"] < -0.5
    assert np.isfinite(transfer["relative_error_end"]).sum() >= 6
