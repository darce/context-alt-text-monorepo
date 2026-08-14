"""Operator CLI: preflight / run / status (score wired in S2)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.bench.driver import read_status, run_pair
from scripts.bench.preflight import preflight_pair
from scripts.bench.stack_pair import BenchError, load_stack_pair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.bench.cross_stack_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pre = sub.add_parser("preflight", help="Fail-closed health/profile/dim check")
    p_pre.add_argument("--config", required=True, help="stack-pair YAML/JSON")
    p_pre.add_argument("--out", default=None, help="optional run-dir to write per-leg preflight.json")

    p_run = sub.add_parser("run", help="ingest → analyze → cluster → export both legs")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--manifest", required=True)
    p_run.add_argument("--images-dir", default=None)
    p_run.add_argument("--out", required=True, help="../../benchmarks/results/crossbench-<stamp>/")

    p_st = sub.add_parser("status", help="read run-dir only; no network")
    p_st.add_argument("--run-dir", required=True)

    p_score = sub.add_parser("score", help="offline score on run-dir (no credentials)")
    p_score.add_argument("--run-dir", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            return _cmd_preflight(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "status":
            return _cmd_status(args)
        if args.command == "score":
            return _cmd_score(args)
    except BenchError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.command}")
    return 2


def _cmd_preflight(args: argparse.Namespace) -> int:
    pair = load_stack_pair(args.config)
    keys = {s.stack_id: os.environ.get(s.api_key_env, "") for s in pair.stacks}
    out_dir = Path(args.out) / "legs" if args.out else None
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        # Preflight must not stamp the stack-pair config bytes as the corpus manifest.
    preflight_pair(pair, out_dir=out_dir, api_keys=keys)
    print("preflight ok")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    pair = load_stack_pair(args.config)
    images_dir = args.images_dir or pair.images_dir
    run_pair(
        pair,
        manifest_path=args.manifest,
        images_dir=images_dir,
        out_dir=args.out,
        skip_preflight=False,
    )
    print(f"run complete: {args.out}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    payload = read_status(args.run_dir)
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    from scripts.bench.score_report import score_head_to_head

    path = score_head_to_head(args.run_dir)
    print(f"score complete: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
