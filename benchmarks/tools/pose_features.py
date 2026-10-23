#!/usr/bin/env python3
"""Roll-corrected pose features from the stored 5-point landmarks.

The first calibration pass used two crude yaw proxies that both conflate yaw with
in-plane rotation: a tilted-but-frontal head displaces the nose horizontally exactly
like a turned one. Before concluding that geometry cannot predict `profile`, the
geometry has to actually be computed properly.

Everything here reads the landmarks already recorded by the detection pass, so no
re-detection is needed. Landmark order is YuNet's:
right_eye, left_eye, nose_tip, right_mouth_corner, left_mouth_corner — where "right"
is the subject's right, i.e. image-left.
"""

from __future__ import annotations

import json
import argparse
from pathlib import Path




def check_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{path} already exists; choose a new output")


def publish(path: Path, data: dict) -> None:
    # Serialize and reject non-finite values before creating any destination.
    payload = json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError:
        raise FileExistsError(f"{path} already exists; choose a new output") from None



def pose(landmarks: list[list[float]]) -> dict:
    """Yaw/roll features in a frame where the eye line is horizontal."""
    import numpy as np

    pts = np.asarray(landmarks, dtype=float)
    if pts.shape != (5, 2) or not np.isfinite(pts).all():
        raise ValueError("landmarks must be five finite 2D points")
    r_eye, l_eye, nose, r_mouth, l_mouth = pts

    eye_vec = l_eye - r_eye
    interocular = float(np.hypot(*eye_vec))
    if interocular < 1e-6:
        return {}
    # De-rotate so roll cannot masquerade as yaw.
    angle = float(np.arctan2(eye_vec[1], eye_vec[0]))
    cos_a, sin_a = np.cos(-angle), np.sin(-angle)
    rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
    flat = (pts - pts.mean(axis=0)) @ rot.T
    fr_eye, fl_eye, fnose, fr_mouth, fl_mouth = flat

    eye_span = float(fl_eye[0] - fr_eye[0])
    mouth_span = float(fl_mouth[0] - fr_mouth[0])

    # Yaw 1: where the nose sits between the eyes. 0.5 = frontal, ->0 or ->1 = turned.
    nose_between_eyes = (float(fnose[0]) - float(fr_eye[0])) / eye_span if abs(eye_span) > 1e-6 else None
    # Yaw 2: same measurement on the mouth pair — an independent landmark pair, so a
    # single mislocated eye cannot drive the result on its own.
    nose_between_mouth = (
        (float(fnose[0]) - float(fr_mouth[0])) / mouth_span if abs(mouth_span) > 1e-6 else None
    )
    # Yaw 3: at profile the far half of the face is foreshortened, so the eye and mouth
    # spans shrink relative to face height. Scale-free via inter-feature vertical extent.
    face_height = float(np.hypot(*((l_mouth + r_mouth) / 2 - (l_eye + r_eye) / 2)))
    eye_span_ratio = abs(eye_span) / face_height if face_height > 1e-6 else None

    return {
        # Folded to [0, 0.5]: turned-left and turned-right are the same stratum.
        "yaw_eye": abs(nose_between_eyes - 0.5) if nose_between_eyes is not None else None,
        "yaw_mouth": abs(nose_between_mouth - 0.5) if nose_between_mouth is not None else None,
        "eye_span_ratio": eye_span_ratio,
        "roll_deg": abs(np.degrees(angle)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    check_output(args.out)
    src = args.source
    data = json.loads(src.read_text())
    enriched = 0
    for row in data["entries"]:
        for face in row["faces"]:
            extra = pose(face["landmarks"])
            if extra:
                face.update({k: (round(v, 4) if v is not None else None) for k, v in extra.items()})
                enriched += 1
    publish(args.out, data)
    print(f"{args.out.name}: enriched {enriched} faces with roll-corrected pose features")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
