"""
wapas.llm_agent
----------------
Called ONLY for the ~35% of events the rules tier marks `needs_llm`. This is
the ONLY place in the entire system that is allowed to exercise "AI
judgment" — and even here, its output is schema-validated and then handed
to a 100%-deterministic policy gate that can override or reject it.

Offline-first contract:
  - Every diagnosis is cached to disk keyed on a hash of the evidence
    content (not the event_id, so it's robust to relabelling) + a prompt
    version string.
  - `make run` / `make batch` NEVER require an API key: if the cache has no
    entry, we fall back to a deterministic, feature-based heuristic that
    stands in for an LLM call — same JSON schema, same fixed action menu,
    genuinely imperfect (it does NOT see the hidden true_cause; its errors
    come from the same feature overlap a real model would have to resolve).
  - `--live` opts in to a real Anthropic API call (schema-forced JSON) when
    ANTHROPIC_API_KEY is set. Swapping the heuristic for a real model later
    is a one-function change; nothing else in the pipeline needs to know.
"""

from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Optional

from .schema import EvidencePacket, CAUSES, ACTIONS, ORACLE_ACTION

PROMPT_VERSION = "v1"
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "diagnosis_cache.json"
LIVE_CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "diagnosis_cache_live.json"

# OpenRouter (OpenAI-compatible REST; stdlib urllib — no new dependencies).
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "google/gemma-4-31b-it:free"
# Free-model pools get saturated independently, so a 429 on one model says
# nothing about the others. On rate limits we walk this chain; whichever
# model actually answers is recorded in the response's `source` tag, so
# provenance stays honest. All verified present in OpenRouter's free
# catalog on 2026-09-05.
OPENROUTER_FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "z-ai/glm-5.2:free",
    "minimax/minimax-m3:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "inclusionai/ling-3.0-flash-fin:free",
]
# Once a model rate-limits us, bench it for a while so batch runs don't
# hammer a saturated pool on every single event.
_MODEL_COOLDOWN: dict = {}
COOLDOWN_SECONDS = 180.0


def _model_chain() -> list:
    """OPENROUTER_MODEL overrides the HEAD of the chain (comma-separate for
    several); the remaining built-in free models follow, so a user who set
    the old single-model env var still gets automatic failover."""
    env = os.environ.get("OPENROUTER_MODEL", "").strip()
    head = [m.strip() for m in env.split(",") if m.strip()] if env else OPENROUTER_FALLBACK_MODELS[:1]
    tail = [m for m in OPENROUTER_FALLBACK_MODELS if m not in head]
    return head + tail

# Human-readable reason the most recent live call failed ("" on success).
# Surfaced by scripts/live_demo.py so a silent fallback can never masquerade
# as a real AI response.
LAST_LIVE_ERROR: str = ""


def set_last_live_error(msg: str) -> None:
    global LAST_LIVE_ERROR
    LAST_LIVE_ERROR = msg


def is_real_provider(source: str) -> bool:
    """True only for responses produced by an actual LLM provider.
    Exact matching on purpose: "llm_heuristic" (the deterministic stand-in)
    also starts with "llm_" and must NEVER count as real."""
    s = str(source)
    return s.startswith("llm_openrouter") or s == "llm_live"


