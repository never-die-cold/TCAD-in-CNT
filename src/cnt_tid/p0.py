"""P0 deliverable: literature-anchored CNTFET TID study in one command.

The pipeline is intentionally linear and auditable:

    parameter registry  ->  structure + bias
    digitized Figure 3  ->  metric calibration  ->  dose laws
    resolved config     ->  device + inverter dose sweep
                        ->  model-versus-literature validation
                        ->  one-at-a-time sensitivity
                        ->  P0 figure set, resolved parameter table, manifest

Every artifact records the SHA-256 of its inputs, so a figure can be traced
back to a config hash, and a config back to the digitized CSV and the PDF.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .calibration import dump_config_toml
from .circuit import solve_inverter
from .config import SimulationConfig, config_sha256
from .cross_source import (
    cui_shift_frame,
    fit_dose_laws,
    load_vt_shift,
    transfer_error,
)
from .device import state_at_dose
from .metric_calibration import (
    MetricCalibration,
    calibrate_from_metrics,
    calibration_payload,
    load_digitized_metrics,
    model_max_gm,
)
from .p0_plots import (
    plot_assumption_sweep,
    plot_cross_source,
    plot_device_validation,
    plot_inverter,
    plot_sensitivity,
    plot_structure,
)
from .registry import ParameterRecord, build_simulation_config, load_registry, number
from .sensitivity import run_sensitivity
from .workflow import run_simulation

DEFAULT_REGISTRY = Path("data/parameters/tid_parameters.csv")
DEFAULT_METRICS = Path("data/literature/cui2023_topgate/fig3_metrics_digitized.csv")
DEFAULT_SECOND_SOURCE = Path("data/literature/kanhaiya2021/vt_shift_vs_tid.csv")


@dataclass(frozen=True)
class P0Result:
    output_dir: Path
    config: SimulationConfig
    calibration: MetricCalibration
    validation: pd.DataFrame
    key_numbers: dict
    parameters: pd.DataFrame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_metrics(config: SimulationConfig) -> pd.DataFrame:
    """Evaluate the calibrated model at every dose in the sweep."""

    thermal_v = 1.380649e-23 * config.temperature_k / 1.602176634e-19
    ideal_ss_mv = 1000.0 * np.log(10.0) * thermal_v
    rows = []
    for dose in config.doses_krad:
        state = state_at_dose(config.p_device, dose, config.temperature_k)
        # Generation-only swing (anneal term removed) visualises what the
        # two-stage decomposition contributes in fig2.
        anneal = config.p_device.qit_anneal_c_cm2 * -np.expm1(
            -dose / config.p_device.qit_anneal_dose_krad
        )
        slope_generation_only = state.slope_factor + anneal / config.p_device.cox_f_cm2
        rows.append(
            {
                "dose_krad": dose,
                "q_ot_c_cm2": state.qot_c_cm2,
                "q_it_c_cm2": state.qit_c_cm2,
                "q_it_density_net_c_cm2": state.qit_density_net_c_cm2,
                "mobility_m2_vs": state.mobility_m2_vs,
                # Evaluated on the resolved device config, i.e. what the
                # simulator actually produces rather than the closed form.
                "vth_mag_v_check": state.threshold_v,
                "gm_s_check": model_max_gm(config.p_device, dose, config.temperature_k),
                "ss_mv_dec_check": ideal_ss_mv * state.slope_factor,
                "ss_mv_dec_generation_only": ideal_ss_mv * slope_generation_only,
            }
        )
    return pd.DataFrame(rows)


def _validation_frame(
    calibration: MetricCalibration, model: pd.DataFrame
) -> pd.DataFrame:
    return calibration.residuals.merge(model, on="dose_krad", how="left")


def _parameters_frame(
    registry: dict[str, ParameterRecord],
    calibration: MetricCalibration,
    config: SimulationConfig,
    metrics_path: Path,
) -> pd.DataFrame:
    """Flatten registry + calibration into one resolved, citable table."""

    rows = []
    for record in registry.values():
        rows.append(
            {
                "param_id": record.param_id,
                "symbol": record.symbol,
                "value": record.value,
                "unit": record.unit,
                "provenance": record.provenance,
                "source": record.source,
                "derivation": record.derivation,
                "uncertainty": record.uncertainty,
            }
        )
    cox = config.p_device.cox_f_cm2
    width_over_length = (config.p_device.width_um * 1e-6) / (config.p_device.length_nm * 1e-9)
    max_dose = max(config.doses_krad)
    metric_source = f"scripts/digitize_cui2023_fig3.py -> {str(metrics_path).replace(chr(92), '/')}"
    entries = [
        ("cal.vth0_mag_v", calibration.vth0_mag_v, "V", "calibrated",
         "zero-dose threshold magnitude", "figure error bar +/- 0.052 V"),
        ("cal.ss0_mv_dec", calibration.ss0_mv_dec, "mV/dec", "calibrated",
         "zero-dose subthreshold swing", "figure error bar +/- 8.5 mV/dec"),
        ("cal.gm0_s", calibration.gm0_s, "S", "calibrated",
         "zero-dose maximum transconductance", "figure error bar +/- 1.7e-7 S"),
        ("cal.slope_factor0", calibration.slope_factor0, "1", "calibrated",
         "SS / (ln10 kT/q)", "derived from the SS error bar"),
        ("cal.mu0_m2_vs", calibration.mobility_m2_vs, "m2/(V s)", "calibrated",
         "model-inverted mobility at Vds = 0.1 V", "inherits Cox assumption (eps_r 12-20)"),
        ("cal.dose_exponent", calibration.dose_exponent, "1", "calibrated",
         "Q = k D^p", "fit standard error reported in calibration_report.json"),
        ("cal.q_tot_slope", calibration.total_charge_slope_c_cm2_per_krad, "C/cm2/krad^p",
         "calibrated", "total trapped-charge slope", "scales with the Cox assumption"),
        ("cal.q_it_slope", calibration.q_it_c_cm2_per_krad, "C/cm2/krad^p",
         "calibrated", "charged interface-trap split (bookkeeping; only the "
         "total charge is threshold-observable)",
         "reduced by the 200 krad dip"),
        ("cal.q_ot_slope", calibration.q_ot_c_cm2_per_krad, "C/cm2/krad^p",
         "calibrated", "oxide-charge slope, remainder", "scales with the Cox assumption"),
        ("cal.q_it_density_slope", calibration.qit_density_slope_c_cm2_per_krad,
         "C/cm2/krad^p", "calibrated", "two-stage swing channel: generated "
         "interface-state density slope", "scales with the Cox assumption"),
        ("cal.q_it_anneal", calibration.qit_anneal_c_cm2, "C/cm2",
         "calibrated", "two-stage swing channel: passivated pre-existing "
         "interface-state equivalent (saturating)", "scales with the Cox assumption"),
        ("cal.q_it_anneal_dose", calibration.qit_anneal_dose_krad, "krad(Si)",
         "calibrated", "annealing dose scale of the swing channel",
         "poorly identified: bound-constrained fit on a sparse dose grid"),
        ("cal.mobility_degradation", calibration.mobility_degradation_per_krad, "1/krad",
         "calibrated", "1/mu = (1 + alpha D)/mu0", "from the Gm dose trend"),
        ("derived.cox_f_cm2", cox, "F/cm2", "derived", "eps0 eps_r / tox",
         "linear in eps_r, inverse in tox"),
        ("derived.width_over_length", width_over_length, "1", "derived",
         "W/L from registered geometry", "exact from reported W and Lg"),
        ("derived.q_tot_at_max_dose",
         calibration.total_charge_slope_c_cm2_per_krad * max_dose**calibration.dose_exponent,
         "C/cm2", "derived", "Q_tot(Dmax)", "scales with the Cox assumption"),
    ]
    for param_id, value, unit, provenance, derivation, uncertainty in entries:
        rows.append(
            {
                "param_id": param_id,
                "symbol": param_id,
                "value": f"{value:.6g}",
                "unit": unit,
                "provenance": provenance,
                "source": (
                    "cnt-tid p0 calibration from " + metric_source
                    if provenance == "calibrated"
                    else "computed by cnt-tid p0 from data/parameters/tid_parameters.csv"
                ),
                "derivation": derivation,
                "uncertainty": uncertainty,
            }
        )
    return pd.DataFrame(rows)


def _inverter_metrics(config: SimulationConfig) -> pd.DataFrame:
    """Inverter static metrics at every dose, without writing artifacts."""

    rows = []
    for dose in config.doses_krad:
        n_state = state_at_dose(config.n_device, dose, config.temperature_k)
        p_state = state_at_dose(config.p_device, dose, config.temperature_k)
        result = solve_inverter(n_state, p_state, config.vdd_v, config.inverter_points)
        rows.append(
            {
                "dose_krad": dose,
                "vm_v": result.vm_v,
                "nml_v": result.nml_v,
                "nmh_v": result.nmh_v,
            }
        )
    return pd.DataFrame(rows)


def run_assumption_sweep(
    registry: dict[str, ParameterRecord],
    metrics: pd.DataFrame,
    config: SimulationConfig,
) -> pd.DataFrame:
    """How far do the results move across the stated assumption ranges?

    The oxide permittivity scales Cox and therefore every charge value; the
    n-over-p ratio sets how the unmeasured n-type device degrades.  Both are
    documented assumptions in the registry, so both are swept here instead of
    being hidden inside a single point estimate.
    """

    variants: list[tuple[str, float, float, float]] = [
        ("eps_r", eps_r, eps_r, 1.0) for eps_r in (12.0, 15.0, 20.0)
    ]
    variants += [("n_over_p_ratio", ratio, 15.0, ratio) for ratio in (0.5, 1.0, 1.5)]

    rows = []
    for kind, value, eps_r, ratio in variants:
        trial_registry = dict(registry)
        trial_registry["dev.oxide_relative_permittivity"] = dataclasses.replace(
            registry["dev.oxide_relative_permittivity"], value=f"{eps_r:g}"
        )
        if kind == "n_over_p_ratio":
            trial_registry["assume.n_p_dose_response_ratio"] = dataclasses.replace(
                registry["assume.n_p_dose_response_ratio"], value=f"{ratio:g}"
            )
        trial_calibration = calibrate_from_metrics(
            metrics,
            oxide_thickness_nm=number(registry, "dev.oxide_thickness_nm"),
            oxide_relative_permittivity=eps_r,
            width_um=number(registry, "dev.width_um"),
            length_nm=number(registry, "dev.length_nm"),
            temperature_k=number(registry, "sim.temperature_k"),
        )
        trial_config = build_simulation_config(
            trial_registry,
            vth0_mag_v=trial_calibration.vth0_mag_v,
            mobility_m2_vs=trial_calibration.mobility_m2_vs,
            slope_factor0=trial_calibration.slope_factor0,
            q_ot_c_cm2_per_krad=trial_calibration.q_ot_c_cm2_per_krad,
            q_it_c_cm2_per_krad=trial_calibration.q_it_c_cm2_per_krad,
            mobility_degradation_per_krad=trial_calibration.mobility_degradation_per_krad,
            dose_exponent=trial_calibration.dose_exponent,
            qit_density_slope_c_cm2_per_krad=trial_calibration.qit_density_slope_c_cm2_per_krad,
            qit_anneal_c_cm2=trial_calibration.qit_anneal_c_cm2,
            qit_anneal_dose_krad=trial_calibration.qit_anneal_dose_krad,
        )
        metrics_frame = _inverter_metrics(trial_config)
        for record in metrics_frame.to_dict(orient="records"):
            rows.append(
                {
                    "assumption": kind,
                    "value": value,
                    "is_baseline": bool(
                        value == (15.0 if kind == "eps_r" else 1.0)
                    ),
                    "cox_f_cm2": trial_calibration.cox_f_cm2,
                    "q_tot_at_max_dose": trial_calibration.total_charge_slope_c_cm2_per_krad
                    * max(trial_config.doses_krad) ** trial_calibration.dose_exponent,
                    **record,
                }
            )
    return pd.DataFrame(rows)


def run_p0(
    registry_path: str | Path = DEFAULT_REGISTRY,
    metrics_path: str | Path = DEFAULT_METRICS,
    output_dir: str | Path = "results/p0",
    publish_dir: str | Path | None = None,
) -> P0Result:
    """Run the whole P0 deliverable and write every artifact.

    publish_dir optionally copies the figure set into a tracked directory
    (docs/figures/p0 in this repository), because results/ is not committed.
    """

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    registry_file = Path(registry_path)
    metrics_file = Path(metrics_path)

    registry = load_registry(registry_file)
    metrics = load_digitized_metrics(metrics_file)
    calibration = calibrate_from_metrics(
        metrics,
        oxide_thickness_nm=number(registry, "dev.oxide_thickness_nm"),
        oxide_relative_permittivity=number(registry, "dev.oxide_relative_permittivity"),
        width_um=number(registry, "dev.width_um"),
        length_nm=number(registry, "dev.length_nm"),
        temperature_k=number(registry, "sim.temperature_k"),
    )
    config = build_simulation_config(
        registry,
        vth0_mag_v=calibration.vth0_mag_v,
        mobility_m2_vs=calibration.mobility_m2_vs,
        slope_factor0=calibration.slope_factor0,
        q_ot_c_cm2_per_krad=calibration.q_ot_c_cm2_per_krad,
        q_it_c_cm2_per_krad=calibration.q_it_c_cm2_per_krad,
        mobility_degradation_per_krad=calibration.mobility_degradation_per_krad,
        dose_exponent=calibration.dose_exponent,
        qit_density_slope_c_cm2_per_krad=calibration.qit_density_slope_c_cm2_per_krad,
        qit_anneal_c_cm2=calibration.qit_anneal_c_cm2,
        qit_anneal_dose_krad=calibration.qit_anneal_dose_krad,
    )

    (output / "config_resolved.toml").write_text(dump_config_toml(config), encoding="utf-8")
    calibration_dir = output / "calibration"
    calibration_dir.mkdir(exist_ok=True)
    (calibration_dir / "calibration_report.json").write_text(
        json.dumps(calibration_payload(calibration), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    calibration.residuals.to_csv(calibration_dir / "residuals.csv", index=False)
    calibration.holdout.to_csv(calibration_dir / "holdout.csv", index=False)

    sweep = run_simulation(config, output / "dose_sweep")

    model = _model_metrics(config)
    validation = _validation_frame(calibration, model)
    validation_dir = output / "validation"
    validation_dir.mkdir(exist_ok=True)
    validation.to_csv(validation_dir / "model_vs_literature.csv", index=False)

    sensitivity = run_sensitivity(config, output / "sensitivity", magnitude=0.1)

    second_source = Path(DEFAULT_SECOND_SOURCE)
    cross_frame = pd.concat(
        [
            cui_shift_frame(
                metrics,
                oxide_thickness_nm=number(registry, "dev.oxide_thickness_nm"),
                oxide_relative_permittivity=number(registry, "dev.oxide_relative_permittivity"),
            ),
            load_vt_shift([second_source]),
        ],
        ignore_index=True,
    )
    cross_fits = fit_dose_laws(cross_frame)
    cross_transfer = transfer_error(cross_frame, cross_fits, "cui2023_top_gate")
    cross_dir = output / "cross_source"
    cross_dir.mkdir(exist_ok=True)
    cross_frame.to_csv(cross_dir / "vt_shift_all_sources.csv", index=False)
    cross_fits.to_csv(cross_dir / "dose_law_fits.csv", index=False)
    cross_transfer.to_csv(cross_dir / "transfer_error.csv", index=False)

    robustness = run_assumption_sweep(registry, metrics, config)
    robustness_dir = output / "robustness"
    robustness_dir.mkdir(exist_ok=True)
    robustness.to_csv(robustness_dir / "assumption_sweep.csv", index=False)

    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    plot_structure(registry, calibration, figures / "fig1_structure.png")
    plot_device_validation(validation, calibration.holdout, calibration, figures / "fig2_validation.png")
    plot_inverter(sweep.inverter, sweep.summary, config.vdd_v, figures / "fig3_inverter.png")
    plot_sensitivity(
        sensitivity.table, max(config.doses_krad), figures / "fig4_sensitivity.png"
    )
    plot_assumption_sweep(robustness, figures / "fig5_robustness.png")
    plot_cross_source(cross_frame, cross_fits, figures / "fig6_cross_source.png")

    consistency_mv = float(
        1000.0 * (validation["vth_v_model"] - validation["vth_mag_v_check"]).abs().max()
    )
    consistency_gm = float(
        (validation["gm_s_model"] - validation["gm_s_check"]).abs().max()
        / validation["gm_s_data"].max()
    )

    parameters = _parameters_frame(registry, calibration, config, metrics_file)
    parameters.to_csv(output / "parameters_resolved.csv", index=False)

    last = sweep.summary.iloc[-1]
    key_numbers = {
        "software_version": __version__,
        "config_sha256": config_sha256(config),
        "dose_max_krad": max(config.doses_krad),
        "dose_unit": config.dose_unit,
        "vth0_mag_v": calibration.vth0_mag_v,
        "vth_shift_at_max_dose_v": float(last["p_threshold_shift_v"]),
        "dose_exponent": calibration.dose_exponent,
        "q_it_slope_c_cm2_per_krad_p": calibration.q_it_c_cm2_per_krad,
        "q_ot_slope_c_cm2_per_krad_p": calibration.q_ot_c_cm2_per_krad,
        "q_tot_at_max_dose_c_cm2": calibration.total_charge_slope_c_cm2_per_krad
        * max(config.doses_krad) ** calibration.dose_exponent,
        "mobility_degradation_per_krad": calibration.mobility_degradation_per_krad,
        "qit_density_slope_c_cm2_per_krad_p": calibration.qit_density_slope_c_cm2_per_krad,
        "qit_anneal_c_cm2": calibration.qit_anneal_c_cm2,
        "qit_anneal_dose_krad": calibration.qit_anneal_dose_krad,
        "max_abs_vth_residual_mv": calibration.diagnostics["max_abs_vth_residual_mv"],
        "max_abs_gm_residual_rel": calibration.diagnostics["max_abs_gm_residual_rel"],
        "max_abs_ss_residual_mv": calibration.diagnostics["max_abs_ss_residual_mv"],
        "ss_valley_dose_krad": calibration.diagnostics["ss_valley_dose_krad"],
        "ss_valley_residual_mv": calibration.diagnostics["ss_valley_residual_mv"],
        "model_vs_closed_form_vth_mv": consistency_mv,
        "model_vs_closed_form_gm_rel": consistency_gm,
        "holdout_max_abs_vth_residual_mv": float(
            calibration.holdout["vth_residual_mv"].abs().max()
        ),
        "vm_v_at_zero_dose": float(sweep.summary["vm_v"].iloc[0]),
        "vm_v_at_max_dose": float(last["vm_v"]),
        "nml_v_at_max_dose": float(last["nml_v"]),
        "nmh_v_at_max_dose": float(last["nmh_v"]),
        "inverter_switching_maintained": bool(np.isfinite(float(last["vm_v"]))),
        "cross_source_variants": int(cross_fits.shape[0]),
        "cross_source_usable_fits": int(cross_fits["usable"].sum()),
        "cross_source_exponent_min": float(cross_fits.loc[cross_fits["usable"], "exponent"].min()),
        "cross_source_exponent_max": float(cross_fits.loc[cross_fits["usable"], "exponent"].max()),
        "transfer_error_max_rel_end": float(
            cross_transfer["relative_error_end"].abs().max()
        ),
        "cross_source_regimes": cross_fits["regime"].value_counts().to_dict(),
    }
    (output / "key_numbers.json").write_text(
        json.dumps(key_numbers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    published: dict[str, str] = {}
    if publish_dir is not None:
        published_dir = Path(publish_dir)
        published_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "fig1_structure.png",
            "fig2_validation.png",
            "fig3_inverter.png",
            "fig4_sensitivity.png",
            "fig5_robustness.png",
            "fig6_cross_source.png",
        ):
            (published_dir / name).write_bytes((figures / name).read_bytes())
            published[name] = _sha256(published_dir / name)

    produced = sorted(
        str(path.relative_to(output)).replace("\\", "/")
        for path in output.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "schema_version": "1.0",
        "software_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(),
        "command": "cnt-tid p0",
        "inputs": {
            str(registry_file).replace("\\", "/"): _sha256(registry_file),
            str(metrics_file).replace("\\", "/"): _sha256(metrics_file),
            str(second_source).replace("\\", "/"): _sha256(second_source),
        },
        "outputs": {name: _sha256(output / name) for name in produced},
        "published_figures": published,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return P0Result(output, config, calibration, validation, key_numbers, parameters)
