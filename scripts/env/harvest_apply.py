from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from env.harvest_extract import secret_looking
from env.manifest import Manifest, Var, load_manifest


_WITHHELD_KEYS = frozenset(
    {"secret", "derived", "unmanaged", "missing", "secret_looking", "unparsed"}
)
_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_HEADER = re.compile(r"^\s*\[")
_VALUES_ASSIGNMENT = re.compile(r"^(?P<prefix>[ \t]*values[ \t]*=[ \t]*)(?P<rhs>.*)$")


class ApplyError(ValueError):
    def __init__(self, field: str, reason: str):
        super().__init__(reason)
        self.field = field
        self.reason = reason


class _DuplicateJSONKey(ValueError):
    pass


@dataclass(frozen=True)
class _ValuesLine:
    index: int
    prefix: str
    newline: str


def _toml_comment_parts(text: str) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "#":
            before = text[:index]
            spacing = before[len(before.rstrip(" \t")) :]
            return before[: len(before) - len(spacing)], spacing + text[index:]
    body = text
    trailing = body[len(body.rstrip(" \t")) :]
    return body[: len(body) - len(trailing)], trailing


def _find_values_line(var: Var, raw: bytes) -> _ValuesLine:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApplyError(var.name, "fragment is not UTF-8") from exc
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.strip() == "[[var]]"]
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if _HEADER.match(lines[index]):
                end = index
                break
        block = "".join(lines[start:end])
        try:
            parsed = tomllib.loads(block)
        except tomllib.TOMLDecodeError as exc:
            raise ApplyError(var.name, "cannot locate values table") from exc
        records = parsed.get("var", [])
        if not records or records[0].get("name") != var.name:
            continue
        assignments = [
            (index, _VALUES_ASSIGNMENT.match(lines[index].rstrip("\r\n")))
            for index in range(start + 1, end)
        ]
        assignments = [(index, match) for index, match in assignments if match is not None]
        if len(assignments) != 1:
            raise ApplyError(var.name, "values table must be single-line")
        index, match = assignments[0]
        line = lines[index]
        line_body = line.rstrip("\r\n")
        newline = line[len(line_body) :]
        rhs, trailing = _toml_comment_parts(match.group("rhs"))
        try:
            parsed_values = tomllib.loads(f"values = {rhs}")["values"]
        except (tomllib.TOMLDecodeError, KeyError) as exc:
            raise ApplyError(var.name, "values table must be single-line") from exc
        if not isinstance(parsed_values, dict) or parsed_values != dict(var.values):
            raise ApplyError(var.name, "values table does not match manifest")
        return _ValuesLine(index, match.group("prefix"), newline)
    raise ApplyError(var.name, "values table was not found")


def _escape_basic_string(value: str) -> str:
    escaped = ['"']
    named = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    for char in value:
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif char in named:
            escaped.append(named[char])
        elif ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F:
            escaped.append(f"\\u{ord(char):04X}")
        else:
            escaped.append(char)
    escaped.append('"')
    return "".join(escaped)


def _escape_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return _escape_basic_string(key)


def _render_values(values: dict[str, str]) -> str:
    members = [f"{_escape_key(env)} = {_escape_basic_string(value)}" for env, value in values.items()]
    return "{ " + ", ".join(members) + " }" if members else "{}"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result


def _decode_input(path: Path) -> list[object]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ApplyError("input", "cannot read JSON") from exc
    if not text.strip():
        raise ApplyError("input", "empty JSON input")
    try:
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, _DuplicateJSONKey):
        documents: list[object] = []
        try:
            for line in text.splitlines():
                if line.strip():
                    documents.append(json.loads(line, object_pairs_hook=_unique_object))
        except (json.JSONDecodeError, _DuplicateJSONKey) as exc:
            raise ApplyError("input", "invalid JSON") from exc
        if not documents:
            raise ApplyError("input", "empty JSON input")
        return documents
    if isinstance(document, list):
        return document
    return [document]


