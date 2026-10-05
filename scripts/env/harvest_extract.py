from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

if __name__ == "__main__" and sys.version_info < (3, 11):
    print("Python 3.11 or newer is required", file=sys.stderr)
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import manifest as manifest_module
from env.manifest import ManifestError, load_manifest


_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_WITHHELD_KEYS = ("secret", "derived", "unmanaged", "missing", "secret_looking", "unparsed")


def _assignments(text: str) -> dict[str, list[str]]:
    assignments: dict[str, list[str]] = {}
    for line in text.split("\n"):
        match = _ASSIGNMENT.match(line)
        if match is not None:
            assignments.setdefault(match.group(1), []).append(match.group(2))
    return assignments


def _name_is_sensitive(name: str) -> bool:
    tokens = name.split("_")
    remaining = []
    index = 0
    while index < len(tokens):
        if tokens[index:index + 2] == ["PUBLISHABLE", "KEY"]:
            index += 2
            continue
        remaining.append(tokens[index])
        index += 1
    return bool(set(remaining) & manifest_module._PUBLIC_SENSITIVE_TOKENS)


def _parse_assignment_values(assignments: dict[str, list[str]]) -> tuple[dict[str, str], set[str]]:
    parsed: dict[str, str] = {}
    unparsed: set[str] = set()
    for name, raw_values in assignments.items():
        if len(raw_values) != 1:
            unparsed.add(name)
            continue
        value = _shell_token(raw_values[0])
        if value is None:
            unparsed.add(name)
            continue
        parsed[name] = value
    return parsed, unparsed


def _shell_token(raw_value: str) -> str | None:
    try:
        tokens = shlex.split(raw_value, posix=True)
    except ValueError:
        return None
    return tokens[0] if len(tokens) == 1 else None


def extract(manifest, target_name: str, env: str, text: str) -> dict[str, object]:
    assignments = _assignments(text)
    parsed, unparsed = _parse_assignment_values(assignments)
    target_vars = {
        var.name: manifest_module.effective_var(manifest, var, target_name)
        for var in manifest.vars
        if target_name in var.targets
    }
    present = set(assignments)
    withheld = {key: set() for key in _WITHHELD_KEYS}
    withheld["unmanaged"].update(present - target_vars.keys())
    withheld["missing"].update(target_vars.keys() - present)
    withheld["unparsed"].update(unparsed)

    values: dict[str, str] = {}
    for name in present & target_vars.keys():
        var = target_vars[name]
        if var.cls == "secret":
            withheld["secret"].add(name)
        if var.derive is not None or var.derive_vault_map:
            withheld["derived"].add(name)

        if var.cls not in {"config", "public"}:
            continue
        sensitive_name = _name_is_sensitive(name)
        sensitive_value = any(
            (value := _shell_token(raw_value)) is not None
            and (manifest_module._LITERAL_SECRET.search(value)
                 or manifest_module._URL_USERINFO_PASSWORD.search(value)
                 or manifest_module._url_query_credential(value))
            for raw_value in assignments[name]
        )
        if sensitive_name or sensitive_value:
            withheld["secret_looking"].add(name)

        if (var.derive is not None or var.derive_vault_map or name in unparsed
                or sensitive_name or sensitive_value):
            continue
        if var.cls in {"config", "public"}:
            values[name] = parsed[name]

    return {
        "version": 1,
        "target": target_name,
        "env": env,
        "values": dict(sorted(values.items())),
        "withheld": {key: sorted(names) for key, names in withheld.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract safe values from a remote VM environment file")
    parser.add_argument("--root", type=Path, required=True, help="environment manifest root")
    parser.add_argument("--target", required=True, help="manifest target name")
    parser.add_argument("--env", required=True, help="target environment name")
    parser.add_argument("--fs-root", type=Path, default=Path("/"), help="filesystem root for remote paths")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.root)
    except (ManifestError, OSError):
        print("Cannot load environment manifest", file=sys.stderr)
        return 2

    target = manifest.targets.get(args.target)
    remote_path = target.remote_paths.get(args.env) if target is not None else None
    if remote_path is None:
        print(f"No remote path for target {args.target} in {args.env}", file=sys.stderr)
        return 2

    fs_root = args.fs_root.resolve()
    path = (fs_root / remote_path.lstrip("/")).resolve()
    try:
        path.relative_to(fs_root)
    except ValueError:
        print(f"Remote env file for target {args.target} in {args.env} escapes fs root", file=sys.stderr)
        return 2
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print(f"Cannot read env file for target {args.target} in {args.env}", file=sys.stderr)
        return 2

    json.dump(extract(manifest, args.target, args.env, text), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
