"""FIR-7 Slice 0a: license allow/denylist as code constants + pure audit functions.

Pure constants and pure functions only. No network calls, no model downloads,
no filesystem scanning outside an explicitly passed-in manifest path.

Enforces commercial-clean provenance for occlusion training data, detector
ingest (Detector A/B + person→face cascade), occluder assets at pack-build,
and tooling dependencies (diagnostic, not training data).

Operator clearance: ``dcface_operator_clearance_20260723`` flips DCFace to
commercial-allowed; residual FFHQ/CASIA generator lineage is disclosed in the
informational ``generator_lineage`` field (exempt from research-source rejection).

Package-identity family matching (FIR-7 Wave F / F3 / F5 / F6 structural rule)
------------------------------------------------------------------------
``PACKAGE_DENYLIST`` seeds are matched by a **structural family-boundary**
rule (replaces the Wave-E size/task tag-strip treadmill, which could not
close an open-ended distribution-spelling space — decision
``cc_fir7_regate4_r0812_30c24d_verdict_fail_wave_f_structural``).

Core head-aligned rules on a token:

  (a) **exact match** on the folded (underscore-separated) or compact form;
  (b) **separator-boundary prefix**: canonical token == ``seed + '_' + rest``
      with non-empty ``rest`` (e.g. ``yolov8n_oiv7``, ``yolov7_tiny``,
      ``yolo_worldv2_s``);
  (c) **bounded compact remainder**: compact token starts with the seed's
      compact form and the remainder is ``[a-z0-9]{1,3}`` (e.g. ``yolov9t``,
      ``fastsamx``, ``yolo11n``). Longer remainders (``yolodummy``) and
      non-prefix tokens (``myyolo``) do **not** hit;
  (d) **head-segment** (legacy): leading ``_``-segment hits via (a) or (c)
      (e.g. ``yolov9t-seg``).

Deny-family matching adds one generalisation (FIR-7-B8-03):

  (e) **compact segment-suffix rule** (gated by
      ``_FAMILY_COMPACT_SUFFIX_ENABLED``): a single segment (or a whole
      one-segment compact token) whose compact form **ends with** a deny
      seed of ≥ 5 compact chars, with a non-empty leading remainder, hits
      that seed. Catches compact glue of a ≥ 5-char deny seed that is
      *not* an exception-prefix residual (``xultralytics``,
      ``yolox_xultralytics``). ``yoloxultralytics`` / ``yoloxsultralytics``
      are F12-1 steal-owned and still DENY when (e) is off. The ≥ 5 floor
      protects short seeds: ``myyolo`` ends with the 4-char seed ``yolo``
      and must still ADMIT.

Exception-family matching keeps (a)/(b)/(c)/(d) for strip targeting —
exception seeds are not matched via (e).

**No inner (d') deny walk** (FIR-7-A9-01 / A9-02 / B9-01): Wave F5's
per-suffix deny check used an inner generalised-suffix walk that hit
INNER ``yolox`` via bare ``yolo`` rule (c) before the outer walk's
exception check on that suffix — over-blocking vendor-prefix exception
forms (``megvii_yolox``, ``hustvl_yolos``, ``hustvl_yolop``,
``megvii_model_yolof``) with a false Ultralytics-AGPL note. The outer
separator-aligned suffix walk (gated by
``_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED``) already provides
suffix coverage, so the inner walk was redundant for deny and is
removed. ``_FAMILY_GENERALIZED_SUFFIX_ENABLED`` is deleted (verdict-dead:
flipping it alone changed zero path-split pins).

**Canonical fold** (FIR-7 F14-1 / F14-2 / F14-3 / F15): ``canonical()``
NFKC-normalises, strips Cf/format characters, then folds mid-token
ASCII whitespace (TAB/LF/CR/space) as official separators (F15-9:
``yolox\\ts`` / ``yolox\\ns`` → ``yolox_s`` admit) before fail-closing
on any remaining C0/C1 control (``yolo\\x00v8`` → ``invalid_row`` with
an honest control-character detail — never silently strip, never the
confusable-scripts text). Every remaining non-alphanumeric ASCII
character except ``/`` folds to ``_`` (total class rule; the F13-1
``+=:@|#`` enumeration is gone). Backslash is normalised to slash first
so it keeps path-component split. ``_`` runs collapse; edges strip.
Known model-file extensions (``.pt`` / ``.pdparams`` / ``.pdmodel`` /
…) strip per slash component before fold (F15-7:
``ppyoloe_plus_crn_s_80e_coco.pdparams`` admits). Before fold,
trailing registry tags ``:latest`` / ``:v0.3.0`` are stripped from
the last path component until none remain (R18-12 loop;
``yolox:latest`` / ``megvii/yolox:latest`` / ``yolox:v0.3.0`` /
``yolox:latest:latest`` admit as the bare family; ``yolo:latest``
strips then denies ``yolo``; ``yolox:s`` is not a registry tag
and folds to ``yolox_s``). A bare single-number tag (``:v8`` / ``:8`` / ``:v2``) is
**not** stripped (F15-3) — it folds to ``_v8`` / ``_8`` / ``_v2`` and
fail-closes as unknown residual, matching the compact twin ``yoloxv8``.
A nonblank identity that strips/folds to empty or slash-only
(``:latest`` / ``/`` / ``///`` / ``/:latest``) is ``invalid_row``
(F15-4); blank/whitespace-only input keeps the existing empty-field
behaviour. After fold, a ``pp`` segment immediately followed by a
``yolo*`` segment merges to ``ppyolo*`` when it is the component head
or is preceded by a known Paddle vendor (``PP-YOLOE+`` /
``PaddlePaddle/PP-YOLOE+`` / ``paddlepaddle_pp_yoloe`` → ``ppyoloe``
admit; ``pp_yolo`` → ``ppyolo`` admits; ``pp_yolov8`` → ``ppyolov8``
unknown residual denies). Deci ``pp_yolo_nas`` is not a PP-YOLO
residual — it carries the YOLO-NAS NC note (F15-10). ``ppyoloe+`` /
``yolox_s+trt`` admit; ``yolox~yolo`` / ``yolox+yolo`` deny; non-NFKC
dashes stay ``invalid_row``.

**Component-split-first** (FIR-7-A6-02): when the canonical form contains
``/``, family matching runs **only** on the individual slash components —
never on the joined full token. Testing the joined form first let bare
``yolo`` rule (b) bridge across the path separator (``yolo_nas/weights`` →
``yolo_`` + ``nas/weights``), falsely denying component-clean paths and
disagreeing with component-level exception/deny outcomes.

**Uniform component scanner** (FIR-7 Wave F5 / F6 / F7 / F8 / F9 / F10 / F11 / F12):
every slash component is scanned by one iterative **deny-first** suffix
walker (FIR-7-A10-02 / B11-01 / B12-1 / F10):

  1. For each separator-aligned suffix S of the current token (longest
     first):
     * **Elevated deny (a)/(b)/(c) first** — :func:`_deny_folded_ab_hit`
       evaluates (a), (b), and (c) independently (FIR-7-B12-1). Elevated
       deny-(c) closes pure compact deny debris whose rem after the deny
       seed fits ``[a-z0-9]{1,3}`` (``yolov9t`` / ``fastsamx``) **and**
       long-seed compact prefix glue (FIR-7-B13-5: ``ultralyticsplus`` —
       denylist stem length ≥
       ``_DENY_COMPACT_PREFIX_GLUE_MIN_SEED_LEN`` with non-empty alnum
       rem). DENY immediately **unless** an exception-family seed
       **claims** S (exact / separator / compact / head-segment / unbounded
       compact prefix). Folded (a)/(b) claims always win (``yolo_x`` /
       ``yolo_seg``) even when an exception compact spelling collides.
     * **Exception residual classification** (single mechanism, FIR-7 F10
       / F11 / F12 — flag ``_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED``).
       After an exception seed is stripped, every residual is classified
       without using length as a discriminator. Residual-(a) is
       **shape-aware** (A14-1):
         (a) **legitimate** — compact glue (no ``_``, or a head compact
             peel of a non-allowlisted rem — F12-2 ``yoloxpt_trt``):
             only per-family compact tags / the explicit compact-glue
             allowlist (empty except documented ``ppyolo`` / ``eplus``;
             F13-5 also peels that rem in head position so
             ``ppyoloeplus_trt`` admits). Separator residuals: family
             compact ∪ separator-only tags ∪ ``_NC_TRAILING_SHIELD_TAGS``
             (``trt`` / ``pt`` / ``bin`` / ``onnx`` / …). Compact glue of
             a shield or separator-only tag (``yoloxpt`` / ``yolostiny``)
             is **not** legitimate;
         (b) **deny-reconstituting** — progressive re-glue matches a
             deny claim that is not a fabricated ``yolo``-via-exception-
             letter hit (F12-7) → DENY with that claim's honest entry
             (``yolos_eg`` → ``yoloseg``; ``yolos_tiny_eg`` → ``yolo``);
         (c) **unknown residual** — fail-closed DENY with an honest
             unknown-residual note (NOT a fabricated Ultralytics
             attribution). Covers compact-glue deny (A14-1), long debris
             (``yolosegme`` / ``yolosfree``), tag+debris laundering
             (``yolox_tiny_eg`` / ``yolox_s_free``), short non-
             artifact rem (``yolox_z`` / ``yolos_ti``), and junk-prefix
             mid-token exception + unknown rem (F15-5:
             ``xyoloxsextra`` / ``myyoloxsextra`` →
             ``yolox_unknown_residual``; separator-aligned twins
             ``xyolox_z`` / ``xyolox_extra`` / ``xyolox_s_free``
             fail-close the same way — never None; ``ayoloxs`` /
             ``xyoloxs`` / ``xyolox_s`` / ``xyolox_tiny`` stay admit).
             R18-01: a deny/NC *stem* glued through
             1–3 junk + exception spelling (``fastsamxyoloxextra`` /
             ``arcfacexyoloxextra``) is owned by that stem — the
             skip is only for an exact folded deny/NC prefix so
             F14-6 / F15-2 stay sole-path (``arcfaceyoloxextra`` /
             ``yoloyoloxextra``).
       **B14-1 / F12-1 steal** is the same mechanism: when the residual
       came from unbounded compact prefix (walker cannot re-queue it)
       and has any deny hit — exact identity included (``yoloxyolo`` →
       ``yolo``) as well as glue / contained long seeds
       (``yoloxultralyticsplus`` → ``ultralytics``) — return that hit.
       Residual-alone deny seeds that the walker *can* re-queue
       (``yolox_ultralytics``) **defer** so attribution stays honest.
       Separator export tags (``yolox_trt`` / ``yolox_pt``) admit as (a).
     * Else exception-family hit → strip seed; pure-exception (empty
       residual) only continues to later suffixes — it never early-returns
       admit past un-scanned deny content (fixes
       ``yolox_xultralytics_yolox``); non-empty residual is queued for
       multi-strip continuation.
     * Else DENY-family hit on S via remaining (d)/(e) → component
       DENIES with that entry.
  2. Queued residuals are scanned by the **same** walker (multi-strip
     continuation). Double-exception compounds ``yolop_yolox`` /
     ``yolox_yolop`` ADMIT after successive pure-exception strips
     (FIR-7-B7-06).

**Per-family tags** (FIR-7-B12-3 / B12-4 / F10 / F12 / F13-4): each
exception seed has compact-(c) tags (fit the 1–3 alnum bound) **and**
separator-only tags (any length) reflecting real checkpoints —
``yolox``: s/m/l/x + nano/tiny/darknet/darknet53 + MMDetection
``8xb8``/``8x8``/``300e``/``coco``/``voc``; ``yolos``: tiny/small/base/large
(no compact single-letter sizes); ``yolof``: r50 + r101/c5/1x/3x/r/50/101/coco
+ ``8xb8``/``8x8`` (Detectron2 / MMDetection schedule / ``R_50`` spelling
/ dataset tag); ``yolop``: v2/v3; ``ppyolo``: e/v2 +
s/m/l/x/t/plus/tiny/large/small/sod/crn/r50vd/r18vd/r101vd/mbv3/dcn/300e/80e/1x/2x/365e/650e/coco
+ auxhead/relu/320/416/640/distill/voc/30e/60e/objects365
+ r/3x/dota (F15-8 PP-YOLOE-R rotate family; ``PP-YOLOE-R`` /
``ppyoloe_r_crn_s_3x_dota`` admit; compact glue ``ppyoloer`` /
``ppyolodota`` stay DENY; ``yolox_dota`` does not leak)
(PaddleDetection catalog). YOLOS single-letter size twins (``yolosx`` /
``yolosn`` / …) are NOT real hustvl sizes → deny; ``yoloxs`` stays
admitted. Compact glue of a separator-only tag stays DENY (A14-1 /
R14-G2-4: ``yoloxtiny`` / ``ppyoloes`` / ``yolox8xb8``). Export/format
tags from ``_NC_TRAILING_SHIELD_TAGS`` are legitimate **separator**
residuals for all families (``yolox_trt`` admits; ``yoloxpt`` denies).
Inventories are per-family — ``yolos_8xb8`` / ``yolox_auxhead`` deny
(``ppyolo_voc`` is native Paddle debris and admits as of F14-7).

Vendor-prefix underscore forms of pure exception seeds
(``megvii_yolox``, ``hustvl_yolos``, ``hustvl_yolop``,
``megvii_model_yolof``) ADMIT: the trailing exception suffix is pure-
exception (exact exception identity — elevated-(c) carve-out). Path-
split / size-tag shields (``yolox/s_ultralytics``, ``s_ultralytics``,
``yolox_xultralytics``) still DENY via the outer suffix walk + (e). Bare
exception seeds and their size/version forms (``yoloxs``, ``yolopv2``,
``yolos_tiny``, ``ppyoloe``) still ADMIT.

**AGPL compact-prefix glue** (FIR-7-B13-5): denylist stems of compact
length ≥ ``_DENY_COMPACT_PREFIX_GLUE_MIN_SEED_LEN`` with a non-empty
alnum remainder deny via elevated folded-compact machinery
(``ultralyticsplus`` / ``ultralytics_plus`` / ``ultralytics-plus``).
Short deny seeds (``yolo``, len 4) keep the 1–3 rem bound so
``yolodummy`` still admits. Multi-axis compounds with a real AGPL glue
hit report ``denylisted_package`` first; bare ``buffalo_l`` stays
``nc_model_derived``.

**Iterative fail-closed bounds** (FIR-7-B8-02 / B8-05 / B9-04): the walker
is an iterative loop, not recursion. Each successful strip must strictly
shrink total canonical length; the hard step cap equals the **initial
segment count** of the component. Exceeding the cap or a non-shrinking
strip is a **defensive invariant** that DENIES with ``denylisted_package``
(detail names the invariant) — never admit, never raise. The non-shrink
half is reachable when strip logic is wrong (or under test monkeypatch);
the hard-cap overflow half is a defensive belt — each counted strip
consumes ≥ 1 unit against a bound of initial segment count, so production
inputs with correct strip helpers do not overflow. Suite probes use a
synthetic ``max_steps`` / non-shrink fixture. Compact-remainder strips
shrink length, not necessarily segment count (``yolos_yoloxs``); the
bound is step-count ≤ initial segments, not "recursion depth ≤ segment
count".

So ``yolox`` / ``yolox_s`` / ``yolos`` / ``megvii_yolox`` admit (empty or
clean residual), while ``yolox_ultralytics`` / ``yolos_yolov8`` /
``yolox_s_ultralytics`` / ``yolox/s_ultralytics`` / ``yoloxultralytics``
DENY. An unbounded exception short-circuit that admitted the whole
component without residual re-scan was an admit bypass — fail-closed.

**NC-weights deny axis** (FIR-7-A6-03): Deci YOLO-NAS (``yolo_nas`` /
``yolonas``) is a **deny** seed, not an exception. Code is Apache-2.0 but
pretrained weights are non-commercial (Deci ``LICENSE.YOLONAS.md``) — the
same NC-weights axis already enforced for ``insightface`` / ``buffalo_l``.
Previously listing it as an Apache-2.0 exception was a policy error.

**Structural NC door matching** (FIR-7-B8-06 / B8-07 / B9-02 / F7): weights-
lineage doors (``audit_derived_from_model`` / ``audit_source``) keep exact
``NC_MODEL_IDS_EXPANDED`` membership first (BR-28 precision controls like
``not-insightface`` / ``buffalo_bill_detector`` stay load-bearing), then:

  1. **Bounded unknown-tag strip** (order-blind, hard bound 3): strip a
     trailing segment when it is a known export/quant/runtime tag
     (``_NC_TRAILING_SHIELD_TAGS``, including longer names like
     ``savedmodel``, ``coreml``, ``openvino``, ``tflite``, ``ncnn``,
     ``rknn``, ``tensorrt``, ``trt``, …) **or** a short tag of ≤ 4
     canonical chars; keep ≥ 1 leading segment; re-test exact membership
     after each strip. Closes ``yolo_nas_l_trt`` / ``buffalo_l_trt`` /
     ``yolo_nas_l_int8_trt`` (mixed order) without an open-ended tag
     treadmill. Bound overflow stops stripping — the un-stripped token
     admits only if its base truly is not NC (package-floor promotion
     still catches NC bases under tag floods; see item 3 below).
  2. **Membership outranks the covering-seed gate** (FIR-7-B10-03 /
     A10-03): after a successful bounded tag strip, if the residual head
     is a member of ``NC_MODEL_IDS_EXPANDED``, that **is** an NC match —
     return it. The covering-seed gate may only ADD precision for
     non-member residuals (export-shaped rest under a base seed); it
     must never veto a member. Closes compact heads of underscore-
     bearing seeds (``yolonasl_trt`` / ``buffalol2_trt`` / ``yolonas_int8``).
  3. when an exception-family component is present (structural,
     unbounded compact prefix — F12-3 — **or** mid-token compact
     occurrence — F14-4), promote a package-floor
     ``nc_model_derived`` hit so residual NC compounds
     (``yolox_s_buffalo_l`` / ``yoloxinsightface`` / ``yoloxyolo_nas`` /
     ``xyoloxinsightface`` / ``aabuffalo_l_yolox``) reject on the derived
     door too. Junk glued onto a multi-segment NC seed (``aabuffalo_l`` /
     ``aayolo_nas_l`` / ``aaantelope_v2``) and both-sides compact NC
     (``aainsightfaceaa`` / ``aaarcfaceaa``) now floor-deny via compact-
     joined rule (e) / mid-occurrence NC (F15-1). Doors still follow the
     exception-promotion rule, so BR-28 precision (``myarcface`` /
     ``not-insightface``) and junk+NC without an exception segment stay
     door-pass. Bare ``buffalo`` exclusions (``aabuffalo`` /
     ``buffalo_bill_detector`` / ``buffalo_lakes``) still admit.
  4. **Multi-axis door promotion** (FIR-7-A10-01 / B11-02): doors consider
     **all** floor hits in a compound, not just the ranked winner. If any
     suffix/component hits an AGPL/``denylisted_package`` entry, reject
     with that entry's honest note; if any hits an NC entry, reject
     ``nc_model_derived`` with the NC entry's note. When **both** axes
     are present, precedence is **AGPL / ``denylisted_package`` first**
     (distribution-channel taint is independently disqualifying and must
     not be shadowed by a longer NC seed ranking win) — never admit, and
     never attribute one lineage's residue to the other's note. Closes
     ``buffalo_l_ultralytics`` / ``arcface_ultralytics`` /
     ``retinaface_yolov8`` etc. **Membership-path precedence** (B11-02):
     when ``match_nc_model_pattern`` hits (exact / slash / tag-strip /
     exception-residual membership), doors still consult multi-axis
     floor promotion; an AGPL hit anywhere in the compound wins over the
     NC membership reason so path dual-axis forms
     (``ultralytics/buffalo_l``, ``yolov8/arcface``) and exception-
     shielded dual-axis forms (``yolox_s_buffalo_l_ultralytics``) report
     ``denylisted_package`` with the AGPL entry's note — never an NC-only
     note that hides Ultralytics residue.
  5. **Derived/source package-floor parity** (FIR-7-B9-02 / B10-04): both
     doors promote whole-component package-floor hits on the NC axis
     for every floor-hit shape — exact (a), export-shaped (b) (any-length
     run of known shield tags, so tag-flood cannot launder), and bounded
     compact (c) — on any separator-aligned suffix. BR-28 ``not_<seed>``
     forms (single leading segment ``not``) stay carved out so
     ``not-insightface`` / ``not-retinaface`` remain admitted on doors
     (the seed sits as a pure suffix with leading alpha glue ``not_`` at
     a separator — deliberate door-precision posture, not a floor miss;
     package/row floor still rejects). Compact (e) glue is still not
     promoted on this path.
  6. **Derived NC-axis package floor** (FIR-7-B10-01 / B10-02 / B10-05):
     NC-axis ``PACKAGE_DENYLIST`` entries are **generated** from the
     canonical NC id surface (``_PINNED_NC_MODEL_IDS`` ∪
     ``_NC_EXPLICIT_VARIANTS`` ∪ the Deci ``yolo_nas`` base stem ∪ the
     Deci SuperGradients framework identity), covering
     both underscore and compact spellings of every id, **minus** an
     explicit exclusion set. Bare ``buffalo`` stays excluded —
     ``buffalo_bill_detector`` must admit; real InsightFace packs are
     ``buffalo_l`` / ``buffalo_s`` / ``buffalo_sc`` / ``buffalo_l2``.
     ``cosface`` / ``magface`` are **deliberately excluded** from the NC
     surface (MagFace is Apache-2.0; CosFace is an algorithm name with
     permissive implementations) — not a gap. ``scrfd`` (InsightFace
     detector family inside antelopev2/buffalo packs; NC weights) **is**
     on the pinned surface and flows through the generator so floors,
     doors, and rows agree. Each generated entry carries its lineage's
     honest note from ``_NC_MODEL_DETAIL_NOTES``. Compact (e) over-block
     of ``myarcface`` (arcface ≥ 5 compact chars) is deliberate.

**Honest lineage notes** (FIR-7-B6-02 / B9-03 / B11-05 / B11-06):
``yolop`` is hustvl BSD-3-Clause (exception); ``yolov2`` / ``yolov4`` are
Darknet-era deny seeds with their own notes so they stop inheriting the
false Ultralytics-AGPL text from bare ``yolo``. **PP-YOLO** (``ppyolo`` /
``ppyoloe`` / ``ppyolov2``) is Baidu PaddleDetection Apache-2.0 — an
exception-family seed so ``ppyolov2`` is not false-denied via compact
suffix on Darknet ``yolov2``. YOLOR (WongKinYiu, GPL-3.0) remains a
deny-axis seed. Membership-door notes resolve through the same compact-
aware per-lineage table the floor generator uses, so compact and
underscore spellings of one id (``yolonasposel`` / ``yolo_nas_pose_l``)
carry identical notes. The ``insightface`` seed has its own zoo wording
(not buffalo-pack boilerplate).

Precedence per component: deny (a)/(b)/(c) (with legitimate exception-
boundary carve-out) → exception-family strip (illegitimate compact
exception steals of deny-seed extensions fail closed as the deny seed)
→ residual / suffix deny re-scan (d)/(e) → residual deny or direct
deny-family hit → ``denylisted_package`` (or the entry's reason, e.g.
``nc_model_derived`` for NC-weights); clean exception or neither → no
hit (admit path continues to other floors). The two seed sets are
asserted **disjoint** at import on exact folded/compact keys (fail
loudly if not).

Package-identity values that are non-empty pre-canonical but whose
:func:`canonical` is ``None`` (confusable / non-ASCII residue, or a
real C0/C1 control such as NUL) or empty / slash-only (Cf-format-only:
ZWSP, BOM, word-joiner; **or** a nonblank spelling that strips to
nothing: ``:latest`` / ``/`` / ``///`` / ``/:latest`` — F15-4) are
fail-closed ``invalid_row`` on row doors and both scalar doors
(FIR-7-B4-01 / B5-04 / F15-4). C0/C1 details name a control character;
confusable-script residue keeps the non-ASCII note (F15-9).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Enums (sr-007 — no magic-string verdicts/categories)
# ---------------------------------------------------------------------------


class PolicyCategory(StrEnum):
    """Policy surface a row or package is evaluated under."""

    TRAINING_DATA = "training_data"
    TOOLING = "tooling"
    MODEL_INGEST = "model_ingest"
    OCCLUDER_ASSET = "occluder_asset"
    SYNTHETIC_SOURCE = "synthetic_source"


class LicenseVerdict(StrEnum):
    """Pass/fail outcome of a license audit."""

    PASS = "pass"
    FAIL = "fail"


class RejectionReason(StrEnum):
    """Machine-checkable rejection reasons (asserted by RED-capable tests)."""

    NC_MODEL_DERIVED = "nc_model_derived"
    RESEARCH_ONLY_SOURCE = "research_only_source"
    RESEARCH_ONLY_LICENSE = "research_only_license"
    PENDING_LEGAL_CLEARANCE = "pending_legal_clearance"
    UNCLEARED_OCCLUDER_ASSET = "uncleared_occluder_asset"
    DENYLISTED_LICENSE = "denylisted_license"
    DENYLISTED_PACKAGE = "denylisted_package"
    MISSING_INGEST_ENTRY = "missing_ingest_entry"
    MISSING_LICENSE_FIELD = "missing_license_field"
    UNKNOWN_SPDX = "unknown_spdx"
    UNKNOWN_SOURCE = "unknown_source"
    INVALID_ROW = "invalid_row"
    UNREGISTERED_DERIVED_MODEL = "unregistered_derived_model"


class ClearanceStatus(StrEnum):
    """Clearance state for synthetic sources and assets."""

    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_LEGAL_CLEARANCE = "pending_legal_clearance"
    OPERATOR_CLEARED = "operator_cleared"
    UNCLEARED = "uncleared"
    CLEARED = "cleared"
    LICENSE_CLEARED = "license_cleared"


class CommercialUse(StrEnum):
    """Commercial-use classification for registered entries."""

    ALLOWED = "allowed"
    NON_COMMERCIAL = "non_commercial"
    FORBIDDEN = "forbidden"


class DetectorRole(StrEnum):
    """Role of a registered model-ingest entry."""

    FACE_DETECTOR = "face_detector"
    PERSON_DETECTOR = "person_detector"
    FACE_EMBEDDER = "face_embedder"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LicenseAuditResult:
    """Outcome of a pure license-policy check."""

    verdict: LicenseVerdict
    reason: RejectionReason | None = None
    detail: str = ""
    category: PolicyCategory | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is LicenseVerdict.PASS


def _pass(
    *,
    detail: str = "",
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    return LicenseAuditResult(
        verdict=LicenseVerdict.PASS,
        detail=detail,
        category=category,
    )


def _fail(
    reason: RejectionReason,
    *,
    detail: str = "",
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    return LicenseAuditResult(
        verdict=LicenseVerdict.FAIL,
        reason=reason,
        detail=detail,
        category=category,
    )


class LicensePolicyError(Exception):
    """Raised when a caller requests a hard fail-closed audit (sr-006)."""

    def __init__(self, result: LicenseAuditResult) -> None:
        self.result = result
        message = result.detail or (
            result.reason.value if result.reason is not None else "license policy failure"
        )
        super().__init__(message)


# ---------------------------------------------------------------------------
# SPDX allow / deny lists (stored casefolded for SPDX case-insensitive rules)
# ---------------------------------------------------------------------------

# Commercially usable SPDX identifiers accepted for training data, model ingest,
# and occluder assets (after other gates). Canonical display forms kept for
# documentation; comparisons use the casefolded frozensets.
ALLOWED_SPDX_IDS: frozenset[str] = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "CC-BY-4.0",
        "ISC",
        "Zlib",
        "Unlicense",
        # NOTE: ``self-generated`` is a *source* value, not an SPDX licence tag.
        # It must not appear here (BR-25); see OCCLUDER_REGISTERED_SOURCES /
        # _POSITIVE_TRAINING_SOURCES.
    }
)

# Explicitly rejected SPDX / license tags (AGPL, NC, research-only).
DENYLISTED_SPDX_IDS: frozenset[str] = frozenset(
    {
        "AGPL-3.0",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "GPL-3.0",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "CC-BY-NC-4.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-NC-ND-4.0",
        "Non-Commercial",
        "non-commercial",
        "research-only",
        "NC",
        "proprietary-nc",
    }
)

ALLOWED_SPDX_IDS_CF: frozenset[str] = frozenset(x.casefold() for x in ALLOWED_SPDX_IDS)
DENYLISTED_SPDX_IDS_CF: frozenset[str] = frozenset(x.casefold() for x in DENYLISTED_SPDX_IDS)

# NC-family tags map to RESEARCH_ONLY_LICENSE rather than DENYLISTED_LICENSE.
_RESEARCH_ONLY_LICENSE_CF: frozenset[str] = frozenset(
    {
        "research-only",
        "non-commercial",
        "nc",
        "proprietary-nc",
        "cc-by-nc-4.0",
        "cc-by-nc-sa-4.0",
        "cc-by-nc-nd-4.0",
    }
)

# Training-data / corpus sources that taint commercial use when present in
# the row ``source`` (or ``license`` tag) field. ``generator_lineage`` is NOT
# checked against this set — it is informational only.
#
# Matching is exact membership against the import-time expanded frozenset
# ``RESEARCH_SOURCE_IDS_EXPANDED`` (B4b / WEB-24 / SECD-05). Shape-inference
# (progressive prefixes, startswith, version-segment regexes) is intentionally
# absent: expand the trusted registry, never the untrusted input.
RESEARCH_ONLY_SOURCES: frozenset[str] = frozenset(
    {
        "widerface",
        "wider_face",
        "mfr",
        "rmfrd",
        "casia",
        "casia-webface",
        "ffhq",
        "webface",
        "webface260m",
        "vggface2",
        "celeba",
        "ms1m",
        "ms-celeb-1m",
        "glint360k",
        "deepglint",
    }
)


# ---------------------------------------------------------------------------
# PINNED non-commercial model id seeds (buffalo OUTPUT ban wall 1)
# ---------------------------------------------------------------------------

# Patterns retained as declarative seeds for documentation + M2 discrimination.
# Matching no longer walks glob/prefix shape on untrusted input (B4b); seeds
# feed ``NC_MODEL_IDS`` / ``NC_MODEL_IDS_EXPANDED`` at import time.
NC_MODEL_PATTERNS: tuple[str, ...] = (
    "insightface/*",
    "insightface",
    "buffalo*",
    "buffalo",
)

# Extra pinned NC model ids beyond table-derived entries (ArcFace ecosystem
# weights that are non-commercial but not always present as registry rows).
# Explicit multi-segment variants live in ``_NC_EXPLICIT_VARIANTS`` so the
# matcher never infers them from spelling shape.
_PINNED_NC_MODEL_IDS: frozenset[str] = frozenset(
    {
        "buffalo",
        "buffalo_s",
        "buffalo_sc",
        "buffalo_l",
        "buffalo_l2",
        "retinaface",
        "arcface",
        "antelopev2",
        "insightface",
        # InsightFace SCRFD detector family (FIR-7-B10-05 / A10-07): the
        # detector inside antelopev2 / buffalo packs; NC weights. Flows
        # through the derived NC floor generator so rows + doors agree.
        "scrfd",
        # vec2face synthetic-face NC lineage (also a SYNTHETIC_SOURCE entry;
        # pinned here so the floor generator cannot drift from the NC
        # surface when synthetic clearance state changes).
        "vec2face",
        # Deci YOLO-NAS real weight variants (FIR-7-A7-01). Package-floor
        # structural match already denies yolo_nas_* compounds; pin the
        # weights-lineage doors (derived_from_model / source) to the same
        # real Deci size/pose set buffalo already has for its packs.
        "yolo_nas_s",
        "yolo_nas_m",
        "yolo_nas_l",
        "yolo_nas_pose_n",
        "yolo_nas_pose_s",
        "yolo_nas_pose_m",
        "yolo_nas_pose_l",
    }
)

# Deliberate NC-surface exclusions (FIR-7-A10-07) — NOT gaps:
#   * cosface — algorithm name; permissive (often Apache/MIT) implementations
#     exist outside InsightFace NC weight packs.
#   * magface — MagFace upstream is Apache-2.0 (verified); not an NC seed.
# Reviewers: do not "fix" these onto the pinned surface without a new
# licence adjudication.
_NC_SURFACE_DELIBERATE_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "cosface",
        "magface",
    }
)

# Per-entry NC lineage notes for audit detail text (FIR-7-B7-04).
# ``audit_derived_from_model`` interpolates the matched id + this note so
# each NC rejection names its own lineage (buffalo keeps historical
# wording; yolo_nas gets honest Deci NC-weights text — never cross-talk).
_NC_MODEL_DETAIL_NOTES: dict[str, str] = {
    "buffalo": "buffalo weights and output-derived data are banned",
    "buffalo_s": "buffalo weights and output-derived data are banned",
    "buffalo_sc": "buffalo weights and output-derived data are banned",
    "buffalo_l": "buffalo weights and output-derived data are banned",
    "buffalo_l2": "buffalo weights and output-derived data are banned",
    "insightface": (
        "InsightFace model zoo weights and output-derived data are banned"
    ),
    "retinaface": (
        "InsightFace RetinaFace weights and output-derived data are banned"
    ),
    "arcface": "InsightFace ArcFace weights and output-derived data are banned",
    "antelopev2": (
        "InsightFace antelopev2 weights and output-derived data are banned"
    ),
    "antelope_v2": (
        "InsightFace antelopev2 weights and output-derived data are banned"
    ),
    "scrfd": (
        "InsightFace SCRFD detector weights and output-derived data are banned"
    ),
    # Prefix rule covers yolo_nas_* size/pose/export variants (FIR-7-A8-04).
    "yolo_nas": (
        "Deci YOLO-NAS pretrained weights are non-commercial "
        "(Deci licence); NC-weights and output-derived data are banned"
    ),
    "super_gradients": (
        "Deci SuperGradients framework (YOLO-NAS training stack) is "
        "non-commercial (Deci licence); NC-weights and output-derived "
        "data are banned"
    ),
    # vec2face NC synthetic-face lineage (FIR-7-A8-04) — was falling through
    # to the generic fallback despite being a first-class NC seed.
    "vec2face": (
        "vec2face synthetic-face weights and output-derived data are banned"
    ),
}

# Explicit NC forms that must fail but are not a single common-suffix hop from
# a seed (multi-segment InsightFace pack / backbone tags).
_NC_EXPLICIT_VARIANTS: frozenset[str] = frozenset(
    {
        "insightface_buffalo_l",
        "insightface_buffalo_s",
        "insightface_buffalo_sc",
        "insightface_buffalo_l2",
        "retinaface_r50",
        "retinaface_mnet025",
        "retinaface_mnet025_v2",
        "arcface_r100",
        "arcface_glint360k_r100",
        "vec2face_g1",
        "antelope_v2",
        # SCRFD real weight ids (FIR-7-B10-05) — multi-segment so the floor
        # generator + door suffix walk cover myprefix_scrfd_10g_kps etc.
        "scrfd_10g_kps",
        "scrfd_10g",
        "scrfd_2.5g",
        "scrfd_2_5g",
        # Bare buffalo is floor-excluded (buffalo_bill_detector); pin the
        # measured export-tag package-row witnesses explicitly (FIR-7-B10-01).
        "buffalo_trt",
        "buffalo_int8",
        "buffalo_onnx",
        "buffalo_fp16",
        "buffalo_pt",
    }
)


# ---------------------------------------------------------------------------
# Registered entries (named ingest / tooling / synthetic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationMetadata:
    """Pinned verification metadata for a registered policy entry."""

    spdx_id: str
    commercial_use: CommercialUse
    source_url: str = ""
    source_ref: str = ""
    verified_at: str = ""
    notes: str = ""
    clearance_decision: str = ""


@dataclass(frozen=True, slots=True)
class ModelIngestEntry:
    """Named detector / cascade person-detector ingest registration."""

    model_id: str
    display_name: str
    role: DetectorRole
    verification: VerificationMetadata
    category: PolicyCategory = PolicyCategory.MODEL_INGEST


@dataclass(frozen=True, slots=True)
class ToolingEntry:
    """Diagnostic / offline tooling dependency (not training data)."""

    package_name: str
    verification: VerificationMetadata
    category: PolicyCategory = PolicyCategory.TOOLING


@dataclass(frozen=True, slots=True)
class SyntheticSourceEntry:
    """Synthetic-identity source clearance state."""

    source_id: str
    verification: VerificationMetadata
    category: PolicyCategory = PolicyCategory.SYNTHETIC_SOURCE


@dataclass(frozen=True, slots=True)
class PackageDenylistEntry:
    """Explicitly denylisted package / framework (e.g. Ultralytics AGPL)."""

    package_id: str
    display_name: str
    spdx_id: str
    reason: RejectionReason
    notes: str = ""


@dataclass(frozen=True, slots=True)
class PackageExceptionEntry:
    """Distinct-lineage package admitted despite overlapping YOLO naming.

    Exception seeds use structural family-boundary rules (a)/(b)/(c) plus
    local head-segment for strip targeting, with **bounded admit**
    semantics: an exception hit strips the exception seed and re-scans the
    residual via the uniform iterative suffix walker (exception-first, then
    DENY rules (a)/(b)/(c)/(d')/(e) — FIR-7-B6-01 / B7-01 / B8-01). A
    residual deny hit DENIES the component; an empty residual or residual
    with no deny hit admits. Other floors still apply after an admit.
    """

    package_id: str
    display_name: str
    spdx_id: str
    notes: str = ""


# Detector A/B (face detectors) + person→face cascade person-detectors.
# Each candidate has a named entry verified at ingest — not QA-doc prose alone.
MODEL_INGEST_ENTRIES: dict[str, ModelIngestEntry] = {
    "mediapipe_blazeface": ModelIngestEntry(
        model_id="mediapipe_blazeface",
        display_name="MediaPipe BlazeFace",
        role=DetectorRole.FACE_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/google-ai-edge/mediapipe",
            source_ref="mediapipe-blazeface",
            verified_at="2026-07-23",
            notes="Detector A drop-in; Apache-2.0 MediaPipe face detector.",
        ),
    ),
    "paddle_blazeface_fpn_ssh": ModelIngestEntry(
        model_id="paddle_blazeface_fpn_ssh",
        display_name="Paddle BlazeFace-FPN-SSH",
        role=DetectorRole.FACE_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/PaddlePaddle/PaddleDetection",
            source_ref="blazeface_fpn_ssh",
            verified_at="2026-07-23",
            notes="Detector B drop-in; PaddleDetection BlazeFace-FPN-SSH.",
        ),
    ),
    "rt_detr": ModelIngestEntry(
        model_id="rt_detr",
        display_name="RT-DETR",
        role=DetectorRole.PERSON_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/lyuwenyu/RT-DETR",
            source_ref="rtdetr",
            verified_at="2026-07-23",
            notes="Cascade person-detector; Apache-verified route around Ultralytics.",
        ),
    ),
    "d_fine": ModelIngestEntry(
        model_id="d_fine",
        display_name="D-FINE",
        role=DetectorRole.PERSON_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/Peterande/D-FINE",
            source_ref="d-fine",
            verified_at="2026-07-23",
            notes="Cascade person-detector; Apache-verified.",
        ),
    ),
    "pp_picodet": ModelIngestEntry(
        model_id="pp_picodet",
        display_name="PP-PicoDet",
        role=DetectorRole.PERSON_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/PaddlePaddle/PaddleDetection",
            source_ref="picodet",
            verified_at="2026-07-23",
            notes="Cascade person-detector; PaddleDetection PicoDet Apache-2.0.",
        ),
    ),
    # Base stack (already owned; registered so ingest of the base path is explicit).
    "yunet": ModelIngestEntry(
        model_id="yunet",
        display_name="YuNet",
        role=DetectorRole.FACE_DETECTOR,
        verification=VerificationMetadata(
            spdx_id="MIT",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/opencv/opencv_zoo",
            source_ref="face_detection_yunet",
            verified_at="2026-07-23",
            notes="OpenCV Zoo YuNet base detector.",
        ),
    ),
    "sface": ModelIngestEntry(
        model_id="sface",
        display_name="SFace",
        role=DetectorRole.FACE_EMBEDDER,
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/opencv/opencv_zoo",
            source_ref="face_recognition_sface",
            verified_at="2026-07-23",
            notes="OpenCV Zoo SFace base embedder.",
        ),
    ),
}

# Ultralytics and other AGPL / NC / GPL frameworks — route cascade around these.
# Matching uses the structural family-boundary rule (module docstring / Wave F):
# exact folded/compact match, separator-boundary prefix, or bounded compact
# remainder. Distinct-lineage YOLO names live in PACKAGE_EXCEPTION_ALLOWLIST
# (admit-family seeds), not here — the two seed sets must stay disjoint.
PACKAGE_DENYLIST: dict[str, PackageDenylistEntry] = {
    "ultralytics": PackageDenylistEntry(
        package_id="ultralytics",
        display_name="Ultralytics YOLO",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="AGPL-3.0; person→face cascade must use RT-DETR / D-FINE / PP-PicoDet.",
    ),
    "yolo": PackageDenylistEntry(
        package_id="yolo",
        display_name="YOLO (Ultralytics family)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL family alias; banned for cascade person-detection.",
    ),
    # Darknet-era lineage (not Ultralytics). Own seeds so they stop inheriting
    # the false Ultralytics-AGPL note from bare ``yolo`` compact remainder
    # (FIR-7-B6-02). Denied as a deliberate fail-closed posture on ambiguous
    # identity / GPL-family channel.
    "yolov2": PackageDenylistEntry(
        package_id="yolov2",
        display_name="YOLOv2 (Darknet-era)",
        spdx_id="GPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=(
            "Darknet-era lineage, not Ultralytics; denied as a deliberate "
            "fail-closed posture on ambiguous identity/GPL-family channel."
        ),
    ),
    # Darknet origin; Ultralytics fork is one common identity. Fail-closed on
    # ambiguous identity / AGPL-distribution channel (FIR-7-B3-02).
    "yolov3": PackageDenylistEntry(
        package_id="yolov3",
        display_name="YOLOv3 (Darknet / Ultralytics fork)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=(
            "Darknet origin; Ultralytics fork is one identity. Fail-closed on "
            "ambiguous identity / AGPL-distribution channel."
        ),
    ),
    # Darknet-era lineage (not Ultralytics). Own seed so compact remainder on
    # bare ``yolo`` cannot attach the false Ultralytics-AGPL note (FIR-7-B6-02).
    "yolov4": PackageDenylistEntry(
        package_id="yolov4",
        display_name="YOLOv4 (Darknet-era)",
        spdx_id="GPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=(
            "Darknet-era lineage, not Ultralytics; denied as a deliberate "
            "fail-closed posture on ambiguous identity/GPL-family channel."
        ),
    ),
    "yolov5": PackageDenylistEntry(
        package_id="yolov5",
        display_name="YOLOv5 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL-3.0 lineage; banned for cascade person-detection.",
    ),
    # Meituan YOLOv6 — GPL-3.0 upstream (not Ultralytics AGPL). Still denied:
    # GPL-3.0 is a deny-axis licence (FIR-7-B3-02).
    "yolov6": PackageDenylistEntry(
        package_id="yolov6",
        display_name="YOLOv6 (Meituan)",
        spdx_id="GPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Meituan YOLOv6, GPL-3.0 upstream; denied on GPL-3.0 axis.",
    ),
    # WongKinYiu YOLOv7 — GPL-3.0 upstream (not Ultralytics AGPL). Still denied
    # on the GPL-3.0 deny-axis (FIR-7-B3-02).
    "yolov7": PackageDenylistEntry(
        package_id="yolov7",
        display_name="YOLOv7 (WongKinYiu)",
        spdx_id="GPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="WongKinYiu YOLOv7, GPL-3.0 upstream; denied on GPL-3.0 axis.",
    ),
    "yolov8": PackageDenylistEntry(
        package_id="yolov8",
        display_name="YOLOv8 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL-3.0 lineage; banned for cascade person-detection.",
    ),
    # Ultralytics YOLOv8 size-tag model ids (n/s/m/l/x) — genuine package tokens.
    "yolov8n": PackageDenylistEntry(
        package_id="yolov8n",
        display_name="YOLOv8n (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLOv8 nano size tag; AGPL-3.0 lineage.",
    ),
    "yolov8s": PackageDenylistEntry(
        package_id="yolov8s",
        display_name="YOLOv8s (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLOv8 small size tag; AGPL-3.0 lineage.",
    ),
    "yolov8m": PackageDenylistEntry(
        package_id="yolov8m",
        display_name="YOLOv8m (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLOv8 medium size tag; AGPL-3.0 lineage.",
    ),
    "yolov8l": PackageDenylistEntry(
        package_id="yolov8l",
        display_name="YOLOv8l (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLOv8 large size tag; AGPL-3.0 lineage.",
    ),
    "yolov8x": PackageDenylistEntry(
        package_id="yolov8x",
        display_name="YOLOv8x (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLOv8 xlarge size tag; AGPL-3.0 lineage.",
    ),
    "yolov9": PackageDenylistEntry(
        package_id="yolov9",
        display_name="YOLOv9 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL-3.0 lineage; banned for cascade person-detection.",
    ),
    # THU-MIG YOLOv10 — Apache-2.0 upstream, commonly consumed via the AGPL
    # ultralytics package. Fail-closed on ambiguous identity / AGPL-distribution
    # channel (FIR-7-B3-02).
    "yolov10": PackageDenylistEntry(
        package_id="yolov10",
        display_name="YOLOv10 (THU-MIG / Ultralytics channel)",
        spdx_id="Apache-2.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=(
            "THU-MIG Apache-2.0 upstream; commonly consumed via AGPL ultralytics. "
            "Fail-closed on ambiguous identity / AGPL-distribution channel."
        ),
    ),
    "yolo11": PackageDenylistEntry(
        package_id="yolo11",
        display_name="YOLO11 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL-3.0 lineage; banned for cascade person-detection.",
    ),
    # Compact form of yolo11 is yolo11; yolov11 is a distinct spelling (v infix).
    "yolov11": PackageDenylistEntry(
        package_id="yolov11",
        display_name="YOLOv11 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLOv11 spelling (v-infix); AGPL-3.0 lineage.",
    ),
    "yolo12": PackageDenylistEntry(
        package_id="yolo12",
        display_name="YOLO12 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLO12 lineage; AGPL-3.0.",
    ),
    # Post-canonical seed: canonical("yolo-world") == "yolo_world".
    "yolo_world": PackageDenylistEntry(
        package_id="yolo_world",
        display_name="YOLO-World (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics YOLO-World; AGPL-3.0 lineage.",
    ),
    "fastsam": PackageDenylistEntry(
        package_id="fastsam",
        display_name="FastSAM (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics FastSAM; AGPL-3.0 lineage.",
    ),
    # Seed key is the post-canonical form: canonical("yolo-v8") == "yolo_v8".
    # Compact fold also maps this onto the yolov8 seed (FIR-7-B3-01).
    "yolo_v8": PackageDenylistEntry(
        package_id="yolo_v8",
        display_name="YOLO v8 (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL family spelling variant (yolo_v8 / yolo-v8); banned.",
    ),
    # Seed key is post-canonical: canonical("ultralytics-yolo") == "ultralytics_yolo".
    "ultralytics_yolo": PackageDenylistEntry(
        package_id="ultralytics_yolo",
        display_name="ultralytics-yolo (Ultralytics)",
        spdx_id="AGPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes="Ultralytics AGPL family compound tag; banned for cascade person-detection.",
    ),
    # WongKinYiu YOLOR — GPL-3.0 (not Apache). Not an exception allowlist
    # entry: GPL-3.0 is a deny-axis licence. Own seed for honest lineage notes
    # (compact remainder on bare ``yolo`` would also hit ``yolor``).
    "yolor": PackageDenylistEntry(
        package_id="yolor",
        display_name="YOLOR (WongKinYiu)",
        spdx_id="GPL-3.0",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=(
            "WongKinYiu YOLOR, GPL-3.0 upstream; denied on GPL-3.0 axis. "
            "Not an exception-family seed (licence is not Apache/MIT-class)."
        ),
    ),
    # NC-axis package-floor seeds are MERGED below from
    # ``_generate_nc_package_denylist_entries`` (FIR-7-B10-01 / B10-02 /
    # B10-05). Do not hand-list insightface / buffalo_* / antelope* /
    # yolo_nas / scrfd / … here — the generator is the single source of
    # truth so underscore + compact spellings cannot drift from the NC
    # id surface.
}

# NC-axis PACKAGE_DENYLIST floor exclusions (FIR-7-B10-01 / B10-05).
# Bare ``buffalo`` stays out: generic-English compounds like
# ``buffalo_bill_detector`` must admit (BR-28); real InsightFace packs
# are the size-tagged ids (buffalo_l / buffalo_s / buffalo_sc / buffalo_l2).
_NC_PACKAGE_FLOOR_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "buffalo",
    }
)


def _nc_package_floor_note_for_seed(seed_canonical: str) -> str:
    """Honest per-lineage package-floor note from ``_NC_MODEL_DETAIL_NOTES``.

    Longest covering note-table key wins (prefix / exact on folded or
    compact form). Independent of the family matcher so the generator can
    run at import before the matcher helpers exist. Always names the seed
    id so sibling packs (buffalo_s vs buffalo_sc) are distinguishable.
    """
    best_note: str | None = None
    best_len = -1
    seed_k = seed_canonical.replace("_", "")
    for key, note in _NC_MODEL_DETAIL_NOTES.items():
        kc = key.casefold().replace("-", "_")
        kk = kc.replace("_", "")
        if (
            seed_canonical == kc
            or seed_k == kk
            or seed_canonical.startswith(kc + "_")
            or (kk and seed_k.startswith(kk))
        ):
            if len(kk) > best_len:
                best_len = len(kk)
                best_note = note
    if best_note is not None:
        return (
            f"{seed_canonical}: {best_note} "
            "(NC-weights package-floor axis)"
        )
    return (
        f"{seed_canonical}: non-commercial weights and output-derived data "
        "are banned on the NC-weights package-floor axis"
    )


def _nc_package_floor_seed_surface() -> set[str]:
    """Canonical NC ids that should become package-floor seeds.

    Single source of truth for the NC-axis floor (FIR-7-B10-01 / A11-4):
    exactly ``_PINNED_NC_MODEL_IDS`` ∪ ``_NC_EXPLICIT_VARIANTS`` ∪ the
    Deci ``yolo_nas`` base stem ∪ the Deci SuperGradients framework
    identity, minus ``_NC_PACKAGE_FLOOR_EXCLUSIONS``
    and ``_NC_SURFACE_DELIBERATE_EXCLUSIONS``. No other derivation
    sources. Compact spellings of underscore-bearing seeds are emitted
    as sibling keys so rule (c)'s 3-char remainder cap cannot make
    coverage tag-length-sensitive (``antelope_v2_int8`` vs
    ``antelope_v2_trt``).

    Requires :func:`canonical` / :func:`_compact_canonical` (called after
    those helpers exist — see the merge at the bottom of this section).
    """
    raw: set[str] = set(_PINNED_NC_MODEL_IDS)
    raw |= set(_NC_EXPLICIT_VARIANTS)
    # Deci YOLO-NAS base stem (pinned surface has size/pose variants only).
    raw.add("yolo_nas")
    # Deci SuperGradients framework (FIR-7-PANEL-rv3-02 / CARD-26).
    # Canonical fold covers super-gradients / super_gradients / super.gradients;
    # deci-ai/super-gradients hits via the slash-component walk (A6-02).
    raw.add("super_gradients")
    out: set[str] = set()
    for rid in raw:
        if rid in _NC_PACKAGE_FLOOR_EXCLUSIONS:
            continue
        if rid in _NC_SURFACE_DELIBERATE_EXCLUSIONS:
            continue
        c = canonical(rid)
        if not c:
            continue
        if c in _NC_PACKAGE_FLOOR_EXCLUSIONS:
            continue
        out.add(c)
        compact = _compact_canonical(c)
        if compact and compact not in _NC_PACKAGE_FLOOR_EXCLUSIONS:
            out.add(compact)
    return out


def _generate_nc_package_denylist_entries() -> dict[str, PackageDenylistEntry]:
    """Build NC-axis PACKAGE_DENYLIST entries from the NC id surface.

    Both underscore and compact spellings of every non-excluded NC id get
    their own entry (same reason + lineage note). Hand-kept parallel lists
    of NC floor seeds are forbidden — add to ``_PINNED_NC_MODEL_IDS`` /
    ``_NC_EXPLICIT_VARIANTS`` instead (FIR-7-B10-01 / B10-02 / B10-05).
    """
    entries: dict[str, PackageDenylistEntry] = {}
    for seed in sorted(_nc_package_floor_seed_surface()):
        note = _nc_package_floor_note_for_seed(seed)
        display = seed
        if seed.startswith("yolo_nas") or seed.startswith("yolonas"):
            display = f"YOLO-NAS ({seed})"
        elif seed.startswith("super_gradient") or seed.startswith("supergradient"):
            display = f"SuperGradients ({seed})"
        elif seed.startswith("buffalo") or seed in {
            "insightface",
            "retinaface",
            "arcface",
            "antelopev2",
            "antelope_v2",
            "scrfd",
        }:
            display = f"InsightFace {seed}"
        elif seed.startswith("vec2face"):
            display = f"vec2face ({seed})"
        entries[seed] = PackageDenylistEntry(
            package_id=seed,
            display_name=display,
            spdx_id="Non-Commercial",
            reason=RejectionReason.NC_MODEL_DERIVED,
            notes=note,
        )
    return entries


# NC-axis floor merge is deferred until after :func:`canonical` exists
# (see ``_merge_nc_package_floor_into_denylist`` below).


# Distinct-lineage packages whose names overlap the YOLO surface but are NOT
# Ultralytics/AGPL and are not on an NC-weights deny axis. Matched with the
# same structural family rules as deny seeds, with **bounded admit** semantics
# (FIR-7 Wave F3/F4): exception-family hit → strip seed → residual DENY
# re-scan via segment-aligned suffixes (FIR-7-B7-01); residual deny →
# component DENIES; empty/clean residual → admit so other floors continue.
# Size / task / export variants of an exception seed with a clean residual
# also admit (``yolox_s``, ``yolos_tiny``) — exceptions are family seeds, not
# bare exact pins. Compounds that glue a deny seed after an exception seed
# (``yolox_ultralytics``, ``yolox_s_ultralytics``) DENY via residual suffix
# re-scan. Double-exception compounds (``yolop_yolox``) admit after recursive
# exception strip (FIR-7-B7-06).
PACKAGE_EXCEPTION_ALLOWLIST: dict[str, PackageExceptionEntry] = {
    "yolox": PackageExceptionEntry(
        package_id="yolox",
        display_name="YOLOX (Megvii)",
        spdx_id="Apache-2.0",
        notes="Megvii YOLOX, Apache-2.0; distinct lineage from Ultralytics AGPL.",
    ),
    "yolos": PackageExceptionEntry(
        package_id="yolos",
        display_name="YOLOS (hustvl)",
        spdx_id="Apache-2.0",
        notes="hustvl/ViT YOLOS, Apache-2.0; distinct lineage from Ultralytics AGPL.",
    ),
    "yolof": PackageExceptionEntry(
        package_id="yolof",
        display_name="YOLOF (megvii-model)",
        spdx_id="MIT",
        notes=(
            "megvii-model/YOLOF, MIT; distinct lineage from Ultralytics AGPL."
        ),
    ),
    # hustvl YOLOP (github.com/hustvl/YOLOP), BSD-3-Clause — same org family as
    # YOLOS. Without this seed, bare ``yolo`` compact remainder falsely denied
    # yolop/yolopv2 under an Ultralytics-AGPL note (FIR-7-B6-02).
    "yolop": PackageExceptionEntry(
        package_id="yolop",
        display_name="YOLOP (hustvl)",
        spdx_id="BSD-3-Clause",
        notes=(
            "hustvl/YOLOP, BSD-3-Clause; distinct lineage from Ultralytics AGPL "
            "(same org family as YOLOS)."
        ),
    ),
    # Baidu PaddleDetection PP-YOLO family (ppyolo / ppyoloe / ppyolov2),
    # Apache-2.0 — not Darknet YOLOv2. Without this seed, compact suffix (e)
    # on deny seed ``yolov2`` false-denied ``ppyolov2`` under a Darknet note
    # (FIR-7-B9-03). Seed ``ppyolo`` covers ppyoloe / ppyolov2 via (c).
    "ppyolo": PackageExceptionEntry(
        package_id="ppyolo",
        display_name="PP-YOLO (Baidu PaddleDetection)",
        spdx_id="Apache-2.0",
        notes=(
            "Baidu PaddleDetection PP-YOLO / PP-YOLOe / PP-YOLOv2, Apache-2.0; "
            "distinct lineage from Darknet YOLOv2 and Ultralytics AGPL."
        ),
    ),
}

# TOOLING allowlist — diagnostic deps, not training data.
TOOLING_ALLOWLIST: dict[str, ToolingEntry] = {
    "umap-learn": ToolingEntry(
        package_name="umap-learn",
        verification=VerificationMetadata(
            spdx_id="BSD-3-Clause",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/lmcinnes/umap",
            verified_at="2026-07-23",
            notes="Slice-3 aligned-UMAP diagnostics; not training data.",
        ),
    ),
    "numba": ToolingEntry(
        package_name="numba",
        verification=VerificationMetadata(
            spdx_id="BSD-2-Clause",
            commercial_use=CommercialUse.ALLOWED,
            verified_at="2026-07-23",
            notes="UMAP runtime dependency.",
        ),
    ),
    "llvmlite": ToolingEntry(
        package_name="llvmlite",
        verification=VerificationMetadata(
            spdx_id="BSD-2-Clause",
            commercial_use=CommercialUse.ALLOWED,
            verified_at="2026-07-23",
            notes="UMAP/numba runtime dependency.",
        ),
    ),
    "tensorflow": ToolingEntry(
        package_name="tensorflow",
        verification=VerificationMetadata(
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            verified_at="2026-07-23",
            notes="ParametricUMAP optional dep; aarch64 fallback may skip it.",
        ),
    ),
}

# Synthetic-identity sources. Default is PENDING until a per-source operator
# clearance decision flips the entry. DCFace is operator-cleared.
DCFACE_CLEARANCE_DECISION = "dcface_operator_clearance_20260723"

SYNTHETIC_SOURCE_ENTRIES: dict[str, SyntheticSourceEntry] = {
    "dcface": SyntheticSourceEntry(
        source_id="dcface",
        verification=VerificationMetadata(
            # Real allowlisted SPDX; commercial admission is via clearance_decision.
            spdx_id="Apache-2.0",
            commercial_use=CommercialUse.ALLOWED,
            source_url="https://github.com/mk-minchul/dcface",
            verified_at="2026-07-23",
            clearance_decision=DCFACE_CLEARANCE_DECISION,
            notes=(
                "Operator-cleared for commercial training use "
                f"({DCFACE_CLEARANCE_DECISION}). "
                "FFHQ/CASIA generator lineage disclosed via generator_lineage "
                "field only — not via source/license."
            ),
        ),
    ),
    "vec2face": SyntheticSourceEntry(
        source_id="vec2face",
        verification=VerificationMetadata(
            spdx_id="PENDING-LEGAL-CLEARANCE",
            commercial_use=CommercialUse.FORBIDDEN,
            verified_at="2026-07-23",
            notes="Synthetic source remains PENDING until per-source clearance.",
        ),
    ),
}

# Occluder pack-build: only these sources are registered for asset provenance.
OCCLUDER_REGISTERED_SOURCES: frozenset[str] = frozenset(
    {
        "self-generated",
        "operator-photo",
        "operator-phone",
        "operator-render",
    }
)

# Positive allowlist for TRAINING_DATA source axis (BR-22 / SECD-05).
# Operator-owned provenance sources; model-ingest keys and synthetic registry
# heads are recognised separately. Anything else defaults to
# PENDING-LEGAL-CLEARANCE rather than falling through to PASS.
_POSITIVE_TRAINING_SOURCES: frozenset[str] = frozenset(
    s.strip().lower() for s in OCCLUDER_REGISTERED_SOURCES
)

# Operator-owned *lineage* tags (GATE-21 / NAME-03). Distinct from the
# training-data provenance namespace in ``source`` / ``_POSITIVE_TRAINING_SOURCES``.
# Registration exemption answers "is this lineage operator-owned?" from the
# lineage value itself — never from a door-dependent ``source`` field.
# Operator-controlled registry; fails closed for anything not listed (BR-24).
OPERATOR_OWNED_LINEAGE: frozenset[str] = frozenset(
    {
        "acx/occluder-renderer-v1",
        "acx_internal_projector",
    }
)
# GATE-24: resolution here is whole-token exact (modulo case/separator
# canonicalisation) -- deliberately NOT :func:`_resolve_registry_head`, whose
# slash-component and variant-suffix vocabulary would let a row author mint
# bypass tokens the operator never registered (``evilcorp/acx_internal_projector``,
# ``acx_internal_projector_r50``). This registry is a pure exemption, so
# over-resolution is a laundering hole, not a naming convenience (BR-24 /
# SECD-05). Matches :func:`_derived_ingest_key`'s exact-only discipline (BR-52).

# Positive clearance statuses accepted at pack-build (module scope).
OCCLUDER_ALLOWED_CLEARANCES: frozenset[str] = frozenset(
    {
        ClearanceStatus.ALLOWED.value,
        ClearanceStatus.OPERATOR_CLEARED.value,
        ClearanceStatus.CLEARED.value,
        ClearanceStatus.LICENSE_CLEARED.value,
    }
)

# Shared model-id alias map (single source of truth for ingest resolution).
_MODEL_ALIASES: dict[str, str] = {
    "mediapipe_blazeface": "mediapipe_blazeface",
    "blazeface": "mediapipe_blazeface",
    "paddle_blazeface_fpn_ssh": "paddle_blazeface_fpn_ssh",
    "blazeface_fpn_ssh": "paddle_blazeface_fpn_ssh",
    "rt_detr": "rt_detr",
    "rtdetr": "rt_detr",
    "d_fine": "d_fine",
    "dfine": "d_fine",
    "pp_picodet": "pp_picodet",
    "picodet": "pp_picodet",
    "ultralytics": "ultralytics",
    "yolov8": "yolov8",
    "yolo": "yolo",
    "yunet": "yunet",
    "sface": "sface",
}


# ---------------------------------------------------------------------------
# Import-time registry expansion (B4b inversion)
# ---------------------------------------------------------------------------

# Bounded variant suffixes cross-producted with registry base ids at import.
# Applied to the *registry*, never walked as a grammar over untrusted input.
_COMMON_VARIANT_SUFFIXES: tuple[str, ...] = (
    "train",
    "val",
    "test",
    "aligned",
    "hq",
    "extra",
    "hd",
    "dev",
    "full",
    "crop",
    "raw",
    "orig",
    "r50",
    "r100",
    "l",
    "s",
    "sc",
    "l2",
    "g1",
    "mnet025",
    "v1",
    "v2",
    "v3",
    "v4",
    "256",
    "512",
    "1024",
)

# Research sources that must stay exact-only after expansion (BR-58).
_RESEARCH_EXACT_ONLY: frozenset[str] = frozenset({"mfr"})

# Known model-file extensions stripped before canonicalisation (BR-54).
_MODEL_FILE_EXTENSIONS: tuple[str, ...] = (
    ".onnx",
    ".pt",
    ".pth",
    ".bin",
    ".safetensors",
    ".pkl",
    ".pb",
    ".tflite",
    ".params",
    ".pdparams",
    ".pdmodel",
)


# F14-1: production uses the total ASCII-punct class fold (every remaining
# non-alnum ASCII character except ``/``). ``_UNOFFICIAL_SEPARATOR_CHARS``
# is the F13-1 enumeration, consulted only when ``_ASCII_PUNCT_FOLD_TOTAL``
# is False (TEST-15 revert to the old charset). Empty charset + total-fold
# off is the pre-F13-1 official-only ``[-_.\\s]`` fold (F13-1 red-proof).
_ASCII_PUNCT_FOLD_TOTAL: bool = True
_UNOFFICIAL_SEPARATOR_CHARS: str = "+=:@|#"
# F14-2: strip one trailing Docker/registry tag from the last path
# component *before* punct fold. ``yolox:s`` is not a registry tag (``s``
# is an official family size) and is owned by the fold. TEST-15: set
# False / empty the regex to restore ``yolox:latest`` → ``yolox_latest``.
_STRIP_REGISTRY_TRAILING_TAG: bool = True
_REGISTRY_TRAILING_TAG_RE = re.compile(
    r":(latest|v?[0-9]+(?:[._-][0-9]+){1,3})$"
)
# F14-3: after fold, merge a leading ``pp`` segment + following ``yolo*``
# segment (``pp_yoloe`` → ``ppyoloe``). Scoped to the ppyolo family only.
# TEST-15: set False to restore ``PP-YOLOE+`` → ``pp_yoloe`` (yolo deny).
_PP_YOLO_SEGMENT_MERGE_ENABLED: bool = True


def _has_c0_c1_control(text: str) -> bool:
    """True when any C0/C1 control (Unicode Cc, including NUL) remains."""
    return any(unicodedata.category(ch) == "Cc" for ch in text)


# F15-9: fold mid-token TAB/LF/CR/space as official separators before
# the C0 fail-close. TEST-15: False restores TAB → invalid_row.
_ASCII_WHITESPACE_AS_SEPARATOR_ENABLED: bool = True
_ASCII_WHITESPACE_SEPARATORS: frozenset[str] = frozenset(" \t\n\r")


def _fold_ascii_whitespace_separators(text: str) -> str:
    """Replace ASCII whitespace with ``_`` so TAB/LF/CR fold like space."""
    if not text or not _ASCII_WHITESPACE_AS_SEPARATOR_ENABLED:
        return text
    return "".join(
        "_" if ch in _ASCII_WHITESPACE_SEPARATORS else ch for ch in text
    )


def _precanonical_has_control(text: str) -> bool:
    """True when a real C0/C1 control survives NFKC/Cf + whitespace fold."""
    t = unicodedata.normalize("NFKC", str(text))
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    t = _fold_ascii_whitespace_separators(t)
    return _has_c0_c1_control(t)


# F15-4: nonblank pre-canonical identities whose canonical is empty or
# slash-only fail invalid_row. TEST-15: False restores the door admit.
_EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED: bool = True


def _canonical_lacks_identity(c: str | None) -> bool:
    """True when canonical is empty or every slash component is empty."""
    if c is None:
        return False
    if not c:
        return True
    return not any(part for part in c.split("/") if part)


def _invalid_identity_reason_clause(text: str) -> str:
    """Honest invalid_row clause for canonical-None identities (F15-9)."""
    if _precanonical_has_control(text):
        return (
            "contains a C0/C1 control character; "
            "control characters are fail-closed"
        )
    return (
        "contains non-ASCII residue after "
        "NFKC/Cf normalisation; confusable scripts are fail-closed"
    )


# F15-10 / R18-05: ``pp_`` + ``yolo*`` may merge when it is the
# component head or is preceded by a known Paddle vendor segment.
# ``paddledet`` / ``ppdet`` are official PaddleDetection shorthands
# (R18-05); ``paddle`` / ``paddledetection`` / ``baidu`` are the
# F15-10 vendor surface (R18-10 pins the set).
_PADDLE_VENDOR_SEGMENTS: frozenset[str] = frozenset(
    {
        "paddlepaddle",
        "paddle",
        "paddledetection",
        "paddledet",
        "ppdet",
        "baidu",
    }
)


def _strip_trailing_registry_tag(text: str) -> str:
    """Strip trailing ``:latest`` / dotted multi-group versions on the last path component.

    Applied before punct fold so ``yolox:latest`` becomes ``yolox`` rather
    than ``yolox_latest``. Does not match official size tags (``:s``).
    A deny seed plus a registry tag (``yolo:latest``) still denies after
    the strip — the strip must never launder a deny.

    F15-3: only ``latest`` and ≥ 2 numeric groups (``:v0.3.0`` /
    ``:0.3.0`` / ``:v2.1``) strip. A bare single-number tag (``:v8`` /
    ``:8`` / ``:v2``) is left for the fold so it fail-closes like the
    compact twin (``yoloxv8`` → ``yolox_unknown_residual``).

    R18-12: stacked tags (``:latest:latest``) are stripped until none
    remain. Leftover empty identity is fail-closed; leftover
    ``yolox:latest:latest`` still admits as ``yolox``.
    """
    if not text or not _STRIP_REGISTRY_TRAILING_TAG or _REGISTRY_TRAILING_TAG_RE is None:
        return text
    parts = text.split("/")
    last = parts[-1]
    stripped = _REGISTRY_TRAILING_TAG_RE.sub("", last, count=1)
    # R18-12: strip stacked tags (``:latest:latest``) until the last
    # component no longer ends in a registry tag. A leftover empty
    # identity is fail-closed by the empty-canonical gate; a leftover
    # real family (``yolox:latest:latest`` → ``yolox``) keeps its
    # documented verdict.
    while stripped != last:
        last = stripped
        stripped = _REGISTRY_TRAILING_TAG_RE.sub("", last, count=1)
    parts[-1] = last
    return "/".join(parts)


def _merge_pp_yolo_segments(text: str) -> str:
    """Merge ``pp`` + ``yolo*`` segments per slash component (F14-3 / F15-10).

    ``PP-YOLOE+`` folds to ``pp_yoloe``; this merge yields ``ppyoloe``.
    F15-10: do not merge Deci ``yolo_nas``. Also merge ``pp`` + ``yolo*``
    when preceded by a known Paddle vendor segment.
    """
    if not text or not _PP_YOLO_SEGMENT_MERGE_ENABLED:
        return text
    out: list[str] = []
    for comp in text.split("/"):
        segs = [s for s in comp.split("_") if s]
        merged: list[str] = []
        i = 0
        while i < len(segs):
            nxt = segs[i + 1] if i + 1 < len(segs) else ""
            # R18-14: ``i > 0`` was tautological in the right branch and
            # ``merged`` is non-empty after any prior iteration.
            vendor_ok = i == 0 or merged[-1] in _PADDLE_VENDOR_SEGMENTS
            is_nas = (
                nxt == "yolo"
                and i + 2 < len(segs)
                and segs[i + 2] == "nas"
            )
            if (
                segs[i] == "pp"
                and nxt.startswith("yolo")
                and vendor_ok
                and not is_nas
            ):
                merged.append(segs[i] + nxt)
                i += 2
                continue
            merged.append(segs[i])
            i += 1
        out.append("_".join(merged))
    return "/".join(out)


def _fold_ascii_non_alnum(text: str) -> str:
    """Fold every non-alphanumeric ASCII character except ``/`` to ``_``.

    Slash keeps path-component split semantics. Backslash is normalised
    to slash before this runs. Non-ASCII survivors are left intact so the
    later residue check can fail-closed ``invalid_row``.
    """
    out: list[str] = []
    for ch in text:
        if ord(ch) < 128 and not ch.isalnum() and ch != "/":
            out.append("_")
        else:
            out.append(ch)
    return "".join(out)


def canonical(value: str) -> str | None:
    """NFKC → strip Cf → fold ASCII ws → fail-closed C0/C1 → fold punct.

    After NFKC and Cf/format stripping, mid-token ASCII whitespace
    (TAB/LF/CR/space) folds as official separators (F15-9) so
    ``yolox\\ts`` becomes ``yolox_s``. Any remaining C0/C1 control
    (including NUL) fails closed (``None`` / ``invalid_row``) — never
    admit, never silently strip. Remaining non-alphanumeric ASCII folds
    to ``_`` except ``/`` (path separator). Backslash is normalised to
    slash first so it keeps component-split behaviour. ``_`` runs
    collapse; leading/trailing ``_`` strip; a token that folds to empty
    is ``""`` (callers treat as ``invalid_row`` on row/scalar floors,
    including slash-only ``/`` / ``///`` — F15-4). Non-ASCII residue
    that survives NFKC (U+2010, en/em-dash) still returns ``None``.
    Fullwidth forms NFKC-map to ASCII first and then fold.

    When ``_ASCII_PUNCT_FOLD_TOTAL`` is False the F13-1 enumeration
    ``_UNOFFICIAL_SEPARATOR_CHARS`` plus official ``[-_.\\s]`` is used
    instead (TEST-15). Trailing registry tags (``:latest`` /
    ``:v0.3.0``) are stripped from the last path component before fold
    until none remain (F14-2 / R18-12). After fold, a ``pp`` segment
    followed by a ``yolo*`` segment merges to ``ppyolo*`` when it is
    the component head or is preceded by a known Paddle vendor
    (F14-3 / F15-10).
    """
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    # F15-9: TAB/LF/CR/space fold as official separators before C0
    # fail-close so ``yolox\\ts`` becomes ``yolox_s``. Remaining C0
    # (NUL, …) still fail closed.
    text = _fold_ascii_whitespace_separators(text)
    # F14-1: C0/C1 controls fail closed — never strip, never admit.
    if _has_c0_c1_control(text):
        return None
    text = text.strip().casefold()
    if not text:
        return ""
    # Preserve path separators; normalise backslash to slash.
    text = text.replace("\\", "/")
    # Strip known model-file extensions on each slash component (BR-54).
    parts = text.split("/")
    stripped_parts: list[str] = []
    for part in parts:
        p = part
        for ext in _MODEL_FILE_EXTENSIONS:
            if p.endswith(ext):
                p = p[: -len(ext)]
                break
        stripped_parts.append(p)
    text = "/".join(stripped_parts)
    # F14-2 / R18-12: strip trailing registry tags from the last
    # component until none remain, *before* punct fold so :latest /
    # :v0.3.0 / stacked :latest:latest do not become unknown debris.
    text = _strip_trailing_registry_tag(text)
    if _ASCII_PUNCT_FOLD_TOTAL:
        # F14-1: total class fold. Enumeration is structurally unwinnable
        # (every ASCII punct outside +=:@#| fail-opened under F13-1).
        text = _fold_ascii_non_alnum(text)
    else:
        # TEST-15 revert: F13-1 unofficial charset, then official ``[-_.\\s]``.
        if _UNOFFICIAL_SEPARATOR_CHARS:
            unofficial_cls = "[" + re.escape(_UNOFFICIAL_SEPARATOR_CHARS) + "]+"
            text = re.sub(unofficial_cls, "_", text)
        text = re.sub(r"[-_.\s]+", "_", text)
    # Collapse underscore runs; trim per slash component and whole token.
    text = re.sub(r"_+", "_", text)
    text = "/".join(seg.strip("_") for seg in text.split("/"))
    text = text.strip("_")
    # F14-3: official PP-YOLOE+ title path (pp_yoloe → ppyoloe).
    text = _merge_pp_yolo_segments(text)
    if any(ord(ch) > 127 for ch in text):
        return None
    return text


def _compact_canonical(value: str) -> str:
    """Drop underscores from a canonical id (``casia_webface`` → ``casiawebface``)."""
    return value.replace("_", "")


def _merge_nc_package_floor_into_denylist() -> None:
    """Merge generated NC-axis floor seeds into ``PACKAGE_DENYLIST`` (F7).

    Called once at import after :func:`canonical` exists and before
    :func:`_derive_nc_model_ids` reads NC-tagged denylist entries.
    """
    PACKAGE_DENYLIST.update(_generate_nc_package_denylist_entries())


_merge_nc_package_floor_into_denylist()


def _expand_id_forms(
    base: str,
    *,
    exact_only: bool = False,
    extra_variants: tuple[str, ...] | frozenset[str] = (),
    suffixes: tuple[str, ...] = _COMMON_VARIANT_SUFFIXES,
) -> set[str]:
    """Expand one registry base id into exact membership forms.

    Produces the canonical form, its compact form, optional explicit variants,
    and (unless ``exact_only``) a cross-product with ``suffixes`` as both
    ``base_suf`` and unsplit ``basesuf`` (plus compact equivalents).
    """
    out: set[str] = set()
    c = canonical(base)
    if c is None or c == "":
        return out
    out.add(c)
    out.add(_compact_canonical(c))
    for raw in extra_variants:
        vc = canonical(raw)
        if vc is None or vc == "":
            continue
        out.add(vc)
        out.add(_compact_canonical(vc))
    if exact_only:
        return out
    # Separated and unsplit suffix forms (registry-side expansion only).
    for suf in suffixes:
        # Separated form (vggface2_train, ffhq_aligned, casia_webface_extra).
        separated = f"{c}_{suf}"
        out.add(separated)
        # M8 discrimination anchor: unsplit compound (ffhq256, widerfacehd,
        # casiawebfaceextra). Built from compact base so it is NOT a duplicate
        # of compact(separated) for multi-segment bases.
        unsplit = f"{_compact_canonical(c)}{suf}"  # unsplit compound startswith-equivalent
        out.add(unsplit)
    return out


def _expand_ids(
    ids: frozenset[str] | set[str] | tuple[str, ...],
    *,
    exact_only_ids: frozenset[str] = frozenset(),
    extra_variants: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Expand a set of base ids with common suffixes + compact forms."""
    out: set[str] = set()
    for raw in ids:
        c = canonical(raw)
        if c is None or not c:
            continue
        exact = c in exact_only_ids or raw in exact_only_ids
        out |= _expand_id_forms(c, exact_only=exact)
    for raw in extra_variants:
        vc = canonical(raw)
        if vc is None or not vc:
            continue
        out.add(vc)
        out.add(_compact_canonical(vc))
        # Also expand explicit variants with one suffix hop (retinaface_mnet025 + v2).
        out |= _expand_id_forms(vc, exact_only=False)
    return frozenset(out)


def _derive_nc_model_ids() -> frozenset[str]:
    """Build NC model-id set from registry tables ∪ pinned extras.

    Sources (all unioned):
      * ``_PINNED_NC_MODEL_IDS`` — ArcFace-ecosystem weights not always registered
      * ``MODEL_INGEST_ENTRIES`` whose ``commercial_use`` is not ALLOWED
        (currently every stock ingest entry is ALLOWED; the loop is kept so a
        future NC-tagged ingest row is denylisted automatically — BR-38)
      * ``SYNTHETIC_SOURCE_ENTRIES`` whose commercial_use is not ALLOWED
      * ``PACKAGE_DENYLIST`` entries tagged ``NC_MODEL_DERIVED``
      * stems extracted from ``NC_MODEL_PATTERNS``
      * ``_NC_EXPLICIT_VARIANTS`` multi-segment pack ids
    """
    ids: set[str] = set(_PINNED_NC_MODEL_IDS)
    ids.update(_NC_EXPLICIT_VARIANTS)
    for key, entry in MODEL_INGEST_ENTRIES.items():
        if entry.verification.commercial_use is not CommercialUse.ALLOWED:
            ids.add(key)
            ids.add(entry.model_id)
    for key, entry in SYNTHETIC_SOURCE_ENTRIES.items():
        if entry.verification.commercial_use is not CommercialUse.ALLOWED:
            ids.add(key)
            ids.add(entry.source_id)
    for entry in PACKAGE_DENYLIST.values():
        if entry.reason is RejectionReason.NC_MODEL_DERIVED:
            ids.add(entry.package_id)
    # Pattern stems so NC_MODEL_IDS stays aligned with NC_MODEL_PATTERNS.
    for pattern in NC_MODEL_PATTERNS:
        p = pattern.casefold()
        if p.endswith("/*"):
            ids.add(p[:-2])
        elif p.endswith("*"):
            ids.add(p[:-1])
        else:
            ids.add(p)
    # Canonicalise seed forms.
    out: set[str] = set()
    for i in ids:
        c = canonical(i)
        if c:
            out.add(c)
    return frozenset(out)


# Derived at import time — any non-ALLOWED table entry is denylisted for
# derived_from_model matching (plan: any model whose license_policy entry is NC).
NC_MODEL_IDS: frozenset[str] = _derive_nc_model_ids()

# Expanded denial sets — exact membership only (B4b / WEB-24).
# Built solely from NC_MODEL_IDS so M3 (empty NC_MODEL_IDS) is discrimination-complete.
NC_MODEL_IDS_EXPANDED: frozenset[str] = _expand_ids(NC_MODEL_IDS)

RESEARCH_SOURCE_IDS_EXPANDED: frozenset[str] = _expand_ids(
    RESEARCH_ONLY_SOURCES,
    exact_only_ids=_RESEARCH_EXACT_ONLY,
)

# Synthetic registry: base ids + bounded version suffixes (dcface_v2, …).
_SYNTHETIC_BASE_IDS: frozenset[str] = frozenset(SYNTHETIC_SOURCE_ENTRIES.keys())
SYNTHETIC_SOURCE_IDS_EXPANDED: frozenset[str] = _expand_ids(_SYNTHETIC_BASE_IDS)

# Map every expanded synthetic id back to its registry entry key (exact only).
_SYNTHETIC_EXPANDED_TO_HEAD: dict[str, str] = {}
for _sk, _sentry in SYNTHETIC_SOURCE_ENTRIES.items():
    _sc = canonical(_sk)
    if _sc is None:
        continue
    for _form in _expand_id_forms(_sc, exact_only=False):
        _SYNTHETIC_EXPANDED_TO_HEAD.setdefault(_form, _sc)


# Clean-name corpus that must never land in denial sets (import-time safety).
_MUST_PASS_CORPUS: frozenset[str] = frozenset(
    {
        "buffalo-wings-detector",
        "buffalo_bill_detector",
        "insightface-free",
        "not-insightface",
        "ffhq-tools",
        "celebase",
        "webfaces-r-us",
        "our_widerface_replacement",
        "arcface_alternative_v2",
        "not-retinaface",
        "mfr_train",
        "mfr/tools",
        "buffalos-eye/v1",
        "my-buffalo-free",
        "retinaface-free-reimpl",
        "insightfaces-r-us/model",
        "casiaset-detector",
        "mfrx-vendor",
        "ffhq_free_internal",
        "glint360k_free",
        "commercial-ffhq-alternative",
        "dataset_not_ffhq",
        "notffhq",
        "casia-device",
        "casiadevice",
        "deepglint-clean",
        "casia-clean",
        "ms1m-clean",
        "arcface_mit",
        "arcface_bsd",
    }
)


def _assert_no_must_pass_collisions() -> None:
    """Import-time guard: expanded denial sets must not contain clean names."""
    denial_nc = NC_MODEL_IDS_EXPANDED
    denial_rs = RESEARCH_SOURCE_IDS_EXPANDED
    exact_only = frozenset(
        x
        for raw in _RESEARCH_EXACT_ONLY
        for x in filter(
            None,
            (
                canonical(raw),
                _compact_canonical(canonical(raw) or ""),
            ),
        )
    )
    collisions: set[str] = set()
    for name in _MUST_PASS_CORPUS:
        c = canonical(name)
        if c is None:
            continue
        # whole-string
        if c in denial_nc or _compact_canonical(c) in denial_nc:
            collisions.add(name)
            continue
        if c in denial_rs or _compact_canonical(c) in denial_rs:
            collisions.add(name)
            continue
        if "/" in c:
            for part in c.split("/"):
                if not part:
                    continue
                if part in denial_nc or _compact_canonical(part) in denial_nc:
                    collisions.add(name)
                    break
                if part in exact_only or _compact_canonical(part) in exact_only:
                    continue
                if part in denial_rs or _compact_canonical(part) in denial_rs:
                    collisions.add(name)
                    break
    if collisions:
        raise AssertionError(
            f"registry expansion over-rejects clean names: {sorted(collisions)}"
        )


_assert_no_must_pass_collisions()


# ---------------------------------------------------------------------------
# Pure matching helpers — exact set membership only (B4b / WEB-24 / SECD-05)
# ---------------------------------------------------------------------------


def _normalize_token(value: str) -> str:
    """Normalise a token with unbound builtins (GATE-15).

    ``str.strip`` / ``str.lower`` so a ``str`` subclass cannot launder a dirty
    payload through overridden instance methods. Honest subclasses
    (``numpy.str_`` shape) still evaluate correctly.
    """
    return str.lower(str.strip(value))


def _resolve_model_key(model_id: str) -> str:
    """Normalise a model id / alias to a registry key (exact, no prefix walk)."""
    c = canonical(str(model_id))
    if c is None or not c:
        key = _normalize_token(str(model_id)).replace("-", "_").replace(" ", "_")
        return _MODEL_ALIASES.get(key, key)
    # Use final slash component for path-shaped ids.
    head = c.split("/")[-1] if "/" in c else c
    return _MODEL_ALIASES.get(head, head)


def _is_model_ingest_key(head: str) -> bool:
    """True when ``head`` resolves to a registered model-ingest entry."""
    resolved = _resolve_model_key(head)
    return resolved in MODEL_INGEST_ENTRIES


# Whole-string-only ids (BR-58): never match as a mere slash component.
_EXACT_ONLY_MEMBERSHIP: frozenset[str] = frozenset(
    {
        x
        for raw in _RESEARCH_EXACT_ONLY
        for x in (
            {canonical(raw) or "", _compact_canonical(canonical(raw) or "")}
        )
        if x
    }
)


def _membership_hit(
    c: str,
    expanded: frozenset[str],
    *,
    exact_only: frozenset[str] = frozenset(),
) -> str | None:
    """Exact membership of canonical form or any slash component (WEB-24).

    ``exact_only`` ids match the whole string only — never as a path component
    of a longer token (BR-58: ``mfr/tools`` must not trip on bare ``mfr``).
    """
    if not c:
        return None
    if c in expanded:
        return c
    compact = _compact_canonical(c)
    if compact and compact in expanded:
        return compact
    # Slash components only — never progressive underscore prefixes (BR-50/52).
    if "/" in c:
        for part in c.split("/"):
            if not part:
                continue
            if part in exact_only or _compact_canonical(part) in exact_only:
                continue
            if part in expanded:
                return part
            pc = _compact_canonical(part)
            if pc and pc in expanded:
                return pc
    return None


def _live_nc_expanded() -> frozenset[str]:
    """NC expanded set, honouring monkeypatched ``NC_MODEL_IDS`` (BR-38)."""
    return _expand_ids(NC_MODEL_IDS)


# Trailing export / quant / runtime tags that must not shield an NC seed on
# the weights-lineage doors (FIR-7-B8-06 / B9-02). Known longer tags live
# here; short tags (≤ ``_NC_STRUCTURAL_SHORT_TAG_MAX_LEN``) are stripped
# structurally without enumeration. Progressive strip + exact re-membership
# keeps multi-segment BR-28 controls (``buffalo_bill_detector``) green —
# full family (b)/(e) on short NC seeds would over-block them on the
# membership axis (package-floor NC promotion uses whole-component match
# only so ``not-insightface`` stays clean on weights doors).
_NC_TRAILING_SHIELD_TAGS: frozenset[str] = frozenset(
    {
        "int8",
        "int4",
        "fp16",
        "fp32",
        "bf16",
        "onnx",
        "engine",
        "torchscript",
        "mlpackage",
        "tflite",
        "openvino",
        "tensorrt",
        "trt",
        "coreml",
        "ncnn",
        "rknn",
        "savedmodel",
        "weights",
        "pretrained",
        "pt",
        "pth",
        "bin",
        "safetensors",
    }
)
# Hard bound on trailing-tag strips per token (FIR-7-B9-02). Overflow stops
# stripping; the un-stripped head admits only if it is not NC.
_NC_MAX_TRAILING_TAG_STRIPS: int = 3
# Structural short-tag threshold: trailing segment of this many canonical
# chars or fewer is treated as an export/quant/runtime tag without being
# listed in ``_NC_TRAILING_SHIELD_TAGS``.
_NC_STRUCTURAL_SHORT_TAG_MAX_LEN: int = 4


def _nc_is_strippable_trailing_tag(
    segment: str,
    *,
    head_after: str,
) -> bool:
    """True when ``segment`` is a known shield tag or a short structural tag.

    Structural short tags (≤ ``_NC_STRUCTURAL_SHORT_TAG_MAX_LEN``):

      * digit-bearing segments (quant codes) always strip;
      * pure-alpha short segments strip when the remaining head is
        multi-segment (size/pose pins like ``yolo_nas_l``) **or** when the
        segment is in ``_NC_TRAILING_SHIELD_TAGS`` (already handled above).

    Pure-alpha short tags on a single-segment head (``insightface_free``,
    ``arcface_mit``, ``buffalos_eye``) do **not** strip — that keeps BR-28
    name-continuation controls green while still unwrapping
    ``yolo_nas_l_trt`` (known tag) and ``yolo_nas_l_x`` (short on
    multi-segment head).
    """
    if not segment:
        return False
    if segment in _NC_TRAILING_SHIELD_TAGS:
        return True
    if len(segment) > _NC_STRUCTURAL_SHORT_TAG_MAX_LEN:
        return False
    if any(ch.isdigit() for ch in segment):
        return True
    # Pure-alpha short: only on multi-segment remaining heads.
    return bool(head_after) and "_" in head_after


def _nc_iter_stripped_heads(token: str) -> list[str]:
    """Successive heads after each trailing-tag strip (≤ bound), longest first.

    Order-blind within the bound: ``int8_trt``, ``trt_int8``, and
    ``fp16_onnx_trt`` all unwrap. A trailing segment strips when it is in
    ``_NC_TRAILING_SHIELD_TAGS``, digit-bearing and ≤ 4 chars, or
    pure-alpha ≤ 4 chars with a multi-segment remaining head. Always
    keeps ≥ 1 leading segment. Fail-closed on bound overflow (stops
    stripping). Used by :func:`match_nc_model_pattern` to re-test exact
    NC membership after every strip (FIR-7-B9-02).
    """
    if not token or "_" not in token:
        return []
    parts = token.split("_")
    heads: list[str] = []
    strips = 0
    while len(parts) > 1 and strips < _NC_MAX_TRAILING_TAG_STRIPS:
        head_after = "_".join(parts[:-1])
        if not _nc_is_strippable_trailing_tag(parts[-1], head_after=head_after):
            break
        parts.pop()
        strips += 1
        heads.append("_".join(parts))
    return heads


def _nc_covering_seed_for_head(head: str) -> str | None:
    """Longest base NC seed covering ``head`` exactly or export-shaped rest.

    Used after bounded tag-strip so a residual like ``yolo_nas_l_int8``
    (not itself in the expanded set) still resolves to ``yolo_nas_l`` when
    the 3-tag bound leaves unstripped export debris. ``seed_`` + rest is
    accepted only when ``rest`` is export-shaped (known/quant tags) so
    name-continuations like ``arcface_alternative`` stay clean (BR-28).
    """
    if not head:
        return None
    live = NC_MODEL_IDS
    best: str | None = None
    best_len = -1
    head_k = _compact_canonical(head)
    for seed in live:
        sc = canonical(str(seed))
        if not sc:
            continue
        if head == sc or (
            "_" not in sc and head_k and head_k == _compact_canonical(sc)
        ):
            if len(sc) > best_len:
                best = sc
                best_len = len(sc)
            continue
        boundary = sc + "_"
        if head.startswith(boundary) and len(head) > len(boundary):
            rest = head[len(boundary) :]
            if not _nc_package_rest_is_export_shaped(rest):
                continue
            if len(sc) > best_len:
                best = sc
                best_len = len(sc)
    return best


def _segment_is_exception_family_identity(seg: str) -> bool:
    """True when ``seg`` is exact/compact identity of an exception seed.

    F13-2 / R15-L-1: used by door-promotion so an exception segment
    *after* an NC head (``insightface_yolox``) is visible. Compact
    (c) spellings (``yoloxs``) count; junk prefixes (``myarcface``)
    and non-exception segments (``not``, ``insightface``) do not.
    """
    if not seg:
        return False
    if _is_legitimate_exception_compact_spelling(seg):
        return True
    seg_k = _compact_canonical(seg)
    for seed_c, seed_k, _entry in _iter_family_seeds(
        PACKAGE_EXCEPTION_ALLOWLIST
    ):
        if (
            seg == seed_c
            or seg == seed_k
            or seg_k == seed_k
            or seg_k == seed_c
        ):
            return True
    return False


def _iter_exception_compact_spellings() -> list[tuple[str, str, str]]:
    """``(seed_c, seed_k, spelling)`` for each exception seed and compact tag.

    Longest spelling first so ``yoloxs`` wins over ``yolox`` at the same
    offset. Shared by mid-adjacency and door-promotion occurrence tests
    (F14-4 / F13-3).
    """
    out: list[tuple[str, str, str]] = []
    for seed_c, seed_k, _entry in _iter_family_seeds(
        PACKAGE_EXCEPTION_ALLOWLIST
    ):
        if not seed_k:
            continue
        out.append((seed_c, seed_k, seed_k))
        for tag in _EXCEPTION_FAMILY_COMPACT_TAGS.get(seed_c, frozenset()):
            if tag:
                out.append((seed_c, seed_k, seed_k + tag))
        for tag in _EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST.get(
            seed_c, frozenset()
        ):
            if tag:
                out.append((seed_c, seed_k, seed_k + tag))
    out.sort(key=lambda item: -len(item[2]))
    return out


def _compact_has_mid_exception_family(part: str) -> bool:
    """True when an exception seed/spelling sits at compact offset > 0.

    F14-4 occurrence predicate (TEST-15). Offset 0 is owned by prefix
    match / F12-1 steal. Shared with
    :func:`_compact_mid_exception_deny_adjacency`.
    """
    if not part:
        return False
    compact = _compact_canonical(part)
    if not compact:
        return False
    for _seed_c, _seed_k, spelling in _iter_exception_compact_spellings():
        idx = compact.find(spelling)
        while idx >= 0:
            if idx > 0:
                return True
            idx = compact.find(spelling, idx + 1)
    return False


def _compact_component_has_exception_tail(part: str) -> bool:
    """True when compact ``part`` ends with an exception seed or spelling.

    Closes one-segment compact forms (``insightfaceyolox`` /
    ``arcfaceyolox``) that have no ``_``-segment equal to an exception
    seed. Requires a non-empty prefix so a bare exception token is
    owned by the prefix-match path.
    """
    if not part:
        return False
    pk = _compact_canonical(part)
    if not pk:
        return False
    for seed_c, seed_k, _entry in _iter_family_seeds(
        PACKAGE_EXCEPTION_ALLOWLIST
    ):
        if seed_k and pk.endswith(seed_k) and len(pk) > len(seed_k):
            return True
        tags = _EXCEPTION_FAMILY_COMPACT_TAGS.get(seed_c, frozenset())
        for tag in tags:
            glued = seed_k + tag
            if glued and pk.endswith(glued) and len(pk) > len(glued):
                return True
    return False


def _token_has_non_prefix_exception_family(part: str) -> bool:
    """True when an exception seed sits at a non-prefix alignment.

    F13-2 / R15-L-1 single load-bearing helper (TEST-15): any ``_``-
    segment is exact/compact exception identity, or the compact form
    ends with an exception seed / legitimate compact spelling.
    """
    if not part:
        return False
    for seg in part.split("_"):
        if _segment_is_exception_family_identity(seg):
            return True
    # F14-4: exception-family structure anywhere in the compact token
    # (xyoloxinsightface), not only a trailing exact spelling.
    if _compact_has_mid_exception_family(part):
        return True
    return _compact_component_has_exception_tail(part)


def _token_has_exception_family(token: str) -> bool:
    """True when any slash component hits an exception-family seed.

    Includes unbounded compact-prefix claims (F12-3 / R14-G1-4) so
    ``yoloxinsightface`` is visible to NC door promotion — structural
    strip alone misses those forms and dropped a known scanner NC hit.

    F13-2 / R15-L-1 / F14-4: also true when any ``_``-segment is
    exact/compact exception identity, the compact component ends with
    an exception seed, **or** an exception seed/spelling occurs at a
    mid-token compact offset (``xyoloxinsightface``). BR-28 floor-only
    controls (``myarcface`` / ``not-insightface``) and junk+NC without
    an exception segment (``aabuffalo_l`` / ``aainsightface`` /
    ``aaayolonas``) have no exception occurrence and stay False — they
    floor-deny (F15-1) but do not grow an exception witness.
    """
    c = canonical(token) if token else None
    if not c:
        return False
    parts = [p for p in c.split("/") if p] if "/" in c else [c]
    for part in parts:
        if _exception_seed_match_for_residual(part) is not None:
            return True
        if _best_exception_hit_with_residual(part) is not None:
            return True
        if _token_has_non_prefix_exception_family(part):
            return True
    return False


def match_nc_model_pattern(derived_from_model: str) -> str | None:
    """Return the pinned NC id that matches ``derived_from_model``, or None.

    Exact set membership against ``NC_MODEL_IDS_EXPANDED`` after
    :func:`canonical` (B4b / WEB-24) is always tried first so the existing
    pin set and multi-segment BR-28 precision controls stay load-bearing.

    FIR-7-B8-06 / B9-02 structural NC (when ``_NC_STRUCTURAL_MATCH_ENABLED``):

      1. Bounded order-blind strip of trailing export/quant/runtime tags
         (known set **or** ≤ 4-char short tags; hard bound 3; keep ≥ 1
         leading segment) then re-check exact membership after each strip
         — closes ``yolo_nas_l_trt`` / ``buffalo_l_int8_trt`` /
         ``antelopev2_trt`` without prefix-overmatch on
         ``buffalo_bill_detector`` / ``not-insightface``.
      2. Package-floor NC hit (``_package_denylist_hit`` reason
         ``nc_model_derived``) when the token also carries an exception-
         family component — residual NC compounds like
         ``yolox_s_buffalo_l`` (FIR-7-B8-07). Bare BR-28 controls have no
         exception family and stay clean on this path.

    Non-ASCII residue yields ``None``; callers must treat that as
    ``invalid_row`` via their own canonical check.
    """
    if not derived_from_model or not str.strip(str(derived_from_model)):
        return None
    c = canonical(str(derived_from_model))
    if c is None:
        return None
    expanded = _live_nc_expanded()
    exact = _membership_hit(c, expanded)
    if exact is not None:
        return exact
    if not _NC_STRUCTURAL_MATCH_ENABLED:
        return None

    # (1) Bounded order-blind trailing-tag strip → exact re-membership
    # after each strip (FIR-7-B9-02 / B10-03). One call strips up to the
    # bound; intermediate heads are re-tested. **Membership outranks the
    # covering-seed gate** (FIR-7-A10-03): if the residual head is in
    # ``NC_MODEL_IDS_EXPANDED``, that IS an NC match — return it. The
    # covering-seed gate may only ADD precision for non-member residuals
    # (export-shaped rest under a base seed); it must never veto a member.
    # Closes compact heads of underscore-bearing seeds (``yolonasl_trt``,
    # ``buffalol2_trt``, ``yolonas_int8``) that the covering gate's
    # compact clause (requires "_" not in the seed) previously discarded.
    if "/" in c:
        tag_candidates = [p for p in c.split("/") if p]
    else:
        tag_candidates = [c]
    for cand in tag_candidates:
        for head in _nc_iter_stripped_heads(cand):
            if not head:
                continue
            hit = _membership_hit(head, expanded)
            if hit is not None:
                return hit
            # Non-member residual: covering seed may still resolve
            # export-shaped rest under a base seed (yolo_nas_l_int8 after
            # partial strip when membership forms miss).
            covering = _nc_covering_seed_for_head(head)
            if covering is not None:
                return covering

    # (2) Exception-residual NC compounds (B8-07): package floor already
    # denies ``yolox_s_buffalo_l`` with nc_model_derived; promote that hit
    # onto the weights door only when an exception-family seed is present
    # so BR-28 controls without exception lineage stay admitted.
    if _token_has_exception_family(c):
        deny = _package_denylist_hit(c)
        if (
            deny is not None
            and deny.reason is RejectionReason.NC_MODEL_DERIVED
        ):
            return deny.package_id
    return None


def _nc_detail_lineage_note(matched: str) -> str:
    """Per-entry NC lineage note for audit detail (FIR-7-B7-04 / B11-05).

    Resolves ``matched`` (from :func:`match_nc_model_pattern`) to the longest
    covering seed in ``_NC_MODEL_DETAIL_NOTES`` with the **same compact-aware
    prefix resolution** the floor generator uses
    (:func:`_nc_package_floor_note_for_seed`), so compact multi-segment
    membership hits (``yolonasposel``, ``arcfaceglint360kr100``,
    ``scrfd10gkps``) carry the same Deci / InsightFace notes as their
    underscore twins — never the generic fallback when lineage is known.
    """
    if not matched:
        return "non-commercial weights and output-derived data are banned"
    c = canonical(str(matched)) or str(matched).casefold().replace("-", "_")
    best_note: str | None = None
    best_len = -1
    seed_k = c.replace("_", "")
    for key, note in _NC_MODEL_DETAIL_NOTES.items():
        kc = key.casefold().replace("-", "_")
        kk = kc.replace("_", "")
        if (
            c == kc
            or seed_k == kk
            or c.startswith(kc + "_")
            or (kk and seed_k.startswith(kk))
        ):
            if len(kk) > best_len:
                best_len = len(kk)
                best_note = note
    if best_note is not None:
        return best_note
    return "non-commercial weights and output-derived data are banned"


def _looks_like_research_source(value: str) -> bool:
    """True when value identifies a research-only corpus (exact membership).

    Uses ``RESEARCH_SOURCE_IDS_EXPANDED`` only — no startswith / progressive
    prefix / version-segment grammar over the input (B4b / WEB-24 / BR-47).
    Non-ASCII residue is treated as tainted so callers fail closed.

    **The slash/underscore asymmetry is deliberate (BR-56, resolved wontfix).**
    A slash is a hierarchical separator, so each path component is an identity
    token in its own right and is matched as one; an underscore is not, so
    underscore forms match whole-string only. Reconciling the two shapes is not
    available in either direction: segment-matching underscore forms is the
    progressive-prefix grammar that BR-50/BR-52 removed for over-matching, and
    relaxing slash components to whole-string matching flips 637 currently
    rejected sources to PASS (measured), including ``vendor/casia/subset`` and
    ``acme/celeba/mirror`` — a subset or a mirror of a research corpus is still
    that corpus. Consistency does not outrank fail-safe defaults [SECD-05].
    """
    if not value or not str.strip(str(value)):
        return False
    c = canonical(str(value))
    if c is None:
        # Caller audits as invalid_row; treat as tainted if asked raw.
        return True
    if not c:
        return False
    return _membership_hit(
        c, RESEARCH_SOURCE_IDS_EXPANDED, exact_only=_EXACT_ONLY_MEMBERSHIP
    ) is not None


def _resolve_registry_head(
    token: str,
    registry: Mapping[str, Any],
) -> str | None:
    """Exact registry-head resolve (B4b / BR-50 / BR-52 / BR-36).

    A token matches when its canonical form (or a slash component) is an
    expanded form of a registry key. Progressive underscore-prefix resolution
    is intentionally absent — ``dcface_evil`` / ``not_dcface`` / ``yunet_evil``
    do not inherit clearance or ingest registration from a substring head.
    """
    if not token or not str.strip(str(token)):
        return None
    c = canonical(str(token))
    if c is None or not c:
        return None

    # Prefer the synthetic expanded→head map when auditing synthetic entries.
    if registry is SYNTHETIC_SOURCE_ENTRIES or set(registry.keys()) <= set(
        SYNTHETIC_SOURCE_ENTRIES.keys()
    ):
        hit = _membership_hit(c, SYNTHETIC_SOURCE_IDS_EXPANDED)
        if hit is not None:
            return _SYNTHETIC_EXPANDED_TO_HEAD.get(hit) or _SYNTHETIC_EXPANDED_TO_HEAD.get(
                _compact_canonical(hit)
            )
        return None

    # Generic: exact key or slash-component key (no progressive prefixes).
    keys_expanded: dict[str, str] = {}
    for key in registry:
        kc = canonical(key)
        if kc is None:
            continue
        for form in _expand_id_forms(kc, exact_only=False):
            keys_expanded.setdefault(form, kc)

    hit = _membership_hit(c, frozenset(keys_expanded))
    if hit is None:
        return None
    return keys_expanded.get(hit) or keys_expanded.get(_compact_canonical(hit))


# Licence-bearing keys examined together so a denylisted secondary cannot hide
# behind an allowlisted primary (BR-35).
_LICENSE_FIELD_KEYS: tuple[str, ...] = ("license", "spdx_id", "license_id")

# GATE-04: matching these keys exactly and case-sensitively let a denylisted
# licence declared as "License" or "licence" slip past the floor unexamined.
# Accept the spelling/casing variants, and treat any OTHER licence-shaped key
# as invalid_row -- a caller who declares a licence must never have it ignored.
_LICENSE_KEY_ALIASES: dict[str, str] = {
    "license": "license",
    "licence": "license",
    "spdx_id": "spdx_id",
    "spdxid": "spdx_id",
    "spdx": "spdx_id",
    "license_id": "license_id",
    "licence_id": "license_id",
    "licenseid": "license_id",
    "licenceid": "license_id",
}
_LICENSE_KEY_SHAPED = re.compile(r"licen[sc]e|spdx")


def _normalise_field_key(key: str) -> str:
    """Fold casing and separators so 'SPDX-ID' and 'spdx_id' agree."""
    return re.sub(r"[^a-z0-9]+", "_", str.lower(str.strip(key))).strip("_")


def _unrecognised_license_keys(row: Mapping[str, Any]) -> list[str]:
    """Licence-shaped keys the collector would silently ignore (GATE-04)."""
    return sorted(
        key
        for key in row
        if isinstance(key, str)
        and _normalise_field_key(key) not in _LICENSE_KEY_ALIASES
        and _LICENSE_KEY_SHAPED.search(_normalise_field_key(key))
    )


def _require_string_field(
    row: Mapping[str, Any],
    key: str,
    *,
    required: bool,
    category: PolicyCategory,
) -> tuple[str | None, LicenseAuditResult | None]:
    """Validate optional/required string fields. Returns (value, error)."""
    if key not in row:
        if required:
            return None, _fail(
                RejectionReason.INVALID_ROW,
                detail=f"provenance row missing required field {key!r}",
                category=category,
            )
        return None, None
    raw = row[key]
    if raw is None:
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=f"provenance row field {key!r} must be a string, got None",
            category=category,
        )
    if not isinstance(raw, str):
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"provenance row field {key!r} must be a string, "
                f"got {type(raw).__name__}"
            ),
            category=category,
        )
    return raw, None


