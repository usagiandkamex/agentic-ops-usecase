#!/usr/bin/env python3
"""Bundled, reviewed CLI for use case 005 (Azure retirement report).

Agents run only these subcommands; they must not write or run any other script.
Every subcommand prints one JSON object (with a "next" hint) to stdout.
Exit codes: 0 = ok, 1 = gate failed, 2 = usage / state error, 3 = network error.
Python 3.9+ standard library only. Network: HTTPS GET to the Release Communications API only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from retirement_lib import api, merge, plan, progress, render, shards  # noqa: E402
from retirement_lib.common import TOOL_VERSION, ToolError, resolve_run  # noqa: E402


def _scope_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scope", required=True, choices=api.SCOPE_TYPES)
    p.add_argument("--start", help="custom scope start month (YYYY-MM)")
    p.add_argument("--end", help="custom scope end month (YYYY-MM)")
    p.add_argument("--as-of", dest="as_of", help="as-of date (YYYY-MM-DD, JST). Defaults to today in JST")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="retirement_tool.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=TOOL_VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="step 2: API availability and candidate counts (writes nothing)")
    _scope_args(p)
    p = sub.add_parser("init", help="step 3: create the run folder, state and progress.md (after approval)")
    _scope_args(p)
    p.add_argument("--mrc-mcp", dest="mrc_mcp", required=True, choices=("available", "unavailable"))

    def run_cmd(name: str, help_: str) -> argparse.ArgumentParser:
        q = sub.add_parser(name, help=help_)
        q.add_argument("--run", required=True, help="run folder name (YYYYMMDD-HHmmss) or its path")
        return q

    run_cmd("enumerate", "step 4: enumerate candidates and write the same-target request")
    q = run_cmd("record-same-target", "step 4: record LLM same-target pairs")
    q.add_argument("--pairs", help='"id,id;id,id"')
    q.add_argument("--none", action="store_true", help="no same-target pairs")
    run_cmd("plan-batches", "step 4: duplicate-candidate groups, batches, findings skeleton (G1)")
    q = run_cmd("next-wave", "step 5: dispatch the next wave of worker batches")
    q.add_argument("--max", type=int, default=6)
    run_cmd("check-shards", "step 5: validate worker shards, plan retries (G2)")
    run_cmd("merge", "step 6: merge, score and aggregate into findings.json (G3)")
    q = run_cmd("set-highlight", "step 6: record the summary text")
    q.add_argument("--text", required=True)
    run_cmd("render", "step 7: render index.html / retirements.csv and run the report gates (G4)")
    run_cmd("verify", "re-run G3 / G4 read-only")
    q = run_cmd("record-review", "step 7: record the independent review result")
    q.add_argument("--result", required=True, choices=("pass", "fail"))
    q.add_argument("--note", default="")
    run_cmd("finalize", "step 8: final gate check and .work/ removal")
    q = sub.add_parser("status", help="resume: current phase and next action (all runs when --run is omitted)")
    q.add_argument("--run")
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    handlers = {
        "enumerate": api.cmd_enumerate, "record-same-target": plan.cmd_record_same_target,
        "plan-batches": plan.cmd_plan_batches, "next-wave": plan.cmd_next_wave, "check-shards": shards.cmd_check_shards,
        "merge": merge.cmd_merge, "set-highlight": merge.cmd_set_highlight, "render": render.cmd_render,
        "verify": render.cmd_verify, "record-review": render.cmd_record_review, "finalize": render.cmd_finalize,
    }
    try:
        if args.cmd == "probe":
            out = api.cmd_probe(args)
        elif args.cmd == "init":
            out = api.cmd_init(args)
        elif args.cmd == "status":
            out = progress.cmd_status(args)
        else:
            out = handlers[args.cmd](args, resolve_run(args.run))
        print(json.dumps({"ok": True, **out}, ensure_ascii=False, indent=2))
        return 0
    except ToolError as e:
        print(json.dumps({"ok": False, "error": str(e), **e.extra}, ensure_ascii=False, indent=2))
        return e.code


if __name__ == "__main__":
    sys.exit(main())
