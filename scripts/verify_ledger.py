#!/usr/bin/env python3
"""
scripts/verify_ledger.py
---------------------------
`make verify` — recomputes the hash chain for every ledger file in out/
and reports where it breaks, if anywhere. This is the live tamper demo:
hand-edit a row in one of the out/ledger_*.jsonl files, rerun this script,
and watch it report exactly which entry broke.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wapas.ledger import Ledger


def main():
    out_dir = ROOT / "out"
    ledger_files = sorted(out_dir.glob("ledger_*.jsonl"))
    if not ledger_files:
        print("No ledger files found in out/ — run `make batch` first.")
        sys.exit(1)

    any_broken = False
    for path in ledger_files:
        ledger = Ledger(path)
        result = ledger.verify()
        if result["ok"]:
            print(f"OK    {path.name}  ({len(ledger.all())} entries, chain intact)")
        else:
            any_broken = True
            print(f"FAIL  {path.name}  CHAIN BROKEN at entry #{result['broken_at']}")

    sys.exit(1 if any_broken else 0)


if __name__ == "__main__":
    main()