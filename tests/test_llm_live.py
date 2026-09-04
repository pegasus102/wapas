"""
tests/test_llm_live.py
----------------------
The AI slot's contract, without any network:
  - live mode uses a SEPARATE cache file (real AI responses never silently
    mix with the deterministic stand-in's)
  - malformed provider output is repaired, never trusted
  - fallback results are NOT persisted to the live cache (a later live run
    retries the API)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wapas import llm_agent
from wapas.schema import EvidencePacket


def _packet(**over) -> EvidencePacket:
    base = dict(
        event_id="evt_test_1", customer_id="cust_t1", invoice_id="inv_t1",
        attempt_no=1, amount=999.0, method="upi", geo_tier="metro",
        timestamp_ist="2026-08-05T13:00:00+05:30", tenure_days=200,
        mandate_status="none", retry_count=0, error_code="SERVER_ERROR",
        error_source="customer", error_reason="PAYMENT_FAILED",
        error_step="payment_initiation", bank_health_score=0.7,
        attempts_today=1, debit_confirmation_flag=False,
        free_text="paise kat gaye the",
    )
    base.update(over)
    return EvidencePacket(**base)


def test_live_and_offline_use_separate_caches(tmp_path, monkeypatch):
    live_p, main_p = tmp_path / "live.json", tmp_path / "main.json"
    ev = _packet()
    hint = {"root_cause": "intent_drop", "confidence": 0.4, "action": "send_payment_link",
            "resolved": False, "needs_llm": True, "basis": "test"}

    monkeypatch.setattr(llm_agent, "_call_openrouter", lambda e: {
        "root_cause": "wrong_vpa", "confidence": 0.7, "action": "send_payment_link",
        "evidence_citations": ["free_text"], "draft_message": "fresh link",
        "source": "llm_openrouter:test", "model": "test"})

    out_live = llm_agent.diagnose(ev, rules_hint=hint, live=True, cache_path=live_p)
    out_off = llm_agent.diagnose(ev, rules_hint=hint, live=False, cache_path=main_p)

    assert out_live["source"] == "llm_openrouter:test"
    assert out_off["source"] == "llm_heuristic"
    # each cache exists, and each contains ONLY its own kind of response
    assert live_p.exists() and main_p.exists()
    live_entries = list(json.loads(live_p.read_text()).values())
    main_entries = list(json.loads(main_p.read_text()).values())
    assert all(e["source"] == "llm_openrouter:test" for e in live_entries)
    assert all(e["source"] == "llm_heuristic" for e in main_entries)


def test_malformed_live_output_is_repaired_not_trusted(tmp_path, monkeypatch):
    live_p = tmp_path / "live.json"
    ev = _packet()
    hint = {"root_cause": "intent_drop", "confidence": 0.4, "action": "send_payment_link",
            "resolved": False, "needs_llm": True, "basis": "test"}

    monkeypatch.setattr(llm_agent, "_call_openrouter", lambda e: {
        "root_cause": "NOT_A_REAL_CAUSE", "confidence": 0.9, "action": "retry_now"})

    out = llm_agent.diagnose(ev, rules_hint=hint, live=True, cache_path=live_p)
    # malformed provider output is discarded -> evidence-based heuristic answers
    # (free_text says "paise kat gaye" -> debited_pending); never the garbage
    assert out["root_cause"] == "debited_pending"
    assert out["source"] == "llm_heuristic"
    assert not live_p.exists()   # garbage/fallback never persisted to live cache


def test_fallback_not_persisted_to_live_cache(tmp_path, monkeypatch):
    live_p = tmp_path / "live.json"
    ev = _packet()
    hint = {"root_cause": "intent_drop", "confidence": 0.4, "action": "send_payment_link",
            "resolved": False, "needs_llm": True, "basis": "test"}

    monkeypatch.setenv("OPENROUTER_API_KEY", "")        # no key
    monkeypatch.setattr(llm_agent, "_call_openrouter", lambda e: None)
    monkeypatch.setattr(llm_agent, "_call_live_llm", lambda e: None)  # provider down

    out = llm_agent.diagnose(ev, rules_hint=hint, live=True, cache_path=live_p)
    assert out["source"] == "llm_heuristic"
    assert not live_p.exists()   # fallback returned, but live cache stays pure
