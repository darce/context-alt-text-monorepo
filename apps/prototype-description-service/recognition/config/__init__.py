"""
Recognition service configuration loader.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from recognition.config.settings import RecognitionSettings


@lru_cache(maxsize=1)
def get_settings() -> "RecognitionSettings":
    """Return cached recognition settings."""
    from recognition.config.settings import RecognitionSettings

    return RecognitionSettings()
