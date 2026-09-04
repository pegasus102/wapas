import json
from pathlib import Path
from wapas.ledger import Ledger


def test_verify_passes_on_untouched_ledger(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    for i in range(5):
        ledger.append({"event_id": f"evt_{i}", "value": i})
    result = ledger.verify()
    assert result["ok"] is True
    assert result["broken_at"] is None


def test_verify_detects_tampering(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    for i in range(5):
        ledger.append({"event_id": f"evt_{i}", "value": i})

    # Tamper: rewrite entry #2's content directly on disk, as if someone
    # hand-edited the ledger file.
    lines = path.read_text().splitlines()
    entry = json.loads(lines[2])
    entry["content"]["value"] = 9999
    lines[2] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n")

    tampered_ledger = Ledger(path)
    result = tampered_ledger.verify()
    assert result["ok"] is False
    assert result["broken_at"] == 2


def test_appends_are_persisted_across_reload(tmp_path):
    path = tmp_path / "ledger.jsonl"
    Ledger(path).append({"a": 1})
    reloaded = Ledger(path)
    assert len(reloaded.all()) == 1
    reloaded.append({"a": 2})
    assert len(Ledger(path).all()) == 2
