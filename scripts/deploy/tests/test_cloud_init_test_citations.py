"""Every test module and test name cloud-init.yaml cites must actually exist.

WBUX6-W4-R-05: the `deliberately NOT written here` note in
`infra/oci/cloud-init.yaml` named `scripts/deploy/tests/
test_gpu_lifecycle_contract_ownership.py` as the enforcer of the tmpfiles
ownership invariant. That module never asserted anything about cloud-init; the
real enforcer is `apps/prototype-description-service/scene/tests/
test_gpu_lifecycle_install_script.py`. A future editor checking the named file
finds no such assertion and can reasonably conclude the invariant is unguarded
-- and delete it.

A citation is a documented command in the same sense as a runbook snippet: it
must resolve as written (rg-006). Nothing checked these, so this module does
(RES-16 a claimed mechanism must be exercised before the claim ships,
~/Development/heuristics-canon-research/lexicons/engineering.md:127).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CLOUD_INIT = REPO_ROOT / "infra/oci/cloud-init.yaml"

# Paths are wrapped across comment lines in the YAML, so join the comment block
# before matching (the citation that regressed spanned two lines).
_COMMENT = re.compile(r"^\s*#\s?(.*)$")
_PY_PATH = re.compile(r"([A-Za-z0-9_./-]+/[A-Za-z0-9_-]+\.py)")
_TEST_NAME = re.compile(r"\b(test_[a-z0-9_]+)\b")


def _comment_prose() -> str:
    lines = []
    for line in CLOUD_INIT.read_text(encoding="utf-8").splitlines():
        match = _COMMENT.match(line)
        if match:
            lines.append(match.group(1).strip())
    # Wrapped paths look like `.../scene/tests/` + `test_foo.py` on the next line.
    return re.sub(r"/\s+", "/", " ".join(lines))


def test_every_python_module_cited_by_cloud_init_exists() -> None:
    prose = _comment_prose()
    cited = sorted(set(_PY_PATH.findall(prose)))

    assert cited, "cloud-init.yaml cites no test module; this guard has lost its subject"
    missing = [path for path in cited if not (REPO_ROOT / path).is_file()]
    assert not missing, f"cloud-init.yaml cites modules that do not exist: {missing}"


def test_every_test_name_cited_by_cloud_init_is_defined_in_a_cited_module() -> None:
    """A named test must be findable, or the citation misdirects the next editor."""

    prose = _comment_prose()
    sources = "\n".join(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in set(_PY_PATH.findall(prose))
        if (REPO_ROOT / path).is_file()
    )
    # `test_gpu_lifecycle_install_script` also appears as a module stem; only
    # bare function names are checked here (module paths are checked above).
    module_stems = {Path(path).stem for path in _PY_PATH.findall(prose)}
    cited_names = sorted(set(_TEST_NAME.findall(prose)) - module_stems)

    assert cited_names, "cloud-init.yaml names no test; this guard has lost its subject"
    undefined = [name for name in cited_names if f"def {name}(" not in sources]
    assert not undefined, (
        f"cloud-init.yaml names tests that no cited module defines: {undefined}. "
        "Either the test was renamed or the wrong module is cited (WBUX6-W4-R-05)."
    )


def test_the_cited_enforcer_actually_reads_cloud_init() -> None:
    """Citing a module that never opens this file is the exact WBUX6-W4-R-05 bug."""

    prose = _comment_prose()
    readers = [
        path
        for path in sorted(set(_PY_PATH.findall(prose)))
        if (REPO_ROOT / path).is_file() and "cloud-init.yaml" in (REPO_ROOT / path).read_text(encoding="utf-8")
    ]

    assert readers, (
        "no module cited by cloud-init.yaml references cloud-init.yaml at all, "
        "so the note points the next editor at a file that cannot be enforcing anything"
    )
