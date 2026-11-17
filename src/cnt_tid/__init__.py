"""CNTFET total-ionizing-dose simulation baseline."""

from .config import DeviceConfig, SimulationConfig, load_config
from .device import DeviceState, drain_current, state_at_dose
from .workflow import run_simulation

__all__ = [
    "DeviceConfig",
    "DeviceState",
    "SimulationConfig",
    "drain_current",
    "load_config",
    "run_simulation",
    "state_at_dose",
]

__version__ = "0.1.0"
