"""Representatives subdomain.

Provides representative embedding management including:
- RepresentativeManager: Adding/managing cluster representatives
- RepresentativeMatcher: Matching identities to clusters via representatives
- Selection and confidence utilities
"""

from recognition.application.representatives.representative_manager import (
    RepresentativeManager,
)
from recognition.application.representatives.representative_matcher import (
    RepresentativeMatcher,
)
from recognition.application.representatives.representative_selection import (
    decide_representative_acceptance,
)

__all__ = [
    "RepresentativeManager",
    "RepresentativeMatcher",
    "decide_representative_acceptance",
]
