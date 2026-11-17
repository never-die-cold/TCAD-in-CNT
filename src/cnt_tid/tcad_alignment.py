"""Zero-dose alignment of an SDevice-exported Id-Vg curve against the compact model.

The P0 acceptance gate for the TCAD branch is quantitative: the first
SDevice run of `tcad/cntfet/topgate/` counts as aligned only when its
zero-dose transfer curve reproduces the compact model's zero-dose curve
within a stated relative deviation.  Both curves are reduced with the SAME
metric extraction (constant-current threshold, minimum swing, maximum Gm at
the probe drain bias), so the comparison measures the devices, not the
extraction methods.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .device import drain_current, state_at_dose

DEFAULT_PROBE_VDS_V = 0.1
DEFAULT_I_REF_A = 1e-6
DEFAULT_GATE_REL = 0.20
MIN_POINTS = 10


@dataclass(frozen=True)
class AlignmentMetrics:
    """Zero-dose metrics extracted with one shared method."""

    ss_mv_dec: float
    gm_max_s: float
    vth_mag_v: float
    i_ref_a: float


@dataclass(frozen=True)
class AlignmentResult:
    """Deviation table and gate verdict for the zero-dose TCAD run."""

    model: AlignmentMetrics
    tcad: AlignmentMetrics
    ss_dev_rel: float
    gm_dev_rel: float
    vth_dev_rel: float
    gate_rel: float
    passed: bool
    probe_vds_v: float
    points_used: int
    points_dropped: int
    tcad_source: str

    def table(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "metric": ["ss_mv_dec", "gm_max_s", "vth_mag_v"],
                "compact_model": [self.model.ss_mv_dec, self.model.gm_max_s, self.model.vth_mag_v],
                "tcad": [self.tcad.ss_mv_dec, self.tcad.gm_max_s, self.tcad.vth_mag_v],
                "relative_deviation": [self.ss_dev_rel, self.gm_dev_rel, self.vth_dev_rel],
                "gate_rel": [self.gate_rel] * 3,
                "passed": [
                    self.ss_dev_rel < self.gate_rel,
                    self.gm_dev_rel < self.gate_rel,
                    self.vth_dev_rel < self.gate_rel,
                ],
            }
        )


def load_tcad_idvg(path: str | Path) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Load a signed SDevice export and convert it to positive magnitudes.

    The export keeps SDevice's signed terminal values.  For the p-FET the
    positive-magnitude convention is Vsg = -VGS, |Id| = -IDS; forward-gate
    points (VGS > 0) are excluded exactly like the literature converter.
    Returns (vsg_v ascending, id_a positive, vds_v, dropped count).
    """

    frame = pd.read_csv(path)
    required = ("vgs_signed_v", "vds_signed_v", "id_signed_a")
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"TCAD export missing columns: {missing}")
    numeric = frame.loc[:, required].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("TCAD export contains NaN or infinite values")
    if frame.empty:
        raise ValueError("TCAD export is empty")
    vds_values = frame["vds_signed_v"].round(12).unique()
    if vds_values.size != 1:
        raise ValueError(f"TCAD export mixes {vds_values.size} drain biases")
    vds_v = float(-vds_values[0])
    if vds_v <= 0:
        raise ValueError("p-FET export must use a negative VDS")
    if (frame["id_signed_a"] >= 0).any():
        raise ValueError("p-FET export must use negative IDS; omit zero-current points")
    forward_gate = frame["vgs_signed_v"] > 0
    kept = frame.loc[~forward_gate]
    vsg = -kept["vgs_signed_v"].to_numpy(dtype=float)
    ids = -kept["id_signed_a"].to_numpy(dtype=float)
    order = np.argsort(vsg)
    return vsg[order], ids[order], vds_v, int(forward_gate.sum())


def extract_metrics(
    vgs_v: np.ndarray, ids_a: np.ndarray, i_ref_a: float = DEFAULT_I_REF_A
) -> AlignmentMetrics:
    """Reduce one transfer curve with the shared extraction method.

    * minimum swing: steepest log10(Id) rise over the sweep grid;
    * maximum Gm: steepest linear-current rise (A/V);
    * threshold magnitude: constant-current gate value at Id = i_ref.
    """

    if vgs_v.size < MIN_POINTS:
        raise ValueError(f"alignment needs at least {MIN_POINTS} sweep points")
    if (ids_a <= 0).any():
        raise ValueError("alignment requires strictly positive currents")
    if i_ref_a <= 0:
        raise ValueError("i_ref_a must be positive")
    log_ids = np.log10(ids_a)
    slope = np.gradient(log_ids, vgs_v)
    if float(slope.max()) <= 0:
        raise ValueError("current does not rise with the gate; check the sweep direction")
    ss_mv_dec = float(1.0 / slope.max()) * 1000.0
    gm_max_s = float(np.max(np.gradient(ids_a, vgs_v)))
    if not ids_a.min() <= i_ref_a <= ids_a.max():
        raise ValueError(
            f"constant-current threshold needs {i_ref_a:g} A inside the swept "
            f"current range [{ids_a.min():.3g}, {ids_a.max():.3g}] A"
        )
    vth_mag_v = float(np.interp(i_ref_a, ids_a, vgs_v))
    return AlignmentMetrics(ss_mv_dec, gm_max_s, vth_mag_v, float(i_ref_a))