def _license_values_of(row: Mapping[str, Any]) -> list[str]:
    """Collect every non-empty licence-bearing field present on ``row`` (BR-35)."""
    by_canonical: dict[str, list[str]] = {key: [] for key in _LICENSE_FIELD_KEYS}
    for key, raw in row.items():
        if not isinstance(key, str):
            continue
        canonical_key = _LICENSE_KEY_ALIASES.get(_normalise_field_key(key))
        if canonical_key is None:
            continue
        if raw is None or not isinstance(raw, str):
            continue
        tag = str.strip(raw)
        if tag:
            by_canonical[canonical_key].append(tag)

    values: list[str] = []
    seen: set[str] = set()
    # Emit in canonical field order; de-dupe exact strings only.
    for key in _LICENSE_FIELD_KEYS:
        for tag in by_canonical[key]:
            if tag not in seen:
                seen.add(tag)
                values.append(tag)
    return values


def _audit_row_licenses(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
    required: bool = True,
) -> LicenseAuditResult:
    """Audit every licence field; fail closed on ambiguity or any denylist hit.

    Distinct licence *values* on the same row are ``invalid_row`` (BR-35).
    When values agree, a single ``audit_spdx`` runs. When they disagree, the
    row is rejected rather than silently preferring the first-truthy key.
    """
    # GATE-04: a licence-shaped key we would not collect must fail closed, not
    # be ignored -- otherwise `License: AGPL-3.0` launders into a pass.
    unrecognised = _unrecognised_license_keys(row)
    if unrecognised:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"provenance row declares licence under unrecognised key(s) "
                f"{unrecognised!r}; use one of {list(_LICENSE_FIELD_KEYS)!r}"
            ),
            category=category,
        )

    # Type-check every present licence key first, aliases included -- a
    # non-string under `License` must fail the same way as under `license`.
    for key in sorted(k for k in row if isinstance(k, str)):
        if _normalise_field_key(key) not in _LICENSE_KEY_ALIASES:
            continue
        raw = row[key]
        if raw is None:
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=f"provenance row field {key!r} must be a string, got None",
                category=category,
            )
        if not isinstance(raw, str):
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    f"provenance row field {key!r} must be a string, "
                    f"got {type(raw).__name__}"
                ),
                category=category,
            )

    values = _license_values_of(row)
    if not values:
        if required:
            return _fail(
                RejectionReason.MISSING_LICENSE_FIELD,
                detail="license / spdx_id field is required",
                category=category,
            )
        return _pass(detail="no license field present", category=category)

    # Normalise for comparison (casefold) — disagreeing SPDX ids fail closed.
    # Unbound casefold: values may still be str subclasses (GATE-15).
    folded = {str.casefold(v) for v in values}
    if len(folded) > 1:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "provenance row declares disagreeing licence values "
                f"{values!r}; fail-closed on ambiguity"
            ),
            category=category,
        )

    # Values agree (possibly different case) — audit the first declaration.
    spdx_result = audit_spdx(values[0])
    if not spdx_result.ok:
        return LicenseAuditResult(
            verdict=spdx_result.verdict,
            reason=spdx_result.reason,
            detail=spdx_result.detail,
            category=category,
        )
    return _pass(detail=spdx_result.detail, category=category)


