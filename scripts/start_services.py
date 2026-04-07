from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / 'scripts'
CREATE_NEW_CONSOLE = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)


def _spawn(script_name: str, args: list[str]) -> None:
    script_path = SCRIPTS_DIR / script_name
    command = [sys.executable, str(script_path), *args]
    subprocess.Popen(command, cwd=REPO_ROOT, creationflags=CREATE_NEW_CONSOLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start fetch and offline services")
    parser.add_argument("--fetch-limit", type=int, default=100)
    parser.add_argument("--fetch-interval", type=int, default=900)
    parser.add_argument("--process-batch-size", type=int, default=10)
    parser.add_argument("--process-interval", type=int, default=300)
    parser.add_argument("--db", type=str, default="data/news.db")
    parser.add_argument("--graph-enabled", action="store_true")
    args = parser.parse_args()

    _spawn(
        'start_fetch.py',
        [
            '--limit', str(args.fetch_limit),
            '--interval', str(args.fetch_interval),
            '--db', args.db,
        ],
    )
    offline_args = [
        '--batch-size', str(args.process_batch_size),
        '--interval', str(args.process_interval),
        '--db', args.db,
    ]
    if args.graph_enabled:
        offline_args.append('--graph-enabled')
    _spawn('start_offline.py', offline_args)
    print('Both startup scripts were launched.')


if __name__ == '__main__':
    main()
