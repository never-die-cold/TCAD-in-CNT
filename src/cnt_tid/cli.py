"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
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
from .sensitivity import PARAMETERS, run_sensitivity
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "calibrate":
        return _cmd_calibrate(args)
    if args.command == "sensitivity":
        return _cmd_sensitivity(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