def _source_of(row: Mapping[str, Any]) -> str:
    raw = row.get("source") or ""
    if not isinstance(raw, str):
        return ""
    return str.strip(raw)


def _parse_row_category(
    row: Mapping[str, Any],
    *,
    audit_category: PolicyCategory,
) -> tuple[PolicyCategory | None, LicenseAuditResult | None]:
    """Parse row-declared ``category`` once (BR-38). Non-dispatching (BR-34).

    Returns ``(declared_or_None, error_or_None)``. Unknown values fail
    ``invalid_row``; empty/absent yields ``(None, None)``.
    """
    if "category" not in row:
        return None, None
    raw_cat = row["category"]
    if raw_cat is None:
        return None, None
    if not isinstance(raw_cat, str):
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                "row category must be a string, "
                f"got {type(raw_cat).__name__}"
            ),
            category=audit_category,
        )
    text = str.strip(raw_cat)
    if not text:
        return None, None
    try:
        return PolicyCategory(text), None
    except ValueError:
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=f"unknown policy category {raw_cat!r}",
            category=audit_category,
        )


def _is_operator_owned_source(source: str) -> bool:
    """True for self-generated / operator-* *provenance* sources.

    Training-data provenance namespace only. Not the registration-exemption
    predicate — that is :func:`_is_operator_owned_lineage` (GATE-21).
    """
    return _normalize_token(source) in _POSITIVE_TRAINING_SOURCES


