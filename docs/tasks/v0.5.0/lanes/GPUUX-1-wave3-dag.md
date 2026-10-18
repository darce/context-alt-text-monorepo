# GPUUX-1 wave-3 lane DAG (GRPH-01 toposort, GRPH-31 critical path)

Generated 2026-09-03 from feature/gpuux-1 @ 4e0828d1. 16 nodes, 21 edges, acyclic (GRPH-02 check passed).

Edges exist only where an artifact moves between nodes (GRPH-32). Parallel lanes have frozen file-ownership contracts (GRPH-33/39) listed in the briefs.

```
N0 freeze contracts
├─ N1 H-05 state_snapshot.py ──────────────┐
├─ N2 H-06 reaper.py publish block ────────┤
├─ N3 H-04 per-env load + aggregate source ┼─ N8a merge gpuux-1 ─ N9a review-slice ─ N10a close+merge main ─ N11 deploy + W8 smoke
├─ N4 H-03/M-07 prod compose + runbook ────┤                                              ▲
├─ N5a toast ASCII ─ N5 E2 toasts hook ────┘                                              │ gate must be on main first
├─ N6 OCIRV-1 P1 test integrity ─┐                                                        │
└─ N7 OCIRV-1 P0 deploy gate ────┴─ N8b merge ocirv-1 ─ N9b review-slice ─ N10b close+merge main
```

| wave | nodes (width) |
|---|---|
| W0 | N0 (1) |
| W1 | N1, N2, N3, N4, N5a, N6, N7 (7) |
| W2 | N5, N8b (2) |
| W3 | N8a, N9b (2) |
| W4 | N9a, N10b (2) |
| W5 | N10a (1) |
| W6 | N11 (1) |

Topological order: N0 -> N1 -> N2 -> N3 -> N4 -> N5a -> N6 -> N7 -> N5 -> N8b -> N8a -> N9b -> N9a -> N10b -> N10a -> N11

Critical path (GRPH-31, est. minutes): N0 -> N6 -> N8b -> N9b -> N10b -> N10a -> N11 = 230 min; serial sum 590 min; parallel speedup 2.57x; max width 7 (remote codex-remote lanes cap dispatch_wave 3600 s each).

| node | est min | owner | label |
|---|---|---|---|
| N0 | 10 | coordinator/local | freeze contracts + briefs (this turn) |
| N1 | 45 | codex-remote gpt-5.6-sol | H-05 read_previous_gpu_state validates written_at/freshness |
| N2 | 45 | codex-remote gpt-5.6-sol | H-06 partial STOP must not publish aggregate STOPPED |
| N3 | 60 | codex-remote gpt-5.6-sol | H-04 per-env load snapshot paths + aggregate JobLoadSource |
| N4 | 30 | codex-remote gpt-5.6-sol | H-03+M-07 prod compose rw load mount + runbook parity |
| N5a | 10 | coordinator/local | E2 ux-map toast ASCII iteration |
| N6 | 75 | codex-remote gpt-5.6-sol | OCIRV-1 P1 S-15..S-18 behavioural tests + mutant kills |
| N7 | 30 | codex-remote gpt-5.6-sol | OCIRV-1 P0 S-02 deploy workflow test gate |
| N5 | 60 | codex-remote gpt-5.6-sol | E2 useGpuStateToasts hook + SPA mount + vitest |
| N8b | 10 | coordinator/local | merge OCIRV-1 lanes into feature/ocirv-1 |
| N8a | 20 | coordinator/local | merge GPUUX-1 lanes into feature/gpuux-1 |
| N9b | 60 | mixed | /wb-review-slice OCIRV-1 (1 local + N remote, canon lenses) |
| N9a | 60 | mixed | /wb-review-slice GPUUX-1 (1 local + N remote, canon lenses) |
| N10b | 15 | coordinator/local | OCIRV-1 close_check(enforce) + merge main (gate lands first) |
| N10a | 15 | coordinator/local | GPUUX-1 close_check(enforce) + merge main |
| N11 | 45 | coordinator/local + OCI A10 | deploy dev via gated workflow + W8 GPU smoke dry->live, guaranteed STOP |

Edge rationale (GRPH-32): N1->N8a: state_snapshot.py diff; N2->N8a: reaper.py diff; N3->N8a: load-source diff; N4->N8a: prod compose diff; N5->N8a: FE diff; N5a->N5: toast policy ASCII screens -> brief; N10b->N10a: CI gate governs GPUUX-1 auto-deploy on push

Non-overlap contracts (GRPH-33): N1 owns state_snapshot.py + test_state_snapshot_contract.py/test_state_snapshot.py; N2 owns reaper.run_reap_cycle publish block + test_batch_fence.py; N3 owns reaper CLI wiring (argparse/load-source construction only), new load_source module, docker-compose.env.yml, gpu-lifecycle-install.sh, check-gpu-snapshots.sh + its tests; N4 owns docker-compose.prod.yml, .env.prod.example, infra/oci/README.md; N5 owns js/admin/hooks/useGpuStateToasts.ts, its test, App.tsx mount, vocabulary strings; N6 owns scripts/test_ocirv1_vault_readiness.py, scripts/deploy/tests/test-ocir-auth.sh (+ pytest wrapper); N7 owns .github/workflows/deploy-recognition.yml + scripts/test_deploy_workflow_gate.py. Shared frozen contract for N3/N4: host load path = /run/acx-write/<ACX_ENV>/describe-load.json, ACX_ENV in {dev,staging,prod}; lifecycle reads the aggregate over /run/acx-write/*/describe-load.json.
