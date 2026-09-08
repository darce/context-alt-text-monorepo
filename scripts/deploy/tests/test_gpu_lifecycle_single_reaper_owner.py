"""The backend idle reaper has one declarative owner."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CLOUD_INIT = REPO_ROOT / "infra/oci/cloud-init.yaml"
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
EXPECTED_REAPER_TIMER = "acx-gpu-reap.timer"
_DEFINED_TIMER = re.compile(
    r"(?:sudo tee [^\n]*/|path:\s*/etc/systemd/system/)(acx-gpu-(?:reap|idle-reaper)\.timer)"
)
_ENABLED_TIMER = re.compile(
    r"systemctl enable(?: --now)?\s+(acx-gpu-(?:reap|idle-reaper)\.timer)"
)


def _reaper_timer_names(text: str) -> set[str]:
    return set(_DEFINED_TIMER.findall(text)) | set(_ENABLED_TIMER.findall(text))


def test_exactly_one_reaper_timer_is_owned_by_the_installer() -> None:
    installer_names = _reaper_timer_names(INSTALLER.read_text(encoding="utf-8"))
    cloud_init_names = _reaper_timer_names(CLOUD_INIT.read_text(encoding="utf-8"))
    all_names = installer_names | cloud_init_names

    assert all_names == {EXPECTED_REAPER_TIMER}, (
        "installer and cloud-init must expose exactly one reaper timer name"
    )
    assert installer_names == {EXPECTED_REAPER_TIMER}
    assert not cloud_init_names, "cloud-init must not define or enable a reaper timer"
