"""Tests for the one-command deliverable rebuild."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from cnt_tid.deliverable import run_deliverable

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "parameters" / "tid_parameters.csv"
METRICS = ROOT / "data" / "literature" / "cui2023_topgate" / "fig3_metrics_digitized.csv"


def _fast_registry(tmp_path: Path) -> Path:
    with REGISTRY.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["param_id"] == "sim.transfer_points":
            row["value"] = "101"
        if row["param_id"] == "sim.inverter_points":
            row["value"] = "201"
    destination = tmp_path / "registry.csv"
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return destination


def test_deliverable_rebuilds_every_stage(tmp_path: Path):
    destination = run_deliverable(
        _fast_registry(tmp_path),
        METRICS,
        tmp_path / "deliverable",
        draws=4,
        seed=5,
        publish_dir=None,
    )
    manifest = json.loads(
        (destination / "deliverable_manifest.json").read_text(encoding="utf-8")
    )
    stages = manifest["stages"]
    assert stages["p0"]["key_numbers"]["dose_exponent"] > 0
    assert stages["monte_carlo"]["draws_completed"] == 4
    assert stages["prediction"]["variants"] == 8
    assert stages["annealing"]["fraction"] == pytest.approx(0.3)
    # Every stage manifest hash must match the file it points at.
    for stage in ("p0", "monte_carlo", "annealing"):
        entry = stages[stage]
        pointer = entry.get("manifest") or entry.get("summary") or entry.get("metadata")
        digest = hashlib.sha256((destination / pointer).read_bytes()).hexdigest()
        assert entry["sha256"] == digest
    assert (destination / "p0" / "figures" / "fig11_device_family.png").exists()
    assert (destination / "mc" / "mc_scan.csv").exists()
    assert (destination / "anneal" / "annealing_scan.csv").exists()
