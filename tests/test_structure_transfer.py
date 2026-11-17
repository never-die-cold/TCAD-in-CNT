"""Tests for the structure-transfer predictor with architecture-class bands."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cnt_tid.cross_source import cui_shift_frame, fit_dose_laws, load_vt_shift
from cnt_tid.metric_calibration import load_digitized_metrics
from cnt_tid.structure_transfer import predict_all, predict_architecture

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "data" / "literature" / "cui2023_topgate" / "fig3_metrics_digitized.csv"
SECOND_SOURCE = ROOT / "data" / "literature" / "kanhaiya2021" / "vt_shift_vs_tid.csv"
GRID = np.array([100.0, 200.0, 3000.0, 10000.0])


@pytest.fixture()
def cross_frame() -> pd.DataFrame:
    metrics = load_digitized_metrics(METRICS)
    return pd.concat(
        [
            cui_shift_frame(metrics, oxide_thickness_nm=10.0, oxide_relative_permittivity=15.0),
            load_vt_shift([SECOND_SOURCE]),
        ],
        ignore_index=True,
    )


def test_own_fit_prediction_tracks_its_anchor_and_stays_inside_the_band(cross_frame):
    fits = fit_dose_laws(cross_frame)
    prediction = predict_architecture(
        cross_frame, fits, "cui2023_top_gate", GRID
    )
    assert prediction.strategy == "own_power_law"
    anchor_row = prediction.table.loc[prediction.table["dose_krad"] == prediction.anchor_dose_krad]
    assert anchor_row["predicted_mv"].iloc[0] == pytest.approx(prediction.anchor_shift_mv, rel=1e-9)
    inside = prediction.table[
        (prediction.table["band_low_mv"] <= prediction.table["predicted_mv"])
        & (prediction.table["predicted_mv"] <= prediction.table["band_high_mv"])
    ]
    assert len(inside) == len(prediction.table)


def test_band_edges_swap_below_the_anchor_dose(cross_frame):
    fits = fit_dose_laws(cross_frame)
    prediction = predict_architecture(cross_frame, fits, "cui2023_top_gate", GRID)
    below = prediction.table[prediction.table["dose_krad"] < prediction.anchor_dose_krad]
    above = prediction.table[prediction.table["dose_krad"] > prediction.anchor_dose_krad]
    # Above the anchor the steeper class edge (p = 0.85) is the upper bound;
    # below it the ordering flips because ratio**p grows with p only above 1.
    assert (below["band_low_mv"] < below["band_high_mv"]).all()
    assert (above["band_high_mv"] > above["band_low_mv"]).all()
    assert above["band_high_mv"].iloc[-1] > above["predicted_mv"].iloc[-1]


def test_anchored_reference_strategy_for_the_knee_regime(cross_frame):
    fits = fit_dose_laws(cross_frame)
    # The knee-regime variant's first usable point sits at 5 Mrad, so the
    # grid must include it for the anchor-identity check.
    grid = np.array([500.0, 5000.0, 10000.0])
    prediction = predict_architecture(cross_frame, fits, "kanhaiya_dual_gate_eot7", grid)
    assert prediction.strategy == "anchored_reference"
    anchor_row = prediction.table.loc[prediction.table["dose_krad"] == prediction.anchor_dose_krad]
    assert anchor_row["predicted_mv"].iloc[0] == pytest.approx(prediction.anchor_shift_mv, rel=1e-9)


def test_below_noise_floor_variant_yields_an_empty_prediction(cross_frame):
    fits = fit_dose_laws(cross_frame)
    prediction = predict_architecture(cross_frame, fits, "kanhaiya_dual_gate", GRID)
    assert prediction.strategy == "below_noise_floor"
    assert prediction.table["predicted_mv"].isna().all()
    assert (prediction.table["extrapolated"]).all()


def test_unknown_device_and_bad_grid_are_rejected(cross_frame):
    fits = fit_dose_laws(cross_frame)
    with pytest.raises(ValueError, match="unknown device_id"):
        predict_architecture(cross_frame, fits, "not_a_device", GRID)
    with pytest.raises(ValueError, match="positive doses"):
        predict_architecture(cross_frame, fits, "cui2023_top_gate", np.array([0.0, 100.0]))


def test_predict_all_covers_every_variant_once(cross_frame):
    table, manifest = predict_all(
        [SECOND_SOURCE],
        load_digitized_metrics(METRICS),
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        dose_grid=GRID,
    )
    variants = {item["device_id"] for item in manifest["variants"]}
    assert variants == set(cross_frame["device_id"].unique())
    assert len(table) == 8 * GRID.size
    strategies = {item["device_id"]: item["strategy"] for item in manifest["variants"]}
    assert strategies["kanhaiya_dual_gate"] == "below_noise_floor"
    assert strategies["kanhaiya_dual_gate_eot7"] == "anchored_reference"
    own = [device for device, strategy in strategies.items() if strategy == "own_power_law"]
    assert len(own) == 5
