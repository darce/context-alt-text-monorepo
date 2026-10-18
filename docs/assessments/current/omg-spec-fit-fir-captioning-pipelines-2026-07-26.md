# OMG Specification Fit — FIR and Captioning Pipelines

> **Metadata**
>
> - **Date**: 2026-07-26
> - **Project**: `apps/prototype-description-service`
> - **Companion to**: `agentic-protocol-monorepo/docs/assessments/omg-specification-suitability-evaluation-2026-07-26.md` and `.../omg-knowledge-vocabulary-specs-canon-fit-2026-07-26.md`
> - **Canon**: heuristics-canon `v0.15.0-22-g6193446`
> - **Status**: evaluation only — no code changed, no gate decision made

## Question

As part of a three-repo evaluation of OMG specifications (BPMN, DMN, DPROD, MVF,
KDM, UAF, and ~12 others), does any of them make the **FIR** (face identity
recognition) or **captioning** pipelines more robust?

## Verdict

**One adoption, modest in scope: SPDX 3.0 for model and dataset lineage.**
Everything else is a reject.

The reason is not that the specs are bad — it is that the eval harness **already
implements** the substance a data-product or decision standard would sell you, in
a lighter and better-typed form. Adopting an RDF/SHACL or XML modelling stack on
top would mean maintaining the same contract twice, which is the defect
**[REF-26]** names: *duplication of intent across representations*.

---

## 1. What the pipeline already has

This section is the load-bearing part of the verdict, so it is specific.

`scripts/eval_harness/` already provides, in code:

| Capability a standard would sell | Where it already exists |
|---|---|
| Versioned schema identity | `schema.py` — `SCHEMA = "acx-eval/v1"` |
| Document-kind discrimination | `DocKind ∈ {run_record, face_run_record, report}`, so a consumer "can tell them apart instead of guessing from which keys happen to be present" |
| Structural validation / closed world | `face_run_record.py` — Pydantic models with `extra="forbid"`, `min_length`/`max_length` bounds, field validators |
| Per-artifact model provenance | `FaceRunItem.model_id`, `FaceRunItem.embedding_dim`, cited to `PROV-01`/`PROV-06` |
| No invented dimensions | `resolve_sface_embedding_dim` resolves the embedding dim **from the producer**, fail-closed — never a hardcoded literal (`rg-015`) |
| Pinned inter-stage contract | `calibrate_face_thresholds.py` consumes `REPORT_KIND = "face_bakeoff"` schema v1 as a pure artifact→artifact CLI |
| Explicit statistical protocol | pair-level **subject-disjoint K-fold** with protocol disclosure emitted into the artifact (`CAL-07`) |
| Honesty about underpowered results | slices below their n-floor are marked `DIRECTIONAL ONLY` and barred from the gate proposal |
| Determinism guarantee | `--check-determinism` — bit-identical report JSON/MD on re-score |
| License isolation as an enforced boundary | two-layer negative-import gate: module import-graph check **plus** source-level symbol check |

That last row deserves emphasis, because it is the strongest argument against
adopting a modelling standard here. The buffalo_l reference leg is
**non-commercially-licensed**, and the rule that it must never touch the
production path is enforced by *executable tests* — a module-graph check for
`face_pass`/`seed_roster`/`remote_client`/`recognition.infrastructure.embeddings`,
**and** a symbol-level check for `RemoteSceneClient`/`media_identities`/
`InsightFaceAdapter`, precisely because "a bare symbol name in a module-only graph
check never matches."

That is **[ARCH-13]** architecture hoisting done properly: the property is enforced
structurally, and the always-green trap was anticipated. No metamodel improves on
a test that fails closed.

---

## 2. The specs, assessed against that baseline

### DPROD (Data Product) — reject

DPROD (`ptc/25-02-01`, 1.0 beta) describes itself as "a profile of the Data Catalog
(DCAT) Vocabulary, designed to describe Data Products" — an RDF/SHACL vocabulary for
**data-mesh cataloguing**: products, ports, owners and policies, so an organisation
can discover and govern them across teams.