def _validate_withheld(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _WITHHELD_KEYS:
        raise ApplyError("withheld", "invalid withheld fields")
    for field in sorted(_WITHHELD_KEYS):
        names = value[field]
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) or _NAME.fullmatch(name) is None for name in names)
            or names != sorted(set(names))
        ):
            raise ApplyError("withheld", "withheld lists must contain sorted names")


def _validate_documents(documents: list[object], manifest: Manifest) -> list[tuple[str, str, dict[str, str]]]:
    if not documents:
        raise ApplyError("input", "empty harvest")
    required = {"version", "target", "env", "values", "withheld"}
    vars_by_name = {var.name: var for var in manifest.vars}
    global_envs = {env for target in manifest.targets.values() for env in target.envs}
    pairs: set[tuple[str, str]] = set()
    result: list[tuple[str, str, dict[str, str]]] = []
    for document in documents:
        if not isinstance(document, dict):
            raise ApplyError("object", "harvest entry must be an object")
        if set(document) != required:
            raise ApplyError("object", "harvest entry fields are invalid")
        if type(document["version"]) is not int or document["version"] != 1:
            raise ApplyError("version", "unsupported harvest version")
        target_name, env = document["target"], document["env"]
        if not isinstance(target_name, str):
            raise ApplyError("target", "invalid target name")
        target = manifest.targets.get(target_name)
        if target is None:
            raise ApplyError("target", "unknown target")
        if not isinstance(env, str) or env not in global_envs:
            raise ApplyError("env", "unknown environment")
        if env not in target.envs:
            raise ApplyError("env", "environment is not configured for target")
        pair = (target_name, env)
        if pair in pairs:
            raise ApplyError("object", "duplicate target and environment")
        pairs.add(pair)
        _validate_withheld(document["withheld"])
        withheld_names = {
            name for names in document["withheld"].values() for name in names
        }
        values = document["values"]
        if not isinstance(values, dict):
            raise ApplyError("values", "values must be an object")
        checked: dict[str, str] = {}
        for name, value in values.items():
            if not isinstance(name, str) or _NAME.fullmatch(name) is None:
                raise ApplyError("values", "invalid variable name")
            var = vars_by_name.get(name)
            if var is None:
                raise ApplyError(name, "variable is not declared")
            if name in withheld_names:
                raise ApplyError(name, "variable is also marked withheld")
            if var.cls == "secret":
                raise ApplyError(name, "secret variables cannot be harvested")
            if target_name not in var.targets:
                raise ApplyError(name, "variable does not target harvest target")
            if var.derive is not None or var.derive_vault_map:
                raise ApplyError(name, "derived variables cannot be harvested")
            if not isinstance(value, str):
                raise ApplyError(name, "harvest value must be a string")
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                raise ApplyError(name, "harvest value contains invalid Unicode")
            if secret_looking(name, value):
                raise ApplyError(name, "secret-looking values cannot be applied")
            checked[name] = value
        result.append((target_name, env, checked))
    return result


def _atomic_replace(path: Path, content: bytes, mode: int) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _unsafe_preimage_fragments(root: Path, fragments: list[Path]) -> list[str]:
    """Return affected fragment names that are not a clean, tracked HEAD pre-image."""
    try:
        root_result = _run_git(root, "rev-parse", "--show-toplevel")
        if root_result.returncode != 0:
            return sorted({fragment.name for fragment in fragments})
        repo_root = Path(root_result.stdout.decode("utf-8").strip()).resolve()
    except (OSError, UnicodeDecodeError):
        return sorted({fragment.name for fragment in fragments})

    unsafe: set[str] = set()
    for fragment in fragments:
        try:
            relative = Path(os.path.abspath(fragment)).relative_to(repo_root).as_posix()
        except ValueError:
            unsafe.add(fragment.name)
            continue
        tracked = _run_git(repo_root, "ls-files", "--error-unmatch", "--", relative)
        if tracked.returncode != 0:
            unsafe.add(fragment.name)
            continue
        index_entry = _run_git(repo_root, "ls-files", "-v", "-z", "--", relative)
        flag_tag = index_entry.stdout.partition(b" ")[0]
        # -v lowercases assume-unchanged tags; S marks skip-worktree entries.
        if index_entry.returncode != 0 or not flag_tag or flag_tag.islower() or flag_tag == b"S":
            unsafe.add(fragment.name)
            continue
        worktree_diff = _run_git(repo_root, "diff", "--quiet", "HEAD", "--", relative)
        index_diff = _run_git(repo_root, "diff", "--cached", "--quiet", "HEAD", "--", relative)
        if worktree_diff.returncode != 0 or index_diff.returncode != 0:
            unsafe.add(fragment.name)
    return sorted(unsafe)


