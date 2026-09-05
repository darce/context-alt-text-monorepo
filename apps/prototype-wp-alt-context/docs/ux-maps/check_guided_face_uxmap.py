"""Contract check for the GPFACE-1 ux-map: the guided prototype map must carry the face-match screen."""

import json
import sys
from pathlib import Path

MAP = Path("apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.uxmap.json")


def main() -> int:
    data = json.loads(MAP.read_text())
    screens = {s.get("id") for s in data.get("screens", [])}
    actions = data.get("actions", [])
    problems = []
    if "face" not in screens:
        problems.append("screen 'face' missing")
    confirm = [a for a in actions if a.get("id") == "confirm"]
    if not confirm:
        problems.append("action 'confirm' missing")
    elif "Keanu" not in json.dumps(confirm[0]):
        problems.append("action 'confirm' does not name the matched person (Keanu)")
    blob = json.dumps(data)
    if "Face found in the photo" not in blob:
        problems.append("face screen copy 'Face found in the photo' missing")
    if problems:
        print("ux-map contract FAILED: " + "; ".join(problems))
        return 1
    print("ux-map ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
