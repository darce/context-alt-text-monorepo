# Caption + Face Eval Report

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
- title hallucinated-name images: 25 (Audrey Hepburn, Bad Bunny, Bea, Bill Murray, Elizabeth Taylor, Erika, Faith Coggin, Faith Windebank, Ivy Bloom, Rachel Rabbit White, Talvi Faustmann)

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

- Addison Vodka: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Addy Lee: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Al Pacino: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Allyee Whaley: precision=null recall=0.000 (tp=0 fp=0 fn=8)
- Alora Lynn: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Alyssa Mettler: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Amanda Row: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Amberly Skay: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Amy Winehouse: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Andy Warhol: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Angelina Jolie: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Anna Gudnason: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Ashley Ruetenik: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Ashley Zelinskie: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Audrey Hepburn: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bad Bunny: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bea: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bea Burke: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Ben Stiller: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bette Davis: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bill Murray: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bob Dylan: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Bob Marley: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bob Ross: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Brad Pitt: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bri Humes: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Brigitte Bardot: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bruce Lee: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Bruce Willis: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Caitlin Weaver: precision=null recall=0.000 (tp=0 fp=0 fn=15)
- Cameron Diaz: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Carla Webb: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Cassandra Trenary: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Cate Blanchett: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Char Stiles: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Charles Chaplin: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Charlize Theron: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Chloe Lavender: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Christian Bale: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Clhoe Heath: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Clint Eastwood: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Coral Osborne: precision=null recall=0.000 (tp=0 fp=0 fn=12)
- Cristina Quintana: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Daniel Craig: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Daniel Radcliffe: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Denzel Washington: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Drake: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Drew Barrymore: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Elizabeth Taylor: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ellyn Heald: precision=null recall=0.000 (tp=0 fp=0 fn=49)
- Emilie Chartrand: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Emilie Diamond: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Emma Stone: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Emma Watson: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Erika: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Erika Hansen Miller: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Erin McLeod: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Faith Coggin: precision=null recall=0.000 (tp=0 fp=0 fn=14)
- Faith Windebank: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Faye Dunaway: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Frieda Nolan: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Gena Mara: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- George Clooney: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Georgia Kauten: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Grace Kelly: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Hann: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Hanna Cowart: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Harrison Ford: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Hillary Sampliner: precision=null recall=0.000 (tp=0 fp=0 fn=29)
- Humphrey Bogart: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- India Price: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Ivy Bloom: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Jane Fonda: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Jennifer Aniston: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Jenny Farman: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Jess Hull: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Jessica Tillson: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Juliana Ortiz: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Kadi Downs: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Kaitlin Till-Landry: precision=null recall=0.000 (tp=0 fp=0 fn=6)
- Kat Duma: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Kelly Curran: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Kelly Woltman: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Kendal Osborne: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Kirstie McCarrel: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Kris Benton: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Krista Fisher: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Lady Gaga: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Laura Sampliner: precision=null recall=0.000 (tp=0 fp=0 fn=12)
- Lauren Treihaft: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Leonard Cohen: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Leonardo DiCaprio: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Liam Maloney: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Liam Neeson: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Lindsay Blair: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Lindsay Wehking: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Luca Lucaroni: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Lucy Rexrode: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Luisa Wiseman: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Maddie Pesavento: precision=null recall=0.000 (tp=0 fp=0 fn=8)
- Maggie Hunter: precision=null recall=0.000 (tp=0 fp=0 fn=18)
- Maren Altman: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Maria Correonero: precision=null recall=0.000 (tp=0 fp=0 fn=18)
- Mathew Scheiner: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Maya Petersen: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Micaela Carolan: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Michelle Cortese: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Michelle Obama: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Natalie McClellan: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Nelle Harwood: precision=null recall=0.000 (tp=0 fp=0 fn=17)
- Nicky Ross: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Olivia Lee: precision=null recall=0.000 (tp=0 fp=0 fn=12)
- Rachel Rabbit White: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Riley Pay: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Rosalie Fransen: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Ryann Wiseman: precision=null recall=0.000 (tp=0 fp=0 fn=8)
- Salvador Dali: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Sara Nicole Prickett: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Sara Olas: precision=null recall=0.000 (tp=0 fp=0 fn=6)
- Sarah Fairbank: precision=null recall=0.000 (tp=0 fp=0 fn=2)
- Scarlett Rose: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Self: precision=null recall=0.000 (tp=0 fp=0 fn=9)
- Sierra Tesanovic: precision=null recall=0.000 (tp=0 fp=0 fn=4)
- Stephanie Browne: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Sybil Prentice: precision=null recall=0.000 (tp=0 fp=0 fn=1)
- Talvi Faustmann: precision=null recall=0.000 (tp=0 fp=0 fn=17)
- Tatciana Wollam: precision=null recall=0.000 (tp=0 fp=0 fn=5)
- Tory Guzman: precision=null recall=0.000 (tp=0 fp=0 fn=7)
- Victoria Bell: precision=null recall=0.000 (tp=0 fp=0 fn=3)
- Zoe Elefterin: precision=null recall=0.000 (tp=0 fp=0 fn=5)

## Per-item failures

- `personal/zoe_elefterin_610.jpg` (media_id=610): RemoteClientError: POST /v1/chat/completions failed: Server disconnected without sending a response.
- `personal/sarah_fairbank_584.jpg` (media_id=584): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 933 (char 932)); raw output: '{"people": [{"position": "center", "appearance": "a woman with long brown hair, wearing a black patterned top and black pants, sitting at a table"}], "setting": "a restaurant with a brick wall, wooden'
- `personal/maria_correonero_330.jpg` (media_id=330): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 288 (char 287)); raw output: '{"people": [{"position": "center", "appearance": "woman with long brown hair, wearing a white lace-sleeved shirt and blue jeans"}], "setting": "indoor space with a wall covered in black and white text'
- `personal/olivia_lee_212.jpg` (media_id=212): PassOneJSONError: pass-1 returned malformed JSON (Expecting ',' delimiter: line 1 column 960 (char 959)); raw output: '{"people": [{"position": "top screen, lying on bed", "appearance": "person lying on their side, wearing black and white striped underwear, with long dark hair"}, {"position": "bottom screen, left imag'
- `personal/hillary_sampliner_172.jpg` (media_id=172): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 1253 (char 1252)); raw output: '{"people": [{"position": "center foreground", "appearance": "two women, one in a red strapless dress, one in a blue top with a black patterned bag"}, {"position": "right foreground", "appearance": "a '
- `personal/ellyn_heald_87.jpg` (media_id=87): PassOneJSONError: pass-1 returned malformed JSON (Unterminated string starting at: line 1 column 1725 (char 1724)); raw output: '{"people": [{"position": "center", "appearance": "woman with dark wavy hair, blue eyes, wearing a floral-patterned camisole"}], "setting": "indoor room with papers taped to the wall, a guitar hanging '
