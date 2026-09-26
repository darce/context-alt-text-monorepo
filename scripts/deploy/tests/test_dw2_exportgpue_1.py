from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORTER = REPO_ROOT / "scripts/deploy/lib/export-gpu-evidence.sh"


def _run_export(tmp_path: Path, fake_oci_source: str, **environment_updates: str) -> subprocess.CompletedProcess[str]:
    fake_oci = tmp_path / "oci"
    fake_oci.write_text(fake_oci_source, encoding="utf-8")
    fake_oci.chmod(0o755)
    environment = os.environ.copy()
    environment.update({
        "PATH": str(Path(sys.executable).parent) + os.pathsep + environment["PATH"],
        "OCI_BIN": str(fake_oci),
        "EVIDENCE_AUDIT_CAPTURE_MAX_SECONDS": "120",
        "EVIDENCE_AUDIT_CAPTURE_MAX_BYTES": "33554432",
        **environment_updates,
    })
    bundle = tmp_path / "bundle"
    args = [
        "bash", str(EXPORTER),
        "--instance-id", "ocid1.instance.example", "--compartment-id", "ocid1.compartment.example",
        "--since", "2026-09-01T00:00:00Z", "--until", "2026-09-01T01:00:00Z", "--out", str(bundle),
    ]
    return subprocess.run(args, env=environment, capture_output=True, text=True, timeout=15, check=False)


def test_audit_capture_fails_closed_at_the_page_limit(tmp_path: Path) -> None:
    fake_oci = r"""#!/usr/bin/env python3
import json
import sys

if sys.argv[1:4] == ["compute", "instance", "get"]:
    print('{"data":{"id":"ocid1.instance.example","compartment-id":"ocid1.compartment.example","lifecycle-state":"STOPPED"}}')
elif "--limit" not in sys.argv or "--all" in sys.argv:
    print('{"data":[]}')
else:
    print(json.dumps({"data": [{}] * 1000}))
"""

    result = _run_export(tmp_path, fake_oci)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "OCI Audit capture reached the 1000-event page limit" in result.stderr
    assert not (tmp_path / "bundle").exists()


def test_audit_capture_enforces_byte_limit_while_streaming(tmp_path: Path) -> None:
    fake_oci = r"""#!/usr/bin/env python3
import sys

if sys.argv[1:4] == ["compute", "instance", "get"]:
    print('{"data":{"id":"ocid1.instance.example","compartment-id":"ocid1.compartment.example","lifecycle-state":"STOPPED"}}')
else:
    sys.stdout.write("x" * 4096)
"""

    result = _run_export(tmp_path, fake_oci, EVIDENCE_AUDIT_CAPTURE_MAX_BYTES="512")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "OCI Audit capture exceeded the 512-byte limit" in result.stderr
    assert not (tmp_path / "bundle").exists()


def test_audit_capture_enforces_wall_clock_limit(tmp_path: Path) -> None:
    fake_oci = r"""#!/usr/bin/env python3
import sys
import time

if sys.argv[1:4] == ["compute", "instance", "get"]:
    print('{"data":{"id":"ocid1.instance.example","compartment-id":"ocid1.compartment.example","lifecycle-state":"STOPPED"}}')
else:
    time.sleep(3)
    print('{"data":[]}')
"""

    result = _run_export(tmp_path, fake_oci, EVIDENCE_AUDIT_CAPTURE_MAX_SECONDS="1")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "OCI Audit capture exceeded the 1-second wall-clock limit" in result.stderr
    assert not (tmp_path / "bundle").exists()