def compact_transfer_curve(
    config_path: str | Path,
    vgs_v: np.ndarray,
    temperature_k: float = 300.0,
    vds_v: float = DEFAULT_PROBE_VDS_V,
) -> np.ndarray:
    """Zero-dose compact-model drain current at the probe drain bias."""

    config = load_config(config_path)
    state = state_at_dose(config.p_device, 0.0, temperature_k)
    return drain_current(state, vgs_v, vds_v)


def align_zero_dose(
    tcad_csv: str | Path,
    config_path: str | Path,
    *,
    i_ref_a: float = DEFAULT_I_REF_A,
    gate_rel: float = DEFAULT_GATE_REL,
    probe_vds_v: float = DEFAULT_PROBE_VDS_V,
    output_dir: str | Path | None = None,
) -> AlignmentResult:
    """Compare the TCAD zero-dose curve with the compact model and gate it.

    ``gate_rel`` is the P0 acceptance threshold (0.20 = 20 %) applied to each
    relative deviation.  An output directory receives the metric table, a
    JSON verdict and an overlay figure.
    """

    vsg, ids, tcad_vds, dropped = load_tcad_idvg(tcad_csv)
    if abs(tcad_vds - probe_vds_v) > 1e-3:
        raise ValueError(
            f"TCAD drain bias |VDS| = {tcad_vds:g} V does not match the compact "
            f"probe bias {probe_vds_v:g} V; align at the same operating point"
        )
    if not 0.0 < gate_rel < 1.0:
        raise ValueError("gate_rel must be in (0, 1)")
    model_ids = compact_transfer_curve(config_path, vsg, vds_v=probe_vds_v)

    model_metrics = extract_metrics(vsg, model_ids, i_ref_a)
    tcad_metrics = extract_metrics(vsg, ids, i_ref_a)

    ss_dev_rel = float(abs(tcad_metrics.ss_mv_dec - model_metrics.ss_mv_dec) / model_metrics.ss_mv_dec)
    gm_dev_rel = float(abs(tcad_metrics.gm_max_s - model_metrics.gm_max_s) / model_metrics.gm_max_s)
    vth_dev_rel = float(
        abs(tcad_metrics.vth_mag_v - model_metrics.vth_mag_v) / model_metrics.vth_mag_v
    )
    passed = bool(max(ss_dev_rel, gm_dev_rel, vth_dev_rel) < gate_rel)
    result = AlignmentResult(
        model=model_metrics,
        tcad=tcad_metrics,
        ss_dev_rel=ss_dev_rel,
        gm_dev_rel=gm_dev_rel,
        vth_dev_rel=vth_dev_rel,
        gate_rel=float(gate_rel),
        passed=passed,
        probe_vds_v=float(probe_vds_v),
        points_used=int(vsg.size),
        points_dropped=dropped,
        tcad_source=str(tcad_csv).replace("\\", "/"),
    )

    if output_dir is not None:
        _write_artifacts(Path(output_dir), result, vsg, model_ids, ids)
    return result


def _write_artifacts(
    output_dir: Path,
    result: AlignmentResult,
    vsg: np.ndarray,
    model_ids: np.ndarray,
    tcad_ids: np.ndarray,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result.table().to_csv(output_dir / "alignment_metrics.csv", index=False)
    payload = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "verdict": "pass" if result.passed else "fail",
        "gate_rel": result.gate_rel,
        "probe_vds_v": result.probe_vds_v,
        "i_ref_a": result.model.i_ref_a,
        "tcad_source": result.tcad_source,
        "points_used": result.points_used,
        "points_dropped_forward_gate": result.points_dropped,
        "model": {
            "ss_mv_dec": result.model.ss_mv_dec,
            "gm_max_s": result.model.gm_max_s,
            "vth_mag_v": result.model.vth_mag_v,
        },
        "tcad": {
            "ss_mv_dec": result.tcad.ss_mv_dec,
            "gm_max_s": result.tcad.gm_max_s,
            "vth_mag_v": result.tcad.vth_mag_v,
        },
        "relative_deviation": {
            "ss": result.ss_dev_rel,
            "gm": result.gm_dev_rel,
            "vth": result.vth_dev_rel,
        },
    }
    (output_dir / "alignment_verdict.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _plot_overlay(output_dir / "alignment_overlay.png", result, vsg, model_ids, tcad_ids)


def _plot_overlay(
    path: Path,
    result: AlignmentResult,
    vsg: np.ndarray,
    model_ids: np.ndarray,
    tcad_ids: np.ndarray,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axis = plt.subplots(figsize=(7.4, 4.6), constrained_layout=True)
    axis.loglog(vsg, tcad_ids, "s", markersize=3.5, color="#4c78a8", label="SDevice (zero dose)")
    axis.loglog(vsg, model_ids, "-", color="#b22222", linewidth=1.5, label="compact model (zero dose)")
    axis.axhline(result.model.i_ref_a, color="#999999", linewidth=0.8, linestyle="--")
    axis.text(
        0.02,
        0.06,
        f"SS {result.ss_dev_rel:.1%} | Gm {result.gm_dev_rel:.1%} | "
        f"Vth(cc) {result.vth_dev_rel:.1%} | gate {result.gate_rel:.0%} -> "
        f"{'PASS' if result.passed else 'FAIL'}",
        transform=axis.transAxes,
        fontsize=8,
        bbox=dict(facecolor="white", edgecolor="#999999", alpha=0.9, pad=3),
    )
    axis.set(xlabel="|Vsg| (V)", ylabel="|Id| (A)", title="Zero-dose alignment: TCAD vs compact model")
    axis.grid(True, which="both", alpha=0.2)
    axis.legend(fontsize=7, loc="lower right")
    fig.savefig(path)
    plt.close(fig)
