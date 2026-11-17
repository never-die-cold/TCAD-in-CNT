"""Traceable parameter registry for the P0 CNTFET TID deliverable.

Every number that reaches a simulation config must come from a row in
`data/parameters/tid_parameters.csv`: reported by the paper, digitized from
a figure, derived by a stated formula, an explicit engineering assumption, or
a compact-model convention.  Nothing enters by accident: the builder refuses
unknown ids, missing rows and assumptions without an uncertainty.

The registry is deliberately a plain CSV so that it diffs, reviews and
survives outside the Python code.  Calibrated quantities are *not* stored
here; they are recomputed by the pipeline from the digitized figure data and
written to `results/p0/parameters_resolved.csv` together with their
provenance chain.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import DeviceConfig, SimulationConfig

PROVENANCE_CLASSES = (
    "reported",      # explicitly stated in the source document
    "digitized",     # read from a figure, reproduced by scripts/
    "derived",       # computed from other registered parameters
    "assumed",       # engineering assumption, always with an uncertainty
    "convention",    # fixed by the compact model definition
    "calibrated",    # fitted by the pipeline, written to the resolved table
)

#: Parameters whose value is text rather than a number.
STRING_IDS = frozenset({"sim.name", "sim.dose_unit", "sim.calibration_status"})

#: Ids the builder needs.  Missing ids are a hard error, not a default value.
REQUIRED_IDS = (
    "sim.name",
    "sim.vdd_v",
    "sim.temperature_k",
    "sim.dose_unit",
    "sim.doses_krad",
    "sim.transfer_points",
    "sim.inverter_points",
    "sim.ro_stages",
    "sim.calibration_status",
    "dev.width_um",
    "dev.length_nm",
    "dev.oxide_thickness_nm",
    "dev.oxide_relative_permittivity",
    "dev.channel_length_modulation",
    "assume.n_p_dose_response_ratio",
)


@dataclass(frozen=True)
class ParameterRecord:
    param_id: str
    symbol: str
    value: str
    unit: str
    provenance: str
    source: str
    derivation: str
    uncertainty: str
    notes: str

    @property
    def number(self) -> float:
        return float(self.value)

    @property
    def numbers(self) -> tuple[float, ...]:
        return tuple(float(item) for item in self.value.split(",") if item.strip())


def load_registry(path: str | Path) -> dict[str, ParameterRecord]:
    """Load and validate the parameter registry."""

    registry_path = Path(path)
    with registry_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty parameter registry: {registry_path}")

    records: dict[str, ParameterRecord] = {}
    for row in rows:
        record = ParameterRecord(
            param_id=row["param_id"].strip(),
            symbol=row["symbol"].strip(),
            value=row["value"].strip(),
            unit=row["unit"].strip(),
            provenance=row["provenance"].strip(),
            source=row["source"].strip(),
            derivation=row.get("derivation", "").strip(),
            uncertainty=row.get("uncertainty", "").strip(),
            notes=row.get("notes", "").strip(),
        )
        if record.param_id in records:
            raise ValueError(f"duplicate parameter id: {record.param_id}")
        if record.provenance not in PROVENANCE_CLASSES:
            raise ValueError(
                f"{record.param_id}: provenance {record.provenance!r} not in {PROVENANCE_CLASSES}"
            )
        if not record.value:
            raise ValueError(f"{record.param_id}: empty value")
        if not record.source:
            raise ValueError(f"{record.param_id}: empty source")
        if record.provenance == "assumed" and (
            not record.uncertainty or record.uncertainty in {"0", "none", "-"}
        ):
            raise ValueError(
                f"{record.param_id}: assumed parameters must state an uncertainty range"
            )
        if record.provenance == "derived" and not record.derivation:
            raise ValueError(f"{record.param_id}: derived rows need a derivation formula")
        if record.param_id in STRING_IDS:
            records[record.param_id] = record
            continue
        try:
            _ = record.numbers
        except ValueError as error:
            raise ValueError(f"{record.param_id}: value {record.value!r} is not numeric") from error
        records[record.param_id] = record

    missing = [param_id for param_id in REQUIRED_IDS if param_id not in records]
    if missing:
        raise ValueError(f"parameter registry is missing required ids: {missing}")
    return records


def number(registry: dict[str, ParameterRecord], param_id: str) -> float:
    return registry[param_id].number


def numbers(registry: dict[str, ParameterRecord], param_id: str) -> tuple[float, ...]:
    return registry[param_id].numbers


def build_simulation_config(
    registry: dict[str, ParameterRecord],
    *,
    vth0_mag_v: float,
    mobility_m2_vs: float,
    slope_factor0: float,
    q_ot_c_cm2_per_krad: float,
    q_it_c_cm2_per_krad: float,
    mobility_degradation_per_krad: float,
    dose_exponent: float,
    qit_density_slope_c_cm2_per_krad: float,
    qit_anneal_c_cm2: float,
    qit_anneal_dose_krad: float,
) -> SimulationConfig:
    """Build the P0 simulation config from registered structure/bias values.

    The n-type device is a documented symmetric-complement assumption: the same
    geometry, zero-dose parameters and dose response, scaled by
    `assume.n_p_dose_response_ratio`.  Only the p-type response is anchored on
    measured data, so the inverter result is conditional on that ratio.  The
    two-stage swing channel (generated density minus saturating anneal) scales
    with the same ratio; the anneal dose scale is a kinetic quantity and is
    not scaled.
    """

    ratio = number(registry, "assume.n_p_dose_response_ratio")

    def device(polarity: str, scale: float) -> DeviceConfig:
        return DeviceConfig(
            polarity=polarity,  # type: ignore[arg-type]
            width_um=number(registry, "dev.width_um"),
            length_nm=number(registry, "dev.length_nm"),
            oxide_thickness_nm=number(registry, "dev.oxide_thickness_nm"),
            oxide_relative_permittivity=number(registry, "dev.oxide_relative_permittivity"),
            mobility_m2_vs=mobility_m2_vs,
            threshold_v=vth0_mag_v,
            slope_factor=slope_factor0,
            channel_length_modulation=number(registry, "dev.channel_length_modulation"),
            qot_slope_c_cm2_per_krad=q_ot_c_cm2_per_krad * scale,
            qit_slope_c_cm2_per_krad=q_it_c_cm2_per_krad * scale,
            mobility_degradation_per_krad=mobility_degradation_per_krad * scale,
            qit_density_slope_c_cm2_per_krad=qit_density_slope_c_cm2_per_krad * scale,
            qit_anneal_c_cm2=qit_anneal_c_cm2 * scale,
            qit_anneal_dose_krad=qit_anneal_dose_krad,
            slope_factor_per_krad=0.0,
            dose_exponent=dose_exponent,
            slope_factor_from_qit=True,
        )

    return SimulationConfig(
        name=registry["sim.name"].value,
        vdd_v=number(registry, "sim.vdd_v"),
        temperature_k=number(registry, "sim.temperature_k"),
        dose_unit=registry["sim.dose_unit"].value,
        doses_krad=numbers(registry, "sim.doses_krad"),
        transfer_points=int(number(registry, "sim.transfer_points")),
        inverter_points=int(number(registry, "sim.inverter_points")),
        ro_stages=int(number(registry, "sim.ro_stages")),
        calibration_status=registry["sim.calibration_status"].value,
        n_device=device("n", ratio),
        p_device=device("p", 1.0),
    )
