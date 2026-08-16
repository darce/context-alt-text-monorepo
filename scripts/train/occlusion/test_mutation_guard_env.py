"""FIR-7-PANEL7D-rv2-01: mutation_guard.py child-env user-site injection guard.

A ``~/.local/lib/python*/site-packages/*.pth`` file executes arbitrary code
at *every* child interpreter startup — including the ``--collect-only``
invocation the RF-01 node-id floor trusts. ``mutation_guard._scrubbed_env``
must neutralise this path (SECD-02 / SECD-03 complete mediation;
perceived-enforced-boundaries.md: a control that is not verified is not
enforced). These tests build a real temp HOME with a sentinel ``.pth`` hook
and assert the sentinel cannot reach a child process built from the guard's
env, both directly and through the actual ``--collect-only`` subprocess.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "mutation_guard.py"
_SPEC = importlib.util.spec_from_file_location(
    "mutation_guard_env_subject",
    _MODULE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
guard = importlib.util.module_from_spec(_SPEC)
sys.modules["mutation_guard_env_subject"] = guard
_SPEC.loader.exec_module(guard)

_SENTINEL = "SENTINEL-PTH-INJECTED"


def _write_sentinel_pth(fake_home: Path) -> None:
    """Real ``.pth`` import-line hook under ``<fake_home>/.local/...``.

    Matches CPython's actual per-user site-packages layout so the pin fails
    if a future interpreter/platform change moves that path and the fix
    stops covering it.
    """
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    site_dir = fake_home / ".local" / "lib" / f"python{pyver}" / "site-packages"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "zzz_sentinel.pth").write_text(
        f'import sys, os; sys.stderr.write("{_SENTINEL}" + os.linesep)\n',
        encoding="utf-8",
    )


class TestRv201ScrubbedEnvBlocksUserSitePth:
    """FIR-7-PANEL7D-rv2-01 red/green pin: guard env vs. a real .pth hook."""

    def test_scrubbed_env_home_is_guard_owned_not_caller_home(
        self, tmp_path: Path, monkeypatch: "object"
    ) -> None:
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        env = guard._scrubbed_env()
        assert env.get("HOME") != str(fake_home), (
            "guard must not trust the caller's HOME verbatim (rv2-01)"
        )
        assert env.get("PYTHONNOUSERSITE") == "1"

    def test_scrubbed_env_child_does_not_see_pth_sentinel(
        self, tmp_path: Path, monkeypatch: "object"
    ) -> None:
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        _write_sentinel_pth(fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        env = guard._scrubbed_env()
        proc = subprocess.run(
            [sys.executable, "-s", "-c", "print('ok')"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert _SENTINEL not in proc.stderr, (
            f"user-site .pth hook leaked into child: {proc.stderr!r}"
        )
        assert proc.stdout.strip() == "ok"

    def test_collect_nodeids_child_does_not_see_pth_sentinel(
        self, tmp_path: Path, monkeypatch: "object"
    ) -> None:
        """The exact subprocess ``_collect_nodeids`` runs, not a stand-in.

        The RF-01 node-id floor trusts ``--collect-only`` output; if the
        sentinel reaches this specific child, an attacker-controlled .pth
        could also forge nodeids on stdout.
        """
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        _write_sentinel_pth(fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        occ = tmp_path / "scratch" / "scripts" / "train" / "occlusion"
        occ.mkdir(parents=True)
        (tmp_path / "scratch" / "scripts" / "train" / "__init__.py").write_text(
            "", encoding="utf-8"
        )
        (occ / "__init__.py").write_text("", encoding="utf-8")
        (occ / "test_license_policy.py").write_text(
            "def test_dummy():\n    assert True\n", encoding="utf-8"
        )
        nodeids, err = guard._collect_nodeids(occ / "test_license_policy.py")
        assert err is None, err
        assert nodeids, "collect-only must still find the dummy test"

    def test_child_user_site_error_is_none_under_scrubbed_env(
        self, tmp_path: Path, monkeypatch: "object"
    ) -> None:
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        _write_sentinel_pth(fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        assert guard._child_user_site_error() is None

    def test_child_user_site_error_fires_on_a_leaking_env(
        self, tmp_path: Path, monkeypatch: "object"
    ) -> None:
        """Red-proof: the startup check must be able to fail, not just pass.

        Simulate the pre-rv2-01 ``_scrubbed_env`` (real HOME copied through,
        no ``PYTHONNOUSERSITE``, no ``-s``) and prove
        ``_child_user_site_error`` actually discriminates that unsafe env
        from a safe one (feedback_verify_assertion_can_fail) instead of
        always returning None.
        """
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        _write_sentinel_pth(fake_home)

        def _unsafe_env() -> dict[str, str]:
            return {"HOME": str(fake_home), "PATH": guard.os.environ.get("PATH", "")}

        monkeypatch.setattr(guard, "_scrubbed_env", _unsafe_env)
        # Mirror the pre-fix subprocess call: no "-s" interpreter flag.
        proc = subprocess.run(
            [sys.executable, "-c", "import site; print(site.ENABLE_USER_SITE)"],
            env=_unsafe_env(),
            capture_output=True,
            text=True,
        )
        assert proc.stdout.strip() == "True", (
            "precondition: the unsafe simulated env must actually enable "
            f"user-site (got {proc.stdout!r}); otherwise this arm proves "
            "nothing"
        )
        err = guard._child_user_site_error()
        assert err is not None, (
            "checker must flag an env that leaves user-site enabled"
        )
        assert "ENABLE_USER_SITE" in err
