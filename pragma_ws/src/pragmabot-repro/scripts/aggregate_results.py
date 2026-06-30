"""Re-aggregate evaluation results from existing trial JSONs.

Usage:
    python scripts/aggregate_results.py --results_dir results/table_2_stub --table table_2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.eval import ReportGenerator, ResultAggregator  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results_dir", required=True)
    p.add_argument("--table", choices=["table_2", "table_3"], default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    agg = ResultAggregator(args.results_dir)
    agg.generate_table_2_csv()
    agg.generate_table_3_csv()
    agg.generate_full_results_csv()
    agg.generate_summary_json()
    if args.table:
        agg.print_table(args.table)
    ReportGenerator(agg).generate(str(Path(args.results_dir) / "report.md"))
    print(f"Aggregates written under {Path(args.results_dir) / 'aggregate'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
