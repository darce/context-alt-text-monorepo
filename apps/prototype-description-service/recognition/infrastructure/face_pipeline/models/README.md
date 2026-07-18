# Face pipeline models (YuNet + SFace)

Pinned ONNX weights for the FIR-3 commercial face-identity pipeline.
Adapters live in `recognition/infrastructure/face_pipeline/`; nothing here is
wired into `scan_worker` until FIR-4.

## Models

| Logical name | File | Version | License | Role |
| --- | --- | --- | --- | --- |
| `yunet` | `face_detection_yunet_2026may.onnx` | 2026may | MIT | Face detection + 5 landmarks |
| `sface` | `face_recognition_sface_2021dec.onnx` | 2021dec | Apache-2.0 | 128D face embedding |

Provenance (sha256, size, source URL, license file hash) is the single source
of truth in `../provenance.py` (`MODEL_MANIFEST`). Load only via
`load_verified_model(name)` — fail-closed on missing file or hash mismatch.

## Source (pinned commit, not a branch)

- Repository: [opencv/opencv_zoo](https://github.com/opencv/opencv_zoo)
- Commit: `47534e27c9851bb1128ccc0102f1145e27f23f98`
- YuNet path: `models/face_detection_yunet/face_detection_yunet_2026may.onnx`
- SFace path: `models/face_recognition_sface/face_recognition_sface_2021dec.onnx`
- ONNX download host: `media.githubusercontent.com` (Git LFS content)
- LICENSE download host: `raw.githubusercontent.com`

## Licensing rationale

InsightFace buffalo weights are non-commercial and blocked for production.
The replacement stack uses only commercially compatible upstream licenses:

- **YuNet 2026may** — MIT (upstream `models/face_detection_yunet/LICENSE`,
  Copyright (c) 2020 Shiqi Yu). MIT permits commercial use, modification, and
  redistribution with attribution / license notice preserved.
- **SFace 2021dec** — Apache-2.0 (upstream
  `models/face_recognition_sface/LICENSE`). Apache-2.0 permits commercial use
  with patent grant; retain NOTICE/license terms in distributions.

Upstream LICENSE files are stored next to the models as `LICENSE.yunet` and
`LICENSE.sface` (committed). ONNX weights are **gitignored** and must be
fetched + hash-verified before use.

## Fetch

From `apps/prototype-description-service`:

```bash
uv run python scripts/fetch_face_pipeline_models.py
```

The script downloads both ONNX files and their LICENSE files into this
directory, verifies sha256 (and size) against `MODEL_MANIFEST`, and refuses to
leave unverified artifacts in place.

## Integrity

```python
from recognition.infrastructure.face_pipeline import load_verified_model

yunet_path = load_verified_model("yunet")  # Path only if sha256 matches
```

If the manifest still contains `PENDING_OPERATOR_FETCH` sentinels (network
unavailable when the manifest was authored), `load_verified_model` raises
`ModelIntegrityError` and never returns a path.
