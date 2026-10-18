#!/usr/bin/env python3
"""Lint user-facing WordPress translation strings against the vocabulary SSOT."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "docs" / "workbay" / "contracts" / "controlled-vocabulary.json"
DEFAULT_SOURCE_ROOT = REPO_ROOT / "apps" / "prototype-wp-alt-context"
SOURCE_SUFFIXES = frozenset({".js", ".jsx", ".php", ".ts", ".tsx"})
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        "__tests__",
        "build",
        "coverage",
        "dist",
        "fixtures",
        "node_modules",
        "public",
        "tests",
        "vendor",
    }
)
TRANSLATION_CALL = re.compile(r"(?<![\w$])(__|_e|_n|_x)\s*\(")
JS_I18N_IMPORT = re.compile(
    r"(?:from\s*|require\s*\(\s*)['\"]@wordpress/i18n['\"]",
    re.MULTILINE,
)


class GateMode(str, Enum):  # noqa: UP042 - the Make gate also runs on macOS Python 3.9
    BASELINE = "baseline"
    HARD_FAIL = "hard_fail"


class VocabularyConfigError(ValueError):
    """Raised when the controlled-vocabulary artifact violates its contract."""


@dataclass(frozen=True)
class TermRule:
    banned: str
    forms: tuple[str, ...]
    say: tuple[tuple[str, str], ...]
    pattern: re.Pattern[str]

    @property
    def suggestion(self) -> str:
        if len(self.say) == 1:
            return self.say[0][1]
        return " / ".join(f"{replacement} ({usage})" for usage, replacement in self.say)


@dataclass(frozen=True)
class BaselineEntry:
    path: str
    message: str
    banned: str
    occurrences: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.message, self.banned)


@dataclass(frozen=True)
class Vocabulary:
    gate_mode: GateMode
    terms: tuple[TermRule, ...]
    known_violations: tuple[BaselineEntry, ...]


@dataclass(frozen=True)
class TranslatableMessage:
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str
    banned: str
    occurrences: int
    suggestion: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.message, self.banned)


def _expect_exact_keys(value: dict[str, Any], expected: set[str], location: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise VocabularyConfigError(f"{location}.{missing[0]} is required")
    if unknown:
        raise VocabularyConfigError(f"{location}.{unknown[0]} is not allowed")


def _nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VocabularyConfigError(f"{location} must be a non-empty string")
    return value.strip()


def _load_term(value: Any, index: int, claimed_forms: set[str]) -> TermRule:
    location = f"terms[{index}]"
    if not isinstance(value, dict):
        raise VocabularyConfigError(f"{location} must be an object")
    _expect_exact_keys(value, {"banned", "forms", "say", "definition", "rationale"}, location)
    banned = _nonempty_string(value["banned"], f"{location}.banned")
    if banned != banned.lower():
        raise VocabularyConfigError(f"{location}.banned must be lowercase")
    _nonempty_string(value["definition"], f"{location}.definition")
    _nonempty_string(value["rationale"], f"{location}.rationale")

    forms_value = value["forms"]
    if not isinstance(forms_value, list) or not forms_value:
        raise VocabularyConfigError(f"{location}.forms must be a non-empty list")
    forms: list[str] = []
    for form_index, raw_form in enumerate(forms_value):
        form = _nonempty_string(raw_form, f"{location}.forms[{form_index}]").lower()
        if form in claimed_forms:
            raise VocabularyConfigError(f"{location}.forms[{form_index}] duplicates the form {form!r}")
        if re.search(r"\s", form):
            raise VocabularyConfigError(f"{location}.forms[{form_index}] must be one word")
        claimed_forms.add(form)
        forms.append(form)
    if banned not in forms:
        raise VocabularyConfigError(f"{location}.forms must include the banned term {banned!r}")

    say_value = value["say"]
    if not isinstance(say_value, dict) or not say_value:
        raise VocabularyConfigError(f"{location}.say must be a non-empty object")
    say: list[tuple[str, str]] = []
    for usage, replacement in say_value.items():
        usage_text = _nonempty_string(usage, f"{location}.say key")
        replacement_text = _nonempty_string(replacement, f"{location}.say.{usage_text}")
        say.append((usage_text, replacement_text))

    alternatives = "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True))
    return TermRule(
        banned=banned,
        forms=tuple(forms),
        say=tuple(say),
        pattern=re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE),
    )


def _load_baseline_entry(value: Any, index: int, banned_terms: set[str]) -> BaselineEntry:
    location = f"known_violations[{index}]"
    if not isinstance(value, dict):
        raise VocabularyConfigError(f"{location} must be an object")
    _expect_exact_keys(value, {"path", "message", "banned", "occurrences"}, location)
    path = _nonempty_string(value["path"], f"{location}.path")
    relative_path = Path(path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise VocabularyConfigError(f"{location}.path must be a safe relative path")
    message = _normalize_message(_nonempty_string(value["message"], f"{location}.message"))
    banned = _nonempty_string(value["banned"], f"{location}.banned")
    if banned not in banned_terms:
        raise VocabularyConfigError(f"{location}.banned must name a term from terms")
    occurrences = value["occurrences"]
    if isinstance(occurrences, bool) or not isinstance(occurrences, int) or occurrences < 1:
        raise VocabularyConfigError(f"{location}.occurrences must be a positive integer")
    return BaselineEntry(path=path, message=message, banned=banned, occurrences=occurrences)


def load_vocabulary(path: Path) -> Vocabulary:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise VocabularyConfigError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VocabularyConfigError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise VocabularyConfigError("controlled vocabulary must be a JSON object")
    _expect_exact_keys(
        payload,
        {"schema_version", "gate_mode", "target_audience", "terms", "known_violations"},
        "controlled_vocabulary",
    )
    if payload["schema_version"] != 1:
        raise VocabularyConfigError("controlled_vocabulary.schema_version must equal 1")
    try:
        gate_mode = GateMode(payload["gate_mode"])
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(mode.value for mode in GateMode)
        raise VocabularyConfigError(f"controlled_vocabulary.gate_mode must be one of: {allowed}") from exc
    _nonempty_string(payload["target_audience"], "controlled_vocabulary.target_audience")

    terms_value = payload["terms"]
    if not isinstance(terms_value, list) or not terms_value:
        raise VocabularyConfigError("controlled_vocabulary.terms must be a non-empty list")
    claimed_forms: set[str] = set()
    terms = tuple(_load_term(value, index, claimed_forms) for index, value in enumerate(terms_value))
    banned_terms = {term.banned for term in terms}
    if len(banned_terms) != len(terms):
        raise VocabularyConfigError("controlled_vocabulary.terms contains duplicate banned terms")

    baseline_value = payload["known_violations"]
    if not isinstance(baseline_value, list):
        raise VocabularyConfigError("controlled_vocabulary.known_violations must be a list")
    baseline = tuple(_load_baseline_entry(value, index, banned_terms) for index, value in enumerate(baseline_value))
    baseline_keys = [entry.key for entry in baseline]
    if len(set(baseline_keys)) != len(baseline_keys):
        raise VocabularyConfigError("controlled_vocabulary.known_violations contains duplicate entries")
    if gate_mode is GateMode.HARD_FAIL and baseline:
        raise VocabularyConfigError("hard_fail mode requires an empty known_violations list")
    return Vocabulary(gate_mode=gate_mode, terms=terms, known_violations=baseline)


def _mask_comments(source: str) -> str:
    chars = list(source)
    index = 0
    state = "code"
    quote = ""
    while index < len(chars):
        char = chars[index]
        following = chars[index + 1] if index + 1 < len(chars) else ""
        if state == "code":
            if char in {"'", '"', "`"}:
                state = "string"
                quote = char
            elif char == "/" and following == "/":
                chars[index] = chars[index + 1] = " "
                state = "line_comment"
                index += 1
            elif char == "/" and following == "*":
                chars[index] = chars[index + 1] = " "
                state = "block_comment"
                index += 1
            elif char == "#":
                chars[index] = " "
                state = "line_comment"
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == quote:
                state = "code"
        elif state == "line_comment":
            if char == "\n":
                state = "code"
            else:
                chars[index] = " "
        elif state == "block_comment":
            if char == "*" and following == "/":
                chars[index] = chars[index + 1] = " "
                state = "code"
                index += 1
            elif char != "\n":
                chars[index] = " "
        index += 1
    return "".join(chars)


def _split_arguments(source: str, open_paren: int) -> list[tuple[str, int]]:
    arguments: list[tuple[str, int]] = []
    argument_start = open_paren + 1
    index = argument_start
    nesting = 0
    quote = ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in {"'", '"', "`"}:
            quote = char
        elif char in "[{(":
            nesting += 1
        elif char in "]}":
            if nesting > 0:
                nesting -= 1
        elif char == ")":
            if nesting == 0:
                arguments.append((source[argument_start:index], argument_start))
                return arguments
            nesting -= 1
        elif char == "," and nesting == 0:
            arguments.append((source[argument_start:index], argument_start))
            argument_start = index + 1
        index += 1
    return []


def _literal_text(argument: str) -> tuple[str, int] | None:
    pieces: list[str] = []
    first_quote = -1
    index = 0
    while index < len(argument):
        if argument[index] not in {"'", '"', "`"}:
            index += 1
            continue
        if first_quote < 0:
            first_quote = index
        quote = argument[index]
        index += 1
        piece: list[str] = []
        while index < len(argument):
            char = argument[index]
            if char == "\\" and index + 1 < len(argument):
                escaped = argument[index + 1]
                if escaped == "u" and index + 5 < len(argument):
                    codepoint = argument[index + 2 : index + 6]
                    if re.fullmatch(r"[0-9a-fA-F]{4}", codepoint):
                        piece.append(chr(int(codepoint, 16)))
                        index += 6
                        continue
                if escaped == "x" and index + 3 < len(argument):
                    codepoint = argument[index + 2 : index + 4]
                    if re.fullmatch(r"[0-9a-fA-F]{2}", codepoint):
                        piece.append(chr(int(codepoint, 16)))
                        index += 4
                        continue
                piece.append(" " if escaped in {"n", "r", "t"} else escaped)
                index += 2
                continue
            if char == quote:
                index += 1
                break
            piece.append(char)
            index += 1
        pieces.append("".join(piece))
    if first_quote < 0:
        return None
    return ("".join(pieces), first_quote)


def _normalize_message(message: str) -> str:
    return " ".join(message.split())


def _display_path(path: Path, source_root: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.relative_to(source_root).as_posix()


def extract_translatable_messages(path: Path, source_root: Path) -> list[TranslatableMessage]:
    source = path.read_text(errors="replace")
    if path.suffix != ".php" and not JS_I18N_IMPORT.search(source):
        return []
    masked = _mask_comments(source)
    messages: list[TranslatableMessage] = []
    for match in TRANSLATION_CALL.finditer(masked):
        function = match.group(1)
        arguments = _split_arguments(masked, match.end() - 1)
        argument_indexes = (0, 1) if function == "_n" else (0,)
        for argument_index in argument_indexes:
            if argument_index >= len(arguments):
                continue
            argument, argument_offset = arguments[argument_index]
            literal = _literal_text(argument)
            if literal is None:
                continue
            text, literal_offset = literal
            absolute_offset = argument_offset + literal_offset
            messages.append(
                TranslatableMessage(
                    path=_display_path(path, source_root),
                    line=masked.count("\n", 0, absolute_offset) + 1,
                    text=_normalize_message(text),
                )
            )
    return messages


def scan_sources(source_root: Path, vocabulary: Vocabulary) -> list[Violation]:
    violations: list[Violation] = []
    paths = (
        [source_root] if source_root.is_file() else sorted(path for path in source_root.rglob("*") if path.is_file())
    )
    for path in paths:
        relative_parts = path.relative_to(source_root).parts if path != source_root else (path.name,)
        if path.suffix not in SOURCE_SUFFIXES or EXCLUDED_PARTS.intersection(relative_parts):
            continue
        for message in extract_translatable_messages(path, source_root):
            for term in vocabulary.terms:
                matches = term.pattern.findall(message.text)
                if matches:
                    violations.append(
                        Violation(
                            path=message.path,
                            line=message.line,
                            message=message.text,
                            banned=term.banned,
                            occurrences=len(matches),
                            suggestion=term.suggestion,
                        )
                    )
    return violations


def _format_violation(prefix: str, violation: Violation, occurrences: int | None = None) -> str:
    count = violation.occurrences if occurrences is None else occurrences
    suffix = f" ({count} occurrences)" if count > 1 else ""
    return (
        f"{prefix} {violation.path}:{violation.line}: don't say {violation.banned!r}{suffix}; "
        f"say {violation.suggestion!r}. String: {violation.message!r}"
    )


def run(config_path: Path, source_root: Path, *, report_all: bool = False) -> int:
    vocabulary = load_vocabulary(config_path)
    if not source_root.exists():
        raise VocabularyConfigError(f"source root does not exist: {source_root}")
    violations = scan_sources(source_root, vocabulary)
    baseline_counts = Counter({entry.key: entry.occurrences for entry in vocabulary.known_violations})
    observed_counts: Counter[tuple[str, str, str]] = Counter()
    known: list[tuple[Violation, int]] = []
    introduced: list[tuple[Violation, int]] = []
    for violation in violations:
        previously_observed = observed_counts[violation.key]
        observed_counts[violation.key] += violation.occurrences
        allowance = baseline_counts[violation.key] if vocabulary.gate_mode is GateMode.BASELINE else 0
        remaining_allowance = max(0, allowance - previously_observed)
        known_count = min(violation.occurrences, remaining_allowance)
        if known_count:
            known.append((violation, known_count))
        new_count = violation.occurrences - known_count
        if new_count:
            introduced.append((violation, new_count))

    if report_all:
        for violation, count in known:
            print(_format_violation("KNOWN", violation, count))
    for violation, count in introduced:
        print(_format_violation("ERROR", violation, count))

    stale = sum(1 for key, count in baseline_counts.items() if observed_counts[key] < count)
    if stale:
        print(
            f"INFO: {stale} baseline entries are no longer fully observed; remove them in the vocabulary cleanup wave."
        )
    if introduced:
        print(f"Controlled-vocabulary check failed: {len(introduced)} new translatable string violation(s).")
        return 1
    print(f"No new controlled-vocabulary violations ({len(known)} known violation(s) remain).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--report-all",
        action="store_true",
        help="print baseline violations as well as newly introduced violations",
    )
    args = parser.parse_args(argv)
    try:
        return run(args.config.resolve(), args.source_root.resolve(), report_all=args.report_all)
    except VocabularyConfigError as exc:
        print(f"controlled-vocabulary config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
