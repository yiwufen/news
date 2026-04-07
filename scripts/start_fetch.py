from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from collectors.eastmoney_crawler import EastMoneyCrawler


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the EastMoney fetch loop")
    parser.add_argument("--limit", type=int, default=100, help="Items per fetch")
    parser.add_argument("--interval", type=int, default=900, help="Fetch interval in seconds")
    parser.add_argument("--db", type=str, default="data/news.db", help="SQLite database path")
    args = parser.parse_args()

    crawler = EastMoneyCrawler(db_path=args.db)
    crawler.run(page_size=args.limit, continuous=True, interval=args.interval)


if __name__ == "__main__":
    main()
