"""CNTFET total-ionizing-dose simulation baseline."""

__version__ = "0.4.0"

from .calibration import CalibrationResult, calibrate, load_measurements
from .config import DeviceConfig, SimulationConfig, load_config
from .device import DeviceState, drain_current, state_at_dose
from .matrix import MatrixResult, run_matrix
from .sensitivity import SensitivityResult, run_sensitivity
from .tcad_vm import TcadSmokeResult, VmrunSettings, run_tcad_smoke
from .workflow import run_simulation

__all__ = [
    "CalibrationResult",
    "DeviceConfig",
    "DeviceState",
    "MatrixResult",
    "SensitivityResult",
    "SimulationConfig",
    "TcadSmokeResult",
    "VmrunSettings",
    "calibrate",
    "drain_current",
    "load_config",
    "load_measurements",
    "run_matrix",
    "run_sensitivity",
    "run_simulation",
    "run_tcad_smoke",
    "state_at_dose",
]
