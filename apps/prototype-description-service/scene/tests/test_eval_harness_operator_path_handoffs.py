"""VLM6-RV18-13: close the remaining operator path handoffs.

The report builder and determinism guard have machine-readable inputs and
outputs, but their diagnostics still carry operator paths.  Exercise the
actual sinks with a C-locale child so a PEP 383 surrogate cannot hide behind
the UTF-8 test runner.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scene.tests.test_eval_harness_cli_stdio import _run_python_bytes
from scripts.eval_harness._pathtext import _UNDECODABLE_PATH_PREFIX

_BUILD_REPORT_CHILD = b"""
import sys
from pathlib import Path
from scripts.eval_harness.build_bakeoff_report import main

output = Path(sys.argv[3])
if len(sys.argv) > 4 and sys.argv[4] == 'success':
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self == output:
            return None
        return real_write_text(self, *args, **kwargs)

    Path.write_text = fake_write_text
elif len(sys.argv) > 4 and sys.argv[4] == 'stale':
    real_exists = Path.exists

    def fake_exists(self):
        if self == output:
            return True
        return real_exists(self)

    Path.exists = fake_exists

raise SystemExit(main([
    '--manifest', sys.argv[1],
    '--run', 'M=' + sys.argv[2],
    '--media-ids', '1',
    '--out', sys.argv[3],
]))
"""


def _write_report_inputs(tmp_path: Path, *, extra_media_id: bool = False) -> tuple[bytes, bytes]:
    manifest = tmp_path / "manifest.json"
    record = tmp_path / "run.json"
    manifest.write_text(
        json.dumps({"entries": [{"media_id": 1, "path": "image.jpg", "present_identities": []}]}),
        encoding="utf-8",
    )
    media_id = 2 if extra_media_id else 1
    record.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "media_id": media_id,
                        "describe": {"alt_text_draft": "A photo.", "passes": [{"latency_s": 1.0}]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return os.fsencode(manifest), os.fsencode(record)


def _invalid_path(tmp_path: Path, leaf: bytes) -> bytes:
    return os.fsencode(tmp_path) + b"/" + leaf + b"-caf\xe9.html"


def test_report_success_path_uses_path_wire_and_preserves_output_argument(tmp_path: Path) -> None:
    """The human success line encodes the path while the output argument is preserved."""
    manifest, record = _write_report_inputs(tmp_path)
    output = _invalid_path(tmp_path, b"report")

    proc = _run_python_bytes(_BUILD_REPORT_CHILD, [manifest, record, output, b"success"])

    assert proc.returncode == 0, proc.stderr
    assert b"wrote undecodable:" in proc.stdout, proc.stdout
    assert b"report-caf\\xe9.html" in proc.stdout, proc.stdout
    assert b"\\udc" not in proc.stdout


def test_report_stale_warning_uses_path_wire_without_rewriting(tmp_path: Path) -> None:
    """A refused report keeps the old artifact path and prints an encodable warning."""
    manifest, record = _write_report_inputs(tmp_path, extra_media_id=True)
    output = _invalid_path(tmp_path, b"stale")
    proc = _run_python_bytes(_BUILD_REPORT_CHILD, [manifest, record, output, b"stale"])

    assert proc.returncode == 4, proc.stderr
    assert b"warning: undecodable:" in proc.stderr, proc.stderr
    assert b"stale-caf\\xe9.html was NOT rewritten" in proc.stderr, proc.stderr
    assert b"\\udc" not in proc.stderr


def test_determinism_module_mismatch_encodes_both_path_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The mismatch diagnostic keeps its ``parent=``/``child=`` wire fields."""
    from scripts.eval_harness import cli

    parent = "/tmp/build-reports-parent-" + chr(0xDCE9) + ".py"
    child = "/tmp/build-reports-child-" + chr(0xDCE9) + ".py"

    monkeypatch.setattr(cli, "_parent_hash_seed_regime", lambda: ("randomized", None))
    monkeypatch.setattr(cli, "_resolve_determinism_child_seeds", lambda _parent: ("17",))

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(argv[-1]).write_text(
            json.dumps({"json": "{}", "md": "", "build_reports_file": child}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as excinfo:
        cli._run_determinism_children(
            "",
            [],
            label="score",
            base_json="{}",
            base_md="",
            artifact_dir=tmp_path,
            expected_build_reports_file=parent,
            announce_pass=False,
        )

    message = str(excinfo.value)
    assert "build_reports module differs" in message
    from scripts.eval_harness._pathtext import _printable_path

    assert f"parent={_printable_path(Path(parent).resolve())}" in message
    assert f"child={_printable_path(Path(child).resolve())}" in message
    assert "parent=" in message and "child=" in message
    assert "\\udc" not in message
