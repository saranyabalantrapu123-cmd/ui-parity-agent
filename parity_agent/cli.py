"""Command-line interface.

    python -m parity_agent run --demo                       # bundled Nimbus Wireless demo sites
    python -m parity_agent run --web URL --app URL [--flows flows.yaml] [--max-pages 30]
    python -m parity_agent eval [--report reports/<timestamp>]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config import DEFAULT_FLOWS, PLANTED_DIFFERENCES, REPORTS_DIR
from .evaluate import EvalResult, evaluate_report


def _print_eval(ev: EvalResult) -> None:
    print("\nEvaluation vs demo_sites/PLANTED_DIFFERENCES.yaml")
    print(f"{'category':<12}{'planted':>8}{'found':>7}{'tp':>5}{'precision':>11}{'recall':>8}")
    for s in [*ev.per_category, ev.overall]:
        print(f"{s.category:<12}{s.tp + s.fn:>8}{s.tp + s.fp:>7}{s.tp:>5}{s.precision:>11.2f}{s.recall:>8.2f}")
    for m in ev.missed:
        print(f"  missed  {m['id']} [{m['category']}] {m.get('description', '')}")
    for fp in ev.false_positives:
        print(f"  extra   {fp['finding']} [{fp['category']}] {fp['page']}: {fp['subject']}")


def cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run_audit  # heavy imports (Playwright) only when running

    web, app = (None, None) if args.demo else (args.web, args.app)
    flows = Path(args.flows) if args.flows else None
    result = run_audit(web, app, flows_path=flows, max_pages=args.max_pages, out_root=Path(args.out))
    print(f"\n{result.llm.describe()}")
    print(f"Crawled {len(result.web_pages)} web pages and {len(result.app_pages)} app screens; "
          f"{len(result.pairs)} matched pairs.")
    for fid, runs in result.flow_runs.items():
        print(f"  flow {fid:<12} web {runs['web'].step_count} steps ({'ok' if runs['web'].success else 'FAILED'}) | "
              f"app {runs['app'].step_count} steps ({'ok' if runs['app'].success else 'FAILED'})")
    print(f"{len(result.findings)} findings. Reports written to {result.out_dir}:")
    for kind, path in result.files.items():
        print(f"  {kind:<6} {path}")
    if result.evaluation:
        _print_eval(result.evaluation)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    if args.report:
        ev = evaluate_report(Path(args.report), PLANTED_DIFFERENCES)
    else:
        from .pipeline import run_audit

        result = run_audit(out_root=Path(args.out))
        assert result.evaluation is not None
        ev = result.evaluation
        print(f"Fresh demo run written to {result.out_dir}")
    _print_eval(ev)
    if ev.overall.recall < args.min_recall:
        print(f"\nRecall {ev.overall.recall:.2f} is below the required {args.min_recall:.2f}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parity_agent", description="Cross-platform (web vs app) UI parity agent.")
    parser.add_argument("-v", "--verbose", action="store_true", help="log crawl/match/flow progress")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="crawl both platforms, diff them, and write reports")
    run.add_argument("--web", help="start URL of the website (default: bundled demo web site)")
    run.add_argument("--app", help="start URL of the app / mobile web (default: bundled demo app)")
    run.add_argument("--demo", action="store_true", help="audit the bundled Nimbus Wireless demo sites")
    run.add_argument("--flows", help=f"flows YAML (default for --demo: {DEFAULT_FLOWS.name})")
    run.add_argument("--max-pages", type=int, default=30, help="max pages to crawl per platform")
    run.add_argument("--out", default=str(REPORTS_DIR), help="reports root directory")
    run.set_defaults(func=cmd_run)

    ev = sub.add_parser("eval", help="score findings against the planted differences (demo sites)")
    ev.add_argument("--report", help="evaluate an existing report directory instead of running the demo")
    ev.add_argument("--out", default=str(REPORTS_DIR), help="reports root directory for a fresh run")
    ev.add_argument("--min-recall", type=float, default=0.0, help="exit non-zero if overall recall is lower")
    ev.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    if args.command == "run" and not args.demo and bool(args.web) != bool(args.app):
        print("Pass both --web and --app (or neither / --demo for the bundled demo sites).", file=sys.stderr)
        return 2
    return args.func(args)