The claim that it does not reach inside a pipeline is checkable rather than
rhetorical. Its shapes file `dprod-shapes.ttl` defines exactly eight `NodeShape`s:

```
DataProductShape          DataServiceShape
DatasetShape              DistributionShape
DataProductLifecycleStatusShape             ProtocolShape
InformationSensitivityClassificationShape   SecuritySchemaTypeShape
```

with property shapes for `dataProductOwner`, `domain`, `purpose`, `lifecycleStatus`,
`inputPort`/`outputPort`, `inputDataset`/`outputDataset`, `hasPolicy`, `endpointURL`,
`protocol`, `format` and `conformsTo`.

Read that against what this harness produces: there is no shape, class or property
for a run record, a `model_id`, an `embedding_dim`, a false-merge rate, a
calibration fold, an n-floor, or a license boundary. DPROD's unit of concern is an
organisationally visible data product — who owns it, how you reach it, what policy
governs access. It stops at the pipeline's edge by design.

At best it could catalogue *published* eval bundles as `Dataset`/`Distribution`. It
cannot express their quality contracts. Expressing the existing Pydantic contracts
as SHACL shapes would add a second serialisation of the same facts, with `pySHACL`
in the loop, validating later than the `extra="forbid"` models already do at the
point of construction — and with nothing forcing the second edit when a field is
added.

*(Generic RDF tooling — `rdflib`, `pySHACL` — can consume DPROD without any
OMG-specific library, so its adoption cost is genuinely lower than the XMI-based
specs. It is still not worth paying here.)*

### DMN (Decision Model and Notation) — borrow the concept only

DMN's decision table with an explicit **hit policy** is a genuinely good idea for
any multi-key routing decision. In this repo the closest analogue is the FIR-6
operator gate: a decision over per-stratum thresholds, floor status, and slice
outcomes.

But the gate is deliberately **operator-owned** — FIR-5 *proposes* numbers and
FIR-6 *decides* (`RLSE-02`/`RLSE-03`). A DMN engine would encode an automatic
decision where the design intentionally requires a human one. Borrow the
completeness/hit-policy discipline if the threshold logic grows; do not adopt
DMN XML or FEEL.

### API4KP (APIs for Knowledge Platforms) — reject

`formal/24-01-10`, v1.0. Standardises APIs for *knowledge* platforms: knowledge-asset
and knowledge-artifact repositories, transrepresentation, knowledge-base
construction, and reasoning.

Worth naming the trap explicitly, because a keyword search will surface it: its IDL
artifact is called **`api.inference.idl`** — and that is **logical/symbolic
inference over a knowledge base**, not neural model inference. Nothing in API4KP
touches an ONNX embedder, a bake-off, or a calibration protocol.

### BPMN / CMMN / PPMN / UAF / KDM and the CORBA-era services — reject

None touch this pipeline. Worth flagging one trap for future searches: several
OMG acronyms that *sound* relevant are 2000–2002 CORBA object services —
**LFCYC** is "Life Cycle Service" (object create/delete/copy/move), **AVSTR** is
"Audio/Video Streams", **COLL** is "Collection Service". `AVSTR` in particular
will surface in any media-related keyword search and is unrelated to captioning.

**PPMN** (Pedigree and Provenance Model and Notation, `dtc/24-09-07`) is the one
near-miss by name — it models lineage, custody and ownership — but it targets
supply-chain and records management, sits at beta, and has no tooling ecosystem
that competes with SPDX for this use case.

---

## 3. The one adoption: SPDX 3.0

**System Package Data Exchange, `formal/24-11-01`, version 3.0 (March 2025).**

Verified directly from the OMG page: SPDX 3.0 defines "an open standard for
communicating bill of materials (BOM) information for different topic areas," and
its metadata scope **explicitly includes "artificial intelligence (AI) models" and
"datasets"** alongside conventional software composition, licensing, build
information, and "relationships between system elements."

### The gap it fills

