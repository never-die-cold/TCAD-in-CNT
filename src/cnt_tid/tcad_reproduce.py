"""Reproduce the calibrated CNTFET TCAD matrices and their audit manifest."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

from .config import load_config
from .device import ELEMENTARY_CHARGE_C, drain_current, state_at_dose
from .tcad_alignment import align_zero_dose, extract_metrics, load_tcad_idvg
from .tcad_io import export_sdevice_idvg
from .tcad_project import render_tcad_project
from .tcad_vm import (
    VmrunSettings,
    _copy_from_guest,
    _copy_to_guest,
    _run_guest,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DOSES_KRAD = (0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0)
BASELINE_DIT_CM2EV = 2.1e13
COMPLETION_MARKERS = ("Curve trace finished.", "Sentaurus Device simulation finished")


@dataclass(frozen=True)
class DoseInput:
    dose_krad: float
    fixed_charge_cm2: float
    interface_dit_cm2ev: float


@dataclass(frozen=True)
class CaseResult:
    name: str
    directory: Path
    guest_workdir: str
    idvg_csv: Path


@dataclass(frozen=True)
class TcadReproductionResult:
    output_dir: Path
    manifest_path: Path
    verification_path: Path
    reference_comparisons: dict[str, Any]
    final_metrics: pd.DataFrame


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dose_inputs(compact_config_path: str | Path) -> dict[float, DoseInput]:
    config = load_config(compact_config_path)
    inputs = {}
    for dose in DOSES_KRAD:
        state = state_at_dose(config.p_device, dose)
        total_charge = state.qot_c_cm2 + state.qit_c_cm2
        inputs[dose] = DoseInput(
            dose_krad=dose,
            fixed_charge_cm2=total_charge / ELEMENTARY_CHARGE_C,
            interface_dit_cm2ev=(
                BASELINE_DIT_CM2EV + state.qit_density_net_c_cm2 / ELEMENTARY_CHARGE_C
            ),
        )
    return inputs


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, float):
        return format(value, ".17g")
    return str(value)


def set_toml_value(text: str, section: str, key: str, value: Any) -> str:
    lines = text.splitlines()
    current_section = ""
    replaced = False
    for index, line in enumerate(lines):
        section_match = re.match(r"^\s*\[([^]]+)]\s*$", line)
        if section_match:
            current_section = section_match.group(1)
        if current_section == section and re.match(rf"^{re.escape(key)}\s*=", line):
            lines[index] = f"{key} = {_toml_value(value)}"
            replaced = True
            break
    if not replaced:
        raise ValueError(f"TOML key not found: [{section}] {key}")
    return "\n".join(lines) + "\n"


def variant_config(
    base_text: str,
    dose_input: DoseInput,
    model: str,
    mesh_scale: float = 1.0,
) -> str:
    if dose_input.dose_krad == 0.0 and model == "zero_dose" and mesh_scale == 1.0:
        return base_text
    text = base_text
    dose = dose_input.dose_krad
    if model == "fixed_charge":
        status = "tcad_tid_fixed_charge_from_compact"
        dit = BASELINE_DIT_CM2EV
    elif model == "final":
        status = "tcad_tid_fixed_charge_and_interface_constant_mobility"
        dit = dose_input.interface_dit_cm2ev
    elif model == "zero_dose":
        status = "tcad_zero_dose_aligned_compact_metrics"
        dit = BASELINE_DIT_CM2EV
    else:
        raise ValueError(f"Unknown TCAD model: {model}")
    text = set_toml_value(text, "", "calibration_status", status)
    text = set_toml_value(text, "run", "name", f"{model}_{dose:g}_krad_si")
    text = set_toml_value(text, "run", "dose_krad", float(dose))
    text = set_toml_value(text, "run", "fixed_charge_cm2", dose_input.fixed_charge_cm2)
    text = set_toml_value(text, "run", "interface_dit_cm2ev", dit)
    if mesh_scale != 1.0:
        values = tomllib.loads(base_text)["mesh"]
        for key, value in values.items():
            text = set_toml_value(text, "mesh", key, float(value) * mesh_scale)
    return text


def _runtime_decks(directory: Path) -> tuple[Path, Path]:
    sde = directory / "sde_run.cmd"
    sde.write_text(
        (directory / "sde_dvs.cmd").read_text(encoding="utf-8").replace("n@node@", "n1"),
        encoding="utf-8",
    )
    replacements = {
        "@tdr@": "n1_msh.tdr",
        "@plot@": "run_des.plt",
        "@tdrdat@": "run_des.tdr",
        "@log@": "run_des.log",
    }
    text = (directory / "sdevice_des.cmd").read_text(encoding="utf-8")
    for token, value in replacements.items():
        text = text.replace(token, value)
    sdevice = directory / "sdevice_run.cmd"
    sdevice.write_text(text, encoding="utf-8")
    return sde, sdevice


def _run_case(
    settings: VmrunSettings,
    output_root: Path,
    template_dir: Path,
    name: str,
    config_text: str,
    run_sde: bool,
    grid_source: str | None = None,
) -> CaseResult:
    directory = output_root / name
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")
    render_tcad_project(config_path, directory, template_dir)
    sde_run, sdevice_run = _runtime_decks(directory)
    guest_workdir = f"{settings.guest_workdir}/{name}"
    case_settings = replace(settings, guest_workdir=guest_workdir)
    _run_guest(case_settings, f"mkdir -p {guest_workdir}")
    if run_sde:
        for path in (sde_run, directory / "datexcodes.txt"):
            _copy_to_guest(case_settings, path, path.name)
        try:
            _run_guest(
                case_settings,
                f"cd {guest_workdir} && sde -e -l sde_run.cmd > sde_stdout.log 2>&1",
            )
        finally:
            _copy_from_guest(case_settings, "sde_stdout.log", directory / "sde_stdout.log")
        sde_log = (directory / "sde_stdout.log").read_text(encoding="utf-8", errors="replace")
        if "Meshing successful" not in sde_log:
            raise RuntimeError(f"SDE did not complete for {name}; inspect {directory}")
    else:
        if grid_source is None:
            raise ValueError(f"Grid source is required when SDE is skipped for {name}")
        _run_guest(
            case_settings,
            f"cp {grid_source}/n1_msh.tdr {guest_workdir}/n1_msh.tdr",
        )
    for path in (sdevice_run, directory / "sdevice.par", directory / "datexcodes.txt"):
        _copy_to_guest(case_settings, path, path.name)
    try:
        _run_guest(
            case_settings,
            f"cd {guest_workdir} && sdevice sdevice_run.cmd > sdevice_stdout.log 2>&1",
        )
    finally:
        for artifact in ("sdevice_stdout.log", "run_des.log", "run_des.plt"):
            with suppress(RuntimeError):
                _copy_from_guest(case_settings, artifact, directory / artifact)
    log_path = directory / "run_des.log"
    log = log_path.read_text(encoding="utf-8", errors="replace")
    if not all(marker in log for marker in COMPLETION_MARKERS):
        raise RuntimeError(f"SDevice did not complete for {name}; inspect {log_path}")
    export_sdevice_idvg(directory / "run_des.plt", directory / "idvg_signed.csv")
    return CaseResult(name, directory, guest_workdir, directory / "idvg_signed.csv")


def _literature_metrics(path: Path, dose: float) -> dict[str, float]:
    frame = pd.read_csv(path)
    return {
        metric: float(
            frame.loc[(frame.dose_value == dose) & (frame.metric == metric), "value"].iloc[0]
        )
        for metric in ("vth_v", "gm_max_s", "ss_mv_dec")
    }


def _analyze_matrix(
    cases: dict[float, CaseResult],
    inputs: dict[float, DoseInput],
    compact_config_path: Path,
    literature_path: Path,
    output_dir: Path,
    final: bool,
    fixed_metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    compact = load_config(compact_config_path)
    fixed_index = fixed_metrics.set_index("dose_krad_si") if final else None
    rows = []
    fig, axis = plt.subplots(figsize=(7.4, 5.0), constrained_layout=True)
    colors = plt.cm.viridis(np.linspace(0, 0.9, len(DOSES_KRAD)))
    for dose, color in zip(DOSES_KRAD, colors, strict=True):
        case = cases[dose]
        vsg, ids, _, _ = load_tcad_idvg(case.idvg_csv)
        tcad = extract_metrics(vsg, ids)
        state = state_at_dose(compact.p_device, dose)
        compact_ids = drain_current(state, vsg, 0.1)
        model = extract_metrics(vsg, compact_ids)
        literature = _literature_metrics(literature_path, dose)
        log = (case.directory / "run_des.log").read_text(encoding="utf-8", errors="replace")
        row: dict[str, Any] = {
            "dose_krad_si": dose,
            "fixed_charge_cm2": inputs[dose].fixed_charge_cm2,
        }
        if final:
            row["interface_dit_cm2ev"] = inputs[dose].interface_dit_cm2ev
            row["mobility_scale"] = 1.0
        row.update(
            {
                "converged": all(marker in log for marker in COMPLETION_MARKERS),
                "tcad_vth_mag_v": tcad.vth_mag_v,
                "compact_vth_mag_v": model.vth_mag_v,
                "literature_vth_mag_v": abs(literature["vth_v"]),
                "tcad_gm_max_s": tcad.gm_max_s,
                "compact_gm_max_s": model.gm_max_s,
                "literature_gm_max_s": literature["gm_max_s"],
                "tcad_ss_mv_dec": tcad.ss_mv_dec,
                "compact_ss_mv_dec": model.ss_mv_dec,
                "literature_ss_mv_dec": literature["ss_mv_dec"],
            }
        )
        if final:
            for metric in ("vth_mag_v", "gm_max_s", "ss_mv_dec"):
                row[f"fixed_charge_tcad_{metric}"] = fixed_index.loc[
                    dose, f"tcad_{metric}"
                ]
        rows.append(row)
        axis.semilogy(vsg, ids, "o", ms=3, color=color, label=f"TCAD {dose:g}")
        axis.semilogy(vsg, compact_ids, "-", lw=1.1, color=color, alpha=0.7)
    frame = pd.DataFrame(rows)
    prefixes = ["tcad", "compact", "literature"] + (["fixed_charge_tcad"] if final else [])
    for prefix in prefixes:
        baseline = frame.loc[frame.dose_krad_si == 0, f"{prefix}_vth_mag_v"].iloc[0]
        frame[f"{prefix}_delta_vth_v"] = frame[f"{prefix}_vth_mag_v"] - baseline
    for prefix in (["tcad", "fixed_charge_tcad"] if final else ["tcad"]):
        for metric in ("vth_mag_v", "gm_max_s", "ss_mv_dec"):
            frame[f"{prefix}_{metric}_deviation_from_literature_rel"] = (
                frame[f"{prefix}_{metric}"] - frame[f"literature_{metric}"]
            ).abs() / frame[f"literature_{metric}"].abs()
    frame.to_csv(output_dir / "metrics.csv", index=False)
    axis.set(
        xlabel="|Vsg| (V)",
        ylabel="|Id| (A)",
        title=f"{'Final joint' if final else 'Fixed-charge'} TCAD matrix vs compact model",
    )
    axis.grid(True, which="both", alpha=0.2)
    axis.legend(title="Dose (krad(Si))", fontsize=7, ncol=2)
    fig.savefig(output_dir / "idvg_overlay.png", dpi=150)
    plt.close(fig)
    _plot_metric_comparison(frame, output_dir / "metrics.png", final)
    return frame


def _plot_metric_comparison(frame: pd.DataFrame, path: Path, final: bool) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), constrained_layout=True)
    for axis, metric, ylabel in zip(
        axes,
        ("delta_vth_v", "gm_max_s", "ss_mv_dec"),
        ("Δ|Vth| (V)", "Gm max (S)", "SS (mV/dec)"),
        strict=True,
    ):
        prefixes = [("tcad", "TCAD", "o"), ("compact", "compact", "-")]
        if final:
            prefixes.insert(0, ("fixed_charge_tcad", "fixed charge only", "x"))
        prefixes.append(("literature", "literature", "s"))
        for prefix, label, marker in prefixes:
            if metric == "gm_max_s":
                axis.semilogy(
                    frame.dose_krad_si, frame[f"{prefix}_{metric}"], marker, ms=4, lw=1.1, label=label
                )
            else:
                axis.plot(
                    frame.dose_krad_si, frame[f"{prefix}_{metric}"], marker, ms=4, lw=1.1, label=label
                )
        axis.set(xlabel="Dose (krad(Si))", ylabel=ylabel)
        axis.grid(True, which="both", alpha=0.2)
    axes[0].legend(fontsize=7)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _mesh_summary(
    output_root: Path,
    zero: CaseResult,
    mesh_cases: dict[str, CaseResult],
) -> pd.DataFrame:
    entries = [("coarse", mesh_cases["coarse"]), ("baseline", zero), ("fine", mesh_cases["fine"])]
    rows = []
    for label, case in entries:
        with (case.directory / "config.toml").open("rb") as handle:
            config = tomllib.load(handle)
        verdict = json.loads((case.directory / "alignment_verdict.json").read_text(encoding="utf-8"))
        log = (case.directory / "sde_stdout.log").read_text(encoding="utf-8", errors="replace")
        mesh = re.search(r"The final mesh has:\s*(\d+) points\.\s*(\d+) elements", log)
        if mesh is None:
            raise ValueError(f"Mesh counts missing from {case.directory / 'sde_stdout.log'}")
        rows.append(
            {
                "mesh": label,
                **{key: float(value) for key, value in config["mesh"].items()},
                "grid_points": int(mesh.group(1)),
                "elements": int(mesh.group(2)),
                "ss_mv_dec": verdict["tcad"]["ss_mv_dec"],
                "gm_max_s": verdict["tcad"]["gm_max_s"],
                "vth_mag_v": verdict["tcad"]["vth_mag_v"],
                "alignment_verdict": verdict["verdict"],
            }
        )
    frame = pd.DataFrame(rows)
    for metric in ("ss_mv_dec", "gm_max_s", "vth_mag_v"):
        baseline = frame.loc[frame.mesh == "baseline", metric].iloc[0]
        frame[f"{metric}_deviation_from_baseline"] = (
            (frame[metric] - baseline).abs() / baseline
        )
    output = output_root / "mesh_convergence"
    output.mkdir(exist_ok=True)
    frame.to_csv(output / "mesh_convergence.csv", index=False)
    payload = {
        "alignment_gate_passed_all_meshes": bool((frame.alignment_verdict == "pass").all()),
        "max_relative_change_from_baseline": {
            metric: float(frame[f"{metric}_deviation_from_baseline"].max())
            for metric in ("ss_mv_dec", "gm_max_s", "vth_mag_v")
        },
    }
    (output / "mesh_convergence_verdict.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return frame


def _compare_reference(output_root: Path, reference: Path) -> dict[str, Any]:
    pairs = {
        "zero_dose/alignment_metrics.csv": "zero_dose/alignment_metrics.csv",
        "mesh_convergence/mesh_convergence.csv": "mesh_convergence/mesh_convergence.csv",
        "fixed_charge/metrics.csv": "tid/tid_metrics.csv",
        "final/metrics.csv": "tid_degraded/tid_degraded_metrics.csv",
    }
    comparisons = {}
    for produced_name, reference_name in pairs.items():
        produced = output_root / produced_name
        expected = reference / reference_name
        record: dict[str, Any] = {
            "produced": str(produced),
            "reference": str(expected),
            "reference_available": expected.is_file(),
        }
        if expected.is_file():
            produced_hash = sha256_file(produced)
            reference_hash = sha256_file(expected)
            left = pd.read_csv(produced)
            right = pd.read_csv(expected)
            numeric_match = left.columns.equals(right.columns) and left.shape == right.shape
            max_relative_difference = None
            if numeric_match:
                max_relative_difference = 0.0
                for column in left.columns:
                    if pd.api.types.is_numeric_dtype(left[column]):
                        denominator = np.maximum(np.abs(right[column].to_numpy(dtype=float)), 1e-300)
                        difference = np.abs(left[column].to_numpy(dtype=float) - right[column].to_numpy(dtype=float)) / denominator
                        max_relative_difference = max(max_relative_difference, float(np.max(difference)))
                    else:
                        numeric_match = left[column].equals(right[column])
                        if not numeric_match:
                            break
                numeric_match = numeric_match and max_relative_difference <= 1e-10
            record.update(
                {
                    "produced_sha256": produced_hash,
                    "reference_sha256": reference_hash,
                    "sha256_match": produced_hash == reference_hash,
                    "numeric_match_rtol_1e-10": numeric_match,
                    "max_relative_difference": max_relative_difference,
                }
            )
        comparisons[produced_name] = record
    return comparisons


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _write_manifest(
    output_root: Path,
    input_files: list[Path],
    command: str,
    reference_comparisons: dict[str, Any],
    final_metrics: pd.DataFrame,
    mesh_metrics: pd.DataFrame,
) -> tuple[Path, Path]:
    output_files = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and not path.name.startswith("tcad_manifest")
    )
    deviations = [
        f"tcad_{metric}_deviation_from_literature_rel"
        for metric in ("vth_mag_v", "gm_max_s", "ss_mv_dec")
    ]
    payload = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "command": command,
        "input_files": {
            _relative(path): sha256_file(path) for path in sorted(input_files)
        },
        "output_files": {
            _relative(path): sha256_file(path) for path in output_files
        },
        "reference_comparisons": reference_comparisons,
        "validation": {
            "all_final_doses_converged": bool(final_metrics.converged.all()),
            "all_final_metric_deviations_below_20pct": bool(
                (final_metrics[deviations].max() < 0.2).all()
            ),
            "final_max_deviation_from_literature_rel": {
                metric: float(final_metrics[f"tcad_{metric}_deviation_from_literature_rel"].max())
                for metric in ("vth_mag_v", "gm_max_s", "ss_mv_dec")
            },
            "all_mesh_alignments_passed": bool(
                (mesh_metrics.alignment_verdict == "pass").all()
            ),
        },
    }
    manifest = output_root / "tcad_manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verification = {
        "manifest": _relative(manifest),
        "checked_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            path: sha256_file(path) == digest for path, digest in payload["input_files"].items()
        },
        "outputs": {
            path: sha256_file(path) == digest for path, digest in payload["output_files"].items()
        },
    }
    verification["all_hashes_match"] = all(verification["inputs"].values()) and all(
        verification["outputs"].values()
    )
    verification_path = output_root / "tcad_manifest_verification.json"
    verification_path.write_text(
        json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_root / "tcad_manifest.sha256").write_text(
        f"{sha256_file(manifest)}  {manifest.name}\n", encoding="ascii"
    )
    return manifest, verification_path


def run_tcad_reproduction(
    settings: VmrunSettings,
    output_dir: str | Path,
    *,
    base_config: str | Path = Path("configs/tcad/cntfet_topgate.toml"),
    compact_config: str | Path = Path("configs/p0/cntfet_tid_p0.toml"),
    literature: str | Path = Path("data/literature/cui2023_topgate/fig3_metrics_digitized.csv"),
    template_dir: str | Path = Path("tcad/cntfet/topgate"),
    reference: str | Path = Path("results/tcad"),
) -> TcadReproductionResult:
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    base_path = Path(base_config).resolve()
    compact_path = Path(compact_config).resolve()
    literature_path = Path(literature).resolve()
    templates = Path(template_dir).resolve()
    base_text = base_path.read_text(encoding="utf-8")
    inputs = dose_inputs(compact_path)
    zero = _run_case(
        settings, output_root, templates, "zero_dose", base_text, run_sde=True
    )
    align_zero_dose(zero.idvg_csv, compact_path, output_dir=zero.directory)
    mesh_cases = {}
    for label, scale in (("coarse", 2.0), ("fine", 0.5)):
        text = variant_config(base_text, inputs[0.0], "zero_dose", mesh_scale=scale)
        case = _run_case(
            settings,
            output_root,
            templates,
            f"mesh_convergence/{label}",
            text,
            run_sde=True,
        )
        align_zero_dose(case.idvg_csv, compact_path, output_dir=case.directory)
        mesh_cases[label] = case
    mesh_metrics = _mesh_summary(output_root, zero, mesh_cases)
    fixed_cases = {0.0: zero}
    final_cases = {0.0: zero}
    for dose in DOSES_KRAD[1:]:
        label = f"dose_{int(dose):04d}"
        fixed_text = variant_config(base_text, inputs[dose], "fixed_charge")
        fixed_cases[dose] = _run_case(
            settings,
            output_root,
            templates,
            f"fixed_charge/{label}",
            fixed_text,
            run_sde=False,
            grid_source=zero.guest_workdir,
        )
        final_text = variant_config(base_text, inputs[dose], "final")
        final_cases[dose] = _run_case(
            settings,
            output_root,
            templates,
            f"final/{label}",
            final_text,
            run_sde=False,
            grid_source=zero.guest_workdir,
        )
    fixed_metrics = _analyze_matrix(
        fixed_cases,
        inputs,
        compact_path,
        literature_path,
        output_root / "fixed_charge",
        final=False,
    )
    final_metrics = _analyze_matrix(
        final_cases,
        inputs,
        compact_path,
        literature_path,
        output_root / "final",
        final=True,
        fixed_metrics=fixed_metrics,
    )
    reference_comparisons = _compare_reference(output_root, Path(reference).resolve())
    input_files = [base_path, compact_path, literature_path]
    input_files.extend(path for path in templates.iterdir() if path.is_file())
    command = f"cnt-tid tcad-reproduce --output {_relative(output_root)}"
    manifest, verification = _write_manifest(
        output_root,
        input_files,
        command,
        reference_comparisons,
        final_metrics,
        mesh_metrics,
    )
    return TcadReproductionResult(
        output_root, manifest, verification, reference_comparisons, final_metrics
    )