def _input_conflicts(harvested: list[tuple[str, str, dict[str, str]]]) -> bool:
    inputs: dict[tuple[str, str], str] = {}
    conflicts: set[tuple[str, str]] = set()
    for _, env, values in harvested:
        for name, value in values.items():
            pair = (name, env)
            if pair in inputs and inputs[pair] != value:
                conflicts.add(pair)
            else:
                inputs[pair] = value
    for name, env in sorted(conflicts):
        print(f"conflict\t{name}\t{env}\tinputs", file=sys.stderr)
    return bool(conflicts)


def _stage_changes(
    manifest: Manifest, harvested: list[tuple[str, str, dict[str, str]]], prefer: bool
) -> tuple[dict[str, dict[str, str]], list[str], list[tuple[str, str]], list[tuple[str, str]]]:
    mentioned: list[str] = []
    seen_names: set[str] = set()
    requested_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    staged = {var.name: dict(var.values) for var in manifest.vars}
    conflicts: list[tuple[str, str]] = []
    seen_conflicts: set[tuple[str, str]] = set()
    for _, env, values in harvested:
        for name, new_value in values.items():
            if name not in seen_names:
                mentioned.append(name)
                seen_names.add(name)
            pair = (name, env)
            if pair not in seen_pairs:
                requested_pairs.append(pair)
                seen_pairs.add(pair)
            current = staged[name].get(env)
            if current == new_value:
                continue
            if current and not prefer:
                if pair not in seen_conflicts:
                    conflicts.append(pair)
                    seen_conflicts.add(pair)
                continue
            staged[name][env] = new_value
    return staged, mentioned, requested_pairs, conflicts


def _locate_values_lines(
    root: Path, vars_by_name: dict[str, Var], mentioned: list[str]
) -> tuple[dict[str, bytes], dict[str, int], dict[str, _ValuesLine]]:
    source_bytes: dict[str, bytes] = {}
    source_modes: dict[str, int] = {}
    line_locations: dict[str, _ValuesLine] = {}
    for name in mentioned:
        var = vars_by_name[name]
        fragment = root / "manifest.d" / var.source
        if var.source not in source_bytes:
            source_bytes[var.source] = fragment.read_bytes()
            source_modes[var.source] = stat.S_IMODE(fragment.stat().st_mode)
        line_locations[name] = _find_values_line(var, source_bytes[var.source])
    return source_bytes, source_modes, line_locations


def _render_changes(
    root: Path, vars_by_name: dict[str, Var], staged: dict[str, dict[str, str]],
    net_changes: list[tuple[str, str]], source_bytes: dict[str, bytes],
    line_locations: dict[str, _ValuesLine],
) -> dict[Path, bytes]:
    edits: dict[str, dict[int, bytes]] = {}
    for name, _ in net_changes:
        var = vars_by_name[name]
        location = line_locations[name]
        rendered = _render_values(staged[name])
        line = source_bytes[var.source].decode("utf-8").splitlines(keepends=True)[location.index]
        line_body = line.rstrip("\r\n")
        match = _VALUES_ASSIGNMENT.match(line_body)
        if match is None:
            raise ApplyError(name, "values table must be single-line")
        _, trailing = _toml_comment_parts(match.group("rhs"))
        edits.setdefault(var.source, {})[location.index] = (
            f"{location.prefix}{rendered}{trailing}{location.newline}".encode("utf-8")
        )

    updated: dict[Path, bytes] = {}
    for source_name, line_edits in edits.items():
        fragment = root / "manifest.d" / source_name
        lines = source_bytes[source_name].decode("utf-8").splitlines(keepends=True)
        for index, replacement in line_edits.items():
            lines[index] = replacement.decode("utf-8")
        updated[fragment] = "".join(lines).encode("utf-8")

    return updated


