"""Figure set for the P0 deliverable.

Seven figures, each stamped with the information it needs to be traced back:

fig1  frozen device structure and the provenance class of every dimension
fig2  calibrated model versus digitized Figure 3 metrics (threshold, Gm, SS,
      with the two-stage swing decomposition)
fig3  device-to-inverter dose sweep (VTC family, static metrics)
fig4  one-at-a-time sensitivity of the inverter metrics
fig5  inverter response across the documented assumption ranges
fig6  cross-source threshold-drift dose laws
fig7  quasi-static ring-oscillator frequency and stage power budget
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from .metric_calibration import MetricCalibration
from .registry import ParameterRecord

PARAMETER_LABELS = {
    "n.threshold_v": "n Vth",
    "n.mobility_m2_vs": "n mu",
    "n.qot_slope": "n Qot slope",
    "n.qit_slope": "n Qit slope",
    "n.mobility_degradation": "n mu degradation",
    "n.slope_factor_per_krad": "n swing slope",
    "p.threshold_v": "p Vth",
    "p.mobility_m2_vs": "p mu",
    "p.qot_slope": "p Qot slope",
    "p.qit_slope": "p Qit slope",
    "p.mobility_degradation": "p mu degradation",
    "p.slope_factor_per_krad": "p swing slope",
}

METRIC_LABELS = {"vm_v": "switching threshold VM", "nml_v": "noise margin NML", "nmh_v": "noise margin NMH"}

PROVENANCE_COLORS = {
    "reported": "#4c78a8",
    "digitized": "#54a24b",
    "derived": "#b279a2",
    "assumed": "#e45756",
    "convention": "#9d9d9d",
    "calibrated": "#f58518",
}


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "savefig.dpi": 200,
            "font.size": 9,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
        }
    )


def _stamp(fig, text: str) -> None:
    # A figure-level xlabel reserves layout space, so the stamp never collides
    # with the axes labels.
    fig.supxlabel(text, x=0.006, ha="left", fontsize=6.5, color="#555555")


def plot_structure(
    registry: dict[str, ParameterRecord], calibration: MetricCalibration, path: Path
) -> None:
    """Cross-section card of the frozen top-gate CNT-network FET."""

    _style()

    def value(key: str) -> float:
        return float(registry[key].value)

    tox_nm = value("dev.oxide_thickness_nm")
    channel_nm = value("dev.channel_thickness_nm")
    gate_um = value("dev.length_nm") / 1000.0
    width_um = value("dev.width_um")

    fig, (axis, notes) = plt.subplots(
        1,
        2,
        figsize=(11.4, 4.8),
        gridspec_kw={"width_ratios": [1.5, 1.0]},
        constrained_layout=True,
    )
    axis.set_xlim(0, 12)
    axis.set_ylim(0, 10)
    axis.axis("off")

    def layer(y, height, x0, x1, color, label, hatch=None):
        axis.add_patch(
            Rectangle((x0, y), x1 - x0, height, facecolor=color, edgecolor="#333333", linewidth=0.8, hatch=hatch)
        )
        axis.text((x0 + x1) / 2, y + height / 2, label, ha="center", va="center", fontsize=7.8)

    layer(0.0, 3.4, 0.5, 11.5, "#d9d9d9", "Si substrate (500 um, truncated)", hatch="//")
    layer(3.4, 1.5, 0.5, 11.5, "#f2e8c9", "buried oxide 280 nm")
    layer(4.9, 0.5, 0.5, 11.5, "#cfe3d4", "CNT network channel (effective film)")
    layer(5.4, 0.6, 3.2, 7.6, "#c9d7ee", f"Y2O3/HfO2 {tox_nm:.0f} nm top dielectric")
    layer(6.0, 0.8, 3.2, 7.6, "#8f8f8f", "gate metal")
    layer(5.4, 0.8, 1.4, 3.0, "#f4b183", "Pd source")
    layer(5.4, 0.8, 7.8, 9.4, "#f4b183", "Pd drain")

    axis.annotate("", xy=(3.2, 7.25), xytext=(7.6, 7.25), arrowprops=dict(arrowstyle="<->", linewidth=0.9))
    axis.text(5.4, 7.5, f"Lg = {gate_um:.1f} um", ha="center", fontsize=8)

    axis.text(0.55, 9.4, f"width W = {width_um:.0f} um (into the page)", fontsize=8)
    axis.text(0.55, 8.85, f"not to scale; {channel_nm:.0f} nm channel film is an effective medium", fontsize=7.5)
    axis.set_title("Frozen P0 structure: top-gate CNT-network p-FET (Cui 2023)")

    notes.axis("off")
    lines = [
        ("Frozen dimensions", None, True),
        ("Lg          4.0 um     reported", "reported", False),
        ("W          30.0 um     reported", "reported", False),
        ("t_ox       10 nm total reported", "reported", False),
        (f"eps_r      {value('dev.oxide_relative_permittivity'):.1f}        assumed 12-20", "assumed", False),
        ("BOX         280 nm     reported", "reported", False),
        (f"channel film {channel_nm:.0f} nm    assumed 2-10", "assumed", False),
        ("", None, False),
        ("Dose conditions", None, True),
        ("Co-60 gamma, 195.476 rad(Si)/s, floating", "reported", False),
        ("0/200/500/1000/2000/3000 krad(Si)", "reported", False),
        ("", None, False),
        ("Zero-dose anchors", None, True),
        (f"|Vth0|  {calibration.vth0_mag_v:.3f} V         digitized", "digitized", False),
        (f"SS0     {calibration.ss0_mv_dec:.1f} mV/dec   digitized", "digitized", False),
        (f"Gm0     {calibration.gm0_s:.2e} S        digitized", "digitized", False),
        (f"VDD     {float(registry['sim.vdd_v'].value):.1f} V          assumed", "assumed", False),
        ("", None, False),
        ("Dose-response laws (fitted)", None, True),
        (f"Q(D) = k D^{calibration.dose_exponent:.2f}", "calibrated", False),
        (
            f"swing: k D^{calibration.dose_exponent:.2f} - qa(1-exp(-D/Da))",
            "calibrated",
            False,
        ),
        (f"qa = {calibration.qit_anneal_c_cm2:.1e} C/cm2, Da = {calibration.qit_anneal_dose_krad:.0f} krad", "calibrated", False),
        (f"n-channel: symmetric complement, ratio {float(registry['assume.n_p_dose_response_ratio'].value):.1f}", "assumed", False),
    ]
    y = 0.99
    for text, provenance, heading in lines:
        color = "#111111" if heading else PROVENANCE_COLORS.get(provenance, "#333333")
        notes.text(
            0.0,
            y,
            text,
            fontsize=8,
            color=color,
            weight="bold" if heading else "normal",
            va="top",
            family="monospace",
        )
        y -= 0.049
    _stamp(fig, "cnt-tid p0 | fig1 | structure card | source: data/parameters/tid_parameters.csv")
    fig.savefig(path)
    plt.close(fig)


def plot_device_validation(
    validation: pd.DataFrame,
    holdout: pd.DataFrame,
    calibration: MetricCalibration,
    path: Path,
) -> None:
    """Model curves against the digitized literature metrics."""

    _style()
    doses = validation["dose_krad"].to_numpy(dtype=float)
    panels = (
        ("vth_v", "Threshold magnitude |Vth| (V)", "vth_err_minus_v", "vth_err_plus_v", "threshold"),
        ("gm_s", "Maximum Gm (S)", "gm_err_minus_s", "gm_err_plus_s", "transconductance"),
        ("ss_mv", "Subthreshold swing (mV/dec)", "ss_err_minus_mv", "ss_err_plus_mv", "swing"),
    )
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.0), constrained_layout=True)
    for axis, (prefix, ylabel, err_minus_key, err_plus_key, title) in zip(axes, panels, strict=True):
        data = validation[f"{prefix}_data"].to_numpy(dtype=float)
        model = validation[f"{prefix}_model"].to_numpy(dtype=float)
        axis.plot(doses, model, "-", color="#4c78a8", linewidth=1.4, label="compact model")
        axis.errorbar(
            doses,
            data,
            yerr=[
                validation[err_minus_key].to_numpy(dtype=float),
                validation[err_plus_key].to_numpy(dtype=float),
            ],
            fmt="s",
            color="black",
            ecolor="#555555",
            elinewidth=0.8,
            capsize=2.5,
            markersize=4.0,
            label="digitized (Cui 2023)",
        )
        axis.set(xlabel="Dose (krad(Si))", ylabel=ylabel, title=title)
        axis.legend(fontsize=7, loc="best")

    # Two-stage decomposition on the swing panel: the dashed curve drops the
    # anneal term, i.e. what a single generated-density law would predict.
    if "ss_mv_dec_generation_only" in validation.columns:
        axes[2].plot(
            doses,
            validation["ss_mv_dec_generation_only"].to_numpy(dtype=float),
            "--",
            color="#9d9d9d",
            linewidth=1.1,
            label="generation only (no anneal)",
        )
        axes[2].legend(fontsize=6.5, loc="best")

    box = dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.5)
    axes[0].text(0.03, 0.95, f"max residual {float(validation['vth_residual_mv'].abs().max()):.0f} mV",
                 transform=axes[0].transAxes, fontsize=7, va="top", bbox=box)
    axes[1].text(0.32, 0.95, f"max residual {100.0 * float(validation['gm_residual_rel'].abs().max()):.1f} %",
                 transform=axes[1].transAxes, fontsize=7, va="top", bbox=box)
    axes[2].text(0.03, 0.95, f"max residual {float(validation['ss_residual_mv'].abs().max()):.0f} mV/dec",
                 transform=axes[2].transAxes, fontsize=7, va="top", bbox=box)
    axes[2].text(
        0.03,
        0.83,
        "two-stage swing law:\n"
        f"anneal {calibration.qit_anneal_c_cm2:.1e} C/cm2 @ D_a "
        f"{calibration.qit_anneal_dose_krad:.0f} krad\ndrives the 200 krad dip",
        transform=axes[2].transAxes,
        fontsize=6.3,
        va="top",
        color="#1b7837",
        bbox=box,
    )
    _stamp(
        fig,
        "cnt-tid p0 | fig2 | model vs digitized Figure 3 | leave-one-dose-out max "
        f"|dVth| = {float(holdout['vth_residual_mv'].abs().max()):.0f} mV",
    )
    fig.savefig(path)
    plt.close(fig)


def plot_inverter(inverter: pd.DataFrame, summary: pd.DataFrame, vdd_v: float, path: Path) -> None:
    _style()
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.1), constrained_layout=True)
    doses = sorted(inverter["dose_krad"].unique())
    cmap = plt.get_cmap("viridis", len(doses))
    for index, dose in enumerate(doses):
        group = inverter[inverter["dose_krad"] == dose]
        left.plot(group["vin_v"], group["vout_v"], color=cmap(index), linewidth=1.3, label=f"{dose:g} krad")
    left.plot([0, vdd_v], [0, vdd_v], "k--", linewidth=0.8)
    left.set(
        xlabel="Vin (V)",
        ylabel="Vout (V)",
        title="Complementary CNTFET inverter VTC",
        xlim=(0, vdd_v),
        ylim=(0, vdd_v),
        aspect="equal",
    )
    left.legend(fontsize=7, loc="lower right")

    right.plot(summary["dose_krad"], summary["vm_v"], "o-", color="#7b3294", label="VM")
    right.plot(summary["dose_krad"], summary["nml_v"], "s-", color="#1b7837", label="NML")
    right.plot(summary["dose_krad"], summary["nmh_v"], "^-", color="#e08214", label="NMH")
    right.set(xlabel="Dose (krad(Si))", ylabel="Voltage (V)", title="Static inverter metrics")
    right.legend(fontsize=7, loc="best")
    _stamp(fig, f"cnt-tid p0 | fig3 | device-to-inverter dose sweep | VDD = {vdd_v:.1f} V")
    fig.savefig(path)
    plt.close(fig)


def plot_sensitivity(table: pd.DataFrame, max_dose: float, path: Path) -> None:
    _style()
    metrics = [metric for metric in ("vm_v", "nml_v", "nmh_v") if metric in table["metric"].unique()]
    fig, axes = plt.subplots(
        1, len(metrics), figsize=(4.4 * len(metrics), 4.8), constrained_layout=True
    )
    if len(metrics) == 1:
        axes = [axes]
    for axis, metric in zip(axes, metrics, strict=True):
        subset = table[table["metric"] == metric]
        pivot = subset.pivot_table(
            index="parameter", columns="direction", values="mean_normalized_sensitivity", aggfunc="mean"
        )
        # +10 % and -10 % give the same elasticity for a smooth response; the
        # difference between them is the curvature (asymmetry) of the response.
        mean = pivot.mean(axis=1)
        pivot = pivot.reindex(mean.abs().sort_values(ascending=False).index)
        mean = mean.reindex(pivot.index)
        y = np.arange(len(pivot))
        colors = ["#b2182b" if value >= 0 else "#2166ac" for value in mean.to_numpy()]
        axis.barh(y, mean.to_numpy(), color=colors, alpha=0.85)
        lower = pivot.min(axis=1).to_numpy()
        upper = pivot.max(axis=1).to_numpy()
        axis.hlines(y, lower, upper, color="black", linewidth=1.1)
        axis.axvline(0.0, color="black", linewidth=0.8)
        axis.set_yticks(y, [PARAMETER_LABELS.get(name, name) for name in pivot.index], fontsize=7)
        axis.set(
            xlabel="normalised sensitivity",
            title=f"{METRIC_LABELS.get(metric, metric)} @ {max_dose:g} krad(Si)",
        )
        axis.invert_yaxis()
    _stamp(
        fig,
        "cnt-tid p0 | fig4 | one-at-a-time +/-10 % perturbation at the maximum dose | "
        "bar = elasticity, red = positive / blue = negative, thin line = spread between the two directions",
    )
    fig.savefig(path)
    plt.close(fig)


def plot_assumption_sweep(frame: pd.DataFrame, path: Path) -> None:
    """Sensitivity of the inverter result to the documented assumptions."""

    _style()
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.2), constrained_layout=True)
    groups = (
        ("eps_r", "top-dielectric eps_r", axes[0]),
        ("n_over_p_ratio", "n/p dose-response ratio", axes[1]),
    )
    for kind, title, axis in groups:
        subset = frame[frame["assumption"] == kind]
        for value, group in subset.groupby("value"):
            baseline = bool(group["is_baseline"].iloc[0])
            axis.plot(
                group["dose_krad"],
                group["vm_v"],
                "-o" if baseline else "--",
                linewidth=2.0 if baseline else 1.2,
                markersize=4,
                label=f"{value:g}" + (" (baseline)" if baseline else ""),
            )
        axis.set(
            xlabel="Dose (krad(Si))",
            ylabel="Switching threshold VM (V)",
            title=title,
        )
        axis.legend(fontsize=7, title="assumed value", title_fontsize=7)
    axes[0].text(
        0.35,
        0.55,
        "eps_r only rescales the reported trapped charge\n"
        "(1.18e-6 -> 1.96e-6 C/cm2 at 3 Mrad);\n"
        "it cancels in the voltage-anchored calibration",
        transform=axes[0].transAxes,
        fontsize=6.5,
        va="center",
        bbox=dict(facecolor="white", edgecolor="#999999", alpha=0.9, pad=3),
    )
    _stamp(
        fig,
        "cnt-tid p0 | fig5 | inverter response across the stated assumption ranges | "
        "eps_r 12-20, n/p ratio 0.5-1.5",
    )
    fig.savefig(path)
    plt.close(fig)


def plot_ring_oscillator(scan: pd.DataFrame, path: Path) -> None:
    """Ring-oscillator frequency collapse and static-power explosion with dose."""

    _style()
    doses = scan["dose_krad"].to_numpy(dtype=float)
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.2), constrained_layout=True)
    left.plot(doses, scan["frequency_hz"], "o-", color="#4c78a8", linewidth=1.4)
    left.set(
        xlabel="Dose (krad(Si))",
        ylabel="Ring frequency (Hz)",
        title="Ring-oscillator frequency",
    )
    right.plot(
        doses,
        scan["static_power_w"],
        "s-",
        color="#b2182b",
        linewidth=1.4,
        label="static",
    )
    right.plot(
        doses,
        scan["dynamic_power_w"],
        "^-",
        color="#2166ac",
        linewidth=1.4,
        label="dynamic",
    )
    right.plot(
        doses,
        scan["total_power_w"],
        "-",
        color="#333333",
        linewidth=1.2,
        alpha=0.6,
        label="total",
    )
    right.set(
        xlabel="Dose (krad(Si))",
        ylabel="Power (W)",
        title="Stage power budget",
    )
    for axis in (left, right):
        axis.set_yscale("log")
        axis.grid(True, which="both", alpha=0.18)
    right.legend(fontsize=7, loc="best")
    _stamp(
        fig,
        "cnt-tid p0 | fig7 | quasi-static ring oscillator | "
        "load = next-stage gate cap, 50 % delay = C_L * integral dV/I over half the rail",
    )
    fig.savefig(path)
    plt.close(fig)


def plot_cross_source(frame: pd.DataFrame, fits: pd.DataFrame, path: Path) -> None:
    """Measured threshold drift of every literature device variant."""

    _style()
    fig, axis = plt.subplots(figsize=(8.2, 5.0), constrained_layout=True)
    markers = ["o", "s", "^", "D", "v", "P", "X", "*"]
    labels = {
        "cui2023_top_gate": "Cui top-gate",
        "kanhaiya_top_gate": "Kanhaiya top-gate",
        "kanhaiya_local_bottom_gate": "local bottom-gate",
        "kanhaiya_local_bottom_gate_eot7": "local bottom-gate, EOT 7 nm",
        "kanhaiya_local_bottom_gate_eot2": "local bottom-gate, EOT 2 nm",
        "kanhaiya_dual_gate": "dual-gate",
        "kanhaiya_dual_gate_eot7": "dual-gate, EOT 7 nm",
        "kanhaiya_dual_gate_eot2": "dual-gate, EOT 2 nm",
    }
    fits_by_id = {row["device_id"]: row for _, row in fits.iterrows()}
    for index, (device_id, group) in enumerate(frame.groupby("device_id")):
        group = group.sort_values("dose_krad")
        fit = fits_by_id[device_id]
        colour = plt.get_cmap("tab10")(index % 10)
        usable = bool(fit["usable"])
        tag = f"p = {fit['exponent']:.2f}" if usable else fit["regime"].replace("_", " ")
        axis.plot(
            group["dose_krad"].replace(0, np.nan),
            group["vt_shift_mv"],
            markers[index % len(markers)],
            color=colour,
            markersize=5,
            alpha=1.0 if usable else 0.45,
            label=f"{labels.get(device_id, device_id)} ({tag})",
        )
        if usable:
            grid = np.logspace(2, 4.15, 80)
            axis.plot(
                grid,
                fit["coefficient_mv_per_krad_p"] * grid ** fit["exponent"],
                "-",
                color=colour,
                linewidth=1.0,
                alpha=0.6,
            )
    axis.set_xscale("log")
    axis.set_xlim(90, 14000)
    axis.set(
        xlabel="Total ionizing dose (krad(Si))",
        ylabel="|VT shift| (mV)",
        title="Threshold drift: the dose law is a property of the architecture",
        ylim=(-25, 700),
    )
    axis.grid(True, which="both", alpha=0.18)
    axis.legend(fontsize=6.2, loc="upper left", framealpha=0.85, borderpad=0.4)
    axis.text(
        0.985,
        0.035,
        "faint markers: fit not usable (below noise floor or knee)",
        transform=axis.transAxes,
        fontsize=6,
        ha="right",
        color="#b22222",
    )
    _stamp(
        fig,
        "cnt-tid p0 | fig6 | cross-source dose laws | Cui 2023 (0.2-3 Mrad) + Kanhaiya 2021 (0.1-10 Mrad)",
    )
    fig.savefig(path)
    plt.close(fig)
