"""Command line entry point: ``python -m evals.run``."""
import argparse
import sys

from .runner import run_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Frontline L3 conversation evaluations")
    parser.add_argument("--client", choices=("replay", "openai"), default="replay")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report the first OpenAI request without sending it",
    )
    args = parser.parse_args()
    try:
        if args.dry_run and args.client != "openai":
            parser.error("--dry-run is only supported with --client openai")
        code, _ = run_suite(args.client, args.runs, dry_run=args.dry_run)
        return code
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
