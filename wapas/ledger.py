"""
wapas.ledger
------------
Append-only, hash-chained audit ledger. Every entry stores the hash of the
PREVIOUS entry's content, so editing any row breaks every hash from that
point forward — `verify()` re-derives the chain and reports exactly where
it broke. This is the `make verify` live-tamper demo.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path


GENESIS_HASH = "0" * 64


def _entry_hash(prev_hash: str, content: dict) -> str:
    blob = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256((prev_hash + blob).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict] = []
        if self.path.exists():
            with open(self.path) as f:
                self._entries = [json.loads(line) for line in f if line.strip()]

    def append(self, content: dict) -> dict:
        prev_hash = self._entries[-1]["entry_hash"] if self._entries else GENESIS_HASH
        h = _entry_hash(prev_hash, content)
        entry = {"prev_hash": prev_hash, "content": content, "entry_hash": h}
        self._entries.append(entry)
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def all(self) -> list[dict]:
        return list(self._entries)

    def verify(self) -> dict:
        """Recomputes the chain from scratch. Returns {"ok": bool, "broken_at": int|None}."""
        prev_hash = GENESIS_HASH
        for i, entry in enumerate(self._entries):
            expected = _entry_hash(prev_hash, entry["content"])
            if expected != entry["entry_hash"] or entry["prev_hash"] != prev_hash:
                return {"ok": False, "broken_at": i}
            prev_hash = entry["entry_hash"]
        return {"ok": True, "broken_at": None}