The harness carries `model_id` and `embedding_dim` inside each run record — good
provenance *for the artifact*. What it does not carry, in any machine-readable
form, is the **lineage of the models and corpora themselves**:

- which ONNX weights file (YuNet, SFace) produced a given embedding set, at what
  revision and checksum
- which corpus/manifest revision (`Golden-150`, `bakeoff10`, `corpus646`) a report
  was scored over
- **which license governs each of those inputs** — the fact that currently makes
  buffalo_l a hard boundary

That last point is why this is worth doing rather than a nice-to-have. The
license-isolation rule is enforced in tests, but the *underlying license facts*
live in prose (task plans, `pyproject.toml` extras, and documents like this one).
The enforcement is executable; the justification is not. SPDX is the standard home
for exactly those facts, and its AI/dataset profile is built for the
model-plus-dataset case.

### Why SPDX and not an OMG modelling stack

SPDX is the only spec in this entire evaluation with a **mature, maintained
open-source ecosystem that requires no OMG modelling machinery** — real Python
tooling, real adoption, JSON/tag-value serialisations. Every other candidate would
require standing up a metamodel parser and a model-to-runtime bridge.

### Suggested scope (deliberately small)

1. Emit an SPDX 3.0 document alongside each bake-off report describing: the two
   legs' model artifacts (with checksums and licenses), the corpus manifest
   revision, and the `Relationship` edges between them and the report.
2. Assert in a test that the buffalo_l leg's SPDX entry carries its
   non-commercial license and that no such entry appears in any production-path
   document — making the license boundary *checkable from the artifact*, not only
   from the import graph.
3. Do **not** attempt repo-wide SBOM coverage as part of this; that is a separate
   supply-chain concern with a different owner.

This should be scoped as its own slice, sequenced behind the existing FIR work —
it is **not** a prerequisite for FIR-6.

---

## 4. What not to do

- Do not express the eval schemas as SHACL/RDF alongside the Pydantic models.
- Do not introduce a decision engine for the FIR-6 gate; the gate is
  operator-owned by design.
- Do not treat SPDX adoption as a reason to touch the negative-import gate. That
  gate is the enforcement; SPDX documents the facts it enforces. Keep both.

---

## Appendix — Method and verification

The spec research ran as **remote grok-4.5 lanes** in web-enabled OCI-VM sandboxes
(seven dispatched, six usable — one was killed by output truncation and was re-run
as two narrower lanes), each under an anti-fabrication gate requiring real document
numbers and artifact filenames. Their claims were verified independently rather
than trusted:

- Fetched `omg.org/spec/SPDX`, `/SACM`, `/LFCYC`, `/ATLAS`, `/PPMN`, `/KDM`
  directly — full names, document numbers, versions and dates matched exactly.
- Parsed the four BPMN CMOF files with `xml.etree` and found two class-count
  errors in the lane's report (documented in the companion assessment).
- A duplicate lane run on an identical brief agreed on 7/8 document numbers and
  8/8 verdicts.

The DPROD verdict specifically was verified from the artifact rather than from
prose: `dprod-shapes.ttl` was fetched directly (15,375 bytes) and its `NodeShape`
subjects enumerated — 8/8 as reported by the lane, no extras and no omissions,
with `owl:versionInfo "OMG Request For Comments Errata 2"` and
`dct:modified "2024-08-31"` matching. Across the two vocabulary/knowledge lanes,
**no fabricated document number or filename was found**.

**Local grounding:** `scripts/eval_harness/{schema.py, face_run_record.py,
calibrate_face_thresholds.py, report.py, manifest.py}`, and the FIR-5 task plan
`docs/tasks/fir/FIR-5-bakeoff-harness-extension-task-plan.md`.

**Limit:** the assessments here rest on landing-page metadata and the normative RDF
artifacts, not full readings of the specification PDFs. That is sufficient to
reject — DPROD's shapes file is decisive on its own — but would not be sufficient
to adopt. The wider triage, including the specs that touch only the WorkBay repo,
is in the companion documents named at the top of this note.
