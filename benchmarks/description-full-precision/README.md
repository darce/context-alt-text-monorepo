# Prospective full-precision RAW-GENERATION v1

This CLI prepares pinned raw-generation contracts and explicitly executes one
model / extraction-treatment / image-chunk operation. Preparation and
`execute --dry-run` create artifacts with **zero POSTs and no keyfile read**.
They do not create an authentication bypass. Actual execution uses the genuine
service's strict descriptor-based keyfile loader (owner, regular file, mode
0400/0600, no symlink, bounded printable credential).

This is a new prospective collection contract. Native, runtime, model-serving,
served-weight and quality evidence remains `UNOBSERVED`. A requested or echoed
model alias is not proof of served weights. There is no human score, quality
winner, speed-based selection, promotion, calibration requirement, issuer or
approval callback. Quality consumers must separately adopt the new producer
source identity. Historical Q4 and native contracts retain their original
meaning. BIND/CACHE adversarial findings remain deferred.

## Behavior and lineage

`raw_generation.py` uses the actual current planner's `load_inputs` and
`cohort_ids` with its unchanged current-input v2 manifest. This verifies the
historical whole-tree parent and the effective 482-file genuine service
manifest without resealing historical sources. It does not invoke the old
public preparer or regenerate its native A-template. Source/root paths, corpus
path map, endpoint bindings and keyfile path are explicit arguments.

| Input | Exact SHA256 |
| --- | --- |
| selected-models.json | `76ba20901ab36ad225e86cbd1a121d4cb275dcde51a0e13b0ec436b2657e0f5e` |
| dispatch audit input-manifest.json | `e1531811f839409cc269fbf4a529f895ec2731e0dc082eafc282c0037306d80a` |
| current factorial planner | `f89a76b34b4104d1f345a6ab2b576d597bbda2f9489775ddfa2846c994bbe617` |
| current-input-manifest.v2.json | `2eab8102506bce422eeb8d7d5f780402f838e65aab4d308fc8df9d08876c0138` |
| original extraction_paired_client.py | `5c89754916884fc3448e00067e40afab4fd0f850bb430200a7a74c82bafc1838` |
| extraction_paired_client_v2.py (new) | `ad5dd57c743f44c440634e54a9715ed4976e6bde621a1ae38fcbd2d9a69b1991` |
| qualified bakeoff.py | `87c58a41cb0a9421605dd9adf80aaee91bdde7eb5b6e54c39cde540f97e3ca66` |
| strict extraction facts schema | `89b958d54e9131cc49b4c4550064914854bc5d7c04f744542fa4b06cdbabe6e5` |
| active120 R2 corpus manifest | `05fe1b169be22c6a8e25d97769ef9aeb143dea1a5ffa7d0b09a48b25cc444a63` |
| R2 original-038 image | `710a6798653ef868338136da63e2c176e892d73bac342e395bf0df640e70022e` |

The producer v2 is a source copy of the exact genuine parent at
`/home/gate/bakeoff-next-model-causal-r4-370182cb56ef4b8a93da5e3fa67710e4/references/producer/extraction_paired_client.py`.
Its changes are the version/docstring, recorded timeout, and bounded timeout
selection: integer **60..1800 seconds, default 600**. The parent's 60-second
default is unqualified for the recorded BF16 80.34-second / 128-token smoke.
No prompt, parser, image/hash validation, redaction, atomic per-item persistence,
zero-retry behavior or response-model stop guard was replaced. The genuine
loader and real service builders are used; no fabricated service modules or
builders are installed. Contract lineage pins both old and new producers,
all effective service inputs and this CLI's source.

The selected profiles are copied in full, including every GGUF filename,
size/hash, repository revision and runtime profile hash. Both require runtime
image `sha256:fc26b60b30836e5a12fdb28823a3d4bda984c9386a4b04200c78e5a5150067fb`,
context 8192, image token cap 1536, parallel 1 and f16 KV.

| Profile | Exact revision | Offload |
| --- | --- | --- |
| qwen38-bf16 | `4ca720788d1e01f1bff70c033e0d0028fd02e502` | `--n-gpu-layers 18` |
| incumbent-f16 | `f54435e6cc31258f04b0969105c3f6badb197931` | `--n-gpu-layers all --cpu-moe` |

Original v3 budgets remain: extraction 1536 tokens, writing 512 tokens,
temperature/seed 0, no thinking, empty context and identity lists. One E0 or
E1 run performs one extraction and passes the same returned raw facts and
original pixels to W0 and W1. Actual writer-message hashes are recorded only
after the facts arrive; preparation leaves them `UNOBSERVED`.

| Cohort | Planned bundles | Nominal completion POSTs | Operations |
| --- | ---: | ---: | ---: |
| integration2 | 16 | 24 | 4 × 2 images |
| exploratory20 | 160 | 240 | 4 × 20 images |
| full120 | 960 | 1440 | 24 × 20 images |

All four E/W arms are included for both profiles. Full120 chunks support both
E arms under this new contract. Selection uses frozen metadata, including the
R2 original-038 correction; no images are synthesized or relabeled. An explicit
JSON image map maps frozen IDs to absolute image paths. Execution retains the
frozen digest check, so relocation never changes source identity.

Execution selects one operation and never switches models or manages GPU
lifecycle/resource admission. The operator must separately ensure one model
resident at a time. Output files are exclusive per attempt. The producer's
atomic raw artifact retains failures; the operation report retains every
planned writer cell as success, failed or unattempted. Upstream extraction
failure marks both dependent cells failed. Later images after model mismatch
remain unattempted. Client pass records include circuit-open failures and can
exceed actual transport POSTs; they are reported separately. Collection success
means parsed raw outputs only, with no quality or serving qualification.