def _load_dotenv() -> None:
    """Tiny stdlib .env loader: KEY=VALUE lines from ROOT/.env. Existing env wins."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

SYSTEM_PROMPT = """You are a payment-failure root-cause diagnosis assistant for an Indian \
D2C merchant on Razorpay. Given a structured evidence packet, return ONLY a JSON object \
with keys: root_cause (one of {causes}), confidence (0..1), action (one of {actions}), \
evidence_citations (list of short strings pointing at specific evidence fields), \
draft_message (a short customer-facing message, Hinglish allowed). \
You never invent an action outside the given menu. If genuinely uncertain, lower \
confidence rather than guessing with false certainty.""".format(
    causes=", ".join(CAUSES), actions=", ".join(ACTIONS)
)


def _cache_key(evidence: EvidencePacket) -> str:
    payload = {
        "error_reason": evidence.error_reason,
        "bank_health_score": evidence.bank_health_score,
        "attempts_today": evidence.attempts_today,
        "debit_confirmation_flag": evidence.debit_confirmation_flag,
        "free_text": evidence.free_text,
        "error_source": evidence.error_source,
        "method": evidence.method,
        "prompt_version": PROMPT_VERSION,
    }
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _load_cache(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _validate(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("root_cause") not in CAUSES:
        return False
    if result.get("action") not in ACTIONS:
        return False
    conf = result.get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
        return False
    return True


def _heuristic_diagnose(evidence: EvidencePacket, rules_hint: dict) -> dict:
    """
    Deterministic, evidence-only stand-in for an LLM call. Does NOT see
    true_cause. Its accuracy comes purely from how informative the evidence
    fields are for the ambiguous buckets, same as a real model would face.
    """
    reason = evidence.error_reason

    if reason == "BANK_DECLINED":
        # Soft nearest-centroid over (bank_health_score, attempts_today),
        # a slightly richer read of the same features the rules tier only
        # thresholds hard on.
        centers = {
            "bank_outage": (0.15, 1.0),
            "bank_decline": (0.60, 1.0),
            "upi_daily_limit": (0.60, 4.0),
        }
        x = (evidence.bank_health_score, float(evidence.attempts_today))
        dists = {
            c: math.dist(x, ctr) for c, ctr in centers.items()
        }
        best = min(dists, key=dists.get)
        d_sorted = sorted(dists.values())
        margin = (d_sorted[1] - d_sorted[0]) if len(d_sorted) > 1 else 1.0
        confidence = max(0.4, min(0.88, 0.55 + margin * 0.25))
        return {
            "root_cause": best,
            "confidence": round(confidence, 3),
            "action": ORACLE_ACTION[best],
            "evidence_citations": ["bank_health_score", "attempts_today"],
            "draft_message": _draft_message(best),
            "source": "llm_heuristic",
        }

    if reason == "PAYMENT_FAILED":
        text = (evidence.free_text or "").lower()
        if any(k in text for k in ("kat gaye", "deducted", "paise")):
            best, confidence = "debited_pending", 0.72
        elif evidence.error_source == "customer":
            best, confidence = "wrong_vpa", 0.60
        else:
            best, confidence = "intent_drop", 0.55
        return {
            "root_cause": best,
            "confidence": confidence,
            "action": ORACLE_ACTION[best],
            "evidence_citations": ["free_text", "error_source"],
            "draft_message": _draft_message(best),
            "source": "llm_heuristic",
        }

    # Should be unreachable (rules tier only escalates the two buckets
    # above) but never crash — fall back to the rules hint verbatim.
    return {**rules_hint, "source": "llm_heuristic_fallback"}


def _draft_message(cause: str) -> str:
    templates = {
        "bank_outage": "We noticed your bank had a temporary issue — we'll retry automatically once it clears.",
        "bank_decline": "Your last payment attempt didn't go through. We'll retry shortly.",
        "upi_daily_limit": "Looks like today's UPI limit was hit — we'll retry tomorrow, or try another method now.",
        "debited_pending": "We're confirming whether your payment was received — no action needed from you yet.",
        "wrong_vpa": "The UPI ID entered didn't match — here's a fresh payment link.",
        "intent_drop": "Your checkout didn't complete — here's a link to finish it.",
    }
    return templates.get(cause, "We're following up on your recent payment.")


def _call_openrouter(evidence: EvidencePacket) -> Optional[dict]:
    """Real LLM call via OpenRouter (OpenAI-compatible REST, stdlib urllib).
    Needs OPENROUTER_API_KEY. Walks the free-model chain on rate limits
    (429/404: one quick retry, then the next model; benched models are
    skipped for COOLDOWN_SECONDS). 401/402 (bad key / no credits) fail fast
    — those are true for every model. Returns None on total failure so the
    caller falls back gracefully (recorded as such — never 'AI-washed')."""
    import urllib.request
    import urllib.error
    import time as _time

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        set_last_live_error("no OPENROUTER_API_KEY in environment")
        return None

    now = _time.time()
    chain = [m for m in _model_chain() if now - _MODEL_COOLDOWN.get(m, 0) >= COOLDOWN_SECONDS]
    chain = chain or _model_chain()  # everything benched -> try anyway
    errors = []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/pegasus102/wapas",
        "X-Title": "WAPAS revenue recovery",
    }
    base_payload = {
        "max_tokens": 400,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(evidence.to_dict(), default=str)},
        ],
    }

    for model in chain:
        payload = dict(base_payload, model=model)
        for attempt in range(2):  # one retry per model on transient/429
            try:
                req = urllib.request.Request(
                    OPENROUTER_URL, data=json.dumps(payload).encode("utf-8"),
                    headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=25) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                text = body["choices"][0]["message"]["content"].strip()
                text = text.removeprefix("```json").removeprefix("```")
                text = text.removesuffix("```").strip()
                result = json.loads(text)
                result["source"] = f"llm_openrouter:{model}"
                result["model"] = model
                _MODEL_COOLDOWN.pop(model, None)
                set_last_live_error("")  # success clears any stale error
                return result
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    detail = ""
                msg = f"[{model}] HTTP {e.code}: {detail}".strip()
                if e.code in (401, 402):  # key/credits problem — same for all models
                    set_last_live_error(msg)
                    return None
                if e.code in (429, 502, 503) and attempt == 0:
                    _time.sleep(5)   # brief backoff, one retry on same model
                    continue
                errors.append(msg)
                if e.code in (429, 404):
                    _MODEL_COOLDOWN[model] = _time.time()  # bench saturated/dead model
                break  # next model
            except Exception as e:
                errors.append(f"[{model}] {type(e).__name__}: {e}")
                break
    set_last_live_error("; ".join(errors) if errors else "all OpenRouter attempts failed")
    return None


def _call_live_llm(evidence: EvidencePacket) -> Optional[dict]:
    """Live provider dispatch: OpenRouter first (key via env), Anthropic
    direct as a fallback if that SDK/key is present. None -> caller falls
    back to the documented heuristic."""
    result = _call_openrouter(evidence)
    if result is not None:
        return result

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # optional dependency, only needed for --live
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    user_content = json.dumps(evidence.to_dict(), default=str)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    result["source"] = "llm_live"
    result["model"] = "claude-sonnet-4-6"
    return result


def diagnose(
    evidence: EvidencePacket,
    rules_hint: dict,
    live: bool = False,
    cache_path: Path | None = None,
) -> dict:
    # Live runs use a SEPARATE cache file: real AI responses must never be
    # silently mixed with the deterministic stand-in's. The official offline
    # run (live=False) keeps its own cache and numbers, untouched.
    if cache_path is None:
        cache_path = LIVE_CACHE_PATH if live else DEFAULT_CACHE_PATH
    cache = _load_cache(cache_path)
    key = _cache_key(evidence)

    if key in cache:
        return cache[key]

    result = None
    if live:
        result = _call_live_llm(evidence)
        if result is not None and not _validate(result):
            result = None  # malformed live response -> repair path below

    if result is None:
        result = _heuristic_diagnose(evidence, rules_hint)

    if not _validate(result):
        # Repair loop: clamp to the rules hint, flag low confidence.
        result = {
            "root_cause": rules_hint["root_cause"],
            "confidence": min(0.3, rules_hint["confidence"]),
            "action": rules_hint["action"],
            "evidence_citations": ["repair:invalid_llm_output"],
            "draft_message": _draft_message(rules_hint["root_cause"]),
            "source": "repair_fallback",
        }

    # In live mode, only REAL provider responses are persisted to the live
    # cache. Fallbacks (heuristic/repair) are returned but not saved, so a
    # later live run retries the API and the live cache stays pure provenance.
    # (Note: "llm_heuristic" deliberately does NOT count as real.)
    from_real = is_real_provider(result.get("source", ""))
    if live and not from_real:
        return result
    cache[key] = result
    _save_cache(cache_path, cache)
    return result