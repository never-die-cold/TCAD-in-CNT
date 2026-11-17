"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from .calibration import (
    apply_calibration,
    calibrate,
    calibration_report_dict,
    calibration_summary_frame,
    dump_config_toml,
    load_measurements,
)
from .config import load_config
from .matrix import run_matrix
from .sensitivity import PARAMETERS, run_sensitivity
from .tcad_io import export_sdevice_idvg, prepare_literature_idvg
from .tcad_project import render_tcad_project
from .tcad_vm import VmrunSettings, run_tcad_smoke
from .workflow import run_simulation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cnt-tid",
        description="CNTFET total-ionizing-dose compact simulation workflow",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a configured dose sweep")
    run.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
    run.add_argument("--output", type=Path, default=Path("results/baseline"))

    calibrate_cmd = subparsers.add_parser(
        "calibrate", help="fit dose coefficients from measured transfer curves"
    )
    calibrate_cmd.add_argument("--data", type=Path, required=True)
    calibrate_cmd.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
    calibrate_cmd.add_argument("--output", type=Path, default=Path("results/calibration"))

    sensitivity_cmd = subparsers.add_parser(
        "sensitivity", help="one-at-a-time parameter sensitivity of the dose sweep"
    )
    sensitivity_cmd.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
    sensitivity_cmd.add_argument("--output", type=Path, default=Path("results/sensitivity"))
    sensitivity_cmd.add_argument(
        "--magnitude", type=float, default=0.1, help="relative perturbation size in (0, 1)"
    )
    sensitivity_cmd.add_argument(
        "--params",
        nargs="*",
        default=None,
        help=f"parameters to perturb (default: all). Choices: {', '.join(PARAMETERS)}",
    )

    matrix_cmd = subparsers.add_parser(
        "matrix", help="run a traceable dose-by-geometry experiment matrix"
    )
    matrix_cmd.add_argument("--config", type=Path, default=Path("configs/baseline.toml"))
    matrix_cmd.add_argument("--output", type=Path, default=Path("results/matrix"))
    matrix_cmd.add_argument(
        "--oxide-scales",
        type=float,
        nargs="+",
        default=(0.8, 1.0, 1.2),
        help="oxide thickness multipliers (default: 0.8 1.0 1.2)",
    )
    matrix_cmd.add_argument(
        "--length-scales",
        type=float,
        nargs="+",
        default=(0.8, 1.0, 1.2),
        help="gate length multipliers (default: 0.8 1.0 1.2)",
    )

    tcad_cmd = subparsers.add_parser(
        "tcad-smoke", help="run the verified SDE/SDevice smoke deck in a VMware guest"
    )
    tcad_cmd.add_argument("--vmrun", type=Path, default=os.environ.get("TCAD_VMRUN"))
    tcad_cmd.add_argument("--vmx", type=Path, default=os.environ.get("TCAD_VMX"))
    tcad_cmd.add_argument("--output", type=Path, default=Path("results/tcad-smoke"))
    tcad_cmd.add_argument("--deck-dir", type=Path, default=Path("tcad/smoke"))
    tcad_cmd.add_argument(
        "--guest-user", default=os.environ.get("TCAD_GUEST_USER", "tcad")
    )
    tcad_cmd.add_argument(
        "--guest-workdir",
        default=os.environ.get("TCAD_GUEST_WORKDIR", "/home/tcad/STDB/cnt_tid_smoke"),
    )

    prepare_cmd = subparsers.add_parser(
        "tcad-prepare", help="render CNTFET decks after all required values are supplied"
    )
    prepare_cmd.add_argument("--config", type=Path, required=True)
    prepare_cmd.add_argument("--template-dir", type=Path, default=Path("tcad/cntfet/topgate"))
    prepare_cmd.add_argument("--output", type=Path, default=Path("results/tcad/prepared"))

    literature_cmd = subparsers.add_parser(
        "tcad-prepare-data", help="convert verified signed literature curves to magnitudes"
    )
    literature_cmd.add_argument("--input", type=Path, required=True)
    literature_cmd.add_argument("--output", type=Path, required=True)

    export_cmd = subparsers.add_parser(
        "tcad-export", help="convert a text SDevice .plt Id-Vg file to signed CSV"
    )
    export_cmd.add_argument("--plt", type=Path, required=True)
    export_cmd.add_argument("--output", type=Path, required=True)
    export_cmd.add_argument("--gate-contact", default="gate")
    export_cmd.add_argument("--drain-contact", default="drain")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    artifacts = run_simulation(config, args.output)
    final = artifacts.summary.iloc[-1]
    print(f"Run complete: {artifacts.output_dir.resolve()}")
    print(f"Calibration status: {config.calibration_status}")
    print(
        f"At {final['dose_krad']:g} krad: "
        f"VM={final['vm_v']:.4f} V, NML={final['nml_v']:.4f} V, "
        f"NMH={final['nmh_v']:.4f} V"
    )
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    frame = load_measurements(args.data)
    result = calibrate(frame, config)
    fitted = apply_calibration(config, result)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "fitted_config.toml").write_text(
        dump_config_toml(fitted), encoding="utf-8"
    )
    calibration_summary_frame(result).to_csv(
        args.output / "calibration_summary.csv", index=False
    )
    with (args.output / "calibration_report.json").open("w", encoding="utf-8") as handle:
        json.dump(calibration_report_dict(result), handle, indent=2, ensure_ascii=False)
    print(f"Calibration complete: {args.output.resolve()}")
    for fit in (result.n_device, result.p_device):
        print(
            f"[{fit.polarity}] Qot slope={fit.qot_slope_c_cm2_per_krad:.3e} "
            f"C/cm2/krad, Qit slope={fit.qit_slope_c_cm2_per_krad:.3e}, "
            f"mobility degradation={fit.mobility_degradation_per_krad:.3e}/krad"
        )
    if result.n_device.holdout_residuals_v or result.p_device.holdout_residuals_v:
        residuals = [
            abs(item["residual_v"])
            for fit in (result.n_device, result.p_device)
            for item in fit.holdout_residuals_v
        ]
        print(f"Leave-one-dose-out threshold residuals: max {max(residuals):.4f} V")
    print(f"Fitted config written to {args.output / 'fitted_config.toml'}")
    return 0


