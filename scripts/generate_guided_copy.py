"""Regenerate js/admin/guidedPrototype/copy.ts from the guided demo copy catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json"
OUT = ROOT / "apps/prototype-wp-alt-context/js/admin/guidedPrototype/copy.ts"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def main() -> None:
    catalog = json.loads(SRC.read_text())
    bad = [k for k, v in catalog.items() if not isinstance(v, str)]
    if bad:
        raise SystemExit(f"non-string catalog entries: {bad}")
    lines = [
        "/**",
        " * Guided demo interface copy. Generated from",
        " * docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json",
        " * by scripts/generate_guided_copy.py; edit the catalog, not this file.",
        " */",
        "",
        "export const GUIDED_COPY = {",
    ]
    for key, value in catalog.items():
        lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},")
    lines += [
        "} as const;",
        "",
        "export type GuidedCopyKey = keyof typeof GUIDED_COPY;",
        "",
        "const PLACEHOLDER = /\\{(\\w+)\\}/g;",
        "",
        "/**",
        " * Resolve `{placeholder}` tokens from verified state. Throws on an unresolved",
        " * token so an unrendered brace can never reach the visitor.",
        " */",
        "export const guidedCopy = (key: GuidedCopyKey, values: Record<string, string | number> = {}): string =>",
        "  GUIDED_COPY[key].replace(PLACEHOLDER, (_match, name: string) => {",
        "    const value = values[name];",
        "    if (value === undefined) {",
        "      throw new Error(`Unresolved guided copy placeholder {${name}} in ${key}`);",
        "    }",
        "    return String(value);",
        "  });",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(catalog)} keys)")


if __name__ == "__main__":
    main()
