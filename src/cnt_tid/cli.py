"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .config import load_config
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
