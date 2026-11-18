"""CNTFET total-ionizing-dose simulation baseline."""

__version__ = "0.13.0"

from .calibration import CalibrationResult, calibrate, load_measurements
from .config import DeviceConfig, SimulationConfig, load_config
from .device import DeviceState, drain_current, state_at_dose
from .matrix import MatrixResult, run_matrix
from .metric_calibration import (
    MetricCalibration,
    calibrate_from_metrics,
    load_digitized_metrics,
)
from .p0 import P0Result, run_p0
from .registry import ParameterRecord, build_simulation_config, load_registry
from .sensitivity import SensitivityResult, run_sensitivity
from .tcad_vm import TcadSmokeResult, VmrunSettings, run_tcad_smoke
from .workflow import run_simulation

__all__ = [
    "CalibrationResult",
    "DeviceConfig",
    "DeviceState",
    "MatrixResult",
    "MetricCalibration",
    "P0Result",
    "ParameterRecord",
    "SensitivityResult",
    "SimulationConfig",
    "TcadSmokeResult",
    "VmrunSettings",
    "build_simulation_config",
    "calibrate",
    "calibrate_from_metrics",
    "drain_current",
    "load_config",
    "load_digitized_metrics",
    "load_measurements",
    "load_registry",
    "run_matrix",
    "run_p0",
    "run_sensitivity",
    "run_simulation",
    "run_tcad_smoke",
    "state_at_dose",
]
