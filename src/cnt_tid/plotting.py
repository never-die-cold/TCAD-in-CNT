"""Publication-oriented plots for the baseline workflow."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 130,
            "savefig.dpi": 180,
            "font.size": 9,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def plot_all(
    transfer: pd.DataFrame,
    inverter: pd.DataFrame,
    summary: pd.DataFrame,
    vdd_v: float,
    output_dir: Path,
) -> None:
    _style()
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), constrained_layout=True)
    for axis, polarity in zip(axes, ("n", "p"), strict=True):
        subset = transfer[transfer["device"] == polarity]
        for dose, group in subset.groupby("dose_krad"):
            axis.semilogy(
                group["vgs_v"],
                np.maximum(group["id_a"], 1e-30),
                label=f"{dose:g} krad",
            )
        positive_current = subset.loc[subset["id_a"] > 0, "id_a"]
        lower = max(float(positive_current.min()) * 0.2, 1e-20)
        upper = float(positive_current.max()) * 2.0
        axis.set(
            title=f"{polarity.upper()}CNTFET transfer",
            xlabel="|VGS| (V)",
            ylabel="|ID| (A)",
            ylim=(lower, upper),
        )
    axes[0].legend(fontsize=7, frameon=False)
    fig.savefig(output_dir / "device_transfer.png")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(4.8, 4.2), constrained_layout=True)
    for dose, group in inverter.groupby("dose_krad"):
        axis.plot(group["vin_v"], group["vout_v"], label=f"{dose:g} krad")
    axis.plot([0, vdd_v], [0, vdd_v], "k--", linewidth=0.8, label="Vout = Vin")
    axis.set(
        title="Complementary CNTFET inverter",
        xlabel="Vin (V)",
        ylabel="Vout (V)",
        xlim=(0, vdd_v),
        ylim=(0, vdd_v),
        aspect="equal",
    )
    axis.legend(fontsize=7, frameon=False)
    fig.savefig(output_dir / "inverter_vtc.png")
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), constrained_layout=True)
    axes[0].plot(summary["dose_krad"], summary["n_threshold_magnitude_v"], "o-", label="nFET")
    axes[0].plot(summary["dose_krad"], summary["p_threshold_magnitude_v"], "s-", label="pFET |Vth|")
    axes[0].set(xlabel="Dose (krad)", ylabel="Threshold magnitude (V)", title="Threshold drift")
    axes[0].legend(fontsize=8, frameon=False)

    axes[1].plot(summary["dose_krad"], summary["vm_v"], "o-", color="tab:purple")
    axes[1].set(xlabel="Dose (krad)", ylabel="VM (V)", title="Inverter switching threshold")

    axes[2].plot(summary["dose_krad"], summary["nml_v"], "o-", label="NML")
    axes[2].plot(summary["dose_krad"], summary["nmh_v"], "s-", label="NMH")
    axes[2].set(xlabel="Dose (krad)", ylabel="Noise margin (V)", title="Static noise margins")
    axes[2].legend(fontsize=8, frameon=False)
    fig.savefig(output_dir / "degradation_metrics.png")
    plt.close(fig)
