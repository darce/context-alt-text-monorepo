"""Regression coverage for credential labels split across streamed output windows."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

import scripts.run_app_portal_evals as runner


@pytest.mark.parametrize("label", ["api_key=", "Authorization: Basic"])
def test_streamed_credential_label_stays_redactable_across_long_whitespace(label: str, tmp_path: Path) -> None:
    secret = "synthetic-review-credential"
    prefix = "unrelated output\n" * 5_000
    source = StringIO(f"{prefix}{label}{' ' * 40_000}{secret}\n")
    destination = StringIO()

    runner._write_redacted_child_log(source, destination, secret_values=())

    persisted_log = destination.getvalue()
    log_path = tmp_path / "child.log"
    log_path.write_text(persisted_log, encoding="utf-8")
    evidence_tail, tail_bytes, tail_truncated, tail_error = runner._read_capped_tail(log_path)
    assert secret not in persisted_log
    assert secret not in evidence_tail
    assert "<redacted>" in persisted_log
    assert tail_bytes == runner.CAPTURED_TAIL_BYTES
    assert tail_truncated is True
    assert tail_error is None


def test_stream_copy_preserves_output_without_a_credential_label() -> None:
    ordinary_output = f"progress:{' ' * 40_000}complete\n"
    source = StringIO(ordinary_output)
    destination = StringIO()

    runner._write_redacted_child_log(source, destination, secret_values=())

    assert destination.getvalue() == ordinary_output
