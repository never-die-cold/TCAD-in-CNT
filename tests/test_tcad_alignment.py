"""Tests for the zero-dose TCAD-versus-compact-model alignment gate."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cnt_tid.config import load_config
from cnt_tid.device import drain_current, state_at_dose
from cnt_tid.tcad_alignment import (
    align_zero_dose,
    extract_metrics,
    load_tcad_idvg,
)

ROOT = Path(__file__).resolve().parents[1]
P0_CONFIG = ROOT / "configs" / "p0" / "cntfet_tid_p0.toml"


def signed_export(
    path: Path,
    *,
    threshold_scale: float = 1.0,
    mobility_scale: float = 1.0,
    forward_gate_rows: int = 0,
) -> Path:
    """Write a synthetic SDevice export from the compact model plus perturbations."""

    config = load_config(P0_CONFIG)
    device = replace(
        config.p_device,
        threshold_v=config.p_device.threshold_v * threshold_scale,
        mobility_m2_vs=config.p_device.mobility_m2_vs * mobility_scale,
    )
    state = state_at_dose(device, 0.0, config.temperature_k)
    vsg = np.linspace(0.0, 2.0, 401)
    ids = drain_current(state, vsg, 0.1)
    rows = []
    for index in range(forward_gate_rows):
        rows.append(
            {
                "vgs_signed_v": 0.2 + 0.1 * index,
                "vds_signed_v": -0.1,
                "id_signed_a": -1e-9 * (1.0 + index),
            }
        )
    for gate, current in zip(vsg, ids, strict=True):
        rows.append(
            {"vgs_signed_v": -gate, "vds_signed_v": -0.1, "id_signed_a": -current}
        )
    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def test_exact_model_curve_passes_with_zero_deviation(tmp_path):
    export = signed_export(tmp_path / "idvg_signed.csv")
    result = align_zero_dose(
        export, P0_CONFIG, output_dir=tmp_path / "align"
    )
    assert result.ss_dev_rel < 1e-6
    assert result.gm_dev_rel < 1e-6
    assert result.vth_dev_rel < 1e-6
    assert result.passed is True
    assert result.points_dropped == 0
    assert result.points_used == 401
    # The compact curve must reproduce its own zero-dose swing (n0 = 3.49 ->
    # SS = 3.49 * 59.6 = 208 mV/dec); the grid-gradient extraction lands a few
    # mV higher on a 0.01 V grid, which is a discretization artefact.
    assert result.model.ss_mv_dec == pytest.approx(207.95, abs=12.0)
    assert (tmp_path / "align" / "alignment_metrics.csv").exists()
    assert (tmp_path / "align" / "alignment_verdict.json").exists()
    assert (tmp_path / "align" / "alignment_overlay.png").exists()


def test_threshold_offset_shifts_the_constant_current_threshold(tmp_path):
    export = signed_export(tmp_path / "idvg_signed.csv", threshold_scale=1.1)
    result = align_zero_dose(export, P0_CONFIG)
    # The whole I(Vg) curve shifts horizontally by the threshold offset, so
    # the constant-current metric shifts one-to-one with it.
    expected_vth_dev = 0.1 * 0.53 / result.model.vth_mag_v
    assert result.vth_dev_rel == pytest.approx(expected_vth_dev, abs=0.005)
    assert result.gm_dev_rel < 0.01
    assert result.passed is True


def test_mobility_offset_shows_up_in_gm(tmp_path):
    export = signed_export(tmp_path / "idvg_signed.csv", mobility_scale=0.85)
    result = align_zero_dose(export, P0_CONFIG)
    assert result.gm_dev_rel == pytest.approx(0.15, abs=0.05)
    # Mobility also moves the constant-current point through the subthreshold
    # pre-factor, but only by a few percent.
    assert 0.0 < result.vth_dev_rel < 0.10
    assert result.passed is True  # inside the 20 % gate


def test_large_threshold_offset_fails_the_gate(tmp_path):
    export = signed_export(tmp_path / "idvg_signed.csv", threshold_scale=1.5)
    result = align_zero_dose(export, P0_CONFIG)
    assert result.passed is False
    assert result.vth_dev_rel > 0.20


def test_forward_gate_rows_are_dropped(tmp_path):
    export = signed_export(
        tmp_path / "idvg_signed.csv", forward_gate_rows=3
    )
    vsg, ids, vds, dropped = load_tcad_idvg(export)
    assert dropped == 3
    assert vds == pytest.approx(0.1)
    assert (vsg >= 0).all()
    assert (ids > 0).all()


def test_mismatched_drain_bias_is_rejected(tmp_path):
    export = signed_export(tmp_path / "idvg_signed.csv")
    frame = pd.read_csv(export)
    frame["vds_signed_v"] = -0.05
    frame.to_csv(export, index=False)
    with pytest.raises(ValueError, match="drain bias"):
        align_zero_dose(export, P0_CONFIG)


def test_extraction_rejects_current_below_the_reference(tmp_path):
    export = signed_export(tmp_path / "idvg_signed.csv")
    vsg, ids, _, _ = load_tcad_idvg(export)
    with pytest.raises(ValueError, match="swept current range"):
        extract_metrics(vsg, ids, i_ref_a=1e-3)
