"""Cost-and-instrument pilot draw for DESCQUAL-2.

The ~30-image draw records inclusion probabilities, dual-annotator packets,
and gold-embedded QC. It does not estimate an intra-subject correlation or a
design effect; full-study n is pre-registered, not derived from this draw.
Unannotatable images are nonresponse to report, not a slot to refill
(AUDIT-13).
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from .audit_sampling import (
    Allocation,
    AuditSamplingError,
    Sample,
    allocate,
    draw,
    project_strata_image_counts,
)

BAKEOFF_SELECTION_SCHEMA = "bakeoff-selection/1"
GOLD_RATE_PERCENT = 10
PILOT_ANNOTATOR_SLOTS: tuple[str, str] = ("ann-01", "ann-02")
PILOT_GOLD_SME = "sme-gold"


class PilotDrawError(ValueError):
    """Invalid pilot-draw, packet, or gold-item inputs."""


class StratumName(StrEnum):
    A_TRUE_OCCLUDER = "A_true_occluder"
    B_EYEWEAR = "B_eyewear"
    C_POSE = "C_pose"
    D_CAPTURE = "D_capture"
    E_CLEAN = "E_clean"


class GoldKind(StrEnum):
    RANDOM = "random"
    BATCH_MATCHED = "batch_matched"
    HARD = "hard"


# HITL-03 three-way mix. Remainder after one-of-each is round-robin in this order.
GOLD_MIX_ORDER: tuple[GoldKind, ...] = (
    GoldKind.HARD,
    GoldKind.BATCH_MATCHED,
    GoldKind.RANDOM,
)


class GoldAnswerSource(StrEnum):
    OPERATOR_CONFIRMED_REFERENCE_FACTS = "operator_confirmed_reference_facts"
    SME_ARBITRATED = "sme_arbitrated"


HARD_STRATA: frozenset[StratumName] = frozenset(
    {StratumName.A_TRUE_OCCLUDER, StratumName.B_EYEWEAR}
)
_CAPTION_POOL_TOKENS = frozenset({"caption_pool", "caption-pool"})


def _require_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PilotDrawError(f"{name} must be an int, got {value!r}")
    return value


def _parse_stratum(raw: object, *, label: str) -> StratumName:
    if not isinstance(raw, str) or not raw:
        raise PilotDrawError(f"{label} must be a non-empty stratum name, got {raw!r}")
    try:
        return StratumName(raw)
    except ValueError:
        raise PilotDrawError(f"{label} names unknown stratum {raw!r}") from None


def _answer_source_token(raw: object) -> str:
    if isinstance(raw, GoldAnswerSource):
        return raw.value
    return str(raw)


@dataclass(frozen=True)
class GoldItem:
    """A known-answer QC image injected *in addition to* the probability sample."""

    sha256: str
    media_id: Hashable
    stratum: StratumName
    kind: GoldKind
    answer_source: GoldAnswerSource
    authored_by: str
    live_queue_annotators: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.sha256 or not str(self.sha256).strip():
            raise PilotDrawError("gold sha256 must be non-empty")
        object.__setattr__(self, "live_queue_annotators", tuple(self.live_queue_annotators))
        token = _answer_source_token(self.answer_source)
        if token in _CAPTION_POOL_TOKENS:
            raise PilotDrawError(
                "gold known answer must not come from the caption pool being judged "
                "(HITL-03)"
            )
        try:
            source = GoldAnswerSource(token)
        except ValueError:
            raise PilotDrawError(
                f"gold known answer source {token!r} is not an eligible provenance"
            ) from None
        object.__setattr__(self, "answer_source", source)
        author = self.authored_by.strip() if isinstance(self.authored_by, str) else ""
        if not author:
            raise PilotDrawError("gold authored_by must be a non-empty identifier")
        live = {slot for slot in self.live_queue_annotators if slot}
        if author in live:
            raise PilotDrawError(
                f"gold authored_by={author!r} is on the live annotation queue; "
                "known answers must be authored by an SME who will not annotate "
                "the live queue (HITL-03)"
            )


@dataclass(frozen=True)
class PilotDraw:
    sample: Sample
    allocation: Allocation
    seed: int
    frame_sizes: Mapping[str, int]
    declared_empty_cells: tuple[object, ...]
    declared_strata_counts: Mapping[str, int]
    frame_sha256s: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame_sizes", MappingProxyType(dict(self.frame_sizes)))
        object.__setattr__(
            self,
            "declared_strata_counts",
            MappingProxyType(dict(self.declared_strata_counts)),
        )
        object.__setattr__(self, "declared_empty_cells", tuple(self.declared_empty_cells))
        object.__setattr__(self, "frame_sha256s", frozenset(self.frame_sha256s))

    def report_rows(self) -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for stratum, n_h_declared in self.declared_strata_counts.items():
            n_h = int(self.allocation.get(stratum, 0))
            n_frame = n_h_declared
            pi = (n_h / n_frame) if n_frame else 0.0
            rows.append(
                {
                    "stratum": stratum,
                    "N_h": n_h_declared,
                    "n_h": n_h,
                    "inclusion_probability": pi,
                }
            )
        for cell in self.declared_empty_cells:
            rows.append({"declared_empty": cell})
        return tuple(rows)


def _load_selection_payload(selection_manifest_path: str | Path) -> dict[str, object]:
    path = Path(selection_manifest_path)
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise PilotDrawError(f"cannot read selection manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PilotDrawError(f"selection manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PilotDrawError(
            f"selection manifest must be a JSON object, got {type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != BAKEOFF_SELECTION_SCHEMA:
        raise PilotDrawError(
            f"selection manifest schema must be {BAKEOFF_SELECTION_SCHEMA!r}, "
            f"got {schema!r}"
        )
    if "declared_empty_cells" not in payload:
        raise PilotDrawError(
            "selection manifest missing declared_empty_cells "
            "(rg-015: pass through, never invent a default)"
        )
    if "strata_counts" not in payload:
        raise PilotDrawError("selection manifest missing strata_counts")
    if "entries" not in payload:
        raise PilotDrawError("selection manifest missing entries")
    return payload


def _parse_entries(
    entries: object,
) -> tuple[dict[str, list[str]], dict[str, Mapping[str, object]]]:
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise PilotDrawError(
            f"entries must be a sequence of objects, got {type(entries).__name__}"
        )
    if not entries:
        raise PilotDrawError("entries must be non-empty")
    members: dict[str, list[str]] = {name.value: [] for name in StratumName}
    by_sha: dict[str, Mapping[str, object]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise PilotDrawError(
                f"entries[{index}] must be an object, got {type(entry).__name__}"
            )
        if "sha256" not in entry:
            raise PilotDrawError(f"entries[{index}] missing sha256")
        sha256 = entry["sha256"]
        if not isinstance(sha256, str) or not sha256:
            raise PilotDrawError(
                f"entries[{index}]['sha256'] must be a non-empty str, got {sha256!r}"
            )
        if sha256 in by_sha:
            raise PilotDrawError(f"duplicate sha256 {sha256!r}")
        stratum = _parse_stratum(entry.get("stratum"), label=f"entries[{index}]['stratum']")
        if "media_id" not in entry:
            raise PilotDrawError(f"entries[{index}] missing media_id")
        if "source_path" not in entry:
            raise PilotDrawError(f"entries[{index}] missing source_path")
        source_path = entry["source_path"]
        if not isinstance(source_path, str) or not source_path:
            raise PilotDrawError(
                f"entries[{index}]['source_path'] must be a non-empty str, "
                f"got {source_path!r}"
            )
        if "present_identities" not in entry:
            raise PilotDrawError(f"entries[{index}] missing present_identities")
        identities = entry["present_identities"]
        if isinstance(identities, (str, bytes)) or not isinstance(identities, Sequence):
            raise PilotDrawError(
                f"entries[{index}]['present_identities'] must be a sequence, "
                f"got {type(identities).__name__}"
            )
        members[stratum.value].append(sha256)
        by_sha[sha256] = entry
    return members, by_sha


def draw_pilot(
    *,
    selection_manifest_path: str | Path,
    n: int,
    seed: int,
    precision_floors: Mapping[str, float] | None = None,
) -> PilotDraw:
    """Stratified probability sample of the frozen selection; ICC-blind (BR-17)."""
    n = _require_int("n", n)
    seed = _require_int("seed", seed)
    payload = _load_selection_payload(selection_manifest_path)
    declared_empty = payload["declared_empty_cells"]
    if not isinstance(declared_empty, list):
        raise PilotDrawError(
            "declared_empty_cells must be a JSON list, "
            f"got {type(declared_empty).__name__}"
        )
    try:
        declared_counts = project_strata_image_counts(payload["strata_counts"])  # type: ignore[arg-type]
    except AuditSamplingError as exc:
        raise PilotDrawError(f"strata_counts is not the declared FIR-12 shape: {exc}") from exc
    unknown_declared = set(declared_counts) - {name.value for name in StratumName}
    if unknown_declared:
        raise PilotDrawError(
            f"strata_counts names unknown strata: {sorted(unknown_declared)}"
        )
    members, by_sha = _parse_entries(payload["entries"])
    frame_sizes = {name: len(units) for name, units in members.items()}
    if frame_sizes != declared_counts:
        raise PilotDrawError(
            "entry counts per stratum do not match declared strata_counts "
            f"(entries={frame_sizes}, declared={dict(declared_counts)})"
        )
    allocation = allocate(
        strata_sizes=declared_counts,
        n=n,
        precision_floors=precision_floors,
    )
    sample = draw(strata_members=members, allocation=allocation, seed=seed)
    return PilotDraw(
        sample=sample,
        allocation=allocation,
        seed=seed,
        frame_sizes=frame_sizes,
        declared_empty_cells=tuple(declared_empty),
        declared_strata_counts=declared_counts,
        frame_sha256s=frozenset(by_sha),
    )


def emit_annotation_packet(
    *,
    pilot: PilotDraw,
    entries_by_sha256: Mapping[str, Mapping[str, object]],
    batch_id: str,
) -> tuple[dict[str, object], ...]:
    """One dual-annotator packet per drawn image; reference_facts start empty."""
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise PilotDrawError("batch_id must be a non-empty str")
    packets: list[dict[str, object]] = []
    for unit in pilot.sample.units:
        sha256 = str(unit.unit_id)
        if sha256 not in entries_by_sha256:
            raise PilotDrawError(f"drawn unit {sha256!r} missing from entries_by_sha256")
        entry = entries_by_sha256[sha256]
        if "media_id" not in entry:
            raise PilotDrawError(f"entry {sha256!r} missing media_id")
        if "source_path" not in entry:
            raise PilotDrawError(f"entry {sha256!r} missing source_path")
        packets.append(
            {
                "sha256": sha256,
                "media_id": entry["media_id"],
                "stratum": unit.stratum,
                "inclusion_probability": unit.inclusion_probability,
                "annotation_batch": batch_id,
                "source_path": entry["source_path"],
                "annotator_slots": [PILOT_ANNOTATOR_SLOTS[0], PILOT_ANNOTATOR_SLOTS[1]],
                "reference_facts": [],
            }
        )
    return tuple(packets)


def _is_hard_entry(entry: Mapping[str, object]) -> bool:
    stratum = _parse_stratum(entry.get("stratum"), label="entry['stratum']")
    if stratum in HARD_STRATA:
        return True
    identities = entry.get("present_identities")
    if isinstance(identities, (str, bytes)) or not isinstance(identities, Sequence):
        raise PilotDrawError("present_identities must be a sequence of names")
    return len(identities) >= 2


def _gold_count(n: int) -> int:
    """Gold is GOLD_RATE_PERCENT of the annotation QUEUE (sample + gold), not of the sample."""
    rate = GOLD_RATE_PERCENT / 100
    return round(n * rate / (1 - rate))


def _min_sample_n_for_gold_count(gold_n: int) -> int:
    sample_n = 0
    while _gold_count(sample_n) < gold_n:
        sample_n += 1
    return sample_n


def _plurality_stratum(pilot: PilotDraw) -> StratumName:
    counts: Counter[str] = Counter(unit.stratum for unit in pilot.sample.units)
    if not counts:
        raise PilotDrawError("cannot match gold to a plurality stratum on an empty sample")
    top = max(counts.values())
    tied = [name for name, count in counts.items() if count == top]
    return _parse_stratum(min(tied), label="plurality stratum")


def _pick_one(
    rng: random.Random,
    candidates: Sequence[str],
    *,
    used: set[str],
    kind: GoldKind,
) -> str:
    available = [sha for sha in candidates if sha not in used]
    if not available:
        raise PilotDrawError(
            f"not enough frame units outside the drawn sample to select gold kind {kind}"
        )
    chosen = rng.sample(available, 1)[0]
    used.add(chosen)
    return chosen


def select_gold_items(
    *,
    pilot: PilotDraw,
    entries_by_sha256: Mapping[str, Mapping[str, object]],
    seed: int,
) -> tuple[GoldItem, ...]:
    """10% gold, drawn from the frozen frame *outside* the probability sample."""
    seed = _require_int("seed", seed)
    n = len(pilot.sample.units)
    if n == 0:
        return ()
    gold_n = _gold_count(n)
    if gold_n < 1:
        raise PilotDrawError(
            f"gold rate {GOLD_RATE_PERCENT}% of n={n} selects zero units; "
            "a QC scheme that embeds no gold is not a QC scheme (HITL-03)"
        )
    mix_n = len(GOLD_MIX_ORDER)
    if gold_n < mix_n:
        kinds = ", ".join(kind.value for kind in GOLD_MIX_ORDER)
        min_n = _min_sample_n_for_gold_count(mix_n)
        raise PilotDrawError(
            f"gold_n={gold_n} from n={n} cannot cover the HITL-03 mix ({kinds}); "
            f"three gold items become available at n={min_n}"
        )
    foreign = sorted(sha for sha in entries_by_sha256 if sha not in pilot.frame_sha256s)
    if foreign:
        raise PilotDrawError(
            "entries_by_sha256 contains sha256 values not in the frozen frame: "
            f"{foreign}"
        )
    drawn = {str(unit.unit_id) for unit in pilot.sample.units}
    remaining = sorted(sha for sha in entries_by_sha256 if sha not in drawn)
    if len(remaining) < gold_n:
        raise PilotDrawError(
            "gold must be drawn from the frame outside the sample "
            f"(need {gold_n}, have {len(remaining)} remaining)"
        )
    for sha in remaining:
        if "media_id" not in entries_by_sha256[sha]:
            raise PilotDrawError(f"entry {sha!r} missing media_id")
        if "stratum" not in entries_by_sha256[sha]:
            raise PilotDrawError(f"entry {sha!r} missing stratum")
    plurality = _plurality_stratum(pilot)
    candidates_by_kind: dict[GoldKind, Sequence[str]] = {
        GoldKind.HARD: [sha for sha in remaining if _is_hard_entry(entries_by_sha256[sha])],
        GoldKind.BATCH_MATCHED: [
            sha
            for sha in remaining
            if _parse_stratum(entries_by_sha256[sha].get("stratum"), label="entry['stratum']")
            is plurality
        ],
        GoldKind.RANDOM: remaining,
    }
    mix = [(kind, candidates_by_kind[kind]) for kind in GOLD_MIX_ORDER]
    rng = random.Random(seed)
    used: set[str] = set()
    picked: list[tuple[GoldKind, str]] = []
    for kind, candidates in mix:
        picked.append((kind, _pick_one(rng, candidates, used=used, kind=kind)))
    extra = gold_n - len(picked)
    for offset in range(extra):
        kind, candidates = mix[offset % len(mix)]
        picked.append((kind, _pick_one(rng, candidates, used=used, kind=kind)))
    items: list[GoldItem] = []
    for kind, sha in picked:
        entry = entries_by_sha256[sha]
        items.append(
            GoldItem(
                sha256=sha,
                media_id=entry["media_id"],
                stratum=_parse_stratum(entry.get("stratum"), label="entry['stratum']"),
                kind=kind,
                answer_source=GoldAnswerSource.SME_ARBITRATED,
                authored_by=PILOT_GOLD_SME,
                live_queue_annotators=PILOT_ANNOTATOR_SLOTS,
            )
        )
    return tuple(items)
