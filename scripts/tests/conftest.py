"""Gates-harness pytest defaults.

This suite does not build ``apps/prototype-wp-alt-context/public/assets/dist``.
Live freshness fails closed unless the operator marks the bundle optional.
"""

from __future__ import annotations

import os

os.environ.setdefault("ACX_BUNDLE_OPTIONAL", "1")
