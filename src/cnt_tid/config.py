"""Strict, SI-based configuration for the compact TID workflow."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

EPSILON_0_F_M = 8.8541878128e-12


@dataclass(frozen=True)
class DeviceConfig:
    """Compact CNTFET parameters; dose coefficients require calibration."""

    polarity: Literal["n", "p"]
    width_um: float = 1.0
    length_nm: float = 50.0
    oxide_thickness_nm: float = 10.0
    oxide_relative_permittivity: float = 3.9
    mobility_m2_vs: float = 0.02
    threshold_v: float = 0.25
    slope_factor: float = 1.3
    channel_length_modulation: float = 0.02
    qot_slope_c_cm2_per_krad: float = 1.0e-11
    qit_slope_c_cm2_per_krad: float = 2.0e-12
    mobility_degradation_per_krad: float = 2.0e-4
    slope_factor_per_krad: float = 5.0e-5

    def __post_init__(self) -> None:
        if self.polarity not in ("n", "p"):
            raise ValueError("polarity must be 'n' or 'p'")
        positive = {
            "width_um": self.width_um,
            "length_nm": self.length_nm,
            "oxide_thickness_nm": self.oxide_thickness_nm,
            "oxide_relative_permittivity": self.oxide_relative_permittivity,
            "mobility_m2_vs": self.mobility_m2_vs,
            "slope_factor": self.slope_factor,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.channel_length_modulation < 0:
            raise ValueError("channel_length_modulation must be non-negative")
        if self.mobility_degradation_per_krad < 0:
            raise ValueError("mobility_degradation_per_krad must be non-negative")
        non_negative_slopes = {
            "qot_slope_c_cm2_per_krad": self.qot_slope_c_cm2_per_krad,
            "qit_slope_c_cm2_per_krad": self.qit_slope_c_cm2_per_krad,
            "slope_factor_per_krad": self.slope_factor_per_krad,
        }
        for name, value in non_negative_slopes.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def width_m(self) -> float:
        return self.width_um * 1e-6

    @property
    def length_m(self) -> float:
        return self.length_nm * 1e-9

    @property
    def oxide_thickness_m(self) -> float:
        return self.oxide_thickness_nm * 1e-9

    @property
    def cox_f_m2(self) -> float:
        return (
            EPSILON_0_F_M * self.oxide_relative_permittivity / self.oxide_thickness_m
        )

    @property
    def cox_f_cm2(self) -> float:
        return self.cox_f_m2 / 1e4


@dataclass(frozen=True)
class SimulationConfig:
    """Top-level simulation conditions."""

    name: str = "baseline"
    vdd_v: float = 0.8
    temperature_k: float = 300.0
    dose_unit: str = "krad(SiO2)"
    doses_krad: tuple[float, ...] = (0.0, 100.0, 300.0, 500.0, 1000.0)
    transfer_points: int = 401
    inverter_points: int = 1001
    calibration_status: str = "illustrative_uncalibrated"
    n_device: DeviceConfig = DeviceConfig(polarity="n")
    p_device: DeviceConfig = DeviceConfig(
        polarity="p",
        threshold_v=0.25,
        qot_slope_c_cm2_per_krad=8.0e-12,
    )

    def __post_init__(self) -> None:
        if self.vdd_v <= 0 or self.temperature_k <= 0:
            raise ValueError("vdd_v and temperature_k must be positive")
        if not self.doses_krad or any(dose < 0 for dose in self.doses_krad):
            raise ValueError("doses_krad must contain non-negative values")
        if len(set(self.doses_krad)) != len(self.doses_krad):
            raise ValueError("doses_krad must not contain duplicates")
        if self.transfer_points < 20 or self.inverter_points < 100:
            raise ValueError("transfer_points >= 20 and inverter_points >= 100 required")
        if self.n_device.polarity != "n" or self.p_device.polarity != "p":
            raise ValueError("n_device and p_device must have matching polarity")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _construct(cls: type[Any], values: dict[str, Any]) -> Any:
    allowed = {field.name for field in fields(cls)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} fields: {sorted(unknown)}")
    return cls(**values)


def load_config(path: str | Path) -> SimulationConfig:
    """Load a TOML file and reject misspelled or unknown fields."""

    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    raw = dict(raw)
    if "n_device" in raw:
        raw["n_device"] = _construct(DeviceConfig, raw["n_device"])
    if "p_device" in raw:
        raw["p_device"] = _construct(DeviceConfig, raw["p_device"])
    if "doses_krad" in raw:
        raw["doses_krad"] = tuple(float(value) for value in raw["doses_krad"])
    return _construct(SimulationConfig, raw)
