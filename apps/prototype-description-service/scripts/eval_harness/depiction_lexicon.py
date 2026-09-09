"""Canon depiction-lexicon injection for the bake-off A/B arm (VLM6-LEX).

The heuristics canon is a separate private repo. Its lexicons are never
vendored into this tree — the tracked snapshots were deleted at 54ef9bef and
must not be recreated. This module reads ``lexicons/depiction.md`` from a canon
checkout at RUN TIME, compiles the ATTRIB/BOUND rows into a system-prompt
addendum, and stamps the file's sha256 plus the canon tag into run-record
provenance, so a lexicon-on leg is reproducible without the rule text ever
landing in git.

The compiled block is a mechanical projection of the canon rows, not a rewrite:
each row's Rule cell already carries the canon's own condition -> action ->
consequence contract ("Reading a row" in the lexicon header), so the renderer
splits on that contract and drops only the columns aimed at engineers
(Trigger, Src) and the cross-lexicon ``↔`` tails that point at files this
addendum does not carry.

Injection point is the prose-writing pass only. Pass-1 of the two-pass pipeline
extracts objective JSON facts and asserts nothing about who is depicted, so it
stays untouched — the A/B delta is then attributable to the pass that actually
makes claims.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

LEXICON_RELPATH = "lexicons/depiction.md"

#: Canon families this loader knows how to project. Kept explicit so a canon
#: release that adds a third family fails loudly here instead of silently
#: shipping a partial rule set into a bake-off leg.
KNOWN_FAMILIES = ("ATTRIB", "BOUND")

#: Canon tier letters: Blocker, Should, Judgment.
KNOWN_TIERS = ("B", "S", "J")

DETAIL_LEVELS = ("full", "brief")

_FAMILY_HEADING_RE = re.compile(r"^##\s+\d+\.\s+([A-Z]{3,8})\s*:")
_ROW_ID_RE = re.compile(r"^\|\s*([A-Z]{3,8}-\d{2})\s*<a name=")
_ANCHOR_RE = re.compile(r"<a name=\"[^\"]*\"></a>")
_WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_RULE_LEAD_RE = re.compile(r"^\*\*(.+?)\*\*\s*:\s*(.*)$", re.DOTALL)


class LexiconError(RuntimeError):
    """The canon lexicon could not be read or does not match the expected shape.

    Raised loudly rather than degraded to an empty rule set: a silently empty
    addendum would turn the lexicon-on leg into a duplicate of the baseline and
    report a delta of zero as if it were a measurement.
    """


@dataclass(frozen=True)
class LexiconRule:
    """One canon row, projected into the parts a describing model can act on."""

    rule_id: str
    family: str
    name: str
    when: str
    do: str
    why: str
    check: str
    tier: str
    phases: tuple[str, ...]


@dataclass(frozen=True)
class DepictionLexicon:
    """A compiled, provenance-stamped projection of the canon depiction lexicon."""

    version: str
    source_path: str
    sha256: str
    families: tuple[str, ...]
    tiers: tuple[str, ...]
    detail: str
    rules: tuple[LexiconRule, ...]

    def render(self) -> str:
        """The system-prompt addendum appended to the prose-writing pass."""
        header = (
            f"Depiction rules ({self.version}, families {'+'.join(self.families)}, "
            f"{len(self.rules)} rules). These bound what your description may assert about "
            "the image and the people in it. Every sentence you write must satisfy all of "
            "them. Do not cite the rule identifiers in your output."
        )
        lines = [header, ""]
        for rule in self.rules:
            lines.append(f"[{rule.rule_id}] {rule.name}")
            lines.append(f"  When: {rule.when}")
            lines.append(f"  Then: {rule.do}")
            if self.detail == "full" and rule.why:
                lines.append(f"  Why: {rule.why}")
            lines.append(f"  Check: {rule.check}")
        return "\n".join(lines)

    def rule_count_summary(self) -> str:
        """Per-family rule counts, for the operator line printed before a run."""
        counts = {family: sum(1 for r in self.rules if r.family == family) for family in self.families}
        return ", ".join(f"{family} {count}" for family, count in counts.items())

    def provenance(self) -> dict[str, object]:
        """Run-record stamp: enough to re-derive this exact addendum, without the text."""
        return {
            "version": self.version,
            "source_path": self.source_path,
            "sha256": self.sha256,
            "families": list(self.families),
            "tiers": list(self.tiers),
            "detail": self.detail,
            "rule_ids": [r.rule_id for r in self.rules],
            "rule_count": len(self.rules),
            "rendered_chars": len(self.render()),
        }


def resolve_lexicon_path(raw: str | Path) -> Path:
    """Accept either the lexicon file itself or a canon checkout root."""
    path = Path(raw).expanduser()
    if path.is_dir():
        path = path / LEXICON_RELPATH
    if not path.is_file():
        raise LexiconError(f"depiction lexicon not found at {path} (pass the canon checkout root or the .md file)")
    return path


def load_depiction_lexicon(
    raw_path: str | Path,
    *,
    families: Sequence[str] | None = None,
    tiers: Sequence[str] | None = None,
    detail: str = "full",
    version: str | None = None,
) -> DepictionLexicon:
    """Read, parse and filter the canon lexicon into an injectable addendum."""
    if detail not in DETAIL_LEVELS:
        raise LexiconError(f"unknown lexicon detail {detail!r}; expected one of {list(DETAIL_LEVELS)}")
    path = resolve_lexicon_path(raw_path)
    text = path.read_text(encoding="utf-8")
    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    wanted_families = _validated(families, KNOWN_FAMILIES, "family") or KNOWN_FAMILIES
    wanted_tiers = _validated(tiers, KNOWN_TIERS, "tier") or KNOWN_TIERS

    parsed = _parse_rules(text, path)
    rules = tuple(r for r in parsed if r.family in wanted_families and r.tier in wanted_tiers)
    if not rules:
        raise LexiconError(
            f"{path} yielded no rules for families={list(wanted_families)} tiers={list(wanted_tiers)} "
            f"(parsed {len(parsed)} rows across {sorted({r.family for r in parsed})})"
        )
    return DepictionLexicon(
        version=version or _canon_version(path),
        source_path=str(path),
        sha256=sha256,
        families=tuple(f for f in wanted_families if any(r.family == f for r in rules)),
        tiers=tuple(t for t in wanted_tiers if any(r.tier == t for r in rules)),
        detail=detail,
        rules=rules,
    )


def _validated(values: Sequence[str] | None, allowed: Sequence[str], label: str) -> tuple[str, ...] | None:
    if values is None:
        return None
    upper = tuple(v.strip().upper() for v in values if v.strip())
    unknown = [v for v in upper if v not in allowed]
    if unknown:
        raise LexiconError(f"unknown lexicon {label} {unknown}; expected a subset of {list(allowed)}")
    return upper or None


def _parse_rules(text: str, path: Path) -> tuple[LexiconRule, ...]:
    rules: list[LexiconRule] = []
    family = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        heading = _FAMILY_HEADING_RE.match(line)
        if heading:
            family = heading.group(1)
            continue
        match = _ROW_ID_RE.match(line)
        if not match:
            continue
        if not family:
            raise LexiconError(f"{path}:{lineno}: rule row {match.group(1)} appears before any family heading")
        rules.append(_parse_row(line, family=family, path=path, lineno=lineno))
    if not rules:
        raise LexiconError(f"{path}: no rule rows found — the canon table shape changed, refusing to inject nothing")
    return tuple(rules)


def _parse_row(line: str, *, family: str, path: Path, lineno: int) -> LexiconRule:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != 6:
        raise LexiconError(f"{path}:{lineno}: expected 6 columns (ID|Trigger|Rule|Answers|T·P|Src), found {len(cells)}")
    rule_id = _clean(cells[0])
    rule_cell = _clean(cells[2])
    check = _clean(cells[3])
    tier, phases = _parse_tier_phase(_clean(cells[4]), path=path, lineno=lineno)

    lead = _RULE_LEAD_RE.match(rule_cell)
    if not lead:
        raise LexiconError(f"{path}:{lineno}: {rule_id} Rule cell has no **bold name**: lead")
    name = lead.group(1).replace("*", "").strip()
    body = lead.group(2).replace("*", "").strip()
    parts = [p.strip(" ;.") for p in body.split("->")]
    when = parts[0] if parts else ""
    do = parts[1] if len(parts) > 1 else ""
    why = parts[2] if len(parts) > 2 else ""
    if not when or not do:
        raise LexiconError(
            f"{path}:{lineno}: {rule_id} Rule cell does not carry the canon condition -> action contract"
        )
    return LexiconRule(
        rule_id=rule_id,
        family=family,
        name=name,
        when=when,
        do=do,
        why=why,
        check=check,
        tier=tier,
        phases=phases,
    )


def _parse_tier_phase(cell: str, *, path: Path, lineno: int) -> tuple[str, tuple[str, ...]]:
    tier, _, phase_part = cell.partition("·")
    tier = tier.strip().upper()
    if tier not in KNOWN_TIERS:
        raise LexiconError(f"{path}:{lineno}: unknown tier {tier!r} in T·P cell {cell!r}; expected {list(KNOWN_TIERS)}")
    phases = tuple(p for p in phase_part.strip().lower() if p in "dev")
    return tier, phases


def _clean(cell: str) -> str:
    """Strip the markdown scaffolding a describing model has no use for.

    Cross-lexicon ``↔`` tails point at rule files this addendum does not carry,
    so a model told to honour them would be citing rules it cannot read; they
    are dropped. In-lexicon ``[[ATTRIB-05]]`` references are flattened to the
    bare identifier because those rows ARE in the block.
    """
    out = _ANCHOR_RE.sub("", cell)
    out = out.split("↔")[0]
    out = _WIKI_LINK_RE.sub(r"\1", out)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = out.replace("`", "")
    return re.sub(r"\s+", " ", out).strip()


def _canon_version(path: Path) -> str:
    """Best-effort canon tag for provenance; the sha256 is the hard identity."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(path.parent), "describe", "--tags", "--always", "--dirty"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    tag = proc.stdout.strip()
    return f"canon {tag}" if proc.returncode == 0 and tag else "unknown"
