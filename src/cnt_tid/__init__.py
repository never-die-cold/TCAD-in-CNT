"""CNTFET total-ionizing-dose simulation baseline."""

__version__ = "0.3.0"

from .calibration import CalibrationResult, calibrate, load_measurements
from .config import DeviceConfig, SimulationConfig, load_config
from .device import DeviceState, drain_current, state_at_dose
from .matrix import MatrixResult, run_matrix
from .sensitivity import SensitivityResult, run_sensitivity
from .workflow import run_simulation

__all__ = [
    "CalibrationResult",
    "DeviceConfig",
    "DeviceState",
    "MatrixResult",
    "SensitivityResult",
    "SimulationConfig",
    "calibrate",
    "drain_current",
    "load_config",
    "load_measurements",
    "run_matrix",
    "run_sensitivity",
    "run_simulation",
    "state_at_dose",
]
