# FR licensing & vendor research — 2026-07-23

Source: remote grok web-research lane (25 turns, $1.06) → `fir-licensing-research-20260723.json`.
Decision-critical claims independently re-verified by coordinator (WebFetch, same day):
buffalo_l explicitly licensable on insightface.ai; VeriLook €339/€859 perpetual confirmed.

## Q1 — InsightFace commercial licensing (no public prices, but the path is concrete)

- **Entity**: InsightFace AI Technology Limited (site publisher). DeepGlint = historical
  research collaborator only, not the licensor. Maintainer Jia Guo (nttstar) redirects all
  pricing asks to email.
- **Channel**: `recognition-oss-pack@insightface.ai` (buffalo_l/OSS packs specifically),
  CC `contact@insightface.ai`; web form at insightface.ai/contact has a
  "Face Recognition Model Licensing" use-case dropdown with volume bands
  (eval / <100K / 100K–1M / 1M+ req/mo / device-based). Business-domain email required;
  1–2 business-day reply claimed.
- **Covers the model zoo**: YES — the enterprise page explicitly lists commercial usage
  rights for buffalo_l, antelopev2, buffalo_s, buffalo_m. Deliverable = ONNX files for
  offline self-hosted inference (works on ARM/OCI A1). Code stays MIT; weights stay NC
  without the paid grant.
- **Pricing**: genuinely ZERO public or anecdotal dollar figures anywhere (GitHub issues
  #2486/#2587, forums, HN/Reddit swept). "Flexible terms from single-product to
  enterprise-wide," startup-friendly language. → Email this week; the head-to-head
  (+0.49 detection recall) is the negotiation anchor.

## Q2 — the market, sorted by what matters to us

### Detectors (our actual gap) — permissive weights
| Detector | Weights license | WIDER-Hard / occlusion | Verdict |
|---|---|---|---|
| YuNet (current) | MIT (opencv_zoo) | 0.708 hard; our masked 0.321 | incumbent, weak |
| MediaPipe BlazeFace short/full | Apache-2.0 | mobile-oriented, likely < SCRFD | cheap A/B, temper hopes |
| PaddleDetection BlazeFace-FPN-SSH | Apache-2.0 (verify model file) | 0.793 hard | **best clean candidate to test** |
| SCRFD (insightface tree) | **code Apache-2.0, InsightFace-distributed weights NC** | 0.830–0.853 hard | clean only via RETRAIN on our own/clean data |
| RetinaFace-10GF (buffalo detector) | NC | 0.904 hard (R50 paper) | the thing we'd be licensing |
| YOLOv5-face / YOLO-face | GPL-3.0 | strong (~0.855 hard) | copyleft trap — no |
| Ultralytics YOLO fine-tune | AGPL-3.0 | n/a | AGPL trap — no |

**Key nuance the sweep surfaced**: SCRFD's *code* is Apache-2.0 — a clean-data retrain of
SCRFD is a legitimate own-your-weights detector path (FIR-7-adjacent), distinct from
using InsightFace's NC .onnx files.

### Clean-weights embedders
- **AuraFace-v1** (fal, HF): Apache-2.0 weights, ArcFace-style 512D, claims commercial-clean
  training data (vendor assertion, not enumerated). Drop-in for InsightFace pipelines.
  Main new option; pair with a clean detector.
- SFace (current): Apache-2.0 in opencv_zoo, but paper trained on MS-Celeb-1M lineage —
  provenance memo for counsel someday.
- Synthetic stacks: IDiff-Face CC-BY-NC (no), DCFace no license (no), Vec2Face MIT but
  ships Glint360K auxiliaries (partial). None are a production shortcut this quarter.

### Commercial SDKs a small SaaS can actually buy
| Vendor | Pricing | ARM/CPU | Small-SaaS | Notes |
|---|---|---|---|---|
| **Neurotechnology VeriLook** | **PUBLIC: €339/€859 SDK one-time + ~€20–70/component, perpetual, no annual** ✅ verified | yes, ARM Linux | **YES — only self-serve option found** | mask claims in brochure; NIST mask-era participant |
| Luxand FaceSDK | quote-only, trial | yes incl. ARM | likely | mask-on detection marketed |
| CyberLink FaceMe | quote-only | yes, many SoCs | mid-touch | NIST top-10 claims (verify against NIST tables) |
| ROC (Rank One) | per-device/stream/txn, 30-day free eval | edge-focused | maybe | gov/enterprise GTM |
| Paravision / Innovatrics / Corsight / NEC / Idemia / Oosto / Pangiam-Trueface | enterprise custom | varies | **no** | wrong GTM for us |

## Recommended moves (unchanged by research, sharpened by it)
1. Email InsightFace (recognition-oss-pack@) this week — path confirmed, buffalo_l named.
2. A/B clean detectors on Golden-150: MediaPipe full-range AND PaddleDetection
   BlazeFace-FPN-SSH (Apache, 0.793 hard — the stronger clean bet).
3. VeriLook Extended trial (€0 to bench) as the commercial fallback with knowable cost.
4. SCRFD clean-retrain = the own-weights endgame if quotes are hostile (FIR-7 scope).
