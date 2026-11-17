"""Run the verified Sentaurus smoke deck through VMware vmrun."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DECK_FILES = ("sde_dvs.cmd", "sdevice_des.cmd")
SMOKE_ARTIFACTS = (
    "sde_stdout.log",
    "sdevice_stdout.log",
    "smoke_des.log",
    "smoke_des.plt",
)


@dataclass(frozen=True)
class VmrunSettings:
    vmrun: Path
    vmx: Path
    guest_password: str = field(repr=False)
    guest_user: str = "tcad"
    guest_workdir: str = "/home/tcad/STDB/cnt_tid_smoke"


@dataclass(frozen=True)
class TcadSmokeResult:
    output_dir: Path
    artifacts: tuple[Path, ...]


def _vmrun(settings: VmrunSettings, *arguments: str) -> None:
    command = [
        str(settings.vmrun),
        "-T",
        "ws",
        "-gu",
        settings.guest_user,
        "-gp",
        settings.guest_password,
        *arguments,
    ]
    environment = os.environ.copy()
    environment["MSYS_NO_PATHCONV"] = "1"
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=environment,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"vmrun {arguments[0]} failed with exit code {completed.returncode}: "
            f"{completed.stdout.strip()}"
        )


def _run_guest(settings: VmrunSettings, script: str) -> None:
    _vmrun(
        settings,
        "runProgramInGuest",
        str(settings.vmx),
        "/bin/bash",
        "-lc",
        script,
    )


def _copy_to_guest(settings: VmrunSettings, source: Path, guest_name: str) -> None:
    _vmrun(
        settings,
        "copyFileFromHostToGuest",
        str(settings.vmx),
        str(source),
        f"{settings.guest_workdir}/{guest_name}",
    )


def _copy_from_guest(settings: VmrunSettings, guest_name: str, destination: Path) -> None:
    _vmrun(
        settings,
        "copyFileFromGuestToHost",
        str(settings.vmx),
        f"{settings.guest_workdir}/{guest_name}",
        str(destination),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tcad_smoke(
    settings: VmrunSettings,
    output_dir: str | Path,
    deck_dir: str | Path = Path("tcad/smoke"),
) -> TcadSmokeResult:
    """Execute SDE and SDevice in the guest and retrieve convergence artifacts."""

    decks = Path(deck_dir).resolve()
    deck_paths = [decks / name for name in DECK_FILES]
    missing = [str(path) for path in deck_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing TCAD smoke decks: {missing}")
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    workdir = shlex.quote(settings.guest_workdir)

    _run_guest(settings, f"mkdir -p {workdir}")
    for path in deck_paths:
        _copy_to_guest(settings, path, path.name)
    _run_guest(
        settings,
        f"cd {workdir} && sde -e -l sde_dvs.cmd > sde_stdout.log 2>&1",
    )
    _run_guest(
        settings,
        f"cd {workdir} && sdevice sdevice_des.cmd > sdevice_stdout.log 2>&1",
    )

    artifacts = []
    for name in SMOKE_ARTIFACTS:
        target = destination / name
        _copy_from_guest(settings, name, target)
        artifacts.append(target)
    log = (destination / "smoke_des.log").read_text(encoding="utf-8", errors="replace")
    required_markers = ("Curve trace finished.", "Sentaurus Device simulation finished")
    if not all(marker in log for marker in required_markers):
        raise RuntimeError("SDevice output is incomplete; inspect the retrieved logs")

    metadata = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "status": "passed",
        "validated_sentaurus_version": "W-2024.09",
        "device_under_test": "silicon_diode_solver_smoke_not_cntfet",
        "deck_sha256": {path.name: _sha256(path) for path in deck_paths},
        "artifacts": list(SMOKE_ARTIFACTS),
        "native_tdr_location": settings.guest_workdir,
    }
    (destination / "tcad_smoke_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return TcadSmokeResult(destination, tuple(artifacts))
