"""
Attention optimization enumerations.

This module contains enums related to attention optimization backends and configurations.
"""

from enum import Enum


class AttentionBackend(Enum):
    """Available attention optimization backends."""
    FLASH_ATTENTION_V2 = "flash_attention_2"
    FLASH_ATTENTION_V1 = "flash_attention_1" 
    SDPA = "sdpa"
    EAGER = "eager"
