import json
import tomllib
from pathlib import Path

import pandas as pd

from cnt_tid.cli import build_parser
from cnt_tid.tcad_reproduce import (
    _runtime_decks,
    _write_manifest,
    dose_inputs,
    variant_config,
)


def test_dose_variants_preserve_final_model_and_mesh_scaling() -> None:
    base = Path("configs/tcad/cntfet_topgate.toml").read_text(encoding="utf-8")
    inputs = dose_inputs("configs/p0/cntfet_tid_p0.toml")

    fixed = tomllib.loads(variant_config(base, inputs[200.0], "fixed_charge"))
    final = tomllib.loads(variant_config(base, inputs[3000.0], "final"))
    coarse = tomllib.loads(variant_config(base, inputs[0.0], "zero_dose", mesh_scale=2.0))

    assert fixed["run"]["fixed_charge_cm2"] == inputs[200.0].fixed_charge_cm2
    assert fixed["run"]["interface_dit_cm2ev"] == 2.1e13
    assert final["run"]["interface_dit_cm2ev"] == inputs[3000.0].interface_dit_cm2ev
    assert final["material"]["hole_mobility_cm2_vs"] == 21.4
    assert final["calibration_status"] == (
        "tcad_tid_fixed_charge_and_interface_constant_mobility"
    )
    assert coarse["mesh"]["global_max_um"] == 1.0
    assert coarse["mesh"]["channel_min_um"] == 0.002


def test_runtime_decks_replace_all_swb_tokens(tmp_path: Path) -> None:
    (tmp_path / "sde_dvs.cmd").write_text('(sde:build-mesh "n@node@")', encoding="utf-8")
    (tmp_path / "sdevice_des.cmd").write_text(
        'Grid="@tdr@" Current="@plot@" Plot="@tdrdat@" Output="@log@"',
        encoding="utf-8",
    )

    sde, sdevice = _runtime_decks(tmp_path)

    assert "n1" in sde.read_text(encoding="utf-8")
    runtime = sdevice.read_text(encoding="utf-8")
    assert "n1_msh.tdr" in runtime
    assert "run_des.plt" in runtime
    assert "@tdr@" not in runtime
    assert "@plot@" not in runtime


def test_manifest_records_and_verifies_input_and_output_hashes(tmp_path: Path) -> None:
    source = tmp_path / "input.toml"
    source.write_text("value = 1\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "curve.csv").write_text("dose,id\n0,1\n", encoding="utf-8")
    final = pd.DataFrame(
        {
            "converged": [True],
            "tcad_vth_mag_v_deviation_from_literature_rel": [0.1],
            "tcad_gm_max_s_deviation_from_literature_rel": [0.1],
            "tcad_ss_mv_dec_deviation_from_literature_rel": [0.1],
        }
    )
    mesh = pd.DataFrame({"alignment_verdict": ["pass"]})

    manifest, verification_path = _write_manifest(
        output, [source], "cnt-tid tcad-reproduce --output results/test", {}, final, mesh
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    assert payload["command"].startswith("cnt-tid tcad-reproduce")
    assert payload["validation"]["all_final_metric_deviations_below_20pct"]
    assert verification["all_hashes_match"]
    assert all(verification["inputs"].values())
    assert all(verification["outputs"].values())


def test_tcad_reproduce_cli_is_registered() -> None:
    args = build_parser().parse_args(["tcad-reproduce", "--output", "results/test"])
    assert args.command == "tcad-reproduce"
    assert args.output == Path("results/test")