def _cmd_sensitivity(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    parameters = tuple(args.params) if args.params else tuple(PARAMETERS)
    result = run_sensitivity(config, args.output, magnitude=args.magnitude, parameters=parameters)
    print(f"Sensitivity complete: {result.output_dir.resolve()}")
    top = (
        result.table.dropna(subset=["mean_normalized_sensitivity"])
        .groupby("parameter")["mean_normalized_sensitivity"]
        .apply(lambda values: values.abs().mean())
        .sort_values(ascending=False)
        .head(5)
    )
    print("Top parameters by mean |normalized sensitivity|:")
    for name, value in top.items():
        print(f"  {name}: {value:.4f}")
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = run_matrix(
        config,
        args.output,
        oxide_scales=tuple(args.oxide_scales),
        length_scales=tuple(args.length_scales),
    )
    passed_count = len(result.manifest) - result.failed_count
    print(f"Matrix complete: {result.output_dir.resolve()}")
    print(f"Scenarios: {passed_count} passed, {result.failed_count} failed")
    if result.failed_count:
        print("Inspect matrix_manifest.csv and the per-scenario failure.txt files")
        return 1
    return 0


def _cmd_tcad_smoke(args: argparse.Namespace) -> int:
    if not args.vmrun or not args.vmx:
        raise ValueError("--vmrun and --vmx are required (or set TCAD_VMRUN and TCAD_VMX)")
    password = os.environ.get("TCAD_GUEST_PASSWORD")
    if not password:
        raise ValueError("Set TCAD_GUEST_PASSWORD in the environment; do not put it in TOML")
    settings = VmrunSettings(
        vmrun=args.vmrun,
        vmx=args.vmx,
        guest_password=password,
        guest_user=args.guest_user,
        guest_workdir=args.guest_workdir,
    )
    result = run_tcad_smoke(settings, args.output, args.deck_dir)
    print(f"TCAD smoke passed: {result.output_dir}")
    print("Retrieved SDE/SDevice logs and smoke_des.plt; native TDR files remain in the guest")
    return 0


def _cmd_tcad_prepare(args: argparse.Namespace) -> int:
    result = render_tcad_project(args.config, args.output, args.template_dir)
    print(f"TCAD project prepared (not run): {result.output_dir}")
    print("Review the generated decks, then run SDE and SDevice from SWB")
    return 0


def _cmd_tcad_prepare_data(args: argparse.Namespace) -> int:
    result = prepare_literature_idvg(args.input, args.output)
    print(f"Literature data written: {result.output_path.resolve()}")
    print(f"Rows retained: {result.output_rows}/{result.input_rows}")
    print(f"Positive-VGS rows excluded from compact calibration: {result.dropped_positive_vgs_rows}")
    return 0


def _cmd_tcad_export(args: argparse.Namespace) -> int:
    csv_path, metadata_path = export_sdevice_idvg(
        args.plt, args.output, args.gate_contact, args.drain_contact
    )
    print(f"SDevice CSV written: {csv_path}")
    print(f"Source checksum written: {metadata_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "calibrate":
        return _cmd_calibrate(args)
    if args.command == "sensitivity":
        return _cmd_sensitivity(args)
    if args.command == "matrix":
        return _cmd_matrix(args)
    if args.command == "tcad-smoke":
        return _cmd_tcad_smoke(args)
    if args.command == "tcad-prepare":
        return _cmd_tcad_prepare(args)
    if args.command == "tcad-prepare-data":
        return _cmd_tcad_prepare_data(args)
    if args.command == "tcad-export":
        return _cmd_tcad_export(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
