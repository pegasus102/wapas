#!/usr/bin/env python3
"""
scripts/verify_readme.py
--------------------------
Regenerates out/RESULTS.md from a clean run and diffs it against the copy
already on disk (which README.md is meant to match). Exits non-zero on any
mismatch. This is what `make verify-results` and the CI results-verify
step run — it's what turns "the numbers are real" from a claim into an
enforced, checkable invariant.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    existing_path = ROOT / "out" / "RESULTS.md"
    if not existing_path.exists():
        print("No existing out/RESULTS.md to compare against — run `make batch` first.")
        sys.exit(1)
    existing = existing_path.read_text()

    fresh_dir = ROOT / "out_verify_tmp"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_batch.py"), "--out", str(fresh_dir.relative_to(ROOT))],
        cwd=ROOT, check=True,
    )
    fresh = (fresh_dir / "RESULTS.md").read_text()

    if fresh != existing:
        print("MISMATCH: freshly regenerated results differ from the committed out/RESULTS.md")
        print("--- committed ---")
        print(existing)
        print("--- freshly regenerated ---")
        print(fresh)
        sys.exit(1)

    print("OK: results-verify passed — RESULTS.md is byte-identical to a clean regeneration.")
    sys.exit(0)


if __name__ == "__main__":
    main()