"""
Recognition service configuration loader.
"""

from functools import lru_cache

from recognition.config.settings import RecognitionSettings


@lru_cache(maxsize=1)
def get_settings() -> RecognitionSettings:
    """Return cached recognition settings."""
    return RecognitionSettings()
