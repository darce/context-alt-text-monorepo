# Caption + Face Eval Report

> **SUPERSEDED (L6-baseline / EVAL-01 / P1-5(a)).** Caption-quality figures below were scored on a pre-L3 corpus (37-image reported set with selection contamination, a 10-image selection set, a 39-image stub, and/or the 646-image interleave) and/or a pre-PRIV-1 roster spelling. They are not Δ-comparable to the current 20-image held-out split (`golden.json` after `8b93c473`). Kept for provenance. Do not cite as current evidence.

- schema: `acx-eval/v1` kind: `report`
- adapter(s): `bakeoff` model(s): `Qwen3-VL-30B-A3B-Instruct` version(s): `Q4_K_M`
- head_sha: `5a67b070fe8e383ffd243a77029d2225b6f8d700`
- base_url: http://localhost:8000
- fetch manifest_sha256: `08751e69bf4d6bb4d4303f0bc7c38758f1f6fdaa60253828b7101ce5c2306d97`
- score manifest_sha256: `13999d331f7dc8c3b62848ba281def5512cd8babda9ac00930ca18c8a56dae93` (matches fetch: False)
- started_at: 2026-07-16T23:33:28Z
- images: 640/646 scored, 6 failed
- notes: S2R4-14 F23-G re-score HELD: docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3.json against apps/prototype-description-service/scripts/eval_harness/corpus646-interleave-manifest-20260716.json at code 896bd17d4277b83ba54993007cb8ae5bbe2e0de7 exited 1 (partial-corpus: 640/646 scored, 6 failed — the same failures already listed in this artifact). regen_eval_report.py will not publish an exit-1 report (S2R4-03). faces.identification is therefore still the pre-S2R3-08 leftover (precision=null, recall=0.0, populated per-identity table). Do not read those rows as current-scorer identification P/R.
- notes: Provenance unchanged: fetch=08751e69bf4d6bb4d4303f0bc7c38758f1f6fdaa60253828b7101ce5c2306d97 score=13999d331f7dc8c3b62848ba281def5512cd8babda9ac00930ca18c8a56dae93 (matches fetch: False). Caption numbers were not rewritten.
- notes: S2R4-15 S2R3-07 rebaseline (commit a90a091e) still published in this held artifact: insertion_rate 0.888→0.890; name_precision 0.685→0.684; wrong_name_images 203→204; title hallucinated-name images 24→25 (new name Sable Current); true_rejections 19→20; long-surface name_precision 0.635→0.634 / wrong_name_images 262→263; score_manifest 08751e69→13999d33 (matches fetch True→False). Failure paths rewritten 2026/07/<slug>_<id>.jpg → personal/<slug>_<id>.jpg. These numbers were not re-scored in F23-G (partial-corpus hold).
- ⚠ produced by the throwaway `bakeoff` transport (VLM-2B) — face detection/identification sections below are **vacuous by design** (stub `analyze`/`media_identities`); 0% is expected, NOT a recognition regression.
- prompt variant: `v3` pipeline: two_pass
- latency: per-image wall-clock p50 5.244s p95 17.197s (640 timed) · model calls/image: 2.0 (total 1280)

## Caption metrics (deterministic tier)

- insertion rate: 0.890
- name precision: 0.684 (wrong-name images: 204, rate: 0.319)
- Must-Right failed images (hard gate): 56 (rubric-defined images: 530)
- policy violations: 0
- mean gated score: 0.627

## Quality axes (short surface, report-only signals)

- meta-framing images: 9
- mean context duplication: 0.021
- name front-loaded rate: 0.895
- sentence band [1, 4] ok rate: 0.986
- titles present: 640
- title word band [3, 8] violations: 2
- title hallucinated-name images: 25 (Audrey Hepburn, Bad Bunny, Quiet, Bill Murray, Elizabeth Taylor, Candid, Ochre Ridgeway, Sylvan Fathom, Plumb Ferry, Tidal Rookery, Sable Current)

## Long surface (alt_text_long)

- images with long: 640
- insertion rate: 0.921 name precision: 0.634
- wrong-name images: 263
- mean gated score: 0.558
- mean word count: 54.6
- meta-framing images: 72
- mean context duplication: 0.009
- name front-loaded rate: 0.901
- sentence band [2, 8] ok rate: 0.991

## Face detection (identity-agnostic)

- REFUSED (detection_refuses_roster_only): detection P/R is not computed unless annotation_mode is exhaustive

## Face identification (named assertions)

- micro precision: null recall: 0.000
- macro precision: null recall: 0.000
- true rejections (strangers): 20

### Wrong-name errors (top product risk — every instance listed)

- none
- ignored (triaged): 0

### Per-identity (macro components)

