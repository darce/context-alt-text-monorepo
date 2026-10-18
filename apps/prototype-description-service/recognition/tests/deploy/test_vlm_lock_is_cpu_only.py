"""ORCH-LAUNCH-01 S1: the `[vlm]` extra must not drag the CUDA stack onto a CPU VM.

torch's own dependency markers gate cuda-*/nvidia-*/triton on
`sys_platform == 'linux'` with **no `platform_machine` guard**, and aarch64
wheels exist for all of them. So a `docker build --platform linux/arm64` of the
vlm extra resolved ~2.1 GB of GPU-only libraries onto a GPU-less Ampere A1 —
and *succeeded*, which is why nothing caught it (ORCH-LAUNCH-01-S1-BR-05; two
reviewers reached opposite conclusions because neither read the lock).

Fixed by pinning linux torch to the PyTorch CPU index in pyproject.toml. This
guard pins the outcome so a future relock cannot silently reintroduce it.
"""

from __future__ import annotations

import re
from pathlib import Path

# recognition/tests/deploy/<this> → parents[3] = the service root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
UV_LOCK = SERVICE_ROOT / "uv.lock"

# Distributions that only make sense with an NVIDIA GPU present.
_GPU_DIST_RE = re.compile(r'^name = "(nvidia-[\w.-]+|cuda-[\w.-]+|triton)"$', re.MULTILINE)


def _gpu_distributions(lockfile: Path = UV_LOCK) -> set[str]:
    return set(_GPU_DIST_RE.findall(Path(lockfile).read_text()))


def _linux_torch_wheels(lockfile: Path = UV_LOCK) -> set[str]:
    """Wheel filenames for any locked torch whose version carries the +cpu local tag."""
    wheels: set[str] = set()
    for block in re.split(r"\n\[\[package\]\]\n", Path(lockfile).read_text()):
        if not re.match(r'name = "torch"', block):
            continue
        version = re.search(r'version = "([^"]+)"', block)
        if not version or "+cpu" not in version.group(1):
            continue
        wheels.update(url.rsplit("/", 1)[-1] for url in re.findall(r'url = "([^"]+)"', block))
    return wheels


def test_lock_pulls_no_gpu_only_distributions() -> None:
    found = _gpu_distributions()
    assert not found, (
        f"uv.lock resolves GPU-only distributions {sorted(found)}. The [vlm] extra targets a "
        "CPU-only Ampere A1; keep torch pinned to the pytorch-cpu index in pyproject.toml."
    )


def test_linux_torch_is_the_cpu_build_with_an_arm64_wheel() -> None:
    wheels = _linux_torch_wheels()
    assert wheels, "expected a +cpu torch build locked for linux"
    assert any("aarch64" in name for name in wheels), (
        f"no aarch64 wheel among the locked CPU torch wheels {sorted(wheels)}; "
        "the arm64 production build would fall back to a source build or fail"
    )


def test_guard_bites_on_a_lock_that_pulls_cuda(tmp_path: Path) -> None:
    """Prove the guard can go red — the pre-fix lock shape must be rejected."""
    synthetic = tmp_path / "uv.lock"
    synthetic.write_text(
        '[[package]]\nname = "torch"\nversion = "2.12.0"\n\n'
        '[[package]]\nname = "nvidia-cublas"\nversion = "13.1.1.3"\n\n'
        '[[package]]\nname = "triton"\nversion = "3.7.0"\n'
    )
    assert _gpu_distributions(synthetic) == {"nvidia-cublas", "triton"}
    assert not _linux_torch_wheels(synthetic)
