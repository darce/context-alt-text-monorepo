# Offline implementation evidence — 2026-10-23

Base workspace commit: `ec0a6c540f6c572eb42ac5cfdd60be039edbdc65`.
Only this directory contains implementation source/tests/docs.

Final source SHA256:

| File | SHA256 |
| --- | --- |
| raw_generation.py | `65899bb0c75984327fa3148a9559ddf9635d07154246e60c925cc49491d9564d` |
| extraction_paired_client_v2.py | `ad5dd57c743f44c440634e54a9715ed4976e6bde621a1ae38fcbd2d9a69b1991` |
| test_raw_generation.py | `914e99072dfd78e326ebcfedc92c58c99529435eb0518ae2573850daf9e1b1f3` |

Original producer SHA `5c89754916884fc3448e00067e40afab4fd0f850bb430200a7a74c82bafc1838`
and qualified bakeoff SHA `87c58a41cb0a9421605dd9adf80aaee91bdde7eb5b6e54c39cde540f97e3ca66`
remain distinct. README lists the other historical/current source identities.

All logs/fixtures are under the supplied OUTPUT root:
`/home/gate/bakeoff-next-model-full-precision-profiles-r1-8d6dcf01f4764c0b9eb1576c238510ac/output`.
Exact test argv/exits are in `test-commands.json`; exact final CLI argv/exits
are in `cli-commands.json`. The README gives runnable examples and the complete
test invocation with explicit input roots.

| Command/check | Exit | Evidence |
| --- | ---: | --- |
| Initial `timeout 900 python -B ...test_raw_generation.py ... -v` | 5 | `offline-v1/tests.log`: system Python lacks cv2; no installation performed |
| Warm `timeout 900 python3 -B ...test_raw_generation.py ... -v` | 0 | `offline-v2/tests.log`: seven passing checks, 40.520 seconds |
| TEST-15 deliberate missing-surfaces mutation, targeted failure test | 1 | `test15-red/tests.log`: assertion rejects a false success after writer model mismatch |
| Restored final `timeout 900 python3 -B ...test_raw_generation.py ... -v` | 0 | `offline-final/tests.log`: seven passing checks, 42.693 seconds |
| Final CLI `prepare --size 20` with default timeout | 0 | `cli-final-prepare.log`: 160 bundles, 240 nominal POSTs |
| Final CLI `execute --dry-run`, qwen38-bf16/E0/000 | 0 | `cli-final-dry-run.log`: zero POSTs, zero client pass records |

The TEST-15 mutation ran on temporary branch `test15-raw-writer-mismatch`.
It deliberately changed the successful-writer predicate to accept an error-free
initialized result without parsed surfaces. The targeted test went RED with
`AssertionError: True is not false`. The predicate was restored, the checkout
returned to master, and the full focused suite went GREEN. No historical
constants or genuine service builders were monkeypatched.

Final evidence includes:

- `offline-final/verified-inputs.json`: all 60 audit-manifest entries verified;
  exact dispatch/startup codemaps checked against 570/74 AST symbols; pinned
  source-audit fixtures read as prior art.
- `canon-inputs-read.json`: ten matching startup canon/distilled files verified;
  current principles/cards and original distilled mechanisms read. Immutable
  selected-models, verification, smoke source and fresh semantic/ONNX artifacts
  were read as historical evidence, without executing their operations/models.
- `offline-final/contract-{2,20,120}.json`: both exact selected profiles,
  all four E/W cells, 16/160/960 bundles and 24/240/1440 nominal POSTs. Both E
  treatments have bounded 20-image full120 operations. R2 original-038's real
  image hash is checked. Frozen source identities are retained.
- `offline-final/causal-red-green.json`: genuine original 60-second request
  timeout fails a simulated 80.34-second deadline; v2's actual transport timeout
  is 600 seconds and succeeds with the same real builders and fixture responses.
- `offline-final/grid-results.json`: 24 actual MockTransport completion POSTs,
  two genuine frozen images, both model labels and all four arms. Writer hashes
  match actual sent messages and independent post-facts builder reconstruction.
- `offline-final/failure-results.json`: real service breaker opens after three
  HTTP 503 POSTs; 20 client pass records and all 40 planned bundles remain.
  Strict extraction/writer failures and model mismatches during extraction and
  writing stop or fail cells without creating a success. A writer mismatch
  leaves the sibling writer and later images unattempted.
- `cli-final-contract20.json`: final CLI contract file SHA256
  `98a19f33f34612b4d01e1be8e6ec995230dd64b00a9cf32f15d31e53ce325ab0`.

No live HTTP, GPU/model inference, lifecycle operation, real credential access,
service installation or native admission occurred. MockTransport results do
not supply native, runtime, served-weight or quality evidence. Those fields
remain `UNOBSERVED`; actual execution dependencies are listed in README.
