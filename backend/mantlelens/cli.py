from __future__ import annotations

import argparse
import json

from .adapters import FixtureWalletAdapter
from .risk import evaluate_wallet_risk


def main() -> None:
    parser = argparse.ArgumentParser(description="MantleLens Day 3/4 fixture scanner")
    parser.add_argument("fixture_id", help="Fixture id, e.g. high_risk_wallet")
    parser.add_argument("--raw", action="store_true", help="Print raw adapter output instead of assessment")
    args = parser.parse_args()

    adapter = FixtureWalletAdapter()
    raw_scan = adapter.scan_raw(args.fixture_id)
    output = raw_scan if args.raw else evaluate_wallet_risk(raw_scan)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
