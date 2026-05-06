from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MAKEFILE = REPO_ROOT / "apps" / "prototype-wp-alt-context" / "Makefile"


def _localwp_batch_run_smoke_block() -> str:
    text = PLUGIN_MAKEFILE.read_text()
    match = re.search(
        r"^localwp-batch-run-smoke:\n(?:^\t.*\n?)+",
        text,
        re.MULTILINE,
    )
    assert match is not None
    return match.group(0)


def test_localwp_batch_run_smoke_does_not_pass_eval_file_separator() -> None:
    block = _localwp_batch_run_smoke_block()

    assert 'eval-file "$(CURDIR)/scripts/localwp/batch-run-smoke.php" -- ' not in block


def test_localwp_batch_run_smoke_passes_four_positional_values() -> None:
    block = _localwp_batch_run_smoke_block()

    assert 'eval-file "$(CURDIR)/scripts/localwp/batch-run-smoke.php" "$(if $(SMOKE_LIMIT),$(SMOKE_LIMIT),100)" "$(if $(BATCH_SIZE),$(BATCH_SIZE),5)" "$(if $(TIMEOUT_SECONDS),$(TIMEOUT_SECONDS),240)" "$(if $(POLL_INTERVAL_MS),$(POLL_INTERVAL_MS),1000)"' in block