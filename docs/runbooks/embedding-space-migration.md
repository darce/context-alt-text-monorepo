# Runbook: Embedding-space partition after a model_id flip

**Why**: scans stamp each face row with an `embedding_model` (the active
`model_id`). Clustering and label inference filter by that id (FIR23-01), so
rows from a prior space silently drop out of nearest-neighbor work once the
active stamp changes. This branch adds a co-located partition alarm on
`/ready`, but **no re-embed or backfill tooling exists today**. When the alarm
fires, nothing fails loudly and there is no automated way out — this runbook
is the operator half.

**When to use**: `/ready` (or `/health/detailed`) reports the `embedding_model`
check as **DEGRADED** with detail mentioning `embedding space partition`, or a
partition alarm / review finding points here.

Related: [ADR-ARCH-07](../adrs/ADR-ARCH-07-opencv-pin-for-face-pipeline-reference.md)
(OpenCV pin + accepted risks), FIR-4 face_pipeline profile,
`recognition/application/health.py` (`check_active_embedding_model`).

## 1. Read the alarm (it does NOT fail a deploy)

The partition detector lives in the readiness probe chain:

```text
GET /ready
→ checks[].name == "embedding_model"
→ status DEGRADED when active model_id matches zero persisted rows
```

Example detail shape (values vary by build and corpus):

```text
active=opencv-sface+cv5.0.0/ort1.28@128d/l2/cosine matches no persisted embedding_model
(persisted=[opencv-sface@128d/l2/cosine, insightface-buffalo_l@512d/l2/cosine]);
embedding space partition
```

or, on the deployed default profile after an insightface id flip that *does*
partition:

```text
active=insightface-buffalo_l@512d/l2/cosine matches no persisted embedding_model
(persisted=[…prior stamps…]); embedding space partition
```

**Deploy impact:**

- **DEGRADED does not fail a deploy.** `/ready` returns **HTTP 200** for both
  OK and DEGRADED. Only **UNHEALTHY** maps to **503** (load balancers pull the
  pod). A partition therefore leaves traffic green while clustering and label
  inference silently ignore the orphaned space via the FIR23-01 filter.
- Confirm with `GET /ready` or auth-gated `GET /health/detailed` — look at the
  `embedding_model` check object, not the top-level HTTP code alone.

Fresh / empty `media_identities` is **not** a partition (`persisted=none` →
OK). A resolve failure (empty / unresolved active id) is **UNHEALTHY**, not
this runbook.

## 2. Count orphaned rows per space

Connect as the app role (or superuser) to the identity DB and run:

```sql
SELECT embedding_model, count(*)
FROM media_identities
GROUP BY 1
ORDER BY 2 DESC;
```

Save the output. Every distinct `embedding_model` that is not the active
`model_id` for the running build is an orphaned space (invisible to clustering
and label inference under FIR23-01). Optional per-tenant drill-down:

```sql
SELECT tenant_id, embedding_model, count(*)
FROM media_identities
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
```

## 3. Determine the active model_id for the running build

The active stamp is profile-selected (`active_embedding_model_id()`):

| `RECOGNITION_FACE_PIPELINE_PROFILE` | Active space (illustrative) |
| --- | --- |
| `insightface` (**production default**) | `insightface-buffalo_l@512d/l2/cosine` — **no** OpenCV space token |
| `face_pipeline` | `opencv-sface+{space_token}@128d/l2/cosine` where `space_token` is OpenCV full version + ORT major.minor (e.g. `cv5.0.0/ort1.28`) |
| `runtime_mode=test` | `stub-detector@test` |

**Ground truth on a live process** (prefer this over guessing from docs):

1. Read the `embedding_model` check detail on `/ready` / `/health/detailed` —
   the `active=…` prefix **is** the resolved id.
2. Or inspect env + pins on the running image:
   - `RECOGNITION_FACE_PIPELINE_PROFILE` (default `insightface`)
   - for face_pipeline: OpenCV / ORT versions that feed
     `NumericRuntimeFingerprint.space_token` (see
     `recognition/infrastructure/face_pipeline/provenance.py` and
     `sface_embedding_model_manifest()`).

**CVUP-1 note:** the SFace bare stamp `opencv-sface@128d/l2/cosine` is
historical (FIR-4). Live face_pipeline rows stamp the space-token form. The
insightface id is unchanged by the OpenCV 5 pin and does **not** partition on
this bump alone — see ADR-ARCH-07 accepted risk (incumbent drift unmeasured).

## 4. Operator decision: re-embed or abandon

There is **no backfill / re-embed script in the repo today**. Do not invent a
one-liner from scan workers or SQL UPDATEs of `embedding` / `embedding_model`
— those columns are only honest when produced by the active detector+embedder
path. Choose deliberately:

### Option A — Re-embed the orphaned corpus

Keep the rows' media, re-run detection+embedding under the **active** profile
so new rows stamp the current `model_id` and re-enter clustering.

**What would have to be built (not present today):**

1. A tenant-scoped job that selects `media_identities` (or distinct
   `media_id`s) where `embedding_model <> <active_model_id>`.
2. Re-fetch media bytes and re-run the active face pipeline (same path as
   scan), writing new embeddings + the active `model_id`.
3. A policy for old rows: delete, soft-orphan, or leave for audit — and how
   cluster membership / representatives / suggestions are invalidated or
   rebuilt after the rewrite.
4. A verification step re-running §2 until orphaned counts are zero (or an
   accepted residual) and `/ready` `embedding_model` returns OK.

Until that tooling exists, the only practical re-embed is a **full rescan** of
affected media through the normal scan surface (operator-driven, no bulk
helper), followed by re-clustering — cost and downtime are operator-estimated
from §2 counts.

### Option B — Abandon the orphaned space

Accept that prior-space rows stay in `media_identities` but never participate
in clustering or label inference under the FIR23-01 filter. Document the
abandoned `embedding_model` values and the tenant/media scope. Optional later
cleanup is a deliberate DELETE of those rows (not covered here; requires its
own data-loss sign-off).

### Decision record

Record which option was chosen, the §2 counts, the active `model_id`, and any
residual orphaned spaces. Partition DEGRADED remains until either the active
id matches at least one persisted row or the table has no model_id rows.

## 5. What this runbook does not cover

- **No automated remediation.** There is no `scripts/` entry, migrate command,
  or admin endpoint that re-embeds by space.
- **Incumbent (insightface) OpenCV drift** does not flip `model_id` and will
  **not** raise this alarm; vectors may still re-baseline under a silent pin
  bump — see ADR-ARCH-07 accepted risk. This runbook cannot detect that class
  of drift.
- Schema / dimension flips (`PGVECTOR_DIM`) are a separate fail-closed path
  (vector typmod check → UNHEALTHY) and are not solved by re-stamping
  `embedding_model` alone.
