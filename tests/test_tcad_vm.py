import json
import subprocess
from pathlib import Path

import pytest

from cnt_tid.tcad_vm import DECK_FILES, VmrunSettings, run_tcad_smoke


def _settings(tmp_path: Path) -> VmrunSettings:
    return VmrunSettings(
        vmrun=tmp_path / "vmrun.exe",
        vmx=tmp_path / "Sentaurus.vmx",
        guest_password="not-a-real-password",
    )


def _write_decks(path: Path) -> None:
    path.mkdir()
    for name in DECK_FILES:
        (path / name).write_text(f"deck: {name}\n", encoding="utf-8")


def test_password_is_not_exposed_in_settings_repr(tmp_path: Path) -> None:
    assert "not-a-real-password" not in repr(_settings(tmp_path))


def test_missing_decks_fail_before_vmrun(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing TCAD smoke decks"):
        run_tcad_smoke(_settings(tmp_path), tmp_path / "output", tmp_path / "decks")


def test_smoke_runs_sde_then_sdevice_and_retrieves_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decks = tmp_path / "decks"
    _write_decks(decks)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        assert kwargs["env"]["MSYS_NO_PATHCONV"] == "1"
        if command[7] == "copyFileFromGuestToHost":
            destination = Path(command[10])
            if destination.suffix == ".log":
                destination.write_text(
                    "Curve trace finished.\nSentaurus Device simulation finished\n",
                    encoding="utf-8",
                )
            else:
                destination.write_text("DF-ISE text\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr("cnt_tid.tcad_vm.subprocess.run", fake_run)
    result = run_tcad_smoke(_settings(tmp_path), tmp_path / "output", decks)

    guest_scripts = [command[-1] for command in commands if command[7] == "runProgramInGuest"]
    assert "sde -e -l sde_dvs.cmd" in guest_scripts[1]
    assert "sdevice sdevice_des.cmd" in guest_scripts[2]
    assert len(result.artifacts) == 4
    metadata = json.loads(
        (result.output_dir / "tcad_smoke_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "passed"
    assert metadata["device_under_test"] == "silicon_diode_solver_smoke_not_cntfet"
    assert "not-a-real-password" not in json.dumps(metadata)


def test_vmrun_error_includes_tool_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decks = tmp_path / "decks"
    _write_decks(decks)

    def fail(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="license server unavailable")

    monkeypatch.setattr("cnt_tid.tcad_vm.subprocess.run", fail)
    with pytest.raises(RuntimeError, match="license server unavailable"):
        run_tcad_smoke(_settings(tmp_path), tmp_path / "output", decks)