def _operator_owned_lineage_forms() -> frozenset[str]:
    """Canonical exact forms of :data:`OPERATOR_OWNED_LINEAGE` (GATE-24).

    Recomputed per call so a test may substitute the registry; the set is two
    entries wide and this runs once per row, not per image.
    """
    forms: set[str] = set()
    for key in OPERATOR_OWNED_LINEAGE:
        kc = canonical(key)
        if kc is None or not kc:
            continue
        forms.update(_expand_id_forms(kc, exact_only=True))
    return frozenset(forms)


def _is_operator_owned_lineage(derived: str) -> bool:
    """True when ``derived`` is exactly an :data:`OPERATOR_OWNED_LINEAGE` tag.

    Whole-token exact match after canonicalisation (GATE-21 / GATE-24). Fails
    closed for anything not listed. Does **not** accept a row-author naming
    convention (bare ``acx/`` prefix), a foreign org prefix
    (``evilcorp/acx_internal_projector``), or a variant suffix
    (``acx_internal_projector_r50``) -- the operator registers the exact
    lineage or the row does not clear registration.
    """
    if not derived or not str.strip(str(derived)):
        return False
    c = canonical(str(derived))
    if c is None or not c:
        return False
    return c in _operator_owned_lineage_forms()


def _is_positive_or_registered_source(source: str) -> bool:
    """Source is on the positive allowlist, model-ingest registry, or synthetic registry."""
    if not source or not str.strip(str(source)):
        return False
    if _is_operator_owned_source(source):
        return True
    if _is_model_ingest_key(source) or _resolve_model_key(source) in MODEL_INGEST_ENTRIES:
        return True
    if _resolve_registry_head(source, SYNTHETIC_SOURCE_ENTRIES) is not None:
        return True
    # Alias forms (blazeface, rtdetr, …).
    resolved = _resolve_model_key(source)
    if resolved in MODEL_INGEST_ENTRIES:
        return True
    return False


def _derived_ingest_key(derived: str) -> str | None:
    """Return the MODEL_INGEST registry key for ``derived``, or None.

    Exact only (B4b / BR-52): the whole canonical form or a slash component
    must resolve to a registered key / alias. Progressive underscore-prefix
    laundering (``yunet_evil`` → ``yunet``) is intentionally absent.
    """
    if not derived or not str.strip(str(derived)):
        return None
    c = canonical(str(derived))
    if c is None or not c:
        return None

    candidates: list[str] = [c]
    if "/" in c:
        # First path component and each component (exact).
        candidates.append(c.split("/")[0])
        candidates.extend(p for p in c.split("/") if p)

    seen: set[str] = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        resolved = _resolve_model_key(cand)
        if resolved in MODEL_INGEST_ENTRIES:
            return resolved
    return None


def _strip_source_token(value: str) -> str:
    """Unbound strip for source-axis tokens (GATE-15 / FIR-7-PANEL-rv1-03).

    Single helper used by :func:`_source_axis_taint` (floor),
    :func:`audit_source`, and the training-data door. A bound-strip
    mutation of this helper alone must turn the ToOp pin red — three
    independent ``str.strip`` sites previously required a dual mutation.
    """
    return str.strip(value)


