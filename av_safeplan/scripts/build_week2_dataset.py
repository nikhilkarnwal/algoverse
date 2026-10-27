#!/usr/bin/env python3
"""Build an immutable CPU-only dataset pilot from existing AV SafePlan logs."""

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from av_safeplan.dataset.builder import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--episode", action="append", default=[], help="Root-relative episode.jsonl; repeat to curate inputs")
    parser.add_argument("--horizon-seconds", type=float, default=3.)
    parser.add_argument("--stride-seconds", type=float, default=.2)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--training-negative-keep", type=float, default=1.)
    parser.add_argument("--previous-splits", type=Path)
    args = parser.parse_args()
    report = build(args.source_root, args.output, PROJECT, args.horizon_seconds,
                   args.stride_seconds, args.seed, args.episode, args.previous_splits,
                   args.training_negative_keep)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
