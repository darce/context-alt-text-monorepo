from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
WORKFLOW = REPO_ROOT / ".github/workflows/gates-harness.yml"


def _recipe_for(text: str, target: str) -> str:
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith(f"{target}:")),
        None,
    )
    assert start is not None, f"missing target {target}"

    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            body.append(line[1:])
            continue
        if not line.strip():
            continue
        break
    recipe = "\n".join(body)
    assert recipe, f"target {target} has no recipe"
    return recipe


def _check_all_recipe(text: str) -> str:
    return _recipe_for(text, "check-all")


def _harness_job(text: str) -> str:
    match = re.search(r"(?ms)^  harness:\n(.*?)(?=^  [^ \n][^:]*:|\Z)", text)
    assert match is not None, "missing harness job"
    return match.group(0)


def _ux_map_parity_step(job: str) -> str:
    match = re.search(
        r"(?ms)^      - name: Check UX-map render parity\n(.*?)(?=^      - name:|\Z)",
        job,
    )
    assert match is not None, "missing UX-map render parity step in harness job"
    return match.group(0)


def test_makefile_declares_ux_map_parity_target() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _recipe_for(makefile, "lint-ux-maps")

    assert "render_ux_maps.py --check" in recipe
    assert "sync_unicode_width.py --check" in recipe


def test_check_all_runs_ux_map_parity_target() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "$(MAKE) lint-ux-maps" in _check_all_recipe(makefile)


def test_makefile_marks_ux_map_parity_target_phony() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    phony_line = next(
        (line for line in makefile.splitlines() if line.startswith(".PHONY:")),
        None,
    )
    assert phony_line is not None, "missing .PHONY declaration"
    assert "lint-ux-maps" in phony_line.split()[1:]


def test_harness_runs_ux_map_parity_in_the_app_working_directory() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = _ux_map_parity_step(_harness_job(workflow))

    assert "working-directory: apps/prototype-wp-alt-context" in step
    assert "python docs/ux-maps/render_ux_maps.py --check" in step
    assert "python docs/ux-maps/sync_unicode_width.py --check" in step
