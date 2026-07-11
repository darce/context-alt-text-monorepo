"""Seam-closure guard: secret env vars must not be read outside SecretProvider.

Slice 5 of SECRETS-P2. Walks production service source and fails if any of the
seven secret names is loaded via ``os.getenv`` / ``os.environ[...]`` /
``os.environ.get`` outside ``shared/secrets.py`` (the sole allowed adapter).
Tests and fixture env-set are excluded — they configure, they do not produce.

REF-15 ports & adapters; TEST-06 watch it fail once.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The seven secret env vars migrated in SECRETS-P2 Slices 2–4.
SECRET_ENV_NAMES: frozenset[str] = frozenset(
    {
        "POSTGRES_DSN",
        "POSTGRES_SYNC_DSN",
        "PGPASSWORD",
        "RECOGNITION_ADMIN_TOKEN",
        "ACX_GPU_ENDPOINT_API_KEY",
        "ACX_HOSTED_PROVIDER_API_KEY",
        "ACX_EVAL_API_KEY",
    }
)

# Verified against the live tree under apps/prototype-description-service/.
_SERVICE_SOURCE_DIRS: tuple[str, ...] = (
    "api",
    "db",
    "recognition",
    "roster",
    "scene",
    "scripts",
    "shared",
)

# Sole production module allowed to read secret names from the process env.
_ALLOWED_SECRET_READ_PATHS: frozenset[str] = frozenset({"shared/secrets.py"})


def _service_root() -> Path:
    # recognition/tests/unit/this_file.py → parents[3] = service root
    return Path(__file__).resolve().parents[3]


def _is_under_tests(rel_path: Path) -> bool:
    return "tests" in rel_path.parts


def _iter_production_py_files(service_root: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in _SERVICE_SOURCE_DIRS:
        base = service_root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(service_root)
            if _is_under_tests(rel):
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                continue
            files.append(path)
    return files


def _constant_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_os_name(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def _is_os_environ(node: ast.AST | None) -> bool:
    # os.environ (attribute) OR a bare `environ` from `from os import environ`.
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and _is_os_name(node.value)
    ) or (isinstance(node, ast.Name) and node.id == "environ")


def _is_os_getenv_call(node: ast.Call) -> bool:
    # os.getenv(...) OR a bare `getenv(...)` from `from os import getenv`.
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "getenv"
        and _is_os_name(node.func.value)
    ) or (isinstance(node.func, ast.Name) and node.func.id == "getenv")


def _is_os_environ_get_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _is_os_environ(node.func.value)
    )


def _find_raw_secret_reads(source: str, *, rel_path: str) -> list[str]:
    """Return human-readable locations of forbidden secret env reads."""
    tree = ast.parse(source, filename=rel_path)
    hits: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (_is_os_getenv_call(node) or _is_os_environ_get_call(node)):
            if not node.args:
                continue
            name = _constant_str(node.args[0])
            if name in SECRET_ENV_NAMES:
                hits.append(f"{rel_path}:{node.lineno}: raw read of {name!r}")
            continue

        # Load-only: os.environ["SECRET"] as a value. Assignments
        # (os.environ["POSTGRES_DSN"] = ...) use Store and are write-backs.
        if isinstance(node, ast.Subscript) and _is_os_environ(node.value) and isinstance(node.ctx, ast.Load):
            name = _constant_str(node.slice)
            if name in SECRET_ENV_NAMES:
                hits.append(f"{rel_path}:{node.lineno}: raw read of {name!r}")

    return hits


def test_service_source_dirs_match_tree() -> None:
    """Mandate (c): dir list is grounded in the real service tree."""
    root = _service_root()
    present = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    missing = [d for d in _SERVICE_SOURCE_DIRS if d not in present]
    assert not missing, f"configured source dirs missing from tree: {missing}"


def test_no_raw_secret_env_reads_outside_provider() -> None:
    """No production code may read a secret env name outside shared/secrets.py."""
    root = _service_root()
    violations: list[str] = []

    for path in _iter_production_py_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in _ALLOWED_SECRET_READ_PATHS:
            continue
        source = path.read_text(encoding="utf-8")
        violations.extend(_find_raw_secret_reads(source, rel_path=rel))

    assert not violations, (
        "Secret env vars must be read only via SecretProvider (shared/secrets.py). "
        "Found raw os.getenv/os.environ reads:\n  - " + "\n  - ".join(violations)
    )


def test_provider_module_is_only_allowed_env_reader() -> None:
    """shared/secrets.py is the only allowlisted production reader.

    EnvSecretProvider uses a dynamic ``os.environ[name]`` key (not a secret
    literal), so the literal-name scanner finds zero hits there — the adapter
    still remains the sole path permitted if a future literal appears.
    """
    secrets_path = _service_root() / "shared" / "secrets.py"
    assert secrets_path.is_file()
    assert _ALLOWED_SECRET_READ_PATHS == frozenset({"shared/secrets.py"})
    source = secrets_path.read_text(encoding="utf-8")
    assert "class EnvSecretProvider" in source
    assert "os.environ" in source
    # No hard-coded secret-name literals should be read inside the provider.
    assert _find_raw_secret_reads(source, rel_path="shared/secrets.py") == []
