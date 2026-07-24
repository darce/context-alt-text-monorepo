#!/usr/bin/env python3
"""Generate decode golden fixtures via REAL InsightFaceAdapter decode methods.

Run from apps/prototype-description-service:

    uv run python recognition/tests/fixtures/face_pipeline/decode_golden/generate_decode_goldens.py

Commits deterministic PNG inputs + expected BGR arrays produced by
InsightFaceAdapter._bytes_to_cv2 (plain PIL/cv2; no insightface package required).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from recognition.infrastructure.embeddings import InsightFaceAdapter

OUT = Path(__file__).resolve().parent


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adapter = InsightFaceAdapter.__new__(InsightFaceAdapter)

    rgb = Image.new("RGB", (8, 6), color=(10, 20, 30))
    for x in range(8):
        for y in range(6):
            rgb.putpixel((x, y), (x * 10 % 256, y * 20 % 256, (x + y) * 7 % 256))

    palette = Image.new("P", (8, 6))
    palette.putpalette([i % 256 for i in range(768)])
    for x in range(8):
        for y in range(6):
            palette.putpixel((x, y), (x + y * 8) % 256)

    la = Image.new("LA", (8, 6), color=(100, 200))

    cases = {
        "rgb": _png_bytes(rgb),
        "palette": _png_bytes(palette),
        "la": _png_bytes(la),
    }

    for name, payload in cases.items():
        (OUT / f"{name}.png").write_bytes(payload)
        arr = adapter._bytes_to_cv2(payload)
        np.save(OUT / f"{name}.npy", arr)
        print(f"{name}: shape={arr.shape} dtype={arr.dtype}")


if __name__ == "__main__":
    main()