- Sylvan Quarry: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Wicker Fathom: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Al Pacino: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Dappled Juniper: precision=null recall=0.000 (tp=0 fp=0 fn=8)
- Russet Harbor: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Sable Kestrel: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Citrine Fathom: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Candid Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Amy Winehouse: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Andy Warhol: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Angelina Jolie: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Brisk Current: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Citrine Bramble: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Muted Fathom: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Audrey Hepburn: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bad Bunny: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Quiet: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Hollow Pennant: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Ben Stiller: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bette Davis: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bill Murray: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bob Dylan: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Bob Marley: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bob Ross: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Brad Pitt: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Gilded Willow: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Brigitte Bardot: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bruce Lee: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bruce Willis: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Russet Fathom: precision=null recall=0.000 (tp=0 fp=0 fn=15)
- Cameron Diaz: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Opaline Bramble: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Marbled Kestrel: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Cate Blanchett: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Russet Lantern: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Charles Chaplin: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Charlize Theron: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Vellum Falcon: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Christian Bale: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Candid Yarrow: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Clint Eastwood: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Pewter Hollow: precision=null recall=0.000 (tp=0 fp=0 fn=12)
- Tidal Harbor: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Daniel Craig: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Daniel Radcliffe: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Denzel Washington: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Drake: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Drew Barrymore: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Elizabeth Taylor: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Gilded Cypress: precision=null recall=0.000 (tp=0 fp=0 fn=49)
- Saffron Cypress: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Sable Bramble: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Emma Stone: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Emma Watson: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Candid: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Muted Current: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Hazel Cypress: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Ochre Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Sylvan Fathom: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Faye Dunaway: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Opaline Cypress: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Onyx Meadow: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- George Clooney: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Verdant Verity: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Grace Kelly: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Amber: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Cobalt Beacon: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Harrison Ford: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Russet Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=29)
- Humphrey Bogart: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Auburn Hollow: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Plumb Ferry: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Jane Fonda: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Jennifer Aniston: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Onyx Beacon: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Auburn Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Muted Hollow: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Umber Compass: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Ochre Willow: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Candid Orchard: precision=null recall=0.000 (tp=0 fp=0 fn=6)
- Hollow Beacon: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ochre Harbor: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Wicker Marsh: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Tidal Quarry: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Auburn Current: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Tidal Bramble: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Onyx Marsh: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Lady Gaga: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Sable Verity: precision=null recall=0.000 (tp=0 fp=0 fn=12)
- Dappled Meadow: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Leonard Cohen: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Leonardo DiCaprio: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Linen Kestrel: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Liam Neeson: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Burnished Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Linen Warren: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Vellum Meadow: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Brisk Rookery: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Cobalt Verity: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Wicker Orchard: precision=null recall=0.000 (tp=0 fp=0 fn=8)
- Saffron Orchard: precision=null recall=0.000 (tp=0 fp=0 fn=18)
- Saffron Beacon: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Slate Willow: precision=null recall=0.000 (tp=0 fp=0 fn=18)
- Vellum Warren: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Indigo Lantern: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Indigo Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Plumb Tanner: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Michelle Obama: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Citrine Juniper: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Onyx Lantern: precision=null recall=0.000 (tp=0 fp=0 fn=17)
- Flaxen Harbor: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Sylvan Orchard: precision=null recall=0.000 (tp=0 fp=0 fn=12)
- Tidal Rookery: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Hazel Yarrow: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Umber Willow: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Muted Yarrow: precision=null recall=0.000 (tp=0 fp=0 fn=8)
- Salvador Dali: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Auburn Lantern: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Candid Lantern: precision=null recall=0.000 (tp=0 fp=0 fn=6)
- Opaline Tanner: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Sylvan Beacon: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Indigo: precision=null recall=0.000 (tp=0 fp=0 fn=9)
- Sylvan Ridgeway: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Onyx Harbor: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Verdant Beacon: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Sable Current: precision=null recall=0.000 (tp=0 fp=0 fn=17)
- Plumb Verity: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Flaxen Yarrow: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Gilded Bramble: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Brisk Compass: precision=null recall=0.000 (tp=0 fp=0 fn=5)

## Per-item failures

- `personal/brisk_compass_610.jpg` (media_id=610): RemoteClientError: POST /v1/chat/completions failed: Server disconnected without sending a response.
- `personal/opaline_tanner_584.jpg` (media_id=584): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 933 (char 932)); raw output: '{"people": [{"position": "center", "appearance": "a woman with long brown hair, wearing a black patterned top and black pants, sitting at a table"}], "setting": "a restaurant with a brick wall, wooden'
- `personal/slate_willow_330.jpg` (media_id=330): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 288 (char 287)); raw output: '{"people": [{"position": "center", "appearance": "woman with long brown hair, wearing a white lace-sleeved shirt and blue jeans"}], "setting": "indoor space with a wall covered in black and white text'
- `personal/sylvan_orchard_212.jpg` (media_id=212): PassOneJSONError: pass-1 returned malformed JSON (Expecting ',' delimiter: line 1 column 960 (char 959)); raw output: '{"people": [{"position": "top screen, lying on bed", "appearance": "person lying on their side, wearing black and white striped underwear, with long dark hair"}, {"position": "bottom screen, left imag'
- `personal/russet_ridgeway_172.jpg` (media_id=172): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 1253 (char 1252)); raw output: '{"people": [{"position": "center foreground", "appearance": "two women, one in a red strapless dress, one in a blue top with a black patterned bag"}, {"position": "right foreground", "appearance": "a '
- `personal/gilded_cypress_87.jpg` (media_id=87): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 1725 (char 1724)); raw output: '{"people": [{"position": "center", "appearance": "woman with dark wavy hair, blue eyes, wearing a floral-patterned camisole"}], "setting": "indoor room with papers taped to the wall, a guitar hanging '
