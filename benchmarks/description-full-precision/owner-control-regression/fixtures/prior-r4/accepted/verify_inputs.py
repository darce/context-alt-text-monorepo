"""Verify every immutable manifest entry, source identity and exact AST map."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


INPUT_ROOT = Path("/home/gate/description-offline-snapshot-inputs-20261023T2231")
MANIFEST_SHA256 = "52a60cba514014701d3eb5e2f229bcfd1b2fc14a9bd4b81c4241af9b5a0b0a0a"
ORIGINAL_SOURCE_SHA256 = "e86b763b95ce9be67964b925c2f6ce7ea3c73ddbd4ababd70b4d36a95c407c2f"
REVIEW_ROOT = Path("/home/gate/description-offline-projection-review-20261023T2254")
REVIEW_MANIFEST_SHA256 = "be6fdc99e44e0dcbdc1b54d1651a315810f4ba76dad084cbeae81571d920685a"


def verify(root=INPUT_ROOT):
    manifest_raw = (root / "input-manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == MANIFEST_SHA256
    manifest = json.loads(manifest_raw)
    checks = []
    for name, expected in manifest.items():
        raw = (root / name).read_bytes()
        actual = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        assert actual == expected, (name, actual, expected)
        checks.append({"file": name, **actual, "verified": True})
    raw_source = (root / "snapshot_source.py").read_bytes()
    assert raw_source == Path(__file__).with_name("snapshot_source.py").read_bytes()
    codemap = []
    for node in ast.parse(raw_source).body:
        if isinstance(node, ast.FunctionDef):
            codemap.append({
                "name": node.name, "start": node.lineno, "end": node.end_lineno,
                "calls": sorted({
                    ast.unparse(call.func) for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                }),
            })
    assert codemap == json.loads((root / "source-ast-codemap.json").read_bytes())
    identity = json.loads((root / "original-source-identity.json").read_bytes())
    assert identity["source_sha256"] == ORIGINAL_SOURCE_SHA256
    assert identity["fixed_transport_limit_bytes"] == 60000
    assert identity["caller_line"] == 385
    return {
        "input_root": str(root), "manifest_sha256": MANIFEST_SHA256,
        "files": checks, "exact_ast_codemap_verified": True,
        "vendored_pure_source_identical": True,
        "source_identity": identity,
        "identity_limit": "Complete original source is not supplied; its identity is manifest metadata.",
    }


def baseline_contract(root=REVIEW_ROOT, inputs=INPUT_ROOT):
    """Pinned baseline caller contract; the source is parsed, never imported.

    Returns compiled AST for view()'s exact return expression and the exact
    native transport predicate, plus the reviewed R3 seed patch text.
    """
    manifest_raw = (root / "input-manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == REVIEW_MANIFEST_SHA256
    manifest = json.loads(manifest_raw)
    files = {}
    for name in ("baseline/owner-custody.py", "candidate/caller.patch"):
        raw = (root / name).read_bytes()
        assert manifest[name] == {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        files[name] = raw
    source = files["baseline/owner-custody.py"]
    assert hashlib.sha256(source).hexdigest() == ORIGINAL_SOURCE_SHA256
    text = source.decode("utf-8")
    assert "".join(text.splitlines(keepends=True)[384:387]) == (
        inputs / "caller_excerpt.txt").read_text()
    functions = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    returned = [n for n in functions["view"].body if isinstance(n, ast.Return)]
    assert len(returned) == 1 and returned[0].lineno == 171
    transport = [
        n for n in ast.walk(functions["native_job"])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "check"
        and len(n.args) == 2 and isinstance(n.args[0], ast.Compare)
        and isinstance(n.args[1], ast.Constant) and n.args[1].value == "job result budget"
        and isinstance(n.args[0].ops[0], ast.Lt)
    ]
    assert len(transport) == 1
    assert ast.unparse(transport[0]) == "check(len(encoded) < 60000, 'job result budget')"
    return {
        "view_return": compile(ast.Expression(returned[0].value), "baseline-view-return", "eval"),
        "view_return_source": ast.unparse(returned[0]),
        "transport_check": compile(ast.Expression(transport[0]), "baseline-transport", "eval"),
        "seed_patch": files["candidate/caller.patch"].decode("utf-8"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=INPUT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.inputs)
    args.output.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, indent=2) + "\n"
    (args.output / "input-verification.json").write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
