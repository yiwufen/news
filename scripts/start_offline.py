from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
import sys

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / '.env')

from src.pipeline.continuous import ContinuousPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the offline processing loop")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size per run")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval in seconds")
    parser.add_argument("--db", type=str, default="data/news.db", help="SQLite database path")
    parser.add_argument("--time-window", type=str, default="", help="Optional ISO week window like 2026-W14")
    parser.add_argument("--graph-enabled", action="store_true", help="Enable graph sync")
    args = parser.parse_args()

    pipeline = ContinuousPipeline(
        batch_size=args.batch_size,
        graph_enabled=args.graph_enabled,
        incremental=True,
        db_path=args.db,
    )

    print("Starting offline processing loop ...", flush=True)
    while True:
        result = pipeline.run(time_window=args.time_window or None, dry_run=False)
        payload = asdict(result) if is_dataclass(result) else result
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
