"""
wapas.diagnosis
----------------
Top-level entry point the rest of the system calls. Orchestrates:

    rules_tier.diagnose()  -- always runs first, free, deterministic
        |
        +-- resolved=True  -> done, no LLM call, source="rules"
        |
        +-- needs_llm=True -> llm_agent.diagnose() (cached / heuristic / live)
                |
                +-- if LLM's root_cause DISAGREES with the rules hint AND
                |   the LLM's own confidence is not high -> route to human
                |   (this is the "second opinion" disagreement rule)
                +-- else -> accept LLM output, source="llm"
"""

from __future__ import annotations
from .schema import EvidencePacket
from . import rules_tier, llm_agent

DISAGREEMENT_CONFIDENCE_THRESHOLD = 0.50


def diagnose_event(evidence: EvidencePacket, live: bool = False) -> dict:
    hint = rules_tier.diagnose(evidence)

    if hint["resolved"]:
        return {
            "root_cause": hint["root_cause"],
            "confidence": hint["confidence"],
            "action": hint["action"],
            "source": "rules",
            "routed_to_llm": False,
            "routed_to_human": False,
            "basis": hint["basis"],
        }

    llm_result = llm_agent.diagnose(evidence, rules_hint=hint, live=live)

    disagree = llm_result["root_cause"] != hint["root_cause"]
    low_conf = llm_result["confidence"] < DISAGREEMENT_CONFIDENCE_THRESHOLD
    routed_to_human = disagree and low_conf

    return {
        "root_cause": llm_result["root_cause"],
        "confidence": llm_result["confidence"],
        "action": "escalate_human" if routed_to_human else llm_result["action"],
        "source": llm_result.get("source", "llm"),
        "routed_to_llm": True,
        "routed_to_human": routed_to_human,
        "basis": f"rules_hint={hint['root_cause']}, llm={llm_result['root_cause']}",
        "draft_message": llm_result.get("draft_message"),
    }
