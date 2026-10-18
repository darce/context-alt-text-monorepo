"""Keep standalone offline harness tests on the deterministic test runtime.

This directory is outside scene/tests and recognition/tests, so their runtime
selection fixtures do not apply when collecting this suite on its own.
"""

import os

os.environ["RECOGNITION_RUNTIME_MODE"] = "test"
