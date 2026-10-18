from __future__ import annotations

import importlib
import json
import logging


def test_cli_logs_unexpected_exception_before_fail_closed_result(monkeypatch, caplog, capsys) -> None:
    validator = importlib.import_module("scripts.validate_fir_dev_runtime")

    def raise_unexpected_error(_path):
        raise RuntimeError("unexpected validator defect")

    monkeypatch.setattr(validator, "_load_json", raise_unexpected_error)
    caplog.set_level(logging.ERROR, logger=validator.__name__)

    exit_code = validator.main(
        [
            "--snapshot",
            "snapshot.json",
            "--freshness-policy",
            "freshness.json",
            "--isolation-policy",
            "isolation.json",
            "--now",
            "2026-09-20T12:01:00Z",
        ]
    )

    output = capsys.readouterr()
    result = json.loads(output.out)
    assert exit_code == 2
    assert result["reason_code"] == "validator_internal_error"
    assert "unexpected validator defect" in caplog.text
