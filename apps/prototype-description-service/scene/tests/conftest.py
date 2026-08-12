"""Scene-suite pytest bootstrap.

``validate_required_secrets`` defaults ``RECOGNITION_RUNTIME_MODE`` to
``production`` when the variable is unset, so a test process that boots the app
without declaring a mode is validated as if it were serving traffic and dies on
``InsecureProductionConfigError: PGPASSWORD is unset`` (VLM6-INT-02).
``recognition/tests/conftest.py`` already pins the mode for its own directory,
but a conftest only applies below its own package — the scene suite never sees
it, and fails whether run alone or as part of the whole suite.

Pinning the mode here does not weaken the production guard: its red-capable
coverage lives in ``recognition/tests/config/test_required_secrets.py``, which
sets ``RECOGNITION_RUNTIME_MODE=production`` explicitly and asserts the raise.
"""

from __future__ import annotations

import os

os.environ.setdefault("RECOGNITION_RUNTIME_MODE", "test")