## Usage

Use `python3 -B` from the existing warm dependency environment. Do not use the
system `python` shim, which lacks the genuine service's cv2 dependency. No
installation is necessary. Set these explicit paths for the supplied packet:

```bash
REFS=/home/gate/bakeoff-next-model-factorial-r4-01857695152440beb366dba0c6d9159f/references
PACKET=/home/gate/description-dispatch-audit-inputs-20261023T2235
IMMUTABLE=/home/gate/bakeoff-next-model-full-precision-profiles-r1-8d6dcf01f4764c0b9eb1576c238510ac/references
ORIGINAL=/home/gate/bakeoff-next-model-causal-r4-370182cb56ef4b8a93da5e3fa67710e4/references/producer/extraction_paired_client.py
CLI=benchmarks/description-full-precision/raw_generation.py
```

Supply `bindings.json` with both selected profile keys. Each value has exactly
`endpoint`, `model_id`, `model_version`, `revision`. `model_version` must equal
the selected profile name and `revision` must equal the table above. Endpoints
are root HTTP(S) URLs without embedded credentials. `model_id` is an explicit
request/response label, not an attestation. Provide `images.json` as an object
of frozen image IDs to absolute existing corpus paths. Preparation does not
open the images or keyfile.

```bash
python3 -B "$CLI" prepare \
  --references "$REFS" --service "$REFS/service" \
  --planner "$PACKET/generation/FACTORIAL-R4/extraction_factorial_plan.py" \
  --input-manifest "$PACKET/generation/FACTORIAL-R4/fixtures/factorial/current-input-manifest.v2.json" \
  --original-producer "$ORIGINAL" --canon-root "$REFS/canon" \
  --loader "$REFS/baseline/depiction_lexicon.py" \
  --selected-models "$IMMUTABLE/selected-models.json" \
  --image-map "$OUTPUT/images.json" --bindings "$OUTPUT/bindings.json" \
  --keyfile /absolute/operator/keyfile --size 2 --timeout 600 \
  --out "$OUTPUT/raw-contract.json"
```

Record `contract_sha256` from stdout. Every execution verifies that file pin,
strict JSON, all current source/input pins, and deterministic reconstruction of
the entire contract. Changing timeout, bindings, paths or sources requires a
new prospective contract; no silent reseal occurs. List operation IDs from
`operations[].operation_id`, then prepare an execution without any POST:

```bash
python3 -B "$CLI" execute --dry-run \
  --contract "$OUTPUT/raw-contract.json" --contract-sha256 "$CONTRACT_SHA256" \
  --operation-id qwen38-bf16/E0/000 \
  --endpoint "$EXPLICIT_ENDPOINT" --model-id "$EXPLICIT_MODEL_ID" \
  --model-version qwen38-bf16 --revision 4ca720788d1e01f1bff70c033e0d0028fd02e502 \
  --keyfile /absolute/operator/keyfile --out "$OUTPUT/execution-preparation.json"
```

Actual collection uses that same command with `--dry-run` omitted and a fresh
output filename. **No actual collection was run in this implementation lane.**
Exit codes: 0 prepared/dry-run/fully parsed collection; 1 incomplete raw
collection with failed/unattempted cells retained; 2 validation/refusal.

## Offline verification

The test runner takes explicit source/evidence paths and writes all fixtures
and logs to a fresh OUTPUT directory. It blocks sockets, service/process
launches, .env files and model artifacts. Only a
public nonsecret fixture key passes through the genuine strict keyfile loader.
The corpus pixels are real; the model labels and all completions are fixtures.
The source audit fixtures are prior art, not inference or native approval.

```bash
timeout 900 python3 -B benchmarks/description-full-precision/test_raw_generation.py \
  --output "$OUTPUT/offline-new" --packet "$PACKET" --references "$REFS" \
  --original-producer "$ORIGINAL" --immutable "$IMMUTABLE" \
  --startup /home/gate/description-gpu-start-inputs-20261023T2155 \
  --audit-fixtures /home/gate/bakeoff-next-model-dispatch-audit-generation-r1-0476069059c94c78a39fea9ea72a1509/output/audit-group-b \
  --r2-image /home/gate/bakeoff-rounds-20261017-inputs/results/LEXICON-AB-FROZEN-120-R2/corpus-revisions/r2/original-038.jpg -v \
  > "$OUTPUT/offline-new.log" 2>&1
```

Checks verify the supplied audit manifest and both exact AST codemaps; reproduce
old size20/E0 refusal, Q4 defaults and unconditional main exit 2; compare the
original 60-second producer against the new 600-second producer with a
simulated 80.34-second deadline; exercise invalid profiles/types/timeouts,
contract tampering and strict keyfile refusal; and run the complete two-image,
two-model, four-arm grid (24 actual MockTransport requests). Actual sent writer
messages are independently rebuilt from returned facts and compared to the
recorded hashes. Strict-schema failures, invalid writers, wrong response models
and the real three-strike breaker retain the planned cells.

Canon v0.26.2/current Principles 1/2/9/15/18, CARD-09 and CARD-11 inform the
bounded calls/data, causal regression tests, lineage, fixed denominators and
strict contracts here (RES-02/05, TEST-15, GRPH-14/32, FM-04). Original distilled
Release It!, Pragmatic Programmer and Building Knowledge Graphs were read along
with the corrected accounting/scoring/causal source boundary. Those consumers'
old source pins remain unchanged and do not adopt producer v2.

Remaining execution dependencies: genuine warm service imports; original
hash-matching corpus bytes; the separately configured strict keyfile; an
explicit endpoint and exact request labels; and separately observed full v3
runtime/context fit, serving/weight identity and external model residency.
