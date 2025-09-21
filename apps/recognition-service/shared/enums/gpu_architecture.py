"""
GPU architecture enumerations.

This module contains enums related to GPU architectures and capabilities.
"""

from enum import Enum


class GPUArchitecture(Enum):
    """GPU Architecture classifications."""
    TURING = "turing"       # 7.5
    AMPERE = "ampere"       # 8.x
    ADA_LOVELACE = "ada"    # 8.9
    HOPPER = "hopper"       # 9.0+
    UNKNOWN = "unknown"