def _source_axis_taint(
    row_or_source: Mapping[str, Any] | str,
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """NC / research taint on the ``source`` axis, re-tagged for the calling door.

    Wraps :func:`audit_source` — the training-data reference implementation —
    so every row-shaped door enforces the same source rules, including its
    confusable fail-closed check. An absent or blank source is not an error
    here; doors that require a source enforce that themselves.
    """
    if isinstance(row_or_source, str):
        text = _strip_source_token(row_or_source)
    else:
        raw = row_or_source.get("source")
        if not isinstance(raw, str):
            return None
        text = _strip_source_token(raw)
    if not text:
        return None
    result = audit_source(text)
    if result.ok:
        return None
    return LicenseAuditResult(
        verdict=result.verdict,
        reason=result.reason,
        detail=result.detail,
        category=category,
    )


def _row_clearance_decision_token(row: Mapping[str, Any]) -> str | None:
    """Return the stripped synthetic-lineage ``clearance_decision`` from ``row``.

    Distinct from :func:`_row_photo_clearance_token` (occluder photo-release).
    One key must not carry both axes (BR-65 / NAME-03).
    """
    raw = row.get("clearance_decision")
    if not isinstance(raw, str):
        return None
    text = str.strip(raw)
    return text if text else None


def _row_photo_clearance_token(row: Mapping[str, Any]) -> str | None:
    """Return the stripped occluder ``photo_clearance`` from ``row``, or None."""
    raw = row.get("photo_clearance")
    if not isinstance(raw, str):
        return None
    text = str.strip(raw)
    return text if text else None


def _audit_clearance_decision(
    entry: SyntheticSourceEntry,
    *,
    row_clearance: str | None,
    category: PolicyCategory,
    source_label: str | None = None,
) -> LicenseAuditResult | None:
    """Compare row ``clearance_decision`` against a registry entry's token.

    Shared by :func:`audit_synthetic_source` and the content-triggered floor
    in :func:`_common_provenance_checks` (GATE-11 / PROV-04). Returns a FAIL
    when the entry requires a decision token that is missing or mismatched;
    ``None`` when no clearance is required or the token matches.
    """
    decision = entry.verification.clearance_decision
    if not decision:
        return None
    # FIR-7-RV-13: exact match on the canonical lower-case token only —
    # case-fold drift (e.g. upper-cased decision string) is refused.
    if row_clearance is not None:
        supplied = str.strip(str(row_clearance))
        if supplied == decision:
            return None
    label = source_label or entry.source_id
    return _fail(
        RejectionReason.PENDING_LEGAL_CLEARANCE,
        detail=(
            f"synthetic source {label!r} requires "
            f"clearance_decision={decision!r}; "
            f"got {row_clearance!r}"
        ),
        category=category,
    )


def _content_triggered_clearance_check(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Content-triggered synthetic-lineage clearance floor (GATE-11 / SECD-03).

    Fires only when the row names a ``source`` or ``derived_from_model`` whose
    synthetic-registry entry carries a non-empty ``clearance_decision``, and
    the row does not supply a matching ``clearance_decision`` field token.
    Rows with no such signal are unaffected — this is not an unconditional
    clearance demand.

    Runs on **every** door, including ``OCCLUDER_ASSET`` (BR-65 / WEB-33 /
    SECD-03). The occluder door ADDs a separate photo-release obligation on
    the independent ``photo_clearance`` field (``uncleared_occluder_asset``);
    that restriction is additive and must never waive this floor. The two
    axes use distinct keys so a generic photo token cannot satisfy synthetic
    lineage clearance and a lineage decision token cannot satisfy photo
    release (NAME-03).
    """
    row_clearance = _row_clearance_decision_token(row)
    # Walk source then derived_from_model; first mismatch wins (short-circuit).
    # Non-string values are rejected by the floor type check before this runs
    # (BR-68); blank strings are absence, not a synthetic signal.
    for key in ("source", "derived_from_model"):
        raw = row.get(key)
        if not isinstance(raw, str) or not str.strip(raw):
            continue
        token = str.strip(raw)
        resolved = _resolve_registry_head(token, SYNTHETIC_SOURCE_ENTRIES)
        if resolved is None:
            continue
        entry = SYNTHETIC_SOURCE_ENTRIES.get(resolved)
        if entry is None:
            continue
        mismatch = _audit_clearance_decision(
            entry,
            row_clearance=row_clearance,
            category=category,
            source_label=entry.source_id,
        )
        if mismatch is not None:
            return mismatch
    return None


def _floor_string_field(
    row: Mapping[str, Any],
    key: str,
    *,
    category: PolicyCategory,
) -> tuple[str | None, LicenseAuditResult | None]:
    """Floor-side optional string validation (BR-68 / SECD-05).

    Absent key → ``(None, None)``. Present non-string (including ``None``) →
    ``invalid_row``. The floor must never ``continue`` past a value it cannot
    validate — an unparseable field is a rejection, not an absence.
    """
    if key not in row:
        return None, None
    raw = row[key]
    if raw is None:
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=f"provenance row field {key!r} must be a string, got None",
            category=category,
        )
    if not isinstance(raw, str):
        return None, _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"provenance row field {key!r} must be a string, "
                f"got {type(raw).__name__}"
            ),
            category=category,
        )
    return raw, None


def _floor_taint_and_clearance(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Taint + clearance + registration half of the complete-mediation floor.

    Precedence within this half (BR-64 / GATE-01 / GATE-11 / BR-66 / BR-68):

      1. ``derived_from_model`` type + taint (NC, research-corpus, invalid type)
      2. ``source`` type + axis taint (NC / research; SYNTHETIC_SOURCE exempt
         only for synthetic-registry heads so its door can report a more
         specific clearance reason, with a PASS backstop re-applying the taint
         — FIR-7-RV-11)
      3. content-triggered synthetic ``clearance_decision`` (GATE-11 / BR-65):
         fires on every door when source/derived resolves to a registry entry
         that carries a decision token
      4. package-identity denylist across package / package_name / model_id /
         source (FIR-7-RV-10) — floor, not first-wins

    Registration (BR-33 / BR-66) is a separate half — :func:`_floor_registration`
    — so the TOOLING door can order package allowlist admission ahead of it
    (GATE-22 / BR-24) without a flag that drops an axis (BR-69).

    Callers that must interleave axes with their own gates (e.g. TOOLING
    package allowlist admission before registration and row SPDX — BR-24 /
    GATE-05 / GATE-22) call this half, then their door gate, then
    :func:`_floor_registration` / :func:`_floor_licenses`. They never get a
    floor call that silently omits an axis (BR-69 / ARCH-13).
    """
    # Taint outranks licence: a row that is both NC-derived and badly licensed
    # must report the NC reason. Swapping the licence field would clear a
    # licence reason while the banned lineage survives, so reporting the
    # licence first understates the problem (BR-64 / GATE-01).
    if "derived_from_model" in row:
        raw, type_err = _floor_string_field(
            row, "derived_from_model", category=category
        )
        if type_err is not None:
            return type_err
        assert raw is not None  # key present and string
        derived_result = audit_derived_from_model(raw)
        if not derived_result.ok:
            # Preserve NC / research / invalid reasons; re-tag for the calling door.
            return LicenseAuditResult(
                verdict=derived_result.verdict,
                reason=derived_result.reason,
                detail=derived_result.detail,
                category=category,
            )

    # BR-68: non-string source fails closed on every door before any axis that
    # would otherwise skip it as "absence".
    if "source" in row:
        raw_src, src_type_err = _floor_string_field(
            row, "source", category=category
        )
        if src_type_err is not None:
            return src_type_err
        assert raw_src is not None

    # BR-53: the `source` axis is category-independent too -- model_ingest and
    # tooling accepted an NC/research source outright while training_data has
    # always rejected it. Registry membership stays a category-specific rule, so
    # doors that legitimately accept an unregistered source are unaffected (the
    # floor may only ADD).
    #
    # FIR-7-RV-11: SYNTHETIC_SOURCE is exempt *only* for tokens that resolve to
    # a synthetic-registry head, so that door can report a more specific
    # clearance reason. Research / NC sources that are not registry heads still
    # report their source-axis taint (research_only_source / nc_model_derived)
    # rather than the generic pending_legal_clearance unknown-head default.
    # The dispatcher re-applies this taint to any PASS from that door, so
    # exempting registry heads cannot widen a verdict.
    if category is PolicyCategory.SYNTHETIC_SOURCE:
        raw_for_taint = row.get("source") if "source" in row else None
        if isinstance(raw_for_taint, str) and _strip_source_token(raw_for_taint):
            head = _resolve_registry_head(
                _strip_source_token(raw_for_taint), SYNTHETIC_SOURCE_ENTRIES
            )
            if head is None:
                source_taint = _source_axis_taint(row, category=category)
                if source_taint is not None:
                    return source_taint
    else:
        source_taint = _source_axis_taint(row, category=category)
        if source_taint is not None:
            return source_taint

    # GATE-11 / BR-65: content-triggered synthetic-lineage clearance on every
    # door. Occluder photo-release is a separate additive axis on photo_clearance.
    clearance_hit = _content_triggered_clearance_check(row, category=category)
    if clearance_hit is not None:
        return clearance_hit

    # FIR-7-RV-10: package-identity denylist floor on every door (after
    # clearance so synthetic-lineage reasons still surface when both fire;
    # before registration / door-local gates so a denylisted secondary field
    # cannot hide behind first-wins selection of a clean primary).
    package_hit = _floor_package_identity_denylist(row, category=category)
    if package_hit is not None:
        return package_hit

    return None


def _floor_registration(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Registration half of the complete-mediation floor (BR-33 / BR-66).

    Content-triggered on every door. Split from :func:`_floor_taint_and_clearance`
    so TOOLING can run the package denylist first (GATE-22 / BR-24) without a
    flag that drops this axis (BR-69 / ARCH-13).
    """
    derived_text = ""
    if "derived_from_model" in row:
        raw = row.get("derived_from_model")
        if isinstance(raw, str):
            derived_text = str.strip(raw)
    source_text = ""
    if "source" in row:
        raw_src = row.get("source")
        if isinstance(raw_src, str):
            source_text = str.strip(raw_src)
    return _audit_derived_registration(
        source=source_text,
        derived=derived_text,
        category=category,
    )


def _floor_licenses(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Licence half of the complete-mediation floor (present values only).

    Runs on every row-shaped door when composed via
    :func:`_common_provenance_checks`. Doors that require a licence field
    still enforce ``required=True`` later. TOOLING calls this half *after*
    its package denylist gate so a self-declared licence cannot launder a
    denylisted package (BR-24 / GATE-05).
    """
    license_result = _audit_row_licenses(row, category=category, required=False)
    if not license_result.ok:
        # GATE-08: re-tag licence failures with door context so a
        # present-but-invalid value caught here reads the same as a
        # missing field caught later by the door's required=True call.
        # INVALID_ROW is left unprefixed (matches the door branch).
        if (
            category is PolicyCategory.OCCLUDER_ASSET
            and license_result.reason is not RejectionReason.INVALID_ROW
        ):
            detail = license_result.detail
            prefix = "occluder asset: "
            if not detail.startswith(prefix):
                detail = f"{prefix}{detail}"
            return LicenseAuditResult(
                verdict=license_result.verdict,
                reason=license_result.reason,
                detail=detail,
                category=category,
            )
        return license_result
    return None


def _common_provenance_checks(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Category-independent floor shared by every row-shaped entry point (BR-26).

    Complete-mediation floor: category-specific doors may only ADD
    restrictions, never subtract (BR-53 / BR-69). There is no parameter that
    can disable an axis — the structure makes subtraction unrepresentable
    (ARCH-13). Callers that legitimately need the licence axis at a different
    point in their own precedence chain call :func:`_floor_taint_and_clearance`
    and :func:`_floor_licenses` explicitly; they never get a floor call that
    silently omits either half.

    Exactly one reason is reported per call (short-circuit). Precedence order
    when a row trips multiple axes:

      1. ``derived_from_model`` type + taint (NC, research-corpus, invalid type)
      2. ``source`` type + axis taint (NC / research; SYNTHETIC_SOURCE exempt
         only for synthetic-registry heads so its door can report a more
         specific clearance reason, with a PASS backstop re-applying the taint
         — FIR-7-RV-11)
      3. content-triggered synthetic ``clearance_decision`` on every door
         (GATE-11 / BR-65); occluder photo-release is a separate additive axis
      4. package-identity denylist floor across package / package_name /
         model_id / source (FIR-7-RV-10 / BR-53 floor, not first-wins)
      5. unregistered ``derived_from_model`` registration (BR-33 / BR-66)
      6. licence values (denylist + allowlist, present values only; doors that
         require a licence field still enforce ``required=True`` later)

    TOOLING does **not** use this full composition for licence ordering: it
    interleaves the package allowlist admission between the taint/clearance/
    package-denylist floor and registration (GATE-22 / BR-24).

    Returns a FAIL result when a floor rule fires; ``None`` means the caller
    may continue with category-specific gates.
    """
    taint = _floor_taint_and_clearance(row, category=category)
    if taint is not None:
        return taint
    unreg = _floor_registration(row, category=category)
    if unreg is not None:
        return unreg
    return _floor_licenses(row, category=category)


# ---------------------------------------------------------------------------
# Public audit functions
# ---------------------------------------------------------------------------


def _reject_non_string(
    value: Any,
    *,
    field: str,
    category: PolicyCategory | None = None,
) -> LicenseAuditResult | None:
    """Shared type contract for public scalar ``audit_*`` entry points (BR-46).

    ``None`` and ``str`` are not type errors — each door documents its own
    empty/missing handling. Every other type returns ``invalid_row`` with a
    detail that names the offending type, so callers never see a policy
    outcome (or an exception) for a programming error.
    """
    if value is None or isinstance(value, str):
        return None
    return _fail(
        RejectionReason.INVALID_ROW,
        detail=f"{field} must be a string, got {type(value).__name__}",
        category=category,
    )


# ---------------------------------------------------------------------------
# Package-identity structural family matching (FIR-7 Wave F / F5 / F6)
# ---------------------------------------------------------------------------
# Replaces the Wave-E size/task tag-strip treadmill. Module docstring owns the
# design narrative; helpers below implement (a)/(b)/(c)/(d) for both deny and
# exception seeds, plus deny-only (e) compact segment-suffix, behind a uniform
# iterative component scanner. Outer separator-aligned suffix walk (gated by
# ``_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED``) provides path-split / size-tag
# coverage — there is no inner (d') walk (FIR-7-A9-01 / A9-02 / B9-01).

# Branch enable flags (always True in production). Tests red-prove each branch
# by monkeypatching EXACTLY ONE flag to False (TEST-15): disable (b) → compound
# witnesses admit; disable (c) → yolov9t admits; disable elevated deny-(c)
# arm alone → pure elevated pins (yolov9t / fastsamx) admit while exception-
# residual classify still closes yoloseg / yolofree (FIR-7 F10 single-
# mechanism split); disable head-segment → yolov9t-seg admits; disable outer
# residual-suffix scan → path-split / size-tag shields admit; disable (e) →
# compact glue sole-path (xultralytics / yolox_xultralytics) admits
# (yoloxultralytics / yoloxsultralytics stay steal-owned and still
# deny); disable residual
# re-scan → yolox_ultralytics admits (exception short-circuit); disable
# multi-strip continuation → yolox_yolop_ultralytics admits; disable fail-
# closed scan bounds → non-shrinking strip admits (synthetic invariant
# probe; FIR-7-B9-04); disable NC structural match → yolo_nas_l_free /
# yolo_nas_l_blah admit on weights doors (sole-path: pure-alpha short tags
# that are NOT export-shaped, so floor whole-component promotion misses —
# FIR-7-B11-04; known export tags like yolo_nas_l_trt still reject via
# floor); disable NC package component-suffix walk → myprefix_antelopev2
# admits on weights doors (FIR-7-B9-02 follow-up); disable exception
# residual classification (``_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED``) →
# yoloseg / yolofree / yolos_eg / yolosfree / yolox_s_free admit (F10
# single mechanism for exception+debris); disable long-seed compact-prefix
# glue → ultralyticsplus admits (FIR-7-B13-5).
# Every surviving flag must change ≥ 1 pinned outcome when flipped alone
# (no-op flags are TEST-15 violations). Flag inventory (F10): the thirteen
# booleans below; ``_FAMILY_GENERALIZED_SUFFIX_ENABLED`` is deleted.
_FAMILY_BOUNDARY_PREFIX_ENABLED: bool = True
_FAMILY_COMPACT_REMAINDER_ENABLED: bool = True
_FAMILY_HEAD_SEGMENT_ENABLED: bool = True
_FAMILY_COMPACT_SUFFIX_ENABLED: bool = True  # (e)
_EXCEPTION_RESIDUAL_RESCAN_ENABLED: bool = True
_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED: bool = True
_EXCEPTION_MULTI_STRIP_CONTINUATION_ENABLED: bool = True
_SCAN_FAIL_CLOSED_BOUNDS_ENABLED: bool = True  # defensive invariant (B9-04)
_NC_STRUCTURAL_MATCH_ENABLED: bool = True  # sole-path: yolo_nas_l_free (B11-04)
# FIR-7-B9-02 follow-up: separator-aligned suffix walk inside
# ``_whole_component_nc_package_hit`` so prefix-shielded NC package seeds
# (``myprefix_antelopev2``) reject on weights doors. When False, only the
# whole slash-component is tested (export-shaped ``insightface_trt`` still
# rejects; prefix forms admit — red-proof cell).
_NC_PACKAGE_COMPONENT_SUFFIX_ENABLED: bool = True
# FIR-7 F10: single-mechanism residual classification for exception-family
# seeds with non-empty residual (compact or separator). Covers short debris
# (yoloseg / yolos_eg), long debris (yolofree / yolosegme / yolosfree),
# tag+debris laundering (yolos_tiny_eg / yolox_s_free), and unknown
# residual fail-closed. Length is never the discriminator. Flag name kept
# for TEST-15 continuity with the F9 steal gate it supersedes.
_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED: bool = True
# FIR-7-B12-1 / F10: gates only the elevated deny-(c) arm (1–3 rem) inside
# ``_deny_folded_ab_hit``. Distinct from ``_FAMILY_COMPACT_REMAINDER_ENABLED``
# so elevated pure-deny pins (yolov9t) are single-mechanism red-provable
# without killing exception (c) matching that residual classify needs.
# Exception-prefix debris (yoloseg) is owned by residual classify, not
# this flag — elevated alone does not close those forms (F10).
_ELEVATED_DENY_COMPACT_ENABLED: bool = True
# FIR-7-B13-5: long denylist-stem compact-prefix glue (ultralyticsplus).
_DENY_COMPACT_PREFIX_GLUE_ENABLED: bool = True

# Bounded compact remainder: 1–3 alphanumeric chars after a seed compact form.
_BOUNDED_COMPACT_REMAINDER = re.compile(r"^[a-z0-9]{1,3}$")
# Compact segment-suffix (e): seed must be at least this many compact chars so
# short seeds like ``yolo`` (4) cannot false-deny ``myyolo``.
_COMPACT_SUFFIX_MIN_SEED_LEN: int = 5
# Long-seed compact-prefix glue (FIR-7-B13-5): denylist stems at least this
# many compact chars deny any non-empty alnum remainder (ultralytics+plus).
# Short seeds (yolo, len 4) stay on the 1–3 bound so yolodummy admits.
# ultralytics=11; keep above buffalo_l/buffalos (8) so separator (b) alone
# still owns buffalo_l_extra (TEST-15 for _FAMILY_BOUNDARY_PREFIX_ENABLED).
_DENY_COMPACT_PREFIX_GLUE_MIN_SEED_LEN: int = 11
_DENY_COMPACT_PREFIX_GLUE_REMAINDER = re.compile(r"^[a-z0-9]+$")
# Progressive residual re-glue bound (FIR-7 F10). Module-level so TEST-15 can
# pin it; length of *segments* is not a debris classifier — this only caps
# how many residual segments participate in deny-reconstitution re-glue.
_MAX_RECONST_SEGMENTS: int = 8


def _folded_family_seed_keys(mapping: Mapping[str, Any]) -> set[str]:
    """Folded + compact identity keys for every seed in a family mapping."""
    keys: set[str] = set()
    for key in mapping:
        kc = canonical(str(key))
        if kc is None or not kc:
            kc = _resolve_model_key(str(key))
        if not kc:
            continue
        keys.add(kc)
        compact = _compact_canonical(kc)
        if compact:
            keys.add(compact)
    return keys


def _assert_package_family_seed_sets_disjoint() -> None:
    """Import-time guard: deny and exception family seeds must not overlap."""
    deny_keys = _folded_family_seed_keys(PACKAGE_DENYLIST)
    exc_keys = _folded_family_seed_keys(PACKAGE_EXCEPTION_ALLOWLIST)
    overlap = deny_keys & exc_keys
    if overlap:
        raise RuntimeError(
            "PACKAGE_DENYLIST and PACKAGE_EXCEPTION_ALLOWLIST seed sets must "
            f"be disjoint; overlapping folded keys: {sorted(overlap)!r}"
        )


def _iter_family_seeds(
    mapping: Mapping[str, Any],
) -> list[tuple[str, str, Any]]:
    """Unique (canonical_seed, compact_seed, entry) triples for a family map.

    Rebuilt per call so monkeypatched ``PACKAGE_DENYLIST`` /
    ``PACKAGE_EXCEPTION_ALLOWLIST`` stay honest under tests.
    """
    out: list[tuple[str, str, Any]] = []
    seen: set[str] = set()
    for key, entry in mapping.items():
        kc = canonical(str(key))
        if kc is None or not kc:
            kc = _resolve_model_key(str(key))
        if not kc or kc in seen:
            continue
        seen.add(kc)
        out.append((kc, _compact_canonical(kc), entry))
    return out


def _family_match_abc(
    token: str,
    seed_canonical: str,
    seed_compact: str,
    *,
    allow_rule_c: bool = True,
) -> bool:
    """True if folded ``token`` hits seed under head-aligned rules (a)(b)(c).

    ``allow_rule_c=False`` skips compact remainder (c) — used by deny-path
    whole-token matching so elevated deny-(c) is the sole whole-token (c)
    closer (FIR-7 F10 TEST-15). Head-segment (d) keeps ``allow_rule_c=True``
    so ``yolov9t-seg`` still matches on the head.
    """
    if not token or not seed_canonical:
        return False
    token_compact = _compact_canonical(token)

    # (a) exact match on folded or compact form.
    if token == seed_canonical or token_compact == seed_compact:
        return True
    if token == seed_compact or token_compact == seed_canonical:
        return True

    # (b) separator-boundary prefix: token == seed + '_' + non-empty rest.
    if _FAMILY_BOUNDARY_PREFIX_ENABLED:
        boundary = seed_canonical + "_"
        if token.startswith(boundary) and len(token) > len(boundary):
            return True

    # (c) bounded compact remainder: compact starts with seed, rem ∈ [a-z0-9]{1,3}.
    if (
        allow_rule_c
        and _FAMILY_COMPACT_REMAINDER_ENABLED
        and seed_compact
    ):
        if token_compact.startswith(seed_compact):
            rem = token_compact[len(seed_compact) :]
            if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
                return True
            # F13-5: documented compact-glue allowlist rem (ppyolo + eplus)
            # is a real identity, not 1–3 debris.
            if rem and rem in _EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST.get(
                seed_canonical, frozenset()
            ):
                return True
    return False


def _family_match_head_segment(
    token: str,
    seed_canonical: str,
    seed_compact: str,
) -> bool:
    """Legacy (d) head-segment: leading segment hits via (a) or (c)."""
    if not _FAMILY_HEAD_SEGMENT_ENABLED or "_" not in token:
        return False
    head = token.split("_", 1)[0]
    if not head:
        return False
    # (a)/(c) on head alone (head has no separator — not (b)).
    return _family_match_abc(head, seed_canonical, seed_compact)


def _family_match_compact_suffix(
    token: str,
    seed_canonical: str,
    seed_compact: str,
) -> bool:
    """Rule (e): segment compact form ends with deny seed of >= 5 chars.

    Only individual segments are tested (a one-segment token is its own
    segment). Multi-segment compact-join is intentionally NOT tested — that
    would shadow the outer suffix walk and break independent red-proofs.
    Leading remainder must be non-empty; seeds shorter than
    ``_COMPACT_SUFFIX_MIN_SEED_LEN`` never match (``myyolo`` / ``yolo``
    admit pin). ``seed_compact`` is already
    ``seed_canonical.replace('_', '')`` so a second endswith on the
    underscore-stripped canonical is unreachable and is not tested
    (FIR-7-A9-03).
    """
    if not _FAMILY_COMPACT_SUFFIX_ENABLED:
        return False
    if not seed_compact or len(seed_compact) < _COMPACT_SUFFIX_MIN_SEED_LEN:
        return False
    # seed_canonical retained for call-site symmetry with other matchers;
    # compact form is the sole endswith target (A9-03).
    _ = seed_canonical
    for seg in token.split("_"):
        if not seg:
            continue
        seg_k = _compact_canonical(seg)
        if not seg_k or len(seg_k) <= len(seed_compact):
            continue
        if seg_k.endswith(seed_compact):
            # Non-empty leading remainder is implied by len check above.
            return True
    return False


def _family_match_seed(
    token: str,
    seed_canonical: str,
    seed_compact: str,
    *,
    for_deny: bool = False,
    allow_rule_e: bool = True,
    allow_rule_c: bool = True,
) -> bool:
    """True if folded ``token`` hits one family seed.

    Exception path (``for_deny=False``): rules (a)(b)(c) + head-segment (d).
    Deny path (``for_deny=True``): whole-token (a)(b)/(c)/(d) plus (e)
    compact segment-suffix when ``allow_rule_e`` is True. Separator-aligned
    suffix coverage is the **outer** walk in :func:`_uniform_component_scan`
    (FIR-7-A9-01) — there is no inner (d') walk. NC doors pass
    ``allow_rule_e=False`` so BR-28 controls like ``not-insightface`` stay
    clean on membership-only paths (FIR-7-B8-06).

    ``allow_rule_c=False`` skips whole-token compact (c) so the uniform
    scanner's trailing deny family hit does not double-cover elevated
    deny-(c) (FIR-7 F10 TEST-15 sole-path). Head-segment (d) still uses
    (c) on the head. NC door promotion keeps ``allow_rule_c=True``.
    """
    if not token or not seed_canonical:
        return False

    if _family_match_abc(
        token,
        seed_canonical,
        seed_compact,
        allow_rule_c=allow_rule_c,
    ):
        return True
    if _family_match_head_segment(token, seed_canonical, seed_compact):
        return True
    if (
        for_deny
        and allow_rule_e
        and _family_match_compact_suffix(token, seed_canonical, seed_compact)
    ):
        return True
    return False


def _family_match_specificity(
    token: str,
    seed_canonical: str,
    seed_compact: str,
) -> int:
    """Match-shape specificity for seed ranking (higher wins).

    FIR-7-F7: when both ``antelopev2`` and ``antelope_v2`` (same compact
    form) match a token, prefer exact folded identity over compact-alias
    or head-segment, so door promotion sees the honest package_id and
    export-shaped (b) on ``antelopev2_int8`` is not stolen by a
    head-segment hit on the underscore alias.
    """
    if not token or not seed_canonical:
        return -1
    token_compact = _compact_canonical(token)
    # Exact folded identity.
    if token == seed_canonical:
        return 5
    # Exact compact identity (token compact == seed compact, or cross).
    if (
        token_compact == seed_compact
        or token == seed_compact
        or token_compact == seed_canonical
    ):
        return 4
    # Separator-boundary (b).
    if _FAMILY_BOUNDARY_PREFIX_ENABLED:
        boundary = seed_canonical + "_"
        if token.startswith(boundary) and len(token) > len(boundary):
            return 3
    # Bounded compact remainder (c).
    if _FAMILY_COMPACT_REMAINDER_ENABLED and seed_compact:
        if token_compact.startswith(seed_compact):
            rem = token_compact[len(seed_compact) :]
            if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
                return 2
    # Head-segment (d) — weaker than whole-token shapes.
    if _family_match_head_segment(token, seed_canonical, seed_compact):
        return 1
    # Compact suffix (e) or other.
    return 0


def _best_family_seed_match(
    token: str,
    mapping: Mapping[str, Any],
    *,
    for_deny: bool = False,
    allow_rule_e: bool = True,
    allow_rule_c: bool = True,
) -> tuple[str, str, Any] | None:
    """Longest-matching family seed triple ``(seed_c, seed_k, entry)``, or None.

    Shared ranking fold for deny hits, exception residual strips, and NC
    detail notes (FIR-7-A7-04 / A8-04 / F7): rank by
    ``(specificity, len(compact), len(canonical))`` descending so exact
    identity outranks compact-alias / head-segment of an equal-compact
    sibling seed.
    """
    best: tuple[str, str, Any] | None = None
    best_key: tuple[int, int, int] = (-1, -1, -1)
    for seed_c, seed_k, entry in _iter_family_seeds(mapping):
        if not _family_match_seed(
            token,
            seed_c,
            seed_k,
            for_deny=for_deny,
            allow_rule_e=allow_rule_e,
            allow_rule_c=allow_rule_c,
        ):
            continue
        spec = _family_match_specificity(token, seed_c, seed_k)
        rank = (spec, len(seed_k), len(seed_c))
        if rank > best_key:
            best_key = rank
            best = (seed_c, seed_k, entry)
    return best


def _best_family_hit(
    token: str,
    mapping: Mapping[str, Any],
    *,
    for_deny: bool = False,
    allow_rule_e: bool = True,
    allow_rule_c: bool = True,
) -> Any | None:
    """Longest-matching family seed entry for ``token``, or None."""
    matched = _best_family_seed_match(
        token,
        mapping,
        for_deny=for_deny,
        allow_rule_e=allow_rule_e,
        allow_rule_c=allow_rule_c,
    )
    if matched is None:
        return None
    return matched[2]


def _strip_exception_seed_residual(
    token: str,
    seed_c: str,
    seed_k: str,
) -> str:
    """Strip a matched exception seed from ``token``; return residual.

    Empty residual means exact seed match (admit, no re-scan). Non-empty
    residual is a whole token (canonical segments rejoined) for residual
    suffix re-scan. Prefer canonical boundary strip, then bounded compact
    remainder, then head-segment strip. Only structural match shapes are
    stripped — no unbounded compact-prefix fallback (FIR-7-A7-04).
    """
    if not token or not seed_c:
        return ""
    token_compact = _compact_canonical(token)

    # (a) exact match → empty residual.
    if token == seed_c or token_compact == seed_k:
        return ""
    if token == seed_k or token_compact == seed_c:
        return ""

    # (b) separator-boundary: strip ``seed_c + '_'``.
    boundary = seed_c + "_"
    if token.startswith(boundary) and len(token) > len(boundary):
        return token[len(boundary) :]

    # (c) bounded compact remainder: residual is the compact rem as a token.
    # F12-4 / R14-G2-6: when the token contains ``_``, prefer the
    # head-segment residual so ``ppyoloe_s`` is ``e``+``s``, not the
    # compact-joined rem ``es``.
    if "_" not in token and seed_k and token_compact.startswith(seed_k):
        rem = token_compact[len(seed_k) :]
        if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
            return rem

    # (d) head-segment: strip the matched head; rejoin rem + trailing rest.
    if _FAMILY_HEAD_SEGMENT_ENABLED and "_" in token:
        head, rest = token.split("_", 1)
        if head:
            head_compact = _compact_canonical(head)
            if (
                head == seed_c
                or head_compact == seed_k
                or head == seed_k
                or head_compact == seed_c
            ):
                return rest
            if _FAMILY_COMPACT_REMAINDER_ENABLED and seed_k:
                if head_compact.startswith(seed_k):
                    rem = head_compact[len(seed_k) :]
                    if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
                        return f"{rem}_{rest}" if rest else rem
                    # F13-5: allowlisted rem is part of the compact
                    # identity (ppyoloeplus); residual is the tail only.
                    if rem and rem in _EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST.get(
                        seed_c, frozenset()
                    ):
                        return rest

    return ""


def _best_exception_hit_with_residual(
    token: str,
) -> tuple[Any, str] | None:
    """Longest exception-family seed hit and its residual, or None."""
    matched = _best_family_seed_match(
        token, PACKAGE_EXCEPTION_ALLOWLIST, for_deny=False
    )
    if matched is None:
        return None
    seed_c, seed_k, entry = matched
    residual = _strip_exception_seed_residual(token, seed_c, seed_k)
    return entry, residual


def _scan_invariant_deny(detail: str) -> PackageDenylistEntry:
    """Fail-closed denylist entry for scanner invariant violations."""
    return PackageDenylistEntry(
        package_id="scan_invariant",
        display_name="package-identity scan invariant",
        spdx_id="FAIL-CLOSED",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=detail,
    )


# Per-family legitimate compact-(c) size/version tags (FIR-7-B12-3).
# Canonical source for compact glue legitimacy (FIR-7 A14-5 / A14-1).
# Only tags that fit the 1–3 alnum compact remainder bound and match REAL
# checkpoints for that exception family. Digit-bearing remainders are NOT
# globally legitimate — ``v8`` / ``s2`` / ``8`` launder through exception
# seeds unless listed here. Longer real tags live in
# ``_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS`` (separator-boundary (b) only).
_EXCEPTION_FAMILY_COMPACT_TAGS: dict[str, frozenset[str]] = {
    # YOLOX (Megvii): s/m/l/x; nano/tiny arrive via separator tags.
    "yolox": frozenset({"s", "m", "l", "x"}),
    # YOLOS (hustvl): tiny/small/base/large are separator-only.
    # No legitimate compact-(c) single-letter sizes (FIR-7-B12-4).
    "yolos": frozenset(),
    # YOLOF: r50 fits compact (c); r101 uses separator tags.
    "yolof": frozenset({"r50"}),
    # YOLOP (hustvl): v2 / v3.
    "yolop": frozenset({"v2", "v3"}),
    # PP-YOLO (Baidu): e (PP-YOLOe) / v2 (PP-YOLOv2).
    "ppyolo": frozenset({"e", "v2"}),
}

# Explicit compact-glue allowlist beyond family compact tags (FIR-7 A14-1).
# Empty for every family except documented real compact spellings that
# exceed the 1–3 compact-(c) bound. ``ppyolo`` / ``eplus`` is the
# published PP-YOLOE+ compact id (PaddleDetection); F13-5 also peels
# that rem in head position (``ppyoloeplus_trt``). Export/shield/
# separator tags stay illegitimate as compact glue (``yoloxpt`` /
# ``yolostiny`` deny; ``yolox_pt`` / ``yolos_tiny`` admit via separator
# residual classification).
_EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST: dict[str, frozenset[str]] = {
    "yolox": frozenset(),
    "yolos": frozenset(),
    "yolof": frozenset(),
    "yolop": frozenset(),
    "ppyolo": frozenset({"eplus"}),
}

# Separator-only size/version/backbone tags (FIR-7 A14-5 / B14-3).
# Not legitimate as compact glue — only as separator residual segments.
# B14-3: ``seg`` deliberately absent from yolos (YOLOS is detection-only;
# ``yolos_seg`` is Ultralytics canonical seg naming with the digit dropped).
#
# PP-YOLO / PP-YOLOE / PP-YOLOv2 (F12-4 / F13-4): real PaddleDetection
# catalog debris. Compact tags stay ``e`` / ``v2``. Separator-only:
#   * sizes after e: s / m / l / x / t  (``ppyoloe_s``; compact
#     ``ppyoloes`` / ``ppyolotiny`` stay DENY — A14-1 / R14-G2-4)
#   * variant: plus (PP-YOLOE+), tiny / large / small / sod
#   * backbone: crn (CSPResNet), r50vd / r18vd / r101vd, mbv3
#   * neck / op: dcn (deformable conv)
#   * schedule: 300e / 80e / 365e / 650e (epoch budgets), 1x / 2x
#   * dataset: coco / voc / objects365
#   * F14-7 PaddleDetection catalog: auxhead / relu / 320 / 416 / 640 /
#     distill / 30e / 60e (native Paddle debris — ``ppyolo_voc`` admits)
#   * F15-8 PP-YOLOE-R rotate family: r / 3x / dota (``PP-YOLOE-R`` /
#     ``ppyoloe_r_crn_s_3x_dota``; compact ``ppyoloer`` / ``ppyolodota``
#     stay DENY; ``yolox_dota`` does not leak)
# These are structural training-config tags for this family, not a
# global schedule shield. A residual containing a deny stem still denies.
# YOLOF (F12-5 / F12b-1 / F13-4) reuses the same schedule/dataset debris
# policy for Detectron2 / MMDetection catalog names (``1x`` / ``3x`` /
# ``coco`` / ``8xb8`` / ``8x8``); each family keeps its own inventory —
# ``coco`` / ``voc`` / ``8xb8`` are not a global dataset shield
# (``yolos_voc`` / ``yolox_auxhead`` / ``yolof_distill`` stay DENY).
# YOLOX (F13-4) adds MMDetection batch/schedule tags ``8xb8`` / ``8x8``
# plus ``300e`` / ``coco`` / ``voc``. Compact-glue allowlist is untouched
# (``yolox8xb8`` / ``yolofcoco`` / ``ppyoloauxhead`` stay DENY).
_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS: dict[str, frozenset[str]] = {
    "yolox": frozenset(
        {
            "nano",
            "tiny",
            "darknet",
            "darknet53",
            "8xb8",
            "8x8",
            "300e",
            "coco",
            "voc",
        }
    ),
    "yolos": frozenset({"tiny", "small", "base", "large"}),
    # YOLOF Detectron2 / MMDetection catalog (F12-5 / F12b-1 / F13-4):
    # r50 is compact; r101/c5 already here. Digit+x schedule tokens
    # (1x / 3x), the split R_50 / R_101 spelling (r, 50, 101), the
    # trailing dataset tag (coco), and MMDetection batch tokens
    # (8xb8 / 8x8) are structural config tags. Same F12-4
    # schedule/dataset debris policy as ppyolo; lists are not shared
    # (per-family inventory — yolos_8xb8 stays DENY; ppyolo_voc admits
    # as of F14-7 — voc is native Paddle debris).
    "yolof": frozenset(
        {"r101", "c5", "1x", "3x", "r", "50", "101", "coco", "8xb8", "8x8"}
    ),
    "yolop": frozenset(),
    "ppyolo": frozenset(
        {
            "s",
            "m",
            "l",
            "x",
            "t",
            "plus",
            "tiny",
            "large",
            "small",
            "sod",
            "crn",
            "r50vd",
            "r18vd",
            "r101vd",
            "mbv3",
            "dcn",
            "300e",
            "80e",
            "1x",
            "2x",
            "365e",
            "650e",
            "coco",
            # F14-7 / R16-G2-2: remaining PaddleDetection catalog debris.
            "auxhead",
            "relu",
            "320",
            "416",
            "640",
            "distill",
            "voc",
            "30e",
            "60e",
            "objects365",
            # F15-8 / R17-G2-3: PP-YOLOE-R rotate family.
            "r",
            "3x",
            "dota",
        }
    ),
}

# Derived separator-boundary inventory = compact tags ∪ separator-only
# (FIR-7 A14-5: single canonical source per form; no duplicated literals).
# Used by residual classification (a) for separator-joined residuals.
_EXCEPTION_FAMILY_SEPARATOR_TAGS: dict[str, frozenset[str]] = {
    seed: (
        _EXCEPTION_FAMILY_COMPACT_TAGS.get(seed, frozenset())
        | _EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(seed, frozenset())
    )
    for seed in (
        "yolox",
        "yolos",
        "yolof",
        "yolop",
        "ppyolo",
    )
}

# Residual classification outcomes (FIR-7 F10).
_RESIDUAL_LEGITIMATE = "legitimate"
_RESIDUAL_DEFER = "defer"
_RESIDUAL_DENY_RECONST = "deny_reconstituting"
_RESIDUAL_UNKNOWN = "unknown"


def _is_legitimate_exception_compact_rem(rem: str, seed_c: str = "") -> bool:
    """True when compact (c) residual is a per-family real size/version tag.

    FIR-7-B12-3: replaces the global size-letter set + digit-wildcard.
    ``seed_c`` selects the family tag set; unknown / empty seed → not
    legitimate (fail-closed).
    """
    if not rem or not _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
        return False
    if not seed_c:
        return False
    tags = _EXCEPTION_FAMILY_COMPACT_TAGS.get(seed_c, frozenset())
    return rem in tags


def _is_legitimate_compact_glue_residual(rem: str, seed_c: str) -> bool:
    """True when a compact-glued residual is a real family compact tag.

    FIR-7 A14-1: compact glue of a separator-only or export/shield tag
    onto a family seed is **not** legitimate (``yoloxpt`` / ``yolostiny``
    deny). Only per-family compact tags and the explicit compact-glue
    allowlist (empty except documented ``ppyolo`` / ``eplus``) admit.
    Separator-joined forms use
    :func:`_is_legitimate_residual_segment` instead.
    """
    if not rem or not seed_c:
        return False
    if rem in _EXCEPTION_FAMILY_COMPACT_TAGS.get(seed_c, frozenset()):
        return True
    if rem in _EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST.get(seed_c, frozenset()):
        return True
    return False


def _head_compact_peel_rem(
    token: str, seed_c: str, seed_k: str
) -> str | None:
    """Return compact rem if ``token``'s head is a compact peel of the seed.

    ``yoloxpt_trt`` → head ``yoloxpt`` peels rem ``pt``. Exact head
    identity (``yolox_pt`` / ``yoloxs_pt``) is not a compact peel.
    """
    if not token or not seed_k or "_" not in token:
        return None
    head, _rest = token.split("_", 1)
    if not head:
        return None
    head_compact = _compact_canonical(head)
    if (
        head == seed_c
        or head_compact == seed_k
        or head == seed_k
        or head_compact == seed_c
    ):
        return None
    if head_compact.startswith(seed_k):
        rem = head_compact[len(seed_k) :]
        if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
            return rem
        # F13-5 / R15-L-4: allowlisted compact-glue rem (eplus, 5 chars)
        # must peel in head position so ppyoloeplus_trt is not unknown.
        if rem and rem in _EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST.get(
            seed_c, frozenset()
        ):
            return rem
    return None


def _exception_residual_uses_compact_glue_rules(
    token: str, seed_c: str, seed_k: str
) -> bool:
    """True when residual must be classified under compact-glue rules.

    Whole-token compact (no ``_``) is always compact glue (A14-1).
    Head compact-peel of a rem that is **not** a legitimate compact-glue
    tag (``pt`` / ``c5`` / ``trt``) forces compact-glue rules so a
    separator tail cannot launder it (F12-2 / ``yoloxpt_trt`` / SECD-05).
    A legitimate compact-tag peel (``yoloxs_pt``) keeps separator rules.
    """
    if "_" not in token:
        return True
    peel = _head_compact_peel_rem(token, seed_c, seed_k)
    if peel is None:
        return False
    return not _is_legitimate_compact_glue_residual(peel, seed_c)


def _is_legitimate_residual_segment(segment: str, seed_c: str) -> bool:
    """True when one residual segment is a family tag or export shield tag.

    FIR-7 F10 classification (a) for **separator-joined** residuals:
    per-family compact/separator tags **or** any member of
    ``_NC_TRAILING_SHIELD_TAGS`` (export/format inventory is the single
    source of truth for ``trt`` / ``pt`` / ``bin`` / ``onnx`` / …).
    Length is never consulted. Compact-glue residuals use
    :func:`_is_legitimate_compact_glue_residual` instead (A14-1).
    """
    if not segment:
        return False
    if segment in _NC_TRAILING_SHIELD_TAGS:
        return True
    if not seed_c:
        return False
    if segment in _EXCEPTION_FAMILY_COMPACT_TAGS.get(seed_c, frozenset()):
        return True
    if segment in _EXCEPTION_FAMILY_SEPARATOR_TAGS.get(seed_c, frozenset()):
        return True
    return False


def _exception_match_shape(
    token: str, seed_c: str, seed_k: str
) -> str | None:
    """Return ``a``/``b``/``c``/``d`` for how ``token`` hits exception seed."""
    if not token or not seed_c:
        return None
    token_compact = _compact_canonical(token)
    if (
        token == seed_c
        or token_compact == seed_k
        or token == seed_k
        or token_compact == seed_c
    ):
        return "a"
    if _FAMILY_BOUNDARY_PREFIX_ENABLED:
        boundary = seed_c + "_"
        if token.startswith(boundary) and len(token) > len(boundary):
            return "b"
    if _FAMILY_COMPACT_REMAINDER_ENABLED and seed_k:
        if token_compact.startswith(seed_k):
            rem = token_compact[len(seed_k) :]
            if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
                return "c"
    if _family_match_head_segment(token, seed_c, seed_k):
        return "d"
    return None


def _is_exact_exception_seed(token: str, seed_c: str, seed_k: str) -> bool:
    """True when token is exact folded/compact identity of exception seed."""
    if not token or not seed_c:
        return False
    token_compact = _compact_canonical(token)
    return (
        token == seed_c
        or token_compact == seed_k
        or token == seed_k
        or token_compact == seed_c
    )


def _exception_seed_match_for_residual(
    token: str,
) -> tuple[str, str, str] | None:
    """Return ``(seed_c, seed_k, residual)`` for residual classification.

    FIR-7 F10: includes unbounded compact-prefix matches so long debris
    (``yolosegme`` / ``yolosfree``) is classifiable. Residual is empty for
    exact seed identity. Longest exception compact seed wins.
    """
    if not token:
        return None
    token_compact = _compact_canonical(token)

    matched = _best_family_seed_match(
        token, PACKAGE_EXCEPTION_ALLOWLIST, for_deny=False
    )
    if matched is not None:
        seed_c, seed_k, _entry = matched
        if _is_exact_exception_seed(token, seed_c, seed_k):
            return seed_c, seed_k, ""
        residual = _strip_exception_seed_residual(token, seed_c, seed_k)
        if residual:
            return seed_c, seed_k, residual
        # Family match without a structural strip residual: fall through
        # to unbounded compact prefix (long debris on a matched seed).

    best: tuple[str, str, str] | None = None
    best_len = -1
    for seed_c, seed_k, _entry in _iter_family_seeds(
        PACKAGE_EXCEPTION_ALLOWLIST
    ):
        if not seed_k or not token_compact.startswith(seed_k):
            continue
        if len(token_compact) <= len(seed_k):
            continue
        rem = token_compact[len(seed_k) :]
        if not rem or not _DENY_COMPACT_PREFIX_GLUE_REMAINDER.fullmatch(rem):
            continue
        # Prefer longest exception seed (yolos over bare collisions).
        rank = len(seed_k)
        if rank > best_len:
            best_len = rank
            best = (seed_c, seed_k, rem)
    return best


def _is_legitimate_exception_compact_spelling(token: str) -> bool:
    """True when ``token`` is exact exception (a), compact (c) + real tag,
    or an allowlisted compact-glue spelling (``ppyoloeplus``).

    R18-06: ``_EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST`` (``ppyolo`` /
    ``eplus``) is part of the official compact identity; without it
    ``yoloppyoloeplus`` landed as dishonest ``yolop_unknown_residual``.
    """
    if not token:
        return False
    compact = _compact_canonical(token)
    if compact:
        for _sc, _sk, spelling in _iter_exception_compact_spellings():
            if compact == spelling or token == spelling:
                return True
    matched = _best_family_seed_match(
        token, PACKAGE_EXCEPTION_ALLOWLIST, for_deny=False
    )
    if matched is None:
        return False
    seed_c, seed_k, _entry = matched
    shape = _exception_match_shape(token, seed_c, seed_k)
    if shape == "a":
        return True
    if shape == "c":
        rem = _compact_canonical(token)[len(seed_k) :]
        return _is_legitimate_exception_compact_rem(rem, seed_c)
    rem = compact[len(seed_k) :] if compact and seed_k else ""
    if rem and rem in _EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST.get(
        seed_c, frozenset()
    ):
        return True
    return False


def _residual_structurally_defer(residual: str) -> bool:
    """True when residual should be residual-rescanned (own-alignment deny).

    Residual-alone deny seeds (``ultralytics``, ``yolov8``, ``xultralytics``)
    must **defer** so multi-strip / honest attribution and flag red-proofs
    for (d)/(e) stay load-bearing (``yolox_ultralytics`` /
    ``yolox_xultralytics``).

    Checks live deny hits **and** structural rule-(e) shape (segment ends
    with a deny seed of ≥ ``_COMPACT_SUFFIX_MIN_SEED_LEN`` compact chars)
    even when the (e) flag is off — deferral must not invent a yolo
    reconstitution that would shadow the (e) red-proof path.
    """
    if not residual:
        return False
    parts = [p for p in residual.split("_") if p]
    if not parts:
        return False
    for i in range(len(parts)):
        suffix = "_".join(parts[i:])
        if _deny_folded_ab_hit(suffix) is not None:
            return True
        if _best_family_hit(suffix, PACKAGE_DENYLIST, for_deny=True) is not None:
            return True
    # Structural (e)-shape defer (flag-independent).
    for part in parts:
        part_k = _compact_canonical(part)
        if not part_k:
            continue
        for _sc, deny_k, _entry in _iter_family_seeds(PACKAGE_DENYLIST):
            if not deny_k or len(deny_k) < _COMPACT_SUFFIX_MIN_SEED_LEN:
                continue
            if part_k == deny_k:
                return True
            if len(part_k) > len(deny_k) and part_k.endswith(deny_k):
                return True
    return False


def _unknown_exception_residual_entry(
    seed_c: str, residual: str
) -> PackageDenylistEntry:
    """Fail-closed deny for unknown exception residual (honest note, F10).

    Does **not** name a deny lineage the residual did not match — no
    fabricated Ultralytics AGPL attribution for unknown debris.
    """
    return PackageDenylistEntry(
        package_id=f"{seed_c}_unknown_residual",
        display_name=f"unknown residual after {seed_c}",
        spdx_id="FAIL-CLOSED",
        reason=RejectionReason.DENYLISTED_PACKAGE,
        notes=(
            f"exception-family seed {seed_c!r} with unknown residual "
            f"{residual!r}; fail-closed (no matching deny-lineage claim)"
        ),
    )


def _is_synthetic_unknown_residual_entry(
    entry: PackageDenylistEntry,
) -> bool:
    """True when ``entry`` is the fail-closed unknown-residual gadget.

    These are not a real AGPL package — they are the honest landing
    for unclassified exception debris. Door promotion must not report
    them as an AGPL-axis hit when the unfiltered floor already named
    an NC seed (R23-03 / AUDIT-08 / PROV-01).
    """
    return (
        entry.spdx_id == "FAIL-CLOSED"
        and entry.package_id.endswith("_unknown_residual")
    )


# Honest ultralytics compact remainders (1–3 alnum). ``seg`` / ``sg``
# are real YOLO-Seg spellings that share an initial letter with the
# yolos exception seed; fabricated rem (``xpt`` / ``spt`` / ``xz``)
# must not inherit the yolo AGPL note (F12-7 / R14-G2-3).
_HONEST_YOLO_COMPACT_REMS: frozenset[str] = frozenset(
    {
        "n",
        "s",
        "m",
        "l",
        "x",
        "t",
        "b",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
        "v11",
        "seg",
        "sg",
        "cls",
        "obb",
        "nas",
    }
)


def _is_fabricated_exception_yolo_hit(
    seed_k: str,
    acc_k: str,
    hit: PackageDenylistEntry | None,
) -> bool:
    """True when a yolo (c) hit is only exception-letter + non-artifact rem.

    ``yolox`` + ``pt`` → ``yoloxpt`` matches yolo via rem ``xpt``; that
    rem is not a real Ultralytics compact remainder. ``yolos`` + ``eg``
    → ``yoloseg`` matches rem ``seg``, which is honest.
    """
    if hit is None or hit.package_id != "yolo":
        return False
    if not seed_k.startswith("yolo") or len(seed_k) <= 4:
        return False
    extra = seed_k[4:]
    if not extra or not acc_k.startswith("yolo"):
        return False
    rem = acc_k[4:]
    if not rem.startswith(extra):
        return False
    return rem not in _HONEST_YOLO_COMPACT_REMS


def _contained_long_deny_seed_hit(
    token: str,
) -> PackageDenylistEntry | None:
    """Longest deny seed of ≥ 5 compact chars appearing inside ``token``.

    Best-effort strongest-hit (F12-7 / R14-G1-6): ``yoloultralyticsplus``
    contains ``ultralytics``. Short seeds (``yolo``, len 4) are skipped
    so every exception family does not collapse to fabricated yolo.
    """
    if not token:
        return None
    rk = _compact_canonical(token)
    if not rk:
        return None
    best: PackageDenylistEntry | None = None
    best_len = -1
    for _seed_c, seed_k, entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if not seed_k or len(seed_k) < _COMPACT_SUFFIX_MIN_SEED_LEN:
            continue
        if seed_k in rk and len(seed_k) > best_len:
            best_len = len(seed_k)
            best = entry
    return best


def _residual_progressive_reconst_deny(
    seed_c: str,
    seed_k: str,
    residual: str,
) -> PackageDenylistEntry | None:
    """Progressive re-glue residual segments onto seed; return deny entry.

    No per-segment length gate (FIR-7 F10). Bounded only by module-level
    ``_MAX_RECONST_SEGMENTS`` (red-proof pinned). Skips glued forms that
    are legitimate exception spellings (``yolox`` + ``s`` → ``yoloxs``).

    Two passes:

      1. all residual segments (tag+debris chains like ``s_eg``);
      2. non-tag segments only (after peeling legit tags/shields).

    Deny-reconstituting requires an elevated/glue deny hit on the glued
    compact form (``yolos``+``eg`` → ``yoloseg`` → yolo). FIR-7 B14-2 /
    F12-7: fabricated ``yolo`` hits whose rem is only the exception
    family's extra letter plus non-artifact debris (``yolox``+``pt`` →
    ``yoloxpt``) are suppressed — those land on unknown residual.
    Honest rem (``seg`` / ``sg``) still reconstitutes. Residual-alone
    package identities (``xultralytics``) do **not** reconstitute here;
    they defer via :func:`_residual_structurally_defer`.
    """
    if not residual or not seed_k:
        return None
    parts = [p for p in residual.split("_") if p]
    if not parts:
        return None

    def _glue_parts(segs: list[str]) -> PackageDenylistEntry | None:
        acc_k = seed_k
        for part in segs[:_MAX_RECONST_SEGMENTS]:
            part_k = _compact_canonical(part)
            if not part_k:
                continue
            acc_k = acc_k + part_k
            if _is_legitimate_exception_compact_spelling(acc_k):
                continue
            hit = _deny_folded_ab_hit(acc_k)
            if hit is not None:
                if _is_fabricated_exception_yolo_hit(seed_k, acc_k, hit):
                    continue
                return hit
        return None

    # Pass 1: all segments. Lets ``yolox``+``s``+``eg`` skip the legit
    # ``yoloxs`` spelling then reach deny on further glue via pass 2.
    hit = _glue_parts(parts)
    if hit is not None:
        return hit

    # Pass 2: non-tag segments only (tag+debris laundering).
    # Honest: only elevated/glue hits count — no underlying-yolo fabrication
    # for unmatched debris (B14-2).
    non_tags = [
        p for p in parts if not _is_legitimate_residual_segment(p, seed_c)
    ]
    if not non_tags:
        return None
    return _glue_parts(non_tags)


def _ppyolo_residual_is_deci_nas(residual: str) -> bool:
    """True when a ppyolo rem is Deci YOLO-NAS, not an English nas* word.

    R18-04: ``rk.startswith("nas")`` attributed ``naso`` / ``nashville``
    / ``nasal`` as Deci. Accept exact ``nas`` or ``nas`` + a known
    yolo_nas compact variant (``nasl`` / ``nasposel``). A leading
    ppyolo compact tag is peeled so ``enas`` (``ppyoloenas``) counts.

    R19-04: trailing ``s`` is not a special case — the boundary is
    exact compact identity. ``nass`` == compact of ``yolo_nas_s``
    (Deci S). ``nasls`` == ``nasl`` + junk ``s`` and is not the
    compact of any Deci seed (unknown residual).
    """
    if not residual:
        return False
    rk = _compact_canonical(residual)
    if not rk:
        return False
    tags = sorted(
        _EXCEPTION_FAMILY_COMPACT_TAGS.get("ppyolo", frozenset()),
        key=len,
        reverse=True,
    )
    peeled = rk
    for tag in tags:
        if tag and peeled.startswith(tag) and len(peeled) > len(tag):
            rest = peeled[len(tag) :]
            if rest.startswith("nas"):
                peeled = rest
                break
    if not peeled.startswith("nas"):
        return False
    if peeled == "nas":
        return True
    compact_id = "yolo" + peeled
    for seed_c, seed_k, entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if entry.reason is not RejectionReason.NC_MODEL_DERIVED:
            continue
        if not (
            seed_c.startswith("yolo_nas") or seed_c.startswith("yolonas")
        ):
            continue
        if compact_id == seed_k or compact_id == _compact_canonical(seed_c):
            return True
    return False


def _classify_exception_residual(
    seed_c: str,
    seed_k: str,
    residual: str,
    *,
    compact_glue: bool = False,
) -> tuple[str, PackageDenylistEntry | None]:
    """Classify residual after exception seed strip (FIR-7 F10 / F11).

    Returns ``(outcome, entry)`` where outcome is one of:

      * ``legitimate`` — residual is a real family tag form for the match
        shape (compact glue: compact tags only; separator: family tags or
        export shields);
      * ``defer`` — residual has a deny hit at its own alignment (re-scan);
      * ``deny_reconstituting`` — re-glue matches a deny claim (entry set);
      * ``unknown`` — fail-closed with honest unknown-residual entry.

    Length is never the discriminator. ``compact_glue=True`` when the
    residual came from compact seed+rem (no separator) **or** from an
    illegitimate head peel (F12-2 / F13-5: a peeled rem that is not in
    the family's compact tags / ppyolo-eplus allowlist forces
    compact-glue rules so a separator tail cannot launder it).
    """
    if not residual:
        return _RESIDUAL_LEGITIMATE, None

    parts = [p for p in residual.split("_") if p]
    if not parts:
        return _RESIDUAL_LEGITIMATE, None

    # (a) legitimate residual for the match shape.
    if compact_glue:
        # Compact glue: only per-family compact tags / ppyolo-eplus
        # allowlist. Forced also by an illegitimate head peel (F12-2 /
        # F13-5). Shield tags (pt/trt/…) and separator-only tags
        # (tiny/darknet/…) require separator-joined form
        # (FIR-7 A14-1 / B12-4).
        if len(parts) == 1 and _is_legitimate_compact_glue_residual(
            parts[0], seed_c
        ):
            return _RESIDUAL_LEGITIMATE, None
    else:
        if all(_is_legitimate_residual_segment(p, seed_c) for p in parts):
            return _RESIDUAL_LEGITIMATE, None

    # F15-10b / R18-04: ppyolo + nas residual is Deci YOLO-NAS (NC),
    # not a generic ppyolo unknown residual. Exact ``nas`` / known
    # yolo_nas variant tails only — ``naso`` / ``nashville`` / ``nasal``
    # are not Deci. ``ppyoloenas`` peels the compact ``e`` tag so rem
    # ``nas`` still carries the Deci note.
    if seed_c == "ppyolo" and _PPYOLO_NAS_RESIDUAL_NC_ENABLED:
        if _ppyolo_residual_is_deci_nas(residual):
            nas = PACKAGE_DENYLIST.get("yolo_nas") or PACKAGE_DENYLIST.get(
                "yolonas"
            )
            if nas is not None:
                return _RESIDUAL_DENY_RECONST, nas

    # Defer residual-alone deny seeds to residual re-scan (honest attribution).
    if _residual_structurally_defer(residual):
        return _RESIDUAL_DEFER, None

    # (b) progressive re-glue reconstitutes a deny claim.
    reconst = _residual_progressive_reconst_deny(seed_c, seed_k, residual)
    if reconst is not None:
        return _RESIDUAL_DENY_RECONST, reconst

    # (c) unknown fail-closed. Post-F12 landing paths (R14-G4-2):
    #   * compact glue of shield/separator tags (``yoloxpt`` / ``yoloxtrt``)
    #     — A14-1, including F12-7 reroute of short rem that previously
    #     fabricated a yolo AGPL note;
    #   * compact peel + separator tail (``yoloxpt_trt``) — F12-2;
    #   * non-compact non-tag debris that does not reconstitute an honest
    #     deny rem (``yolox_z`` / ``yolos_ti`` / ``zqx``) — B14-2 / F12-7;
    #   * compact glue of separator-only family tags (``yolostiny``).
    # Honest reconst (``yolos_eg`` / ``yolos_tiny_eg`` → ``yolo``)
    # returns above at (b). ``yolox_tiny_eg`` is a true unknown
    # witness (tiny is a yolox tag; eg does not reconstitute).
    non_tags = [
        p for p in parts if not _is_legitimate_residual_segment(p, seed_c)
    ]
    if non_tags or compact_glue:
        return _RESIDUAL_UNKNOWN, _unknown_exception_residual_entry(
            seed_c, residual
        )

    # Fail-closed default (A14-2): every segment-legit non-compact path
    # already returned above; never silently admit on fall-through.
    return _RESIDUAL_UNKNOWN, _unknown_exception_residual_entry(
        seed_c, residual
    )


def _token_has_exception_seed_claim(token: str) -> bool:
    """True when an exception seed claims ``token`` (any residual length).

    Used as the elevated deny-(c) carve-out gate (FIR-7 F10): exception-
    prefix debris is owned by residual classification, not elevated (c).
    Folded deny (a)/(b) claims still win via ``_deny_has_folded_ab_claim``.
    """
    return _exception_seed_match_for_residual(token) is not None


def _token_has_legitimate_exception_boundary(token: str) -> bool:
    """True when token is a clean exception-family spelling (B11-01 / F10).

    Load-bearing helper for residual-classify legitimacy and tests.
    Residual classification (a) or empty residual → legitimate. Deny-
    reconstituting / unknown residual → not legitimate. Defer (residual-
    alone deny seed) counts as boundary so the walker can strip and
    residual-rescan with honest attribution. Compact glue vs separator
    residual legitimacy is distinguished via ``compact_glue`` (A14-1).
    """
    matched = _exception_seed_match_for_residual(token)
    if matched is None:
        return False
    seed_c, seed_k, residual = matched
    if not residual:
        return True
    outcome, _entry = _classify_exception_residual(
        seed_c,
        seed_k,
        residual,
        compact_glue=_exception_residual_uses_compact_glue_rules(
            token, seed_c, seed_k
        ),
    )
    return outcome in (_RESIDUAL_LEGITIMATE, _RESIDUAL_DEFER)


def _deny_has_folded_ab_claim(token: str) -> bool:
    """True when any deny seed claims ``token`` via folded (a) or (b) only.

    Folded (a)/(b) claims are never suppressed by the exception-boundary
    carve-out — ``yolo_x`` / ``yolo_s`` / ``yolo_seg`` must DENY even though
    their compact forms spell exception seeds ``yolox`` / ``yolos``.
    Load-bearing at the elevated-deny call site (FIR-7-B12-1): without it
    the carve-out would suppress ``yolo_x`` via compact exception identity.

    The (b) ``seed_`` arm is live at the walker call site (``yolo_x``).
    Mid-adjacency passes a compact prefix slice (no ``_``), so only
    folded (a) can fire there — not a bypass, just compact-only
    exactness on that path (R19-05).
    """
    if not token:
        return False
    token_compact = _compact_canonical(token)
    for seed_c, seed_k, _entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if (
            token == seed_c
            or token_compact == seed_k
            or token == seed_k
            or token_compact == seed_c
        ):
            # Exact compact identity of a deny seed — but if the token's
            # *folded* form differs and equals an exception, still (a) on
            # compact. For deny seeds this is fine. Exception seeds are
            # disjoint so this is a real deny (a).
            return True
        if _FAMILY_BOUNDARY_PREFIX_ENABLED:
            boundary = seed_c + "_"
            if token.startswith(boundary) and len(token) > len(boundary):
                return True
    return False


def _exception_spelling_plus_residual(
    rem: str,
) -> tuple[str, str, str] | None:
    """Return ``(seed_c, seed_k, residual)`` when rem is spelling + leftover.

    Longest exception compact spelling wins (``yoloxs`` over ``yolox``).
    """
    if not rem:
        return None
    rem_k = _compact_canonical(rem)
    if not rem_k:
        return None
    best: tuple[str, str, str] | None = None
    best_len = -1
    for seed_c, seed_k, spelling in _iter_exception_compact_spellings():
        if rem_k.startswith(spelling) and len(rem_k) > len(spelling):
            residual = rem_k[len(spelling) :]
            if residual and residual.isalnum() and len(spelling) > best_len:
                best_len = len(spelling)
                best = (seed_c, seed_k, residual)
    return best


def _classify_exception_plus_residual(
    rem: str,
) -> PackageDenylistEntry | None:
    """Fail-closed entry when rem is exception-spelling + non-legit residual."""
    if not _SUFFIX_TOLERANT_GLUE_ENABLED:
        return None
    matched = _exception_spelling_plus_residual(rem)
    if matched is None:
        return None
    seed_c, seed_k, residual = matched
    outcome, entry = _classify_exception_residual(
        seed_c, seed_k, residual, compact_glue=True
    )
    if outcome == _RESIDUAL_LEGITIMATE:
        return None
    return entry


def _deny_prefix_plus_residual_hit(rem: str) -> PackageDenylistEntry | None:
    """Longest deny/NC seed that is a proper prefix of compact rem + leftover."""
    if not rem or not _SUFFIX_TOLERANT_GLUE_ENABLED:
        return None
    rem_k = _compact_canonical(rem)
    if not rem_k:
        return None
    best: PackageDenylistEntry | None = None
    best_len = -1
    for _seed_c, seed_k, entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if not seed_k or not rem_k.startswith(seed_k):
            continue
        leftover = rem_k[len(seed_k) :]
        if leftover and leftover.isalnum() and len(seed_k) > best_len:
            best_len = len(seed_k)
            best = entry
    return best


def _rem_is_known_family_or_seed(rem: str) -> bool:
    """True when compact rem is an exception spelling or any known seed.

    F13-3 / R15-L-2 remainder predicate: ``yolox`` / ``yoloxs`` (exception
    family) and exact deny/NC identities (``yolo`` / ``yolov8``).

    F14-6: also true when rem is exception-spelling (or deny-seed) + a
    residual that residual-classify does not treat as legitimate
    (``yoloxextra`` / ``yoloxcoco``). Exact membership is unchanged.
    """
    if not rem:
        return False
    rem_k = _compact_canonical(rem)
    if _is_legitimate_exception_compact_spelling(rem):
        return True
    if rem_k != rem and _is_legitimate_exception_compact_spelling(rem_k):
        return True
    for mapping in (PACKAGE_EXCEPTION_ALLOWLIST, PACKAGE_DENYLIST):
        for seed_c, seed_k, _entry in _iter_family_seeds(mapping):
            if (
                rem == seed_c
                or rem == seed_k
                or rem_k == seed_k
                or rem_k == seed_c
            ):
                return True
    if _classify_exception_plus_residual(rem) is not None:
        return True
    if _deny_prefix_plus_residual_hit(rem) is not None:
        return True
    return False


# F14-5: 4-char deny heads (``yolo``) accept an exact exception-family rem.
# Restore ``5`` to revert to the F13-3 min-len-5 refusal (TEST-15).
_DENY_HEAD_KNOWN_REM_MIN_SEED_LEN: int = 4
# F14-6: head glue / mid-adjacency accept exception-or-deny spelling +
# residual (classify residual fail-closed). False restores exact-membership
# remainder (TEST-15).
_SUFFIX_TOLERANT_GLUE_ENABLED: bool = True
# F15-1: when the separator-aligned walk misses, run rule (e) on the
# compact-joined component so junk+multi-segment NC seeds (``aabuffalo_l``)
# hit compact denylist keys (``buffalol``). TEST-15: False restores admit.
_COMPACT_JOINED_RULE_E_ENABLED: bool = True
# F15-1: compact mid-occurrence NC — seed at offset > 0 with leftover
# after the seed (junk on both sides: ``aainsightfaceaa``). TEST-15:
# False restores both-sides-junk admit.
_COMPACT_MID_NC_OCCURRENCE_ENABLED: bool = True
# F15-2: deny-head of compact length ≥ 5 + a known variant rem that
# does not fit the 1–3 (c) bound (``tiny`` / ``small`` / …) fail-closes
# as the catalog seed (``yolov4tiny``). Not a generic long-rem deny —
# ``buffalo_lakes`` (BR-28 name-continuation) and F14-6 suffix-tolerant
# witnesses must stay on their own axes. TEST-15: False restores the
# 1–3-only (c) bound.
_DENY_HEAD_LONG_REM_ENABLED: bool = True
_DENY_HEAD_LONG_VARIANT_REMS: frozenset[str] = frozenset(
    {"tiny", "small", "large", "nano", "base"}
)
# F15-5 / R18-01: unknown non-tag rem after a mid-token exception
# spelling fail-closes as ``<family>_unknown_residual``
# (``xyoloxsextra``). A deny/NC stem in the prefix that is not an
# exact folded identity (``fastsamx`` / ``arcfacex``) owns the full
# token even when rem is empty (``fastsamxyolox``). TEST-15: False
# restores the deny/NC-rem-only mid scanner (gadgets admit again).
_MID_EXCEPTION_UNKNOWN_REM_ENABLED: bool = True
# R19-03: prefer a deny/NC stem in the mid-exception prefix when rem
# is itself a legitimate exception spelling (``fastsamxyoloxsyolox``
# → fastsam, not fabricated yolo). TEST-15 sole-path.
_MID_EXCEPTION_STEM_OVER_EXC_REM_ENABLED: bool = True
# R20-01: empty-rem underscore ownership also runs when rem lives in
# its own ``_`` / folded-tag segment (``buffalo_lxyolox_v8`` /
# ``buffalo_lxyolox:v8``). TEST-15: False restores the rem-path
# has_sep skip so rem-bearing tails admit again.
_MID_EXCEPTION_SEPARATE_REM_OWNER_ENABLED: bool = True
# R21-01: when rem is several trailing ``_`` segments (``v8-3`` /
# ``onnx_tiny``) the single-segment peel misses (canon ``v83`` !=
# ``3``). Retry ownership after peeling those segments. TEST-15:
# False restores last-segment-only peel so multi-segment rem tails
# admit again.
_MID_EXCEPTION_MULTI_SEGMENT_REM_OWNER_ENABLED: bool = True
# Rem longer than this skips peel (the 1200-yolop pin's cost is the
# pre-existing scanner) and fail-closes via the unpeeled owner.
# Not a fail-open and not a test-only toggle.
_MAX_COMPOSED_REM_COMPACT_LEN: int = 48
# F15-10b: ppyolo + nas residual → Deci YOLO-NAS NC. TEST-15: False
# restores generic ppyolo unknown residual for ``pp_yolo_nas``.
_PPYOLO_NAS_RESIDUAL_NC_ENABLED: bool = True


def _deny_head_known_rem_glue(token_compact: str, seed_k: str) -> bool:
    """F13-3 / F14-5: deny/NC head + exception/known-seed rem.

    Accepts seeds of compact length ≥ ``_COMPACT_SUFFIX_MIN_SEED_LEN``
    when the remainder is itself an exception-family spelling or any
    known seed. Distinct from B13-5 long-seed glue (min 11, any alnum
    rem).

    F14-5: a 4-char head (``yolo``) also hits when the *entire* rem is
    exactly an exception-family spelling (``yoloyolox`` / ``yoloyoloxs``).
    F15-2: the same 4-char head now routes unknown/non-exception rem
    through :func:`_rem_is_known_family_or_seed` (suffix-tolerant
    classification) so ``yoloyoloxextra`` / ``yoloyolo`` deny.
    ``yolodummy`` rem is not an exception spelling or known seed and
    stays admitted. Floor is ``_DENY_HEAD_KNOWN_REM_MIN_SEED_LEN``
    (TEST-15: restore 5).
    """
    if not token_compact or not seed_k:
        return False
    if not token_compact.startswith(seed_k):
        return False
    rem = token_compact[len(seed_k) :]
    if not rem:
        return False
    if len(seed_k) < _DENY_HEAD_KNOWN_REM_MIN_SEED_LEN:
        return False
    if len(seed_k) == 4:
        # F15-2a: suffix-tolerant exception rem (yoloyoloxextra) or an
        # exact known seed (yoloyolo / yolobuffalol). Do NOT take
        # deny-prefix leftovers (ultralyticsplus) — that would let the
        # 4-char yolo head outrank a longer honest AGPL seed.
        # R18-13: ``yolobuffalo_l`` lands ``yolo`` because this 4-char
        # head outranks the compact NC rem; the test pin documents that
        # ranking rather than silently retargeting the F15-1 NC witness.
        if _is_legitimate_exception_compact_spelling(rem):
            return True
        rem_k = _compact_canonical(rem)
        for mapping in (PACKAGE_EXCEPTION_ALLOWLIST, PACKAGE_DENYLIST):
            for seed_c, sk, _entry in _iter_family_seeds(mapping):
                if rem == seed_c or rem == sk or rem_k == sk or rem_k == seed_c:
                    return True
        return _classify_exception_plus_residual(rem) is not None
    if len(seed_k) < _COMPACT_SUFFIX_MIN_SEED_LEN:
        return False
    return _rem_is_known_family_or_seed(rem)


def _deny_head_is_exception_spelling_glue(token: str) -> bool:
    """True when compact token is deny-head + exact exception spelling.

    F15-10a / R18-06: ``yoloppyoloe`` is ``yolo`` + ``ppyoloe`` and
    ``yoloppyoloeplus`` is ``yolo`` + ``ppyoloeplus``, not
    ``yolop`` + unknown residual.
    """
    if not token:
        return False
    compact = _compact_canonical(token)
    if not compact:
        return False
    for _seed_c, seed_k, _entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if not seed_k or not compact.startswith(seed_k):
            continue
        rem = compact[len(seed_k) :]
        if rem and _is_legitimate_exception_compact_spelling(rem):
            return True
    return False


def _mid_exception_prefix_deny_owner(
    prefix: str,
) -> PackageDenylistEntry | None:
    """Deny/NC entry that owns a non-exact mid-exception prefix (R18-01).

    Exact folded (a)/(b) identities (``arcface`` / ``yolo``) are *not*
    returned here — those stay on F14-6 / F15-2 so their red-proofs
    remain sole-path. Deny-(c) debris (``fastsamx``) and a contained
    long seed inside the prefix (``fastsam`` in ``fastsamx``) prove the
    full token is owned by that stem.
    """
    if not prefix:
        return None
    # R18-01 gadgets are ``{seed}{1-3 alnum}{exception}{debris}``.
    # A punctuation-bearing prefix (``insightface~``) is the F14-1
    # fold's sole-path witness — do not treat ``~`` as junk infix.
    prefix_k = _compact_canonical(prefix)
    if not prefix_k or not prefix_k.isalnum():
        return None
    contained = _contained_long_deny_seed_hit(prefix)
    if contained is not None:
        return contained
    return _deny_folded_ab_hit(prefix)


def _underscore_preserving_glued_seed_owner(
    token: str,
) -> PackageDenylistEntry | None:
    """Longest underscore-preserving deny/NC seed glued onto ``token``.

    R19-01: ``buffalo_lxyolox`` starts with ``buffalo_l`` and continues
    with alnum (not a ``seed_`` (b) boundary). Compact contained-long
    on the joined form would also fire, but that same compact prefix
    owner falsely attributes exception compounds (``yolop_yolox`` →
    yolo via (c) on compact ``yolop``). Matching the folded
    underscore seed against the underscore-preserving token makes
    ownership visible without collapsing exception-family compounds.

    Longest ``seed_c`` wins so ``buffalo_scxyolox`` names ``buffalo_sc``
    not ``buffalo_s``. Junk after the seed is unbounded.
    """
    if not token or "_" not in token:
        return None
    best: PackageDenylistEntry | None = None
    best_len = -1
    for seed_c, _seed_k, entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if "_" not in seed_c:
            continue
        if not token.startswith(seed_c):
            continue
        rest = token[len(seed_c) :]
        if not rest or not rest[0].isalnum():
            continue
        if len(seed_c) > best_len:
            best_len = len(seed_c)
            best = entry
    return best


def _mid_exception_rem_is_trailing_segment(
    token: str, rem: str
) -> bool:
    """True when compact rem is exactly the last ``_``-separated segment.

    R20-01: ``buffalo_lxyolox_v8`` / ``buffalo_lxyolox:v8`` (``:v8``
    folds to ``_v8``) carry rem in their own trailing segment. Glued
    rem (``buffalo_lxyoloxextra``) does not — last segment is
    ``lxyoloxextra``, not ``extra`` (A.3). Mid-chain rem
    (``yolop_yolop_…``) also misses so the deep-chain pin stays O(n).
    """
    if not rem or not token:
        return False
    sep = token.rfind("_")
    if sep < 0:
        return False
    return token[sep + 1 :] == rem


def _exception_compact_spelling_set() -> frozenset[str]:
    """Compact exception spellings (cached). Used to refuse fabricated yolo."""
    cached = getattr(_exception_compact_spelling_set, "_cached", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    out = frozenset(
        spelling for _sc, _sk, spelling in _iter_exception_compact_spellings()
    )
    _exception_compact_spelling_set._cached = out  # type: ignore[attr-defined]
    return out


def _underscore_deny_seed_heads() -> tuple[str, ...]:
    """First-segment heads of underscore deny/NC seeds (cached).

    Class-level (derived from ``PACKAGE_DENYLIST``), not a gadget
    denylist. Cheap prefilter so the 1200-yolop pin does not pay
    ``_underscore_preserving_glued_seed_owner`` on every suffix.
    """
    cached = getattr(_underscore_deny_seed_heads, "_cached", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    heads: list[str] = []
    seen: set[str] = set()
    for seed_c, _sk, _entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if "_" not in seed_c:
            continue
        head = seed_c.split("_", 1)[0] + "_"
        if head not in seen:
            seen.add(head)
            heads.append(head)
    out = tuple(heads)
    _underscore_deny_seed_heads._cached = out  # type: ignore[attr-defined]
    return out


def _token_starts_with_underscore_deny_head(token: str) -> bool:
    """True when ``token`` begins with an underscore deny/NC seed head."""
    if not token:
        return False
    for head in _underscore_deny_seed_heads():
        if token.startswith(head):
            return True
    return False


def _long_composed_rem_unpeeled_owner(
    token: str, prefix: str
) -> PackageDenylistEntry | None:
    """Owner for rem past the peel budget — never peel, never admit.

    The peel of a 1200-``yolop`` chain is O(n²) across suffixes, so
    rem longer than :data:`_MAX_COMPOSED_REM_COMPACT_LEN` skips peel
    and names the owner from the unpeeled token / prefix.

    R22-02: a ``len(prefix) <= 16`` gate on this path admitted every
    compact-head seed once junk between the seed and the exception
    spelling pushed the prefix past 16 (``fastsam`` + 9 junk +
    ``xyolox_v8_`` + 47 ``a``). Prefix length is not a gate. The
    cheap skips that remain cannot be walked around by padding:

      * underscore-head → glued-owner (deep-chain ``yolox_`` does
        not start with a deny/NC underscore head, so it never pays
        this call on every suffix);
      * exception-family head or exact-spelling prefix → skip
        prefix-owner (``yolox`` / ``yolop`` deep-chain; also stops
        fabricated ``yolo`` via (c) on an exception prefix).

    Compact-head stems (``fastsam`` / ``yolor`` / ``arcface``) and
    mid-token long seeds (``…ultralyticsx…``) have neither shape, so
    :func:`_mid_exception_prefix_deny_owner` always sees them.
    """
    if not token:
        return None
    if _token_starts_with_underscore_deny_head(token):
        owned = _underscore_preserving_glued_seed_owner(token)
        if owned is not None:
            return owned
    if not prefix:
        return None
    spellings = _exception_compact_spelling_set()
    if prefix in spellings:
        return None
    head_seg = token.split("_", 1)[0]
    if head_seg in spellings:
        return None
    return _mid_exception_prefix_deny_owner(prefix)


def _peel_composed_trailing_rem_segments(
    token: str, rem: str
) -> str | None:
    """Peel trailing ``_`` segments that together compose compact rem.

    R21-01: ``buffalo_lxyolox_v8_3`` rem ``v83`` is two segments
    (``v8`` + ``3``), so last-segment-equals-rem fails (``v83`` !=
    ``3``; ``onnxtiny`` != ``tiny``). Peel while the last segment's
    compact form is a suffix of the remaining rem; return the prefix
    once rem is fully consumed by **two or more** segments. A single
    trailing rem segment stays on
    :func:`_mid_exception_rem_is_trailing_segment` (R20-01 sole-path).
    Glued rem (``buffalo_lxyoloxextra``) cannot start a peel — the last
    segment is longer than rem — so A.3 unknown-residual holds.

    R22: the peel is monotone (each step strictly shortens ``current``)
    and has no production cap. F19 returned None at three cliffs
    (8 segments, 48-char rem, ``spelling in rem``) and the caller
    treated that as "no owner" and admitted. Those fail-opens are
    gone — not parked behind a test-only toggle. Rem longer than
    :data:`_MAX_COMPOSED_REM_COMPACT_LEN` is skipped by the caller
    and fail-closes via the unpeeled owner.

    R22-04: leftover rem glued into the last segment after one or
    more successful peels (``buffalo_lxyoloxextra_v8`` / compact-head
    ``fastsamxyoloxextra_v8``) returns the prefix so the caller can
    still name the owner — never admit.
    """
    if not rem or not token or "_" not in token:
        return None
    remaining = rem
    current = token
    peels = 0
    while remaining and "_" in current:
        sep = current.rfind("_")
        last = current[sep + 1 :]
        last_k = _compact_canonical(last) if last else ""
        if not last_k or not remaining.endswith(last_k):
            # R22-04: leftover rem is glued into the last segment.
            return current if peels >= 1 else None
        remaining = remaining[: -len(last_k)]
        current = current[:sep].rstrip("_")
        peels += 1
        if not current:
            return None
        if not remaining:
            return current if peels >= 2 else None
    # R22-04: trailing ``_`` exhausted (compact-head seed) with rem
    # still leftover — ``fastsamxyoloxextra_v8`` after peeling ``v8``.
    if remaining and peels >= 1:
        return current
    return None


def _token_tail_after_compact_len(token: str, compact_len: int) -> str:
    """Suffix of ``token`` after the first ``compact_len`` non-``_`` chars.

    Maps a compact-form offset back onto the underscore-preserving token
    so separator rem (``s_free`` / ``s_trt``) is classified with
    separator semantics, not the compact-joined remainder.
    """
    if compact_len <= 0:
        return token.lstrip("_")
    seen = 0
    for i, ch in enumerate(token):
        if ch == "_":
            continue
        seen += 1
        if seen == compact_len:
            return token[i + 1 :].lstrip("_")
    return ""


def _mid_exception_r22_sep_rem_fence(
    token: str, compact_end: int, spelling: str, sep_rem: str
) -> bool:
    """True when the R22 fence must skip junk-prefix unknown-rem fail-closed.

    ``xyoloxs_v8`` / ``xyoloxextra_v8`` either glue the first rem char
    onto the seed or are a single honest-yolo rem after a compact-tag
    spelling (``yoloxs`` + ``v8``). Separator-aligned multi-segment rem
    (``xyolox_z_v8``) is never fenced — last-segment honesty is not a
    skip (FIR-7-PANEL7D-rv3-01 / SECD-05 / CARD-26).
    """
    if not token or compact_end <= 0:
        return False
    seen = 0
    for i, ch in enumerate(token):
        if ch == "_":
            continue
        seen += 1
        if seen == compact_end:
            nxt = token[i + 1 : i + 2]
            if nxt and nxt.isalnum():
                return True
            break
    if (
        sep_rem
        and "_" not in sep_rem
        and sep_rem in _HONEST_YOLO_COMPACT_REMS
        and _is_legitimate_exception_compact_spelling(spelling)
    ):
        return True
    return False


def _compact_mid_exception_deny_adjacency(
    token: str,
) -> PackageDenylistEntry | None:
    """F13-3 / R15-L-3: exception seed at compact offset > 0 + deny rem.

    Closes junk-prefix defeat of F12-1 (``xyoloxyolo`` / ``myyoloxyolo``
    / ``abcyoloxyolo``). Offset 0 is owned by F12-1 steal.
    ``yolodummy`` has no exception seed and stays admitted.
    Single load-bearing helper (TEST-15).

    R18-01: the F15-5 skip is only for an *exact* folded deny/NC
    prefix. A prefix-only deny-(c) hit (``fastsamx``) does not own
    the full token and must not launder ``fastsamxyoloxextra`` /
    ``fastsamxyolox``. Empty rem after a deny-stem + junk prefix is
    the same ownership (``fastsamxyolox`` / ``fastsamxyoloxs``).

    R19-01: the empty-rem ownership arm also runs on underscore-
    preserving tokens, but via
    :func:`_underscore_preserving_glued_seed_owner` — not compact
    contained-long / (c) on the joined prefix. The walker used to
    bail on ``_`` so ``buffalo_lxyolox`` was scanned only as
    last-segment ``lxyolox``, whose prefix ``lx`` looks like
    anonymous junk (the pinned ``ayoloxs`` shape). Matching the
    folded seed (``buffalo_l``) against the underscore-preserving
    token makes ownership visible; compact (c) on ``yolop`` would
    false-deny ``yolop_yolox``. Junk length is unbounded
    (``buffalo_labcdyolox``). Glued non-empty rem still skips
    underscore tokens so ``buffalo_lxyoloxextra`` stays F15-5
    unknown-residual (A.3 attribution fence). R20-01: rem that
    lives in its own ``_`` / folded-tag segment
    (``buffalo_lxyolox_v8`` / ``:v8``) is peeled first so the
    same empty-rem owner sees ``buffalo_lxyolox``. R21-01:
    multi-segment rem tails (``v8-3`` / ``onnx_tiny``) fail
    last-segment-equals-rem and retry on progressively peeled
    trailing rem segments. R22: peel is monotone with no
    segment cap and no exception-spelling bail. Rem longer
    than the historical 48-char cliff skips the peel (the
    1200-``yolop`` pin's cost is the pre-existing scanner)
    and fail-closes via the unpeeled owner — never admit.
    R22-02: that owner is not gated on prefix length.
    Separator-aligned deny forms (``my_yoloxyolo`` /
    ``buffalo_l_xyolox``) still hit earlier via (b) / suffix
    walk. Prefix ownership on the compact (no-``_``) path is
    compact-(a) / contained-long / elevated (c) only — the
    folded (b) ``seed_`` arm of ``_deny_has_folded_ab_claim``
    cannot fire on a compact slice (R19-05).
    """
    if not token:
        return None
    has_sep = "_" in token
    compact = _compact_canonical(token)
    if not compact:
        return None
    # F14-4: share the occurrence predicate (seed + compact-tag spellings,
    # offset > 0) with ``_compact_has_mid_exception_family``.
    for _seed_c, _seed_k, spelling in _iter_exception_compact_spellings():
        start = 0
        while True:
            idx = compact.find(spelling, start)
            if idx < 0:
                break
            if idx == 0:
                start = idx + 1
                continue
            rem = compact[idx + len(spelling) :]
            prefix = compact[:idx]
            if rem:
                # R20-01: rem in its own trailing ``_`` / folded-tag
                # segment is not glued debris. Peel it and apply the
                # empty-rem owner so ``buffalo_lxyolox_v8`` names
                # ``buffalo_l``. Compact tokens that only gained ``_``
                # from the rem tail (``fastsamxyolox:v8``) use the
                # prefix owner. A legitimate family/export rem no
                # longer skips a deny-(c) prefix (R23-01
                # ``fastsamxyolox_tiny``). Exact folded deny/NC
                # prefixes (``yolov8yolox_s``) stay on F13
                # head-known-rem glue.
                peeled = None
                if has_sep and _MID_EXCEPTION_SEPARATE_REM_OWNER_ENABLED:
                    if _mid_exception_rem_is_trailing_segment(token, rem):
                        peeled = token[: token.rfind("_")].rstrip("_")
                    elif _MID_EXCEPTION_MULTI_SEGMENT_REM_OWNER_ENABLED:
                        # R22 / R22-02: rem longer than the historical
                        # 48-char cliff is mid-chain residue (1200-yolop)
                        # or a long export tail. Unbounded peel of the
                        # deep-chain is O(n²) across suffixes. Skip peel
                        # and fail-close via the unpeeled owner — never
                        # admit. Prefix length is not a gate (R22-02).
                        if len(rem) > _MAX_COMPOSED_REM_COMPACT_LEN:
                            owned = _long_composed_rem_unpeeled_owner(
                                token, prefix
                            )
                            if owned is not None:
                                return owned
                            start = idx + 1
                            continue
                        # R21-01: last-segment peel misses when rem is
                        # several trailing segments (``v83`` != ``3``).
                        peeled = _peel_composed_trailing_rem_segments(
                            token, rem
                        )
                if peeled:
                    owned = None
                    if "_" in peeled:
                        owned = _underscore_preserving_glued_seed_owner(
                            peeled
                        )
                    # R23-01: a single-segment legitimate family/export
                    # tag used to skip the prefix owner
                    # (``fastsamxyolox_tiny`` / ``fastsamxyolos_tiny``
                    # admitted). Consult it whenever the prefix is not
                    # an exact folded deny/NC identity — those stay on
                    # F13 head-known-rem glue (``yolov8yolox_s``).
                    # Exception-family prefixes (``yolox``) must not
                    # run the prefix owner: (c) fabricates ``yolo`` and
                    # steals the multi-strip red-proof
                    # (``yolox_yolop_ultralytics``).
                    if (
                        owned is None
                        and prefix
                        and prefix not in _exception_compact_spelling_set()
                        and (
                            not _is_legitimate_residual_segment(
                                rem, _seed_c
                            )
                            or not _deny_has_folded_ab_claim(prefix)
                        )
                    ):
                        owned = _mid_exception_prefix_deny_owner(prefix)
                    if owned is not None:
                        return owned
                # R19-01: rem-path on underscore tokens would compact-
                # join the dropped head into the prefix and retarget
                # ``buffalo_lxyoloxextra`` from yolox_unknown_residual
                # to buffalo_l (A.3). Leave *purely glued* non-empty
                # rem to the last-segment suffix, which still sees
                # prefix ``lx``. R22-04: rem that has a peelable
                # trailing segment still consults the unpeeled owner
                # before this skip (partial-peel leftover, or a peel
                # miss that must not admit).
                if has_sep:
                    if _MID_EXCEPTION_MULTI_SEGMENT_REM_OWNER_ENABLED:
                        sep_u = token.rfind("_")
                        last_u = token[sep_u + 1 :] if sep_u >= 0 else ""
                        last_uk = (
                            _compact_canonical(last_u) if last_u else ""
                        )
                        if (
                            last_uk
                            and rem.endswith(last_uk)
                            and rem != last_uk
                        ):
                            owned = (
                                _underscore_preserving_glued_seed_owner(
                                    token
                                )
                            )
                            # Prefix-owner on a legitimate exception
                            # head (``yolox``) fabricates ``yolo`` via
                            # (c). Only consult it for deny/NC stems
                            # (``fastsamx``). Cap prefix length so
                            # mid-chain buildup stays off this path.
                            if (
                                owned is None
                                and prefix
                                and len(prefix) <= 16
                                and prefix
                                not in _exception_compact_spelling_set()
                            ):
                                owned = _mid_exception_prefix_deny_owner(
                                    prefix
                                )
                            if owned is not None:
                                return owned
                    # FIR-7-PANEL7D-rv3-01 / rv3-02: no-owner is not
                    # permit for junk-prefix + unknown rem. Fail-closed
                    # depends only on ``_MID_EXCEPTION_UNKNOWN_REM_ENABLED``
                    # — peel-owner TEST-15 flags must not re-open
                    # ``xyolox_z``. Classify the FULL separator rem
                    # (never last-segment peelable: ``xyolox_z_v8``).
                    # Skip fail-closed only on legitimate / defer
                    # outcomes, a whole-rem legitimate residual, or
                    # the R22 compact-glue / compact-tag-tail fence
                    # (``xyoloxs_v8`` / ``xyoloxextra_v8``). Reconst
                    # returns the named deny. Prefix owners are not
                    # stolen (buffalo / fastsam red-proofs).
                    if _MID_EXCEPTION_UNKNOWN_REM_ENABLED:  # FIR-7-PANEL7D-rv3-02 sole flag
                        prefix_owned = (
                            _deny_has_folded_ab_claim(prefix)
                            or _mid_exception_prefix_deny_owner(prefix)
                            is not None
                            or _underscore_preserving_glued_seed_owner(token)
                            is not None
                        )
                        if not prefix_owned:
                            sep_rem = (
                                _token_tail_after_compact_len(
                                    token, idx + len(spelling)
                                )
                                or rem
                            )
                            # FIR-7-PANEL7D-rv3-01: classify FULL sep_rem
                            # (not last-segment peelable).
                            if not _mid_exception_r22_sep_rem_fence(
                                token,
                                idx + len(spelling),
                                spelling,
                                sep_rem,
                            ) and not _is_legitimate_residual_segment(
                                sep_rem, _seed_c
                            ):
                                outcome, entry = (
                                    _classify_exception_residual(
                                        _seed_c,
                                        _seed_k,
                                        sep_rem,
                                        compact_glue=False,
                                    )
                                )
                                if outcome == _RESIDUAL_UNKNOWN:
                                    return (
                                        entry
                                        or _unknown_exception_residual_entry(
                                            _seed_c, sep_rem
                                        )
                                    )
                                if (
                                    outcome == _RESIDUAL_DENY_RECONST
                                    and entry is not None
                                ):
                                    return entry
                    start = idx + 1
                    continue
                deny = _deny_folded_ab_hit(rem)
                if deny is None:
                    deny = _contained_long_deny_seed_hit(rem)
                if deny is None:
                    deny = _best_family_hit(
                        rem, PACKAGE_DENYLIST, for_deny=True
                    )
                # F14-6: rem is exception/deny spelling + residual.
                if deny is None:
                    deny = _classify_exception_plus_residual(rem)
                if deny is None:
                    deny = _deny_prefix_plus_residual_hit(rem)
                # R19-03: a rem that is itself a legitimate exception
                # spelling (``yolox`` after mid-token ``yoloxs``) hits
                # fabricated yolo via (c). Prefer a deny/NC stem in
                # the prefix so ``fastsamxyoloxsyolox`` names
                # ``fastsam``, not ``yolo``. Junk prefixes (``x``)
                # have no owner and keep the rem hit — fail-closed
                # and family-true.
                if (
                    deny is not None
                    and _MID_EXCEPTION_STEM_OVER_EXC_REM_ENABLED
                    and _is_legitimate_exception_compact_spelling(rem)
                ):
                    owned = _mid_exception_prefix_deny_owner(prefix)
                    if owned is not None:
                        deny = owned
                # F15-5 / R18-01: unknown non-tag rem after a mid-token
                # exception spelling uses the same fail-closed landing
                # as offset-0 steal (``xyoloxsextra`` →
                # yolox_unknown_residual). Skip only when the prefix
                # is an exact folded deny/NC identity so F14-6 /
                # F15-2 red-proofs stay sole-path
                # (``arcfaceyoloxextra`` / ``yoloyoloxextra``).
                # Deny-(c) debris prefixes (``fastsamx``) are not
                # ownership of the full token — return the stem.
                if deny is None and _MID_EXCEPTION_UNKNOWN_REM_ENABLED:
                    if prefix and not _deny_has_folded_ab_claim(prefix):
                        owned = _mid_exception_prefix_deny_owner(prefix)
                        if owned is not None:
                            deny = owned
                        else:
                            outcome, entry = _classify_exception_residual(
                                _seed_c, _seed_k, rem, compact_glue=True
                            )
                            if outcome != _RESIDUAL_LEGITIMATE:
                                deny = (
                                    entry
                                    or _unknown_exception_residual_entry(
                                        _seed_c, rem
                                    )
                                )
                if deny is not None:
                    return deny
            elif (
                _MID_EXCEPTION_UNKNOWN_REM_ENABLED
                and prefix
                and not _deny_has_folded_ab_claim(prefix)
            ):
                # Empty rem: ``{prefix}{exception}``. Junk-only
                # prefixes (``ayoloxs`` / ``xyoloxs``) stay admit.
                # A deny/NC stem in the prefix owns the token
                # (``fastsamxyolox`` / ``fastsamxyoloxs``).
                # Underscore tokens use the folded-seed owner so
                # ``buffalo_lxyolox`` names ``buffalo_l`` without
                # collapsing ``yolop_yolox`` to fabricated yolo.
                if has_sep:
                    owned = _underscore_preserving_glued_seed_owner(token)
                else:
                    owned = _mid_exception_prefix_deny_owner(prefix)
                if owned is not None:
                    return owned
            start = idx + 1
    return None


def _compact_joined_rule_e_hit(
    token: str,
) -> PackageDenylistEntry | None:
    """F15-1: rule (e) on the compact-joined component.

    Per-segment (e) misses when junk is glued to the head of a
    multi-segment NC seed (``aabuffalo`` + ``_l``): the seed splits
    across ``_`` and bare ``buffalo`` is BR-28-excluded. Compact
    denylist keys (``buffalol`` / ``buffalos`` / ``buffalosc`` /
    ``buffalol2`` / ``yolonasl`` / ``antelopev2`` / ``buffalotrt``)
    already catch the glued spelling when (e) runs on
    ``_compact_canonical(component)``. Single-segment tokens are a
    no-op (compact == token; the walk already tested (e)). Bare
    ``buffalo`` stays excluded so ``aabuffalo`` / ``buffalo_lakes`` /
    ``buffalo_bill_detector`` admit.
    """
    if not token or not _COMPACT_JOINED_RULE_E_ENABLED:
        return None
    if "_" not in token:
        return None
    compact = _compact_canonical(token)
    if not compact or compact == token:
        return None
    # NC-axis only (F15-1). A general compact (e) on the joined form
    # would also own ``yolox_s_ultralytics`` / ``yoloxyolo_v8`` and
    # steal the suffix-walk / steal-flag red-proofs.
    nc_map = {
        k: e
        for k, e in PACKAGE_DENYLIST.items()
        if e.reason is RejectionReason.NC_MODEL_DERIVED
    }
    return _best_family_hit(
        compact, nc_map, for_deny=True, allow_rule_c=False
    )


def _compact_mid_nc_occurrence(
    token: str,
) -> PackageDenylistEntry | None:
    """F15-1: NC seed occurs mid-compact with junk on both sides.

    Rule (e) is endswith-only and (c) is startswith-only, so
    ``aainsightfaceaa`` / ``aaarcfaceaa`` admitted everywhere. Mirror
    the F14-4 mid-exception scanner: an NC compact key of ≥
    ``_COMPACT_SUFFIX_MIN_SEED_LEN`` at offset > 0 with a non-empty
    remainder after the seed is a floor hit. Bare ``buffalo`` is
    excluded. Longest compact key wins.
    """
    if not token or not _COMPACT_MID_NC_OCCURRENCE_ENABLED:
        return None
    compact = _compact_canonical(token)
    if not compact:
        return None
    best: PackageDenylistEntry | None = None
    best_len = -1
    for seed_c, seed_k, entry in _iter_family_seeds(PACKAGE_DENYLIST):
        if entry.reason is not RejectionReason.NC_MODEL_DERIVED:
            continue
        if not seed_k or len(seed_k) < _COMPACT_SUFFIX_MIN_SEED_LEN:
            continue
        if (
            seed_c in _NC_PACKAGE_FLOOR_EXCLUSIONS
            or seed_k in _NC_PACKAGE_FLOOR_EXCLUSIONS
        ):
            continue
        start = 0
        while True:
            idx = compact.find(seed_k, start)
            if idx < 0:
                break
            if idx > 0 and idx + len(seed_k) < len(compact):
                if len(seed_k) > best_len:
                    best_len = len(seed_k)
                    best = entry
            start = idx + 1
    return best


def _deny_folded_ab_hit(token: str) -> PackageDenylistEntry | None:
    """Longest deny seed claiming ``token`` via (a)/(b)/(c)/glue (F10).

    Elevated before exception absorption. **Architecture (F10):**

      * Elevated deny-(c) closes pure compact deny debris whose rem after
        the deny seed fits ``[a-z0-9]{1,3}`` (``yolov9t`` / ``fastsamx``).
      * Long-seed compact-prefix glue (FIR-7-B13-5) closes denylist stems
        of compact length ≥ ``_DENY_COMPACT_PREFIX_GLUE_MIN_SEED_LEN`` with
        any non-empty alnum rem (``ultralyticsplus``).
      * Exception-prefix debris (``yoloseg`` / ``yolofree`` / ``yolos_eg``)
        is owned by residual classification (``_exception_illegitimate_deny_steal``),
        not by elevated (c) — callers carve out when an exception seed
        claims the token.

    F13-3 / R15-L-2: deny/NC heads of compact length ≥
    ``_COMPACT_SUFFIX_MIN_SEED_LEN`` whose remainder is itself an
    exception-family spelling or known seed (``arcfaceyolox`` /
    ``yolov8yolox``) also hit — the 11-char B13-5 glue floor left
    seeds of length 5–10 blind in head position.

    FIR-7-B12-1: (a), (b), and (c) are each evaluated independently —
    flag-gating only what the flag governs. The prior ``elif
    _FAMILY_BOUNDARY_PREFIX_ENABLED`` chain made (c) dead code whenever
    the (b) flag was on (always in production): a failed startswith
    exited the chain before the compact-remainder arm.

    Ranking uses the same specificity fold as :func:`_best_family_seed_match`
    so exact folded identity (``antelopev2``) outranks a compact-alias
    sibling (``antelope_v2``) of equal compact length.
    """
    if not token:
        return None
    best: PackageDenylistEntry | None = None
    best_key: tuple[int, int, int] = (-1, -1, -1)
    token_compact = _compact_canonical(token)
    for seed_c, seed_k, entry in _iter_family_seeds(PACKAGE_DENYLIST):
        hit = False
        # (a) exact on folded or compact form.
        if (
            token == seed_c
            or token_compact == seed_k
            or token == seed_k
            or token_compact == seed_c
        ):
            hit = True
        # (b) separator-boundary prefix on the folded form.
        if (
            not hit
            and _FAMILY_BOUNDARY_PREFIX_ENABLED
        ):
            boundary = seed_c + "_"
            if token.startswith(boundary) and len(token) > len(boundary):
                hit = True
        # (c) bounded compact remainder — evaluated even when (b) is
        # enabled but does not match (FIR-7-B12-1). Gated by both the
        # family (c) flag and the elevated-only flag so TEST-15 can
        # neuter the elevated closer without killing exception (c).
        if (
            not hit
            and _FAMILY_COMPACT_REMAINDER_ENABLED
            and _ELEVATED_DENY_COMPACT_ENABLED
            and seed_k
            and token_compact.startswith(seed_k)
        ):
            rem = token_compact[len(seed_k) :]
            if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
                hit = True
        # (c-glue) long-seed compact-prefix glue (FIR-7-B13-5).
        if (
            not hit
            and _DENY_COMPACT_PREFIX_GLUE_ENABLED
            and seed_k
            and len(seed_k) >= _DENY_COMPACT_PREFIX_GLUE_MIN_SEED_LEN
            and token_compact.startswith(seed_k)
        ):
            rem = token_compact[len(seed_k) :]
            if rem and _DENY_COMPACT_PREFIX_GLUE_REMAINDER.fullmatch(rem):
                hit = True
        # F13-3 / R15-L-2: head-position deny/NC + known-seed rem.
        if not hit and seed_k and _deny_head_known_rem_glue(token_compact, seed_k):
            hit = True
        # F15-2: deny-head (len ≥ 5) + known variant rem longer than
        # (c)'s 1–3 bound. ``yolov4tiny`` is the Darknet tiny twin of
        # ``yolov4_tiny``. Generic leftover (``akes`` / ``yoloxextra``)
        # is NOT this path.
        if (
            not hit
            and _DENY_HEAD_LONG_REM_ENABLED
            and seed_k
            and len(seed_k) >= _COMPACT_SUFFIX_MIN_SEED_LEN
            and token_compact.startswith(seed_k)
        ):
            rem = token_compact[len(seed_k) :]
            if rem in _DENY_HEAD_LONG_VARIANT_REMS:
                hit = True
        if not hit:
            continue
        spec = _family_match_specificity(token, seed_c, seed_k)
        if spec <= 0 and _deny_head_known_rem_glue(token_compact, seed_k):
            spec = 2
        if (
            spec <= 0
            and _DENY_HEAD_LONG_REM_ENABLED
            and seed_k
            and len(seed_k) >= _COMPACT_SUFFIX_MIN_SEED_LEN
            and token_compact.startswith(seed_k)
        ):
            rem = token_compact[len(seed_k) :]
            if rem in _DENY_HEAD_LONG_VARIANT_REMS:
                spec = 2
        # Prefer the seed whose folded spelling is actually in the token
        # (yolov8yolox → yolov8, not the yolo_v8 compact alias).
        folded_prefix = 1 if token.startswith(seed_c) else 0
        # F13-6 / R15-G1-4: prefer a (c) rem that is an honest task tag
        # (seg) over a longer seed with junk rem (yolov8seg → yolov8,
        # not yolov8s+eg).
        honesty = 0
        if seed_k and token_compact.startswith(seed_k):
            rem = token_compact[len(seed_k) :]
            if rem and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem):
                if rem in _HONEST_YOLO_COMPACT_REMS:
                    honesty = 1
        rank = (spec, honesty, folded_prefix, len(seed_k), len(seed_c))
        if rank > best_key:
            best_key = rank
            best = entry
    return best


def _exception_illegitimate_deny_steal(
    token: str,
) -> PackageDenylistEntry | None:
    """Deny entry for exception-family residual that fails F10 classification.

    **Single mechanism** (FIR-7 F10 / F11 / F12) for all exception+debris
    forms — short compact (``yoloseg``), long compact (``yolofree`` /
    ``yolosegme`` / ``yolosfree``), separator twins (``yolos_eg`` /
    ``yolof_ree``), tag+debris laundering (``yolos_tiny_eg`` /
    ``yolox_s_free``), compact export-tag glue (``yoloxpt``; A14-1), and
    unbounded compact residual deny glue (``yoloxultralyticsplus``;
    B14-1). Length is never the discriminator.

    **F12-1 steal is a pre-classifier branch**: when the residual came
    from unbounded compact prefix (``structural != residual``) and has
    any deny hit — exact identity included (``yoloxyolo`` → ``yolo``)
    as well as glue / contained long seeds (``yoloxultralyticsplus`` →
    ``ultralytics``) — return that hit *before*
    :func:`_classify_exception_residual` runs. ``yoloxultralytics`` /
    ``yoloxsultralytics`` are owned here, not by rule (e).

    Classification via :func:`_classify_exception_residual`
    (the pre-classifier paragraph above owns F12-1 steal):

      * legitimate tag residual (shape-aware) → ``None`` (admit / strip);
      * defer (residual-alone deny seed re-queueable by walker) → ``None``;
      * deny-reconstituting → the matched deny entry (honest lineage);
      * unknown residual → fail-closed entry with honest unknown-residual
        note (never fabricates an Ultralytics attribution).

    Gated by ``_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED`` (TEST-15 flag name
    retained from the F9 steal gate this supersedes).
    """
    if not _EXCEPTION_ILLEGITIMATE_STEAL_ENABLED:
        return None
    matched = _exception_seed_match_for_residual(token)
    if matched is None:
        return None
    seed_c, seed_k, residual = matched
    if not residual:
        return None

    compact_glue = _exception_residual_uses_compact_glue_rules(
        token, seed_c, seed_k
    )

    # B14-1 / F12-1: DEFER granted unboundedly (classifier) but walker
    # strip only re-queues bounded compact rem / separator residual.
    # When residual came from unbounded compact prefix and has ANY deny
    # hit — exact identity included (yolo / yolov8 / yolonas) as well as
    # non-exact glue (ultralyticsplus / yolov8seg) — return that hit.
    # Trailing (e) cannot see seeds shorter than
    # ``_COMPACT_SUFFIX_MIN_SEED_LEN`` (``yolo``, len 4) and cannot see
    # seeds reconstituted across segments, so leaving exact residuals on
    # DEFER was a fail-open (R14-G1-1 / R14-G1-2 / SECD-05). Seed-ending
    # compact glue of a ≥5-char deny seed (``xultralytics``) remains (e)
    # sole-path; ``yoloxultralytics`` is now owned by this steal.
    structural = _strip_exception_seed_residual(token, seed_c, seed_k)
    if residual and structural != residual:
        residual_deny = _deny_folded_ab_hit(residual)
        if residual_deny is None:
            residual_deny = _contained_long_deny_seed_hit(residual)
        # F13-6 / R15-G1-5: recurse steal on the residual so a
        # multi-stack compact (yoloxyoloxyolo) names the inner deny
        # seed (yolo) instead of landing on unknown residual.
        if residual_deny is None and residual != token:
            residual_deny = _exception_illegitimate_deny_steal(residual)
        if residual_deny is not None:
            return residual_deny

    # Legitimate / re-queueable-defer residuals use the shared boundary
    # helper so it stays load-bearing (TEST dead-helper guard).
    if _token_has_legitimate_exception_boundary(token):
        return None
    _outcome, entry = _classify_exception_residual(
        seed_c, seed_k, residual, compact_glue=compact_glue
    )
    # Boundary already returned for legitimate/defer; remaining outcomes
    # always carry an entry (deny-reconst or unknown). Fail-closed if not.
    if entry is not None:
        return entry
    return _unknown_exception_residual_entry(seed_c, residual)


def _uniform_component_scan(
    token: str,
    *,
    max_steps: int | None = None,
    reasons: frozenset[RejectionReason] | None = None,
) -> PackageDenylistEntry | None:
    """Uniform iterative deny-first suffix scan on one component.

    FIR-7-B8-01 / B8-02 / B8-05 / A9-01 / A10-02 / B11-01: one code path
    for direct component checks and post-exception residual re-scans.
    Separator-aligned suffixes are walked longest-first with **deny-first
    (a)/(b)/(c)** before exception absorption (an exception hit must never
    consume characters a deny seed claims at the same alignment — closes
    folded ``yolo_seg`` / ``yolo_x`` **and** compact ``yoloseg`` /
    ``yolofree`` / ``yolopose`` under junk prefixes while pure exception
    identities ``yolox`` / ``yolopv2`` / ``megvii_yolox`` / ``yoloxs`` still
    admit via the legitimate-exception-boundary carve-out). Pure-exception
    (empty residual) only continues to later suffixes — it never
    early-returns admit past un-scanned deny content. Remaining DENY uses
    (d)/(e). Iterative loop with hard step bound = initial segment count
    of the component; non-shrinking strip or bound overflow DENIES
    (``denylisted_package``, detail names the invariant).

    Bound is step-count ≤ initial segment count. Compact-remainder strips
    shrink total canonical length, not necessarily segment count, so the
    historical "recursion depth ≤ segment count" claim is false — this
    walker states the real bound (FIR-7-A8-03). The hard-cap overflow
    branch is a **defensive invariant** (FIR-7-B9-04): with correct strip
    helpers each counted strip consumes ≥ 1 unit against a bound of the
    initial segment count, so production inputs do not overflow; suite
    probes may force it via synthetic ``max_steps``.

    ``reasons``, when set, only returns deny hits whose ``reason`` is in
    the set (FIR-7-A10-01 multi-axis door collection: scan for AGPL hits
    even when a longer NC seed would rank first). Other-axis deny hits
    are skipped so shorter suffixes remain visible.

    ``strip_depth`` tracks how many exception strips have already been
    applied. The first strip (depth 0→1) is the single-strip residual path
    (B6-01); further strips require
    ``_EXCEPTION_MULTI_STRIP_CONTINUATION_ENABLED`` (B8-04 / A8-01) so
    multi-strip can be red-proven independently of single-strip re-scan.
    """
    if not token:
        return None
    if max_steps is None:
        max_steps = max(1, token.count("_") + 1)

    # Iterative work stack of (token, strips_already_applied). Bound counts
    # exception strips only (not every suffix pass): a compact-remainder
    # strip on a 1-segment token (``yoloxs`` → ``s``) is one strip against
    # a bound of 1 and must still admit (FIR-7-A8-03).
    stack: list[tuple[str, int]] = [(token, 0)]
    strips_done = 0
    while stack:
        current, strip_depth = stack.pop()
        if not current:
            continue

        segments = current.split("_")
        queued: tuple[str, int] | None = None

        # When residual-suffix scan is disabled (F4 red-proof path), only the
        # whole current token is considered — size-tag shields admit unless
        # residual-leading deny seeds still hit whole-token (a)/(b)/(c)/(d).
        suffix_starts = (
            range(len(segments))
            if _EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED
            else range(0, 1)
        )

        for i in suffix_starts:
            suffix = "_".join(segments[i:])
            if not suffix:
                continue

            # FIR-7-A10-02 / B11-01 / F10: deny (a)/(b)/(c)/glue BEFORE
            # exception absorption. Folded (a)/(b) always win (yolo_x /
            # yolo_seg). Pure elevated (c)/glue is suppressed when an
            # exception-family seed *claims* the suffix (any residual
            # length) — residual classification owns exception+debris
            # (yoloseg / yolofree / yolos_eg / yoloxs / yolos_tiny).
            abc_deny = _deny_folded_ab_hit(suffix)
            if abc_deny is not None:
                ab_claim = _deny_has_folded_ab_claim(suffix)
                # F15-10a: deny-head + exact exception spelling
                # (``yoloppyoloe`` = yolo + ppyoloe) is a structural
                # yolo reading and must not be carved out by a shorter
                # exception prefix claim (yolop + pyoloe).
                spelling_glue = _deny_head_is_exception_spelling_glue(suffix)
                if (
                    ab_claim
                    or spelling_glue
                    or not _token_has_exception_seed_claim(suffix)
                ):
                    if reasons is None or abc_deny.reason in reasons:
                        return abc_deny
                    # Other-axis elevated deny under reasons filter: do not
                    # let exception strip consume the deny alignment either.
                    continue
                # Exception seed claims suffix: fall through to residual
                # classification (bare yolop / yoloxs / yoloseg / yolofree).

            # FIR-7 F10: exception residual classification (single mechanism
            # for exception+debris — short/long compact, separator twins,
            # tag+debris laundering, unknown residual fail-closed).
            steal = _exception_illegitimate_deny_steal(suffix)
            if steal is not None:
                if reasons is None or steal.reason in reasons:
                    return steal
                continue

            # F13-3 / R15-L-3: junk-prefix exception+deny adjacency
            # (xyoloxyolo). Independent of F12-1 steal (offset 0).
            mid = _compact_mid_exception_deny_adjacency(suffix)
            if mid is not None:
                if reasons is None or mid.reason in reasons:
                    return mid
                continue

            exc = _best_exception_hit_with_residual(suffix)
            if exc is not None:
                _entry, new_residual = exc
                if not new_residual:
                    # Pure exception seed: do NOT early-return admit — keep
                    # scanning shorter suffixes for deny content (B8-01
                    # ordering: deny scan completes before exception admit).
                    continue
                # Non-empty residual after strip.
                if len(new_residual) >= len(suffix):
                    if _SCAN_FAIL_CLOSED_BOUNDS_ENABLED:
                        return _scan_invariant_deny(
                            "package-identity exception strip did not shrink "
                            "canonical length; invariant violation fail-closed"
                        )
                    # Fail-open red-proof path: treat as clean admit.
                    return None
                strips_done += 1
                if _SCAN_FAIL_CLOSED_BOUNDS_ENABLED and strips_done > max_steps:
                    return _scan_invariant_deny(
                        f"package-identity scan exceeded segment-count bound "
                        f"({max_steps}); invariant violation fail-closed"
                    )
                # Nested strip (already stripped once) requires multi-strip
                # continuation; single-strip residual re-scan is depth 0 only.
                if (
                    strip_depth >= 1
                    and not _EXCEPTION_MULTI_STRIP_CONTINUATION_ENABLED
                ):
                    return None
                queued = (new_residual, strip_depth + 1)
                break

            # Trailing deny (d)/(e): skip whole-token (c) — elevated already
            # owns pure compact (c) (FIR-7 F10 sole-path TEST-15).
            deny = _best_family_hit(
                suffix,
                PACKAGE_DENYLIST,
                for_deny=True,
                allow_rule_c=False,
            )
            if deny is not None and (
                reasons is None or deny.reason in reasons
            ):
                return deny  # type: ignore[no-any-return]
            # Other-axis deny under reasons filter → keep walking suffixes.

        if queued is not None:
            stack.append(queued)
            continue
        # No deny on any suffix and no residual to continue → current clean.
    # F15-1: separator-aligned walk missed. Compact-joined (e) catches
    # junk+multi-segment NC seeds — only after a real suffix walk, so
    # disabling the walk still admits ``yolox_s_buffalo_l`` (red-proof).
    # Mid-occurrence NC is independent (both-sides junk on one compact
    # token; no suffix needed). Reasons filter honoured for multi-axis
    # door collection.
    if _EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED:
        joined = _compact_joined_rule_e_hit(token)
        if joined is not None and (
            reasons is None or joined.reason in reasons
        ):
            return joined
    mid_nc = _compact_mid_nc_occurrence(token)
    if mid_nc is not None and (reasons is None or mid_nc.reason in reasons):
        return mid_nc
    return None


def _package_denylist_hit(
    value: str,
    *,
    reasons: frozenset[RejectionReason] | None = None,
) -> PackageDenylistEntry | None:
    """Structural family-boundary PACKAGE_DENYLIST lookup (BR-51 / Wave F6/F7).

    Fold via :func:`canonical` (NFKC, casefold, unify ``-``/``_``/``.``/space).
    When ``/`` is present, test **only** slash components (never the joined
    full token — FIR-7-A6-02). Each component is matched by the **uniform
    iterative scanner** (FIR-7-B8-01 / B8-02 / A9-01 / A10-02): folded deny
    (a)/(b) first, then exception-family strip with residual re-scan, then
    deny-family via whole-suffix (c)/(d)/(e). Outer separator-aligned suffix
    walk supplies path-split coverage; there is no inner (d') walk. A
    component hits a deny family seed under any of:

      (a) exact folded/compact match;
      (b) separator-boundary prefix (``seed_`` + rest);
      (c) bounded compact remainder (1–3 alnum after seed compact form);
      (d) head-segment (leading segment hits via (a) or (c));
      (e) compact segment-suffix (seed ≥ 5 compact chars, non-empty lead).

    ``yolo-v5`` / ``yolov8n_oiv7`` / ``yolov9t`` / ``yolov9t-seg`` /
    ``yolox_ultralytics`` / ``yolox_s_ultralytics`` / ``yolox/s_ultralytics`` /
    ``yoloxultralytics`` / ``checkpoints_yolo_seg`` deny; ``yolodummy`` /
    ``myyolo`` / pure exception-family tokens (``yolox``, ``yolos``,
    ``yolop_yolox``, ``megvii_yolox``, ``ppyolov2``) do not. Empty / None
    / slash-only canonical → no denylist hit (doors treat empty/None/
    slash-only as ``invalid_row`` separately — FIR-7-B4-01 / B5-04 /
    F15-4).

    ``reasons`` (FIR-7-A10-01): when set, only return hits whose reason is
    in the set — lets door promotion collect AGPL-axis hits even when a
    longer NC seed ranks first on the unfiltered scan.
    """
    c = canonical(value)
    if c is None or not c:
        return None
    # FIR-7-A6-02: component-split-first — never family-test the joined
    # full token when '/' is present (bare-seed (b) would otherwise bridge
    # across the path separator).
    if "/" in c:
        candidates = [p for p in c.split("/") if p]
    else:
        candidates = [c]

    seen: set[str] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        bound = max(1, cand.count("_") + 1)

        # Bounded exception short-circuit gate (FIR-7-B6-01 red-proof): when
        # residual re-scan is disabled, any exception-family hit admits the
        # component without residual deny scan. Production keeps re-scan on
        # and routes every component through the uniform scanner.
        if not _EXCEPTION_RESIDUAL_RESCAN_ENABLED:
            exc = _best_exception_hit_with_residual(cand)
            if exc is not None:
                continue
            hit = _best_family_hit(cand, PACKAGE_DENYLIST, for_deny=True)
            if hit is not None and (
                reasons is None or hit.reason in reasons
            ):
                return hit  # type: ignore[no-any-return]
            continue

        hit = _uniform_component_scan(
            cand, max_steps=bound, reasons=reasons
        )
        if hit is not None:
            return hit
    return None


def _nc_package_rest_is_export_shaped(rest: str) -> bool:
    """True when ``rest`` is entirely export/quant/runtime shield tags.

    Used by whole-component NC package promotion so ``insightface_trt``
    rejects while BR-28 name-continuations like ``insightface_free`` /
    ``buffalo_l_extra`` stay admitted on weights doors. A rest segment
    counts when it is in ``_NC_TRAILING_SHIELD_TAGS`` or contains a digit
    (structural quant codes like ``int8``). Pure-alpha short name
    continuations (``free``, ``extra``) do not qualify.

    FIR-7-A10-05: **no length cap** on the tag run — a tag-flood of known
    shield tags (``buffalo_l_onnx_int8_fp16_trt_ncnn_tflite_pt``) is still
    export-shaped so the package-floor door promotion catches NC bases
    that the membership strip bound of 3 cannot fully unwrap. Bound
    overflow on the membership strip path admits only when the base truly
    is not NC *and* the floor promotion also misses.
    """
    if not rest:
        return False
    parts = [p for p in rest.split("_") if p]
    if not parts:
        return False
    for seg in parts:
        if seg in _NC_TRAILING_SHIELD_TAGS:
            continue
        if any(ch.isdigit() for ch in seg) and len(seg) <= _NC_STRUCTURAL_SHORT_TAG_MAX_LEN:
            continue
        return False
    return True


def _whole_component_nc_package_hit(value: str) -> PackageDenylistEntry | None:
    """NC package-floor hit for weights doors (FIR-7-B9-02 / B10-04 / A10-04).

    Unlike :func:`_package_denylist_hit`, this does **not** run exception
    residual strip or promote compact (e) glue. Each slash component is
    tested as a whole token under deny rules, then — when
    ``_NC_PACKAGE_COMPONENT_SUFFIX_ENABLED`` — every separator-aligned
    **suffix** of that component is tested the same way. Promotion
    accepts every floor-hit shape that preserves BR-28 precision:

      * exact / compact (a);
      * export-shaped (b) residuals (any-length known-tag run — A10-05);
      * bounded compact remainder (c) (FIR-7-B10-04) — closes
        ``myprefix_buffalo_l2`` / compact-rule-(c) floor hits on doors.

    Multi-segment seeds under junk prefixes (``myprefix_yolo_nas_l``,
    ``myprefix_arcface_glint360k_r100``) reject via the suffix walk + (a).
    BR-28 ``not_<seed>`` forms (single leading segment ``not``) are carved
    out so ``not_insightface`` / ``not-retinaface`` remain admitted on
    weights doors (deliberate door-precision: the seed sits as a pure
    suffix with leading alpha glue ``not_`` at a separator; package/row
    floor still rejects via the uniform scanner). Compact (e) glue is
    still not promoted on this path.
    """
    c = canonical(value)
    if c is None or not c:
        return None
    if "/" in c:
        components = [p for p in c.split("/") if p]
    else:
        components = [c]
    # Restrict the family map to NC-axis entries once (FIR-7-A11-1): an AGPL
    # seed ranking win cannot steal this path (multi-axis is handled
    # separately by door promotion — FIR-7-A10-01).
    nc_map = {
        k: e
        for k, e in PACKAGE_DENYLIST.items()
        if e.reason is RejectionReason.NC_MODEL_DERIVED
    }
    seen: set[str] = set()
    for comp in components:
        if comp in seen:
            continue
        seen.add(comp)
        segments = [s for s in comp.split("_") if s]
        if not segments:
            continue
        # Whole component first; then shorter separator-aligned suffixes
        # when the B9-02 follow-up flag is on (prefix-shield close).
        suffix_starts = (
            range(len(segments))
            if _NC_PACKAGE_COMPONENT_SUFFIX_ENABLED
            else range(0, 1)
        )
        for i in suffix_starts:
            cand = "_".join(segments[i:])
            if not cand:
                continue
            # BR-28 negation carve-out: ``not_<seed>`` / ``not_<seed>_<tags>``
            # stay clean on weights doors. Only a single leading ``not``
            # segment is carved out — ``myprefix_antelopev2`` still rejects.
            if i == 1 and segments[0] == "not":
                continue
            matched = _best_family_seed_match(
                cand, nc_map, for_deny=True, allow_rule_e=False
            )
            if matched is None:
                continue
            seed_c, seed_k, entry = matched
            if entry.reason is not RejectionReason.NC_MODEL_DERIVED:
                continue
            # Exact / compact (a): always promote.
            # Multi-segment NC ids under junk prefixes
            # (``myprefix_scrfd_10g_kps``) resolve here: specificity ranking
            # returns the full multi-segment seed as exact (a) on the suffix
            # ``scrfd_10g_kps`` — no (b)-fallback is required (FIR-7-A11-1).
            cand_k = _compact_canonical(cand)
            if (
                cand == seed_c
                or cand_k == seed_k
                or cand == seed_k
                or cand_k == seed_c
            ):
                return entry  # type: ignore[no-any-return]
            # (b) separator-boundary: promote when residual is export-shaped
            # (tag-flood OK — A10-05). Name-continuations like
            # ``insightface_free`` miss (not export-shaped) and stay clean
            # on doors.
            boundary = seed_c + "_"
            if cand.startswith(boundary) and len(cand) > len(boundary):
                rest = cand[len(boundary) :]
                if _nc_package_rest_is_export_shaped(rest):
                    return entry  # type: ignore[no-any-return]
            # (c) bounded compact remainder (FIR-7-B10-04): promote when the
            # remainder is **digit-bearing** (size/version debris like
            # ``l2`` / ``v2`` / ``10``) so compact rule-(c) floor hits reach
            # the weights doors. Pure-alpha remainders (``eye`` on
            # ``buffalos_eye``) are NOT promoted — that is the BR-28
            # name-continuation posture (doors admit; package/row floor may
            # still reject via unrestricted (c)). A dedicated unit test
            # monkeypatches a floor entry to exercise pure (c) promotion
            # independently of the digit-bearing filter.
            if (
                _FAMILY_COMPACT_REMAINDER_ENABLED
                and seed_k
                and cand_k.startswith(seed_k)
            ):
                rem = cand_k[len(seed_k) :]
                if (
                    rem
                    and _BOUNDED_COMPACT_REMAINDER.fullmatch(rem)
                    and any(ch.isdigit() for ch in rem)
                ):
                    return entry  # type: ignore[no-any-return]
            # Do not promote (d)/(e)-only / pure-alpha-(c) hits on doors.
            continue
    return None


def _door_package_floor_promotion(
    value: str,
) -> PackageDenylistEntry | None:
    """Multi-axis package-floor promotion for weights doors (FIR-7-A10-01).

    Considers **all** floor hits in a compound, not just the ranked winner
    from :func:`_package_denylist_hit`:

      * AGPL / ``denylisted_package`` axis — filtered uniform scan;
      * NC / ``nc_model_derived`` axis — whole-component NC promotion
        (shapes (a)/(b)/(c)).

    **Precedence when both axes are present: AGPL / denylisted_package
    first.** Distribution-channel taint is independently disqualifying and
    must not be shadowed by a longer NC seed ranking win (e.g.
    ``buffalo_l_ultralytics`` → ultralytics AGPL note, not a silent admit
    and not an NC note on an AGPL residue). Never admit a dual-axis
    compound; never attribute one lineage's residue to the other's note.

    Compact AGPL-adjacent glue on long denylist stems (``ultralyticsplus``
    — FIR-7-B13-5) is an AGPL floor hit via elevated compact-prefix glue.
    Bare NC seeds (``buffalo_l``) stay ``nc_model_derived``.

    R23-03: a synthetic ``<family>_unknown_residual`` hit is not a
    real AGPL package. When the unfiltered floor already named an NC
    seed (``buffalo_lxyolox_yolop_tiny``), the door reports that NC
    licence class — never an AGPL-axis unknown-residual note that
    sends a consumer down the wrong remediation path. Real AGPL
    packages (``buffalo_l_ultralytics`` / ``fastsam…``) still win.
    """
    agpl_reasons = frozenset({RejectionReason.DENYLISTED_PACKAGE})
    agpl = _package_denylist_hit(value, reasons=agpl_reasons)
    if agpl is not None:
        if _is_synthetic_unknown_residual_entry(agpl):
            unfiltered = _package_denylist_hit(value)
            if (
                unfiltered is not None
                and unfiltered.reason is RejectionReason.NC_MODEL_DERIVED
            ):
                return unfiltered
        return agpl
    nc = _whole_component_nc_package_hit(value)
    if nc is not None:
        return nc
    # F12-3 / R14-G1-4 / F14-4 / F15-1: fail closed when the uniform
    # scanner already found NC but whole-component promotion missed.
    # Promote whenever exception-family structure is witnessed
    # *anywhere* in the compact token (prefix, trailing segment, or
    # mid-token ``xyoloxinsightface`` / ``aabuffalo_l_yolox``). BR-28
    # door-precision (``myarcface`` / ``not-insightface``) and junk+NC
    # without an exception segment (``aabuffalo_l`` / ``aainsightface``
    # / ``aaayolonas``) stay door-pass — deliberate asymmetry, not a
    # scanner miss. Those junk+NC forms now floor-deny (F15-1 compact-
    # joined (e) / mid-occurrence NC); the door still requires an
    # exception witness to promote.
    if _token_has_exception_family(value):
        scanned_nc = _package_denylist_hit(
            value, reasons=frozenset({RejectionReason.NC_MODEL_DERIVED})
        )
        if scanned_nc is not None:
            return scanned_nc
    return None


def _audit_weights_lineage_token(
    text: str,
    *,
    field: str,
    research_detail: str,
) -> LicenseAuditResult | None:
    """Shared AGPL → NC membership → research → NC-floor sequence (FIR-7-A12-3).

    Both :func:`audit_derived_from_model` and :func:`audit_source` call this
    single helper so a source-door-only (or derived-door-only) demotion of
    any branch is structurally impossible — one edit site, both doors.
    Returns a FAIL result, or ``None`` when the token is clean on every
    axis (caller emits the door-specific PASS detail).
    """
    # FIR-7-B11-02 / A10-01: multi-axis package-floor promotion runs even
    # when NC membership matches. AGPL / denylisted_package anywhere in the
    # compound outranks nc_model_derived.
    floor = _door_package_floor_promotion(text)
    if (
        floor is not None
        and floor.reason is RejectionReason.DENYLISTED_PACKAGE
    ):
        return _fail(
            floor.reason,
            detail=(
                f"{field}={text!r} hits PACKAGE_DENYLIST entry "
                f"{floor.package_id!r} ({floor.spdx_id}): {floor.notes}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    matched = match_nc_model_pattern(text)
    if matched is not None:
        lineage = _nc_detail_lineage_note(matched)
        return _fail(
            RejectionReason.NC_MODEL_DERIVED,
            detail=(
                f"{field}={text!r} matches non-commercial pattern "
                f"{matched!r}; {lineage}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    if _looks_like_research_source(text):
        return _fail(
            RejectionReason.RESEARCH_ONLY_SOURCE,
            detail=research_detail,
            category=PolicyCategory.TRAINING_DATA,
        )

    # NC-axis floor promotion (no AGPL hit; membership missed).
    if floor is not None:
        return _fail(
            floor.reason,
            detail=(
                f"{field}={text!r} hits PACKAGE_DENYLIST entry "
                f"{floor.package_id!r} ({floor.spdx_id}): {floor.notes}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
    return None


# Fail loudly at import if a reviewer adds the same seed to both tables.
_assert_package_family_seed_sets_disjoint()



# Fields that may carry a package / framework identity token. First-wins
# selection among these keys must not hide a denylisted token behind another
# non-empty field (FIR-7-RV-10 / BR-53 floor semantics).
_PACKAGE_IDENTITY_FIELD_KEYS: tuple[str, ...] = (
    "package",
    "package_name",
    "model_id",
    "source",
)

# GATE-04 / FIR-7-B2-02: package-identity keys get the same case + separator
# normalisation as licence keys (via :func:`_normalise_field_key`). Map
# normalised spellings to the canonical field name. ``packagename`` /
# ``modelid`` cover the no-separator fold of ``packageName`` / ``modelId``.
_PACKAGE_IDENTITY_KEY_ALIASES: dict[str, str] = {
    "package": "package",
    "package_name": "package_name",
    "packagename": "package_name",
    "model_id": "model_id",
    "modelid": "model_id",
    "source": "source",
}


def _floor_package_identity_denylist(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """Package-denylist floor across every package-identity field (FIR-7-RV-10).

    A denylisted package token in **any** of ``package`` / ``package_name`` /
    ``model_id`` / ``source`` fails closed on every door — floor semantics
    like BR-53, not first-wins among identity fields. Rejection detail names
    both the denylisted token and the field it appeared in.

    Key aliases use :func:`_normalise_field_key` (case fold + underscore/hyphen
    fold) so ``Package`` / ``PACKAGE`` / ``package_Name`` / ``Model-Id`` cannot
    bypass the floor (FIR-7-B2-02 / GATE-04). Non-string, non-None values are
    fail-closed ``invalid_row`` (FIR-7-B2-01 / BR-68 parity). Disagreeing
    values under the same canonical key after normalisation are
    ``invalid_row`` (licence-key precedent).
    """
    # Collect (raw_key, canonical_key, raw_value) for every present identity
    # field, including case/separator aliases. Type-check before denylist so a
    # list/dict under ``Package`` cannot skip the floor (FIR-7-B2-01).
    by_canonical: dict[str, list[tuple[str, Any]]] = {
        key: [] for key in _PACKAGE_IDENTITY_FIELD_KEYS
    }
    for key in row:
        if not isinstance(key, str):
            continue
        canonical_key = _PACKAGE_IDENTITY_KEY_ALIASES.get(_normalise_field_key(key))
        if canonical_key is None:
            continue
        by_canonical[canonical_key].append((key, row[key]))

    # BR-68 / FIR-7-B2-01: non-string present values fail closed, naming field
    # and type. None is treated as a type error when the key is present (same
    # contract as :func:`_floor_string_field` / licence keys).
    for _canonical_key, entries in by_canonical.items():
        for raw_key, raw in entries:
            if raw is None:
                return _fail(
                    RejectionReason.INVALID_ROW,
                    detail=(
                        f"provenance row field {raw_key!r} must be a string, "
                        f"got None"
                    ),
                    category=category,
                )
            if not isinstance(raw, str):
                return _fail(
                    RejectionReason.INVALID_ROW,
                    detail=(
                        f"provenance row field {raw_key!r} must be a string, "
                        f"got {type(raw).__name__}"
                    ),
                    category=category,
                )

    # Disagreeing non-empty values under one canonical key → invalid_row
    # (licence-key BR-35 / FIR-7-B2-02 precedent).
    for canonical_key, entries in by_canonical.items():
        texts = [str.strip(raw) for _k, raw in entries if str.strip(raw)]
        if len({str.casefold(t) for t in texts}) > 1:
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    f"provenance row declares disagreeing {canonical_key!r} "
                    f"values {texts!r} under alias keys; fail-closed on ambiguity"
                ),
                category=category,
            )

    # Denylist scan: every non-empty string value under any identity alias.
    # Emit against the raw key so detail names what the row author wrote.
    # FIR-7-B4-01 / BR-21: a present value whose :func:`canonical` is None
    # (non-ASCII residue after NFKC/Cf — unicode dashes, confusable scripts)
    # is fail-closed ``invalid_row``. FIR-7-B5-04: non-empty pre-canonical
    # that folds to the empty string (Cf-format-only: ZWSP, BOM, word-joiner)
    # is the same fail-closed treatment. Never treat either miss as "no
    # denylist hit" and silently skip the floor.
    for canonical_key in _PACKAGE_IDENTITY_FIELD_KEYS:
        for raw_key, raw in by_canonical[canonical_key]:
            text = str.strip(raw)
            if not text:
                continue
            folded = canonical(text)
            if folded is None:
                return _fail(
                    RejectionReason.INVALID_ROW,
                    detail=(
                        f"{raw_key}={text!r} "
                        f"{_invalid_identity_reason_clause(text)}"
                    ),
                    category=category,
                )
            if folded == "" or (
                _EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED
                and _canonical_lacks_identity(folded)
            ):
                return _fail(
                    RejectionReason.INVALID_ROW,
                    detail=(
                        f"{raw_key}={text!r} canonicalises to an empty "
                        "identity; nonblank input with no identity token "
                        "is fail-closed"
                    ),
                    category=category,
                )
            deny = _package_denylist_hit(text)
            if deny is None:
                continue
            return _fail(
                deny.reason,
                detail=(
                    f"{raw_key}={text!r} hits PACKAGE_DENYLIST entry "
                    f"{deny.package_id!r} ({deny.spdx_id}): {deny.notes}"
                ),
                category=category,
            )
    return None

def audit_derived_from_model(derived_from_model: str | None) -> LicenseAuditResult:
    """Audit a ``derived_from_model`` provenance tag (buffalo OUTPUT ban).

    Empty string is allowed (not every row is model-derived). Any match
    against the expanded NC id set FAILS with ``RejectionReason.NC_MODEL_DERIVED``.
    PACKAGE_DENYLIST hits (Ultralytics family) FAIL with their denylist reason
    (BR-51). Non-ASCII residue after :func:`canonical` FAILS ``invalid_row``
    (BR-21 fail-closed). Non-string inputs FAIL ``invalid_row`` (BR-46).
    """
    type_err = _reject_non_string(
        derived_from_model,
        field="derived_from_model",
        category=PolicyCategory.TRAINING_DATA,
    )
    if type_err is not None:
        return type_err
    if derived_from_model is None:
        return _pass(detail="no derived_from_model tag")
    if not str.strip(derived_from_model):
        return _pass(detail="no derived_from_model tag")

    text = str.strip(derived_from_model)
    c = canonical(text)
    if c is None:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"derived_from_model={text!r} "
                f"{_invalid_identity_reason_clause(text)}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
    if _EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED and _canonical_lacks_identity(c):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"derived_from_model={text!r} canonicalises to an empty "
                "identity; nonblank input with no identity token is fail-closed"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    # FIR-7-A12-3: shared multi-axis sequence with audit_source.
    tainted = _audit_weights_lineage_token(
        text,
        field="derived_from_model",
        research_detail=(
            f"derived_from_model={text!r} is a research-only corpus; "
            "research-tainted lineage is banned for commercial use"
        ),
    )
    if tainted is not None:
        return tainted

    return _pass(
        detail=f"derived_from_model={text!r} is not on the NC pattern list",
        category=PolicyCategory.TRAINING_DATA,
    )


# SPDX expression joiners (GATE-10). Matched as whole tokens so licence ids
# that happen to contain those letters are not split.
_SPDX_EXPRESSION_JOINERS = re.compile(r"\s+(?:OR|AND|WITH)\s+", re.IGNORECASE)


def _spdx_base_token(tok: str) -> str:
    """Map a single SPDX component to its base id (FIR-7-RV-12).

    Strips a trailing ``+`` (SPDX "or later" shorthand) and a trailing
    ``-or-later`` / ``-only`` is **not** stripped for ``-only`` (those are
    distinct SPDX ids on the denylist). Only ``+`` and ``-or-later`` map to
    the base identifier for allowlist membership.
    """
    text = str.strip(tok)
    if not text:
        return text
    if text.endswith("+"):
        text = text[:-1].rstrip()
    # Case-insensitive -or-later suffix → base id (Apache-2.0-or-later → Apache-2.0).
    folded = str.casefold(text)
    suffix = "-or-later"
    if folded.endswith(suffix):
        text = text[: -len(suffix)].rstrip()
    return text


def _spdx_expression_malformed_reason(tag: str) -> str | None:
    """Return an expression-hygiene detail when ``tag`` has empty components.

    Empty parentheses (``()``), a trailing / leading operator (``MIT AND``,
    ``OR MIT``), or an empty RHS after an operator must fail closed (GATE-10 /
    FIR-7-B2-06) — never silently drop the empty component and admit the rest.

    Unicode dashes (en/em) and unbalanced parentheses also fail closed with an
    expression-hygiene label (FIR-7-B3-04 / FIR-7-A3-02) — bare ``unknown_spdx``
    without the hygiene detail would hide the structural defect, and unbalanced
    ``(MIT`` / ``MIT)`` must not admit after silent paren strip.
    """
    text = str.strip(tag)
    if not text:
        return None
    # FIR-7-B3-04: non-ASCII dash/hyphen variants are not SPDX punctuation.
    # U+2010..U+2015 (hyphen / non-breaking hyphen / figure dash / en / em /
    # horizontal bar) and U+2212 (minus sign).
    if re.search(r"[\u2010-\u2015\u2212]", text):
        return (
            f"license {tag!r} is a malformed SPDX expression "
            "(expression-hygiene: non-ASCII dash)"
        )
    # FIR-7-A3-02: unbalanced parentheses — count and order.
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return (
                    f"license {tag!r} is a malformed SPDX expression "
                    "(expression-hygiene: unbalanced parentheses)"
                )
    if depth != 0:
        return (
            f"license {tag!r} is a malformed SPDX expression "
            "(expression-hygiene: unbalanced parentheses)"
        )
    if re.search(r"\(\s*\)", text):
        return (
            f"license {tag!r} is a malformed SPDX expression "
            "(expression-hygiene: empty parentheses)"
        )
    # Strip grouping parens to spaces before operator / empty-part checks so
    # ``(MIT)`` stays well-formed while ``MIT OR ()`` is already caught above.
    work = text.replace("(", " ").replace(")", " ")
    work_stripped = str.strip(work)
    if not work_stripped:
        return (
            f"license {tag!r} is a malformed SPDX expression "
            "(expression-hygiene: empty component)"
        )
    # Trailing / leading operator with no RHS / LHS (``MIT AND``, ``OR MIT``).
    if re.search(r"(?:^|\s)(?:OR|AND|WITH)\s*$", work_stripped, re.IGNORECASE):
        return (
            f"license {tag!r} is a malformed SPDX expression "
            "(expression-hygiene: trailing operator / empty RHS)"
        )
    if re.search(r"^(?:OR|AND|WITH)(?:\s|$)", work_stripped, re.IGNORECASE):
        return (
            f"license {tag!r} is a malformed SPDX expression "
            "(expression-hygiene: leading operator / empty LHS)"
        )
    parts = _SPDX_EXPRESSION_JOINERS.split(work)
    if len(parts) > 1:
        for part in parts:
            if not str.strip(part):
                return (
                    f"license {tag!r} is a malformed SPDX expression "
                    "(expression-hygiene: empty component)"
                )
    return None


def _spdx_expression_tokens(tag: str) -> list[str]:
    """Split a compound SPDX expression into licence-id tokens (GATE-10).

    Handles ``OR`` / ``AND`` / ``WITH``, strips parentheses, and maps each
    component through :func:`_spdx_base_token` (trailing ``+`` / ``-or-later``).
    Does not attempt to evaluate the expression — callers check each token
    against the denylist then the allowlist fail-closed.

    Callers must run :func:`_spdx_expression_malformed_reason` first so empty
    parentheses / empty RHS cannot be silently dropped (FIR-7-B2-06).
    """
    text = str.strip(tag).replace("(", " ").replace(")", " ")
    tokens: list[str] = []
    for part in _SPDX_EXPRESSION_JOINERS.split(text):
        tok = _spdx_base_token(part)
        if tok:
            tokens.append(tok)
    return tokens


def _denylist_reason_for_spdx_token(tag_cf: str) -> RejectionReason | None:
    """Return the denylist rejection reason for a casefolded SPDX token, or None."""
    if tag_cf not in DENYLISTED_SPDX_IDS_CF:
        return None
    if tag_cf in _RESEARCH_ONLY_LICENSE_CF:
        return RejectionReason.RESEARCH_ONLY_LICENSE
    return RejectionReason.DENYLISTED_LICENSE


def audit_spdx(spdx_id: str | None) -> LicenseAuditResult:
    """Audit a bare SPDX / license tag (case-insensitive).

    Non-string inputs FAIL ``invalid_row`` (BR-46). ``None`` / blank →
    ``missing_license_field``.

    Compound SPDX expressions (``OR`` / ``AND`` / ``WITH``, trailing ``+`` /
    ``-or-later``, parentheses) are tokenised; denylist checks run first on
    every component (GATE-10). A single denylisted component fails the whole
    expression — allowlisted siblings cannot launder it. When **every**
    component is allowlisted (and none denylisted), the expression PASSes
    (FIR-7-RV-12). An unknown component fails closed naming that component.
    """
    type_err = _reject_non_string(spdx_id, field="license")
    if type_err is not None:
        return type_err
    if spdx_id is None or not str.strip(spdx_id):
        return _fail(
            RejectionReason.MISSING_LICENSE_FIELD,
            detail="license / spdx_id field is required",
        )
    # Unbound strip/casefold so str subclasses cannot launder (GATE-15).
    tag = str.strip(spdx_id)
    tag_cf = str.casefold(tag)

    denied = _denylist_reason_for_spdx_token(tag_cf)
    if denied is not None:
        return _fail(
            denied,
            detail=f"license {tag!r} is denylisted for commercial training use",
        )
    if tag_cf in ALLOWED_SPDX_IDS_CF:
        return _pass(detail=f"license {tag!r} is allowlisted")
    if tag_cf == "pending-legal-clearance":
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail="license is PENDING-LEGAL-CLEARANCE",
        )

    # FIR-7-B2-06 / GATE-10: empty parens / trailing operator / empty RHS are
    # expression-hygiene failures — fail closed before silent component-drop.
    hygiene = _spdx_expression_malformed_reason(tag)
    if hygiene is not None:
        return _fail(RejectionReason.UNKNOWN_SPDX, detail=hygiene)

    tokens = _spdx_expression_tokens(tag)
    # GATE-10: denylist components before allowlist / unknown_spdx.
    for tok in tokens:
        tok_cf = str.casefold(tok)
        denied = _denylist_reason_for_spdx_token(tok_cf)
        if denied is not None:
            return _fail(
                denied,
                detail=(
                    f"license {tag!r} contains denylisted component {tok!r}; "
                    "fail-closed for commercial training use"
                ),
            )

    # FIR-7-RV-12: every component allowlisted (and none denylisted) → PASS.
    if tokens and all(str.casefold(tok) in ALLOWED_SPDX_IDS_CF for tok in tokens):
        return _pass(
            detail=(
                f"license {tag!r} is allowlisted "
                f"(all components {[t for t in tokens]!r})"
            ),
        )

    # Name the first unknown component when present (reason fidelity).
    for tok in tokens:
        if str.casefold(tok) not in ALLOWED_SPDX_IDS_CF:
            return _fail(
                RejectionReason.UNKNOWN_SPDX,
                detail=(
                    f"license {tag!r} contains unknown component {tok!r}; "
                    "not on the allowlist"
                ),
            )

    # operator-cleared is NOT an SPDX value and is never an unconditional pass.
    return _fail(
        RejectionReason.UNKNOWN_SPDX,
        detail=f"license {tag!r} is not on the allowlist",
    )


def audit_source(source: str | None) -> LicenseAuditResult:
    """Audit a training-data ``source`` field against NC models + research-only.

    NC model patterns/ids take precedence over research-only (BR-20): banned
    weights named as ``source`` fail with ``nc_model_derived`` just as they
    do in ``derived_from_model``. Does **not** inspect ``generator_lineage``.
    Non-string inputs FAIL ``invalid_row`` (BR-46). ``None`` / blank →
    ``unknown_source``.
    """
    type_err = _reject_non_string(
        source, field="source", category=PolicyCategory.TRAINING_DATA
    )
    if type_err is not None:
        return type_err
    if source is None or not _strip_source_token(source):
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="source field is required for training-data rows",
            category=PolicyCategory.TRAINING_DATA,
        )
    text = _strip_source_token(source)
    c = canonical(text)
    if c is None:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"source {text!r} {_invalid_identity_reason_clause(text)}"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
    if _EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED and _canonical_lacks_identity(c):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"source {text!r} canonicalises to an empty identity; "
                "nonblank input with no identity token is fail-closed"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )
    # FIR-7-A12-3: shared multi-axis sequence with audit_derived_from_model.
    tainted = _audit_weights_lineage_token(
        text,
        field="source",
        research_detail=(
            f"source {text!r} is research-only and taints commercial use"
        ),
    )
    if tainted is not None:
        return tainted
    return _pass(
        detail=f"source {text!r} is not research-only",
        category=PolicyCategory.TRAINING_DATA,
    )


def audit_model_ingest(model_id: str) -> LicenseAuditResult:
    """Verify a detector / cascade model has a named commercial-allowed ingest entry.

    Missing entry → FAIL ``MISSING_INGEST_ENTRY``.
    Denylisted package (Ultralytics etc.) → FAIL with that package's reason.
    NC-tagged entry → FAIL ``NC_MODEL_DERIVED``.
    Non-string inputs FAIL ``invalid_row`` (BR-46) — not a missing registry entry.
    """
    type_err = _reject_non_string(
        model_id, field="model_id", category=PolicyCategory.MODEL_INGEST
    )
    if type_err is not None:
        return type_err
    if model_id is None or not str.strip(model_id):
        return _fail(
            RejectionReason.MISSING_INGEST_ENTRY,
            detail="model_id is required for ingest",
            category=PolicyCategory.MODEL_INGEST,
        )
    text = str.strip(model_id)
    # FIR-7-B4-01 / BR-21: non-ASCII residue is invalid identity, not a
    # missing registry entry (do not imply the token is merely unregistered).
    # FIR-7-B5-04: Cf-format-only (canonical → "") is the same fail-closed
    # invalid_row treatment.
    folded = canonical(text)
    if folded is None:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"model_id={text!r} {_invalid_identity_reason_clause(text)}"
            ),
            category=PolicyCategory.MODEL_INGEST,
        )
    if folded == "" or (
        _EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED
        and _canonical_lacks_identity(folded)
    ):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"model_id={text!r} canonicalises to an empty identity; "
                "nonblank input with no identity token is fail-closed"
            ),
            category=PolicyCategory.MODEL_INGEST,
        )
    resolved = _resolve_model_key(model_id)

    # FIR-7-B3-01: folded denylist lookup (separator/case + compact) so
    # yolo-v5 / yolo_v5 hit the same seed as yolov5.
    deny = _package_denylist_hit(text)
    if deny is not None:
        return _fail(
            deny.reason,
            detail=(
                f"package {deny.display_name!r} ({deny.spdx_id}) is denylisted: "
                f"{deny.notes}"
            ),
            category=PolicyCategory.MODEL_INGEST,
        )

    entry = MODEL_INGEST_ENTRIES.get(resolved)
    if entry is None:
        return _fail(
            RejectionReason.MISSING_INGEST_ENTRY,
            detail=f"no named license_policy ingest entry for model_id={model_id!r}",
            category=PolicyCategory.MODEL_INGEST,
        )
    if entry.verification.commercial_use is not CommercialUse.ALLOWED:
        return _fail(
            RejectionReason.NC_MODEL_DERIVED,
            detail=(
                f"ingest entry {entry.model_id!r} is "
                f"{entry.verification.commercial_use.value}, not commercially allowed"
            ),
            category=PolicyCategory.MODEL_INGEST,
        )
    spdx_result = audit_spdx(entry.verification.spdx_id)
    if not spdx_result.ok:
        return LicenseAuditResult(
            verdict=spdx_result.verdict,
            reason=spdx_result.reason,
            detail=spdx_result.detail,
            category=PolicyCategory.MODEL_INGEST,
        )
    return _pass(
        detail=f"ingest entry {entry.display_name!r} ({entry.verification.spdx_id}) allowed",
        category=PolicyCategory.MODEL_INGEST,
    )


def get_model_ingest_entry(model_id: str) -> ModelIngestEntry:
    """Return the named ingest entry or raise ``LicensePolicyError`` (sr-006)."""
    result = audit_model_ingest(model_id)
    if not result.ok:
        raise LicensePolicyError(result)
    resolved = _resolve_model_key(model_id)
    entry = MODEL_INGEST_ENTRIES.get(resolved)
    if entry is None:
        # audit_model_ingest already returned non-ok on a miss; unreachable.
        raise LicensePolicyError(result)
    return entry


def audit_tooling_dependency(package_name: str) -> LicenseAuditResult:
    """Audit a TOOLING dependency (diagnostic; not training data).

    Non-string inputs FAIL ``invalid_row`` (BR-46) rather than raising.
    """
    type_err = _reject_non_string(
        package_name, field="package_name", category=PolicyCategory.TOOLING
    )
    if type_err is not None:
        return type_err
    if package_name is None or not str.strip(package_name):
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="tooling package_name is required",
            category=PolicyCategory.TOOLING,
        )
    text = str.strip(package_name)
    # FIR-7-B4-01 / BR-21: non-ASCII residue is invalid identity, not an
    # unregistered tooling package (do not imply the token is merely missing
    # from the allowlist). FIR-7-B5-04: Cf-format-only (canonical → "") is
    # the same fail-closed invalid_row treatment.
    folded = canonical(text)
    if folded is None:
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"package_name={text!r} {_invalid_identity_reason_clause(text)}"
            ),
            category=PolicyCategory.TOOLING,
        )
    if folded == "" or (
        _EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED
        and _canonical_lacks_identity(folded)
    ):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=(
                f"package_name={text!r} canonicalises to an empty identity; "
                "nonblank input with no identity token is fail-closed"
            ),
            category=PolicyCategory.TOOLING,
        )
    key = _normalize_token(package_name)
    # FIR-7-A3-01 / FIR-7-B3-01: denylist lookup uses the same separator/case
    # fold as row doors (via _package_denylist_hit). Bare PACKAGE_DENYLIST.get
    # on the lowercased token missed yolo-v8 / ultralytics-yolo and reported
    # unknown_source instead of denylisted_package.
    deny = _package_denylist_hit(text)
    if deny is not None:
        return _fail(
            deny.reason,
            detail=f"tooling package {package_name!r} is denylisted ({deny.spdx_id})",
            category=PolicyCategory.TOOLING,
        )
    entry = TOOLING_ALLOWLIST.get(key)
    if entry is None:
        entry = TOOLING_ALLOWLIST.get(key.replace("_", "-"))
    if entry is None:
        entry = TOOLING_ALLOWLIST.get(key.replace("-", "_"))
    if entry is None:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=f"tooling package {package_name!r} is not on the TOOLING allowlist",
            category=PolicyCategory.TOOLING,
        )
    return _pass(
        detail=(
            f"tooling package {entry.package_name!r} "
            f"({entry.verification.spdx_id}) is allowlisted"
        ),
        category=PolicyCategory.TOOLING,
    )


def is_tooling_allowlisted(package_name: str) -> bool:
    """Return True iff ``package_name`` is on the TOOLING allowlist."""
    return audit_tooling_dependency(package_name).ok


def audit_occluder_asset(asset: Mapping[str, Any]) -> LicenseAuditResult:
    """Gate an occluder-asset row at pack-build.

    Required: allowlisted license, positive ``photo_clearance`` (photo-release
    axis), and a non-empty **registered** source. Unknown sources FAIL (not
    only research names). Synthetic-lineage clearance is a separate floor
    obligation on ``clearance_decision`` (BR-65); this door ADDs photo-release
    and never waives the floor.

    Unconditional NC provenance (``derived_from_model``) is applied via
    :func:`_common_provenance_checks` before category-specific gates (BR-26).
    """
    if not isinstance(asset, Mapping):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail="occluder asset must be a mapping with license fields",
            category=PolicyCategory.OCCLUDER_ASSET,
        )

    cat = PolicyCategory.OCCLUDER_ASSET

    # BR-26: NC ban is unconditional across every entry point.
    common = _common_provenance_checks(asset, category=cat)
    if common is not None:
        return common

    license_result = _audit_row_licenses(asset, category=cat, required=True)
    if not license_result.ok:
        return LicenseAuditResult(
            verdict=license_result.verdict,
            reason=license_result.reason,
            detail=(
                license_result.detail
                if license_result.reason is RejectionReason.INVALID_ROW
                else f"occluder asset: {license_result.detail}"
            ),
            category=cat,
        )

    # BR-65: photo-release axis is independent of synthetic-lineage
    # clearance_decision. Single key ``photo_clearance`` only — no dual-shape
    # clearance / clearance_status overload (greenfield / NAME-03).
    if "photo_clearance" in asset:
        photo_raw = asset["photo_clearance"]
        if photo_raw is not None and not isinstance(photo_raw, str):
            return _fail(
                RejectionReason.INVALID_ROW,
                detail=(
                    "occluder asset photo_clearance must be a string, "
                    f"got {type(photo_raw).__name__}"
                ),
                category=cat,
            )
    else:
        photo_raw = None
    # FIR-7-RV-13: exact match on the canonical lower-case token only.
    # Case-fold drift (e.g. photo_clearance='CLEARED') is refused — same
    # fail-closed discipline as clearance_decision on the lineage axis.
    photo_token = _row_photo_clearance_token(asset)
    photo = photo_token if photo_token else ""
    if photo not in OCCLUDER_ALLOWED_CLEARANCES:
        return _fail(
            RejectionReason.UNCLEARED_OCCLUDER_ASSET,
            detail=(
                f"occluder asset source photo is uncleared "
                f"(photo_clearance={photo_raw!r}); pack-build refused"
            ),
            category=cat,
        )

    source = _source_of(asset)
    if not source:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="occluder asset requires a non-empty registered source",
            category=cat,
        )
    source_key = _normalize_token(source)
    if source_key not in {_normalize_token(s) for s in OCCLUDER_REGISTERED_SOURCES}:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=(
                f"occluder asset source {source!r} is not a registered "
                "occluder provenance source"
            ),
            category=cat,
        )

    return _pass(
        detail="occluder asset license fields cleared for pack-build",
        category=cat,
    )


def audit_synthetic_source(
    source_id: str,
    *,
    row_clearance: str | None = None,
) -> LicenseAuditResult:
    """Audit a synthetic-identity source clearance entry.

    When the registered entry carries a ``clearance_decision``, the caller must
    supply a matching ``row_clearance`` value drawn from the row's
    ``clearance_decision`` field (PROV-04 / BR-65) — not from photo-release
    vocabulary.

    Registry head resolution is exact against the import-time expanded
    synthetic id set (BR-36 / BR-50): ``dcface_v2``, ``dcface/v2``, and
    ``myorg/dcface`` resolve to the ``dcface`` clearance entry; ``dcface_evil``
    and ``not_dcface`` do not inherit clearance.

    Non-string inputs FAIL ``invalid_row`` (BR-46) — not a clearance outcome.
    """
    type_err = _reject_non_string(
        source_id, field="source_id", category=PolicyCategory.SYNTHETIC_SOURCE
    )
    if type_err is not None:
        return type_err
    if source_id is None or not str.strip(source_id):
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="synthetic source_id is required",
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    resolved = _resolve_registry_head(source_id, SYNTHETIC_SOURCE_ENTRIES)
    entry = (
        SYNTHETIC_SOURCE_ENTRIES.get(resolved) if resolved is not None else None
    )
    if entry is None:
        # Unknown synthetic sources default to pending (fail-closed).
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"synthetic source {source_id!r} has no clearance entry; "
                "defaults to PENDING-LEGAL-CLEARANCE"
            ),
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    if entry.verification.commercial_use is not CommercialUse.ALLOWED:
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"synthetic source {entry.source_id!r} is "
                f"{entry.verification.spdx_id} / "
                f"{entry.verification.commercial_use.value}"
            ),
            category=PolicyCategory.SYNTHETIC_SOURCE,
        )
    # PROV-04 / GATE-11: shared clearance comparison with the floor helper.
    clearance_fail = _audit_clearance_decision(
        entry,
        row_clearance=row_clearance,
        category=PolicyCategory.SYNTHETIC_SOURCE,
    )
    if clearance_fail is not None:
        return clearance_fail
    return _pass(
        detail=(
            f"synthetic source {entry.source_id!r} commercial-allowed "
            f"(clearance_decision="
            f"{entry.verification.clearance_decision or 'n/a'})"
        ),
        category=PolicyCategory.SYNTHETIC_SOURCE,
    )


def _synthetic_audit_targets(
    *,
    source: str,
    derived: str,
    category: PolicyCategory,
    has_generator_lineage: bool,
) -> list[str]:
    """Collect synthetic source ids that must be fail-closed audited.

    Routes to ``audit_synthetic_source`` when (BR-33 / BR-34):
      - **caller** category is SYNTHETIC_SOURCE (and source is not the
        operator-owned ``self-generated`` tag), or
      - generator_lineage is present (and source is not pure self-generated), or
      - source/derived resolves to a known SYNTHETIC_SOURCE_ENTRIES key
        (exact expanded-id resolve — BR-36 / BR-50), including the
        no-lineage path so clearance cannot be skipped by omitting lineage.

    Unregistered ``derived_from_model`` values that are **not** synthetic-registry
    heads are NOT routed here — they use ``UNREGISTERED_DERIVED_MODEL`` (or pass
    for operator-owned sources) instead of the synthetic clearance gate (BR-33).
    """
    targets: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        t = str.strip(token)
        if not t:
            return
        key = _normalize_token(t)
        if key in seen:
            return
        seen.add(key)
        targets.append(t)

    if category is PolicyCategory.SYNTHETIC_SOURCE and source:
        # BR-34: self-generated is an operator source, not a synthetic generator.
        if _normalize_token(source) != "self-generated":
            _add(source)

    if has_generator_lineage and source:
        # self-generated + lineage disclosure is informational (exemption path);
        # do not treat pure self-generated rows as synthetic generators.
        if _normalize_token(source) != "self-generated":
            _add(source)

    # BR-36: registry resolve on source/derived even without lineage, so
    # dcface_v2 cannot skip clearance by omitting generator_lineage.
    # BR-33: only actual synthetic-registry heads — not every unregistered
    # derived_from_model token.
    for token in (source, derived):
        if not token:
            continue
        if _resolve_registry_head(token, SYNTHETIC_SOURCE_ENTRIES) is not None:
            _add(token)

    return targets


def _audit_derived_registration(
    *,
    source: str,
    derived: str,
    category: PolicyCategory,
) -> LicenseAuditResult | None:
    """BR-33 / BR-66 / GATE-21 / GATE-23: unregistered derived registration.

    Returns a FAIL when ``derived`` is non-empty, not NC (already checked),
    not a registered model-ingest head, not an ALLOWED synthetic-registry
    head, and not in :data:`OPERATOR_OWNED_LINEAGE`.

    Exemption is keyed off the **lineage value** (operator-controlled registry),
    never off the door-dependent ``source`` field (GATE-21 / NAME-03). The
    ``source`` parameter is retained for call-site compatibility but is not
    consulted.

    Synthetic-registry heads are re-checked for ``commercial_use`` on every
    door (GATE-23): a FORBIDDEN / non-ALLOWED entry is not exempted merely
    because ``_synthetic_audit_targets`` would handle it on TRAINING_DATA.
    Returns ``None`` when no dedicated derived gate fires.
    """
    del source  # GATE-21: provenance namespace must not exempt registration.
    if not derived:
        return None
    # Registered commercial ingest head → fine.
    if _derived_ingest_key(derived) is not None:
        return None
    # Synthetic registry head — re-check commercial_use on every door (GATE-23).
    # Previously exempted unconditionally with "handled by _synthetic_audit_targets",
    # but that helper only runs on the TRAINING_DATA path; TOOLING / MODEL_INGEST
    # would silently PASS a FORBIDDEN synthetic not mirrored into NC_MODEL_IDS.
    resolved_synth = _resolve_registry_head(derived, SYNTHETIC_SOURCE_ENTRIES)
    if resolved_synth is not None:
        entry = SYNTHETIC_SOURCE_ENTRIES.get(resolved_synth)
        if entry is not None and entry.verification.commercial_use is CommercialUse.ALLOWED:
            return None
        label = entry.source_id if entry is not None else derived
        use = (
            entry.verification.commercial_use.value
            if entry is not None
            else "unknown"
        )
        spdx = (
            entry.verification.spdx_id
            if entry is not None
            else "PENDING-LEGAL-CLEARANCE"
        )
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"synthetic source {label!r} is {spdx} / {use}"
            ),
            category=category,
        )
    # GATE-21: operator-owned LINEAGE registry (not source provenance namespace).
    if _is_operator_owned_lineage(derived):
        return None
    return _fail(
        RejectionReason.UNREGISTERED_DERIVED_MODEL,
        detail=(
            f"derived_from_model={derived!r} is not a registered model-ingest "
            "or synthetic-source entry; register the model or remove the tag"
        ),
        category=category,
    )


def audit_provenance_row(
    row: Mapping[str, Any],
    *,
    category: PolicyCategory | None = None,
) -> LicenseAuditResult:
    """Full provenance-row audit for a training-data (or synthetic) manifest row.

    ``category`` is supplied by the **caller**, never trusted from the row body
    for gate selection (BR-34). A row-declared ``category`` is parsed once
    through ``PolicyCategory`` and rejected when unknown; it is validated but
    **non-dispatching**. Caller-supplied ``category`` *does* dispatch (BR-23):

      * ``OCCLUDER_ASSET``  → :func:`audit_occluder_asset`
      * ``MODEL_INGEST``    → :func:`audit_model_ingest`
      * ``SYNTHETIC_SOURCE``→ :func:`audit_synthetic_source`
      * ``TOOLING``         → :func:`audit_tooling_row`
      * ``TRAINING_DATA``   → training-data path below

    **Exactly one reason is reported per call** (short-circuit evaluation). A
    multi-fault row surfaces only the highest-precedence axis that fires —
    operators must not read a single reason as "the only fault" (GATE-09 /
    CLM-03). Floor precedence is documented on
    :func:`_common_provenance_checks`; door-specific gates run only after the
    floor returns ``None``.

    Checks on the training-data path, in order:
      0. structural field validation (types + required keys)
      1. shared floor via :func:`_common_provenance_checks` (six steps):
         derived type/taint → source type/taint → content-triggered
         clearance_decision (GATE-11 / BR-65) → package-identity denylist
         across package / package_name / model_id / source (FIR-7-RV-10) →
         unregistered derived registration (BR-66) → present licence values
      2. ``source`` against research-only / NC (NOT ``generator_lineage``)
         — redundant with floor source taint for non-empty sources; still
         enforces required-source
      3. every licence-bearing field with ``required=True`` (BR-35)
      4. fail-closed unknown source → PENDING-LEGAL-CLEARANCE (BR-22 / SECD-05)
      5. synthetic-source clearance for registry heads only (BR-33) — backstop
         for heads already covered by the floor clearance axis

    ``generator_lineage`` is informational and never causes research-source
    rejection by itself. Unregistered ``derived_from_model`` is mediated on
    the floor (BR-66), not as a training-data-only trailing gate.
    """
    if not isinstance(row, Mapping):
        raise LicensePolicyError(
            _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="provenance row must be a mapping",
                category=PolicyCategory.TRAINING_DATA,
            )
        )

    # Caller-owned category (default training_data). Row body cannot pick its gate.
    audit_category = category if category is not None else PolicyCategory.TRAINING_DATA
    if not isinstance(audit_category, PolicyCategory):
        return _fail(
            RejectionReason.INVALID_ROW,
            detail=f"category parameter must be PolicyCategory, got {audit_category!r}",
            category=PolicyCategory.TRAINING_DATA,
        )

    # Parse row-declared category once (BR-38). Validated, never used for dispatch.
    _declared_cat, cat_err = _parse_row_category(row, audit_category=audit_category)
    if cat_err is not None:
        return cat_err
    del _declared_cat  # non-dispatching by design (BR-34)

    # ------------------------------------------------------------------
    # BR-23: caller-supplied category dispatches to the matching gate.
    # ------------------------------------------------------------------
    if audit_category is PolicyCategory.OCCLUDER_ASSET:
        return audit_occluder_asset(row)

    if audit_category is PolicyCategory.TOOLING:
        return audit_tooling_row(row)

    if audit_category is PolicyCategory.MODEL_INGEST:
        # Prefer explicit model_id; fall back to source (row-shaped ingest).
        model_id = ""
        for key in ("model_id", "source", "package_name", "package"):
            raw = row.get(key)
            if isinstance(raw, str) and str.strip(raw):
                model_id = str.strip(raw)
                break
        common = _common_provenance_checks(row, category=PolicyCategory.MODEL_INGEST)
        if common is not None:
            return common
        return audit_model_ingest(model_id)

    if audit_category is PolicyCategory.SYNTHETIC_SOURCE:
        # Floor first (BR-68): non-string source/derived must fail invalid_row
        # before this door treats a non-string as a missing source.
        common = _common_provenance_checks(row, category=PolicyCategory.SYNTHETIC_SOURCE)
        if common is not None:
            return common
        source_raw = row.get("source")
        if not isinstance(source_raw, str) or not str.strip(source_raw):
            return _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="synthetic_source category requires a non-empty source field",
                category=PolicyCategory.SYNTHETIC_SOURCE,
            )
        row_clearance = _row_clearance_decision_token(row)
        synth = audit_synthetic_source(
            str.strip(source_raw), row_clearance=row_clearance
        )
        if synth.ok:
            # The floor skipped the source taint so this door could report its
            # more specific reason. Re-apply it to any PASS so the exemption can
            # never widen a verdict, even if a future registry entry is both
            # commercially ALLOWED and NC by pattern (SECD-05 fail closed).
            backstop = _source_axis_taint(
                str.strip(source_raw), category=PolicyCategory.SYNTHETIC_SOURCE
            )
            if backstop is not None:
                return backstop
        return synth

    # ------------------------------------------------------------------
    # TRAINING_DATA path (default)
    # ------------------------------------------------------------------

    # Structural validation — require derived_from_model KEY ('' is valid opt-out).
    _derived_val, derived_err = _require_string_field(
        row, "derived_from_model", required=True, category=audit_category
    )
    if derived_err is not None:
        return derived_err

    for key in ("source", "clearance_decision", "photo_clearance", "generator_lineage"):
        _val, field_err = _require_string_field(
            row, key, required=False, category=audit_category
        )
        if field_err is not None:
            return field_err
        del _val

    # Licence keys type-checked inside _audit_row_licenses.

    # BR-26: shared unconditional NC (and type) checks. Registration and
    # content-triggered clearance live on the floor (BR-65 / BR-66).
    common = _common_provenance_checks(row, category=audit_category)
    if common is not None:
        return common

    derived = (
        str.strip(_derived_val) if _derived_val is not None else ""
    )

    source = ""
    if "source" in row and isinstance(row["source"], str):
        source = _strip_source_token(row["source"])

    # Training-data audits always require source (row cannot waive via category).
    if not source:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail="training-data provenance row requires a source field",
            category=PolicyCategory.TRAINING_DATA,
        )
    source_result = audit_source(source)
    if not source_result.ok:
        return source_result

    # Licence before the fail-closed source allowlist so a pseudo-licence tag
    # (e.g. ``self-generated`` as SPDX — BR-25) is reported rather than masked
    # by the later PENDING-LEGAL-CLEARANCE default.
    #
    # BR-74 / GATE-11: when the floor's content-triggered clearance axis also
    # fires (synthetic-registry source/derived without a matching
    # clearance_decision token), that reason is reported *before* this licence
    # check — the floor short-circuits. BR-25's "licence before allowlist"
    # ordering still holds among the *door-local* gates below; it does not
    # outrank the floor's clearance / registration axes.
    license_result = _audit_row_licenses(
        row, category=audit_category, required=True
    )
    if not license_result.ok:
        return license_result

    # BR-22 / SECD-05: fail closed on the source axis. Research / NC already
    # handled by audit_source; remaining unknowns are PENDING-LEGAL-CLEARANCE
    # unless positively allowlisted or registered.
    if not _is_positive_or_registered_source(source):
        return _fail(
            RejectionReason.PENDING_LEGAL_CLEARANCE,
            detail=(
                f"source {source!r} is not on the positive allowlist or a "
                "registered ingest/synthetic entry; defaults to "
                "PENDING-LEGAL-CLEARANCE"
            ),
            category=PolicyCategory.TRAINING_DATA,
        )

    lineage_raw = row.get("generator_lineage")
    has_lineage = bool(
        str.strip(lineage_raw) if isinstance(lineage_raw, str) else False
    )
    # BR-34: only the *caller-supplied* category participates in synthetic
    # routing — never the row-declared value.
    row_clearance = _row_clearance_decision_token(row)

    for cand in _synthetic_audit_targets(
        source=source,
        derived=derived,
        category=audit_category,
        has_generator_lineage=has_lineage,
    ):
        synth_result = audit_synthetic_source(cand, row_clearance=row_clearance)
        if not synth_result.ok:
            # GATE-27 / rg-015: the synthetic backstop decides verdict/reason/
            # detail, but the returned category must remain the door the
            # *caller* asked for — never the helper's own SYNTHETIC_SOURCE stamp.
            return LicenseAuditResult(
                verdict=synth_result.verdict,
                reason=synth_result.reason,
                detail=synth_result.detail,
                category=audit_category,
            )

    # Unregistered derived is floor-mediated (BR-66); no door-local re-check.

    return _pass(
        detail="provenance row passes license policy",
        category=audit_category,
    )


def audit_tooling_row(row: Mapping[str, Any]) -> LicenseAuditResult:
    """Audit a tooling dependency row (caller-owned TOOLING category).

    Ordering (BR-24 / GATE-05 / GATE-22) — package denylist cannot be masked
    by a row-author-controlled self-declaration on any axis:

      1. Floor taint + content-triggered clearance + package-identity denylist
         via :func:`_floor_taint_and_clearance` (``derived_from_model``
         NC/research taint, ``source`` taint, synthetic clearance, then
         package-identity denylist as floor step 4 / FIR-7-RV-10). Registration
         and licence halves are deferred so neither can mask the package reason.
      2. Resolve a package identifier from ``package`` / ``package_name`` /
         ``source`` and run :func:`audit_tooling_dependency` **before**
         registration and any row-declared SPDX check so a self-declared
         licence **or** a junk ``derived_from_model`` tag cannot launder a
         denylisted package (BR-24 / GATE-22). This door-local denylist /
         allowlist check is **shadow coverage** of the floor package-identity
         denylist (step 1 / floor step 4) for the first-wins primary field —
         the floor already rejects denylisted tokens in any secondary identity
         field (FIR-7-D2-02).
      3. Unregistered ``derived_from_model`` registration via
         :func:`_floor_registration` (BR-66 / GATE-21).
      4. Present row-declared licence values via :func:`_floor_licenses`
         (required=False) — still enforced, just after the package gate.

    Missing package identifier fails closed. The complete floor composition
    :func:`_common_provenance_checks` is not used here because registration
    and licence halves must interleave *after* the package gate; every half
    still runs (BR-69 / ARCH-13).
    """
    if not isinstance(row, Mapping):
        raise LicensePolicyError(
            _fail(
                RejectionReason.UNKNOWN_SOURCE,
                detail="tooling row must be a mapping",
                category=PolicyCategory.TOOLING,
            )
        )

    cat = PolicyCategory.TOOLING

    # Taint + clearance + floor step 4 (`_floor_package_identity_denylist`).
    # GATE-22 is that floor step, not the door-local first-wins loop below:
    # a denylisted token in any identity field (including `model_id`, which
    # the door-local loop never sees) must report denylisted_package before
    # registration or row SPDX. Inverting the door-local order leaves GATE-22
    # green because step 4 already fired. BR-69: call each half explicitly.
    common = _floor_taint_and_clearance(row, category=cat)
    if common is not None:
        return common

    package = ""
    for key in ("package", "package_name", "source"):
        raw = row.get(key)
        if isinstance(raw, str) and str.strip(raw):
            package = str.strip(raw)
            break

    if not package:
        return _fail(
            RejectionReason.UNKNOWN_SOURCE,
            detail=(
                "tooling row requires a package identifier "
                "(package / package_name / source)"
            ),
            category=cat,
        )

    # Authoritative package gate — denylist / allowlist pin wins over both
    # registration (GATE-22) and row SPDX (GATE-05 / BR-24).
    dep_result = audit_tooling_dependency(package)
    if not dep_result.ok:
        return dep_result

    # Registration after package so a junk lineage tag cannot mask AGPL
    # (GATE-22). Same predicate as the complete floor's registration axis.
    unreg = _floor_registration(row, category=cat)
    if unreg is not None:
        return unreg

    # Row-declared licence still fails closed when present, but only after the
    # package reason has had its chance to surface (GATE-05). Same half as the
    # complete floor's licence axis (BR-69).
    license_hit = _floor_licenses(row, category=cat)
    if license_hit is not None:
        return license_hit

    return _pass(
        detail=dep_result.detail,
        category=cat,
    )


def require_pass(result: LicenseAuditResult) -> LicenseAuditResult:
    """Raise ``LicensePolicyError`` when ``result`` is not a PASS (sr-006)."""
    if not result.ok:
        raise LicensePolicyError(result)
    return result


# Convenience: ordered required named ingest display names for fixtures.
REQUIRED_DETECTOR_AB_DISPLAY_NAMES: tuple[str, ...] = (
    "MediaPipe BlazeFace",
    "Paddle BlazeFace-FPN-SSH",
)
REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES: tuple[str, ...] = (
    "RT-DETR",
    "D-FINE",
    "PP-PicoDet",
)
REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = (
    *REQUIRED_DETECTOR_AB_DISPLAY_NAMES,
    *REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES,
)
