"""Render traceable Sentaurus CNTFET templates from an explicit user configuration."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PLACEHOLDER = re.compile(r"@([A-Z0-9_]+)@")


@dataclass(frozen=True)
class TcadProjectResult:
    output_dir: Path
    generated_files: tuple[Path, ...]


def _flatten(values: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened = {}
    for key, value in values.items():
        name = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            flattened.update(_flatten(value, name))
        else:
            flattened[name.upper()] = value
    return flattened


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_tcad_project(
    config_path: str | Path,
    output_dir: str | Path,
    template_dir: str | Path = Path("tcad/cntfet/topgate"),
) -> TcadProjectResult:
    """Generate deck files only after every required value has been supplied."""

    config = Path(config_path).resolve()
    templates = Path(template_dir).resolve()
    with config.open("rb") as handle:
        raw = tomllib.load(handle)
    values = _flatten(raw)
    missing_values = sorted(
        key
        for key, value in values.items()
        if isinstance(value, str) and value.startswith("REQUIRED")
    )
    if missing_values:
        raise ValueError(
            "TCAD configuration still has REQUIRED values: " + ", ".join(missing_values)
        )
    source_data = Path(str(raw["source_data"])).resolve()
    if not source_data.is_dir():
        raise FileNotFoundError(f"TCAD source_data directory does not exist: {source_data}")

    rendered: dict[str, str] = {}
    plain_files: dict[str, bytes] = {}
    for source in sorted(templates.iterdir()):
        if not source.is_file():
            continue
        if source.suffix == ".in":
            text = source.read_text(encoding="utf-8")
            placeholders = set(PLACEHOLDER.findall(text))
            unknown = sorted(placeholders - values.keys())
            if unknown:
                raise ValueError(
                    f"Template {source.name} has no configured values for: {unknown}"
                )
            rendered[source.stem] = PLACEHOLDER.sub(
                lambda match: str(values[match.group(1)]), text
            )
        else:
            plain_files[source.name] = source.read_bytes()
    if not rendered:
        raise ValueError(f"No .in templates found in {templates}")

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    generated = []
    for name, text in rendered.items():
        target = destination / name
        target.write_text(text, encoding="utf-8")
        generated.append(target)
    for name, content in plain_files.items():
        target = destination / name
        target.write_bytes(content)
        generated.append(target)

    metadata = {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(),
        "status": "prepared_not_run",
        "calibration_status": raw["calibration_status"],
        "source_data": raw["source_data"],
        "config_sha256": _sha256(config),
        "source_files_sha256": {
            str(path.relative_to(source_data)): _sha256(path)
            for path in sorted(source_data.rglob("*"))
            if path.is_file()
        },
        "template_sha256": {
            path.name: _sha256(path)
            for path in sorted(templates.iterdir())
            if path.is_file()
        },
        "generated_files": sorted(path.name for path in generated),
    }
    (destination / "tcad_project_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return TcadProjectResult(destination, tuple(generated))