def _write_and_validate(
    root: Path, updated: dict[Path, bytes], source_bytes: dict[str, bytes], source_modes: dict[str, int]
) -> int:
    original_bytes = {root / "manifest.d" / source: raw for source, raw in source_bytes.items()}
    unsafe = _unsafe_preimage_fragments(root, list(updated))
    if unsafe:
        for name in unsafe:
            print(f"error\tfragment\tunsafe pre-image\t{name}", file=sys.stderr)
        return 2

    attempted: list[Path] = []
    try:
        for fragment, content in updated.items():
            attempted.append(fragment)
            source_name = fragment.name
            _atomic_replace(fragment, content, source_modes[source_name])
        load_manifest(root)
    except Exception:
        restore_errors: list[Exception] = []
        for fragment in reversed(attempted):
            try:
                _atomic_replace(fragment, original_bytes[fragment], source_modes[fragment.name])
            except Exception as exc:
                restore_errors.append(exc)
        if restore_errors:
            print("error\tmanifest\tapply failed; rollback failed", file=sys.stderr)
        else:
            print("error\tmanifest\tapply failed; files restored", file=sys.stderr)
        return 2

    return 0


def _apply_changes(root: Path, manifest: Manifest, harvested: list[tuple[str, str, dict[str, str]]], prefer: bool) -> int:
    if _input_conflicts(harvested):
        return 3
    vars_by_name = {var.name: var for var in manifest.vars}
    staged, mentioned, requested_pairs, conflicts = _stage_changes(manifest, harvested, prefer)
    root = Path(root)
    try:
        source_bytes, source_modes, line_locations = _locate_values_lines(root, vars_by_name, mentioned)
    except (OSError, ApplyError) as exc:
        if isinstance(exc, ApplyError):
            print(f"error\t{exc.field}\t{exc.reason}", file=sys.stderr)
        else:
            print("error\tfragment\tcannot read", file=sys.stderr)
        return 2
    if conflicts:
        for name, env in conflicts:
            print(f"conflict\t{name}\t{env}", file=sys.stderr)
        return 3
    net_changes = [
        (name, env) for name, env in requested_pairs
        if vars_by_name[name].values.get(env) != staged[name].get(env)
    ]
    if not net_changes:
        return 0
    try:
        updated = _render_changes(root, vars_by_name, staged, net_changes, source_bytes, line_locations)
    except ApplyError as exc:
        print(f"error\t{exc.field}\t{exc.reason}", file=sys.stderr)
        return 2
    code = _write_and_validate(root, updated, source_bytes, source_modes)
    if code:
        return code
    for name, env in net_changes:
        print(f"set\t{name}\t{env}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply harvested non-secret values to manifest fragments")
    parser.add_argument("--root", required=True, type=Path, help="environment manifest root")
    parser.add_argument("--prefer-harvest", action="store_true", help="replace conflicting manifest values")
    parser.add_argument("json", nargs="+", type=Path, help="harvest JSON files")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.root)
    except Exception:
        print("error\tmanifest\tinvalid", file=sys.stderr)
        return 2
    try:
        documents = [document for path in args.json for document in _decode_input(path)]
        harvested = _validate_documents(documents, manifest)
    except ApplyError as exc:
        print(f"error\t{exc.field}\t{exc.reason}", file=sys.stderr)
        return 2
    except Exception:
        print("error\tinput\tinvalid", file=sys.stderr)
        return 2
    return _apply_changes(args.root, manifest, harvested, args.prefer_harvest)


if __name__ == "__main__":
    raise SystemExit(main())
