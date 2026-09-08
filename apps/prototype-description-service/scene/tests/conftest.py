"""Hermetic environment for the scene suite.

`recognition.config.security` defaults `RECOGNITION_RUNTIME_MODE` to
`production` when the variable is unset, which is the correct fail-closed
default for a server but means any test that boots the app inherits the
production credential guard. The root worktree happened to satisfy that guard
through an untracked `.env`; linked lane worktrees do not have one and must not
receive a copy, so those tests failed in every lane and turned the offload
self-verify gate into noise.

Pin the mode here, the way `recognition/tests/conftest.py` already does, so the
suite depends on the fixture rather than on the invoking shell.
"""

from __future__ import annotations

import os

os.environ["RECOGNITION_RUNTIME_MODE"] = "test"
