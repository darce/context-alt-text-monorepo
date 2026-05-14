# E15-3a LocalWP Proof-Bundle Capture Checklist

> **Purpose**: Execute the pending E15-3a Slice 2 seeded-media proof run directly from the `Seeded-Media Proof-Bundle Capture Packet` already defined in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md).
> **Primary record**: Update [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md) as you go, and record slice completion/final verdicts in MCP handoff; this checklist is the operator sequence, not a second source of truth.

Use this checklist for one seeded-media Workbench scan that produces the reusable E15-22 proof bundle. Keep one `proof-bundle artifact bundle ID` and one `source scan run identifier` for the whole run.

## Phase 0: Local PostgreSQL First

1. Verify the local description-service database path before touching OCI.
2. From `apps/prototype-description-service`, use the default native local PostgreSQL contract on `localhost:5432` first:
   - `cp .env.example .env`
   - `make postgres-start`
   - `make reset`
3. Use the repo-native database shell instead of raw `psql` when you need to inspect the local DB:
   - `./scripts/db_shell.sh --admin -c "SELECT current_database(), current_user;"`
   - `./scripts/db_shell.sh --admin -c "SELECT COUNT(*) FROM tenants;"`
4. If native local PostgreSQL is unavailable, fall back to the disposable Docker database and keep that mode explicit in the run log:
   - `docker compose -f docker-compose.db.yml up -d postgres`
   - `PGPORT=55432 make reset`
5. Record the local DB mode (`localhost:5432` native or `localhost:55432` Docker) in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md) before continuing.
6. Only after the local DB path is green should you open OCI stdout, `GET /metrics`, and the remote proof-capture flow below.

## Before You Start

1. Complete the local PostgreSQL preflight above and record whether you used native `localhost:5432` or Docker `localhost:55432`.
2. Open [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md) and fill the pending header fields before touching the UI:
   - `proof-bundle artifact bundle ID`
   - `source scan run identifier`
   - `seeded-media set identifier`
   - `E15-11 hosted transport proof reference`
   - `Local PostgreSQL mode`
3. Confirm the LocalWP site and plugin build still match the packet assumptions:
   - LocalWP origin `http://localhost:10010`
   - backend `https://api.altcontext.com`
   - build under test `feature/e15-22`
4. Open the two backend evidence surfaces before starting the scan:
   - OCI stdout log tail: `cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f`
   - metrics endpoint: `GET /metrics`
5. Keep one browser session for the Workbench capture so the screenshot/transcript sequence stays tied to the same `source scan run identifier`.
6. Decide whether the avatar proof is expected to show a representative avatar or an explicit unavailable-image fallback so you know which path to capture if the UI degrades.

## Slice 2 Capture Sequence

1. After the local PostgreSQL preflight is green, capture the pre-scan Workbench state before starting the seeded-media scan.
2. Start the scan and stay on the same Workbench route until the UI reaches the review-ready completion state.
3. During the run, capture one avatar checkpoint and one mid-run progress checkpoint before the UI shows `Scan complete`.
4. After the UI reaches the ready state, capture the completion checkpoint and then collect the backend evidence packet from OCI stdout and `GET /metrics`.
5. Write each artifact back into [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md) before moving to Slice 3 or Slice 4.

## Checkpoint 1: Pre-Scan State

1. Capture a screenshot or transcript frame showing:
   - the seeded-media set in the current LocalWP session
   - the Workbench route under test
   - enough UI context to prove the run starts from the same browser session used for the later proof bundle
2. Record these fields in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md):
   - `Before screenshot`
   - `source scan run identifier`
   - `seeded-media set identifier`
   - `Media provenance set`
   - `Media count`

## Checkpoint 2: Avatar Evidence

1. When the first representative card or review drawer is visible, capture one screenshot or transcript frame that shows either:
   - a representative avatar rendered from `thumb_url`, or
   - the explicit fallback with the unavailable-image label
2. Record these fields in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md):
   - `Proof-bundle artifact bundle ID`
   - `Source scan run identifier`
   - `Capture checkpoint`
   - `Surface shown`
   - `Representative source`
   - `Representative cluster / media reference`
   - `Screenshot / transcript path`
3. If no representative avatar is available, make sure the capture still shows the explicit fallback rather than a blank state.

## Checkpoint 3: Mid-Run Progress

1. Before the UI reaches completion, capture one mid-run frame that visibly shows:
   - the processed count
   - the current in-progress state
   - no premature `Scan complete` label
2. Record these fields in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md):
   - `Proof-bundle artifact bundle ID`
   - `Source scan run identifier`
   - `Capture checkpoints`
   - `Processed-count checkpoints`
   - `Screenshot / transcript path`
3. Keep the processed count values in order so the later proof shows the count increasing rather than being reconstructed from memory.

## Checkpoint 4: UI-Ready Completion

1. Wait until the Workbench is actually review-ready, then capture the completion frame that shows `Scan complete` only after clustering/projection is ready.
2. Pair that frame with the pre-completion checkpoint from Checkpoint 3.
3. Record these fields in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md):
   - `Pre-completion checkpoint path`
   - `Completion checkpoint path`
   - `scanProgress.phase / UI-ready state at completion capture`
   - `Notes`

## Checkpoint 5: Backend Evidence Packet

1. From the OCI stdout log tail (`cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml logs -f`), capture the backend correlation IDs tied to the same `source scan run identifier`.
2. From `GET /metrics`, record the latency evidence needed for the run log table.
3. Capture or summarize a redacted payload snapshot with counts and labels only.
4. Record these fields in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md):
   - `Representative backend correlation IDs`
   - `Recognition result summary`
   - `Metric Window / Route / P50 / P95`
   - `Redacted payload snapshot`

## After the Scan

1. Update the `Evidence Index` rows in [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md) for the Slice 2 green scan round-trip, representative backend correlation IDs, and latency evidence.
2. Fill the `Reuse Metadata` section so E15-3 and E15-5 can reuse the same proof-bundle artifact without redefining avatar/progress success.
3. Update the `MVP Exit Criteria Ledger` for the Slice 2 round-trip evidence.
4. Record a slice-complete MCP handoff write for the LocalWP run once the run log is internally complete, even if Slices 3 and 4 are still pending.
5. If any required capture is missing, stop and fill the gap before starting Slice 3A; do not rely on memory to reconstruct the proof packet later.
