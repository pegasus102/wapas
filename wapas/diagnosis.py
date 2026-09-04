"""
wapas.diagnosis
----------------
Top-level entry point:

    rules_tier.diagnose()  -- always first; free; deterministic
        |
        +-- resolved       -> done, source="rules", no LLM call
        |
        +-- needs_llm      -> llm_agent.diagnose() (cache / fallback / --live)
                |
                +-- the ACTION is always the policy table applied to the
                |   LLM's root_cause. If the LLM's own stated action
                |   disagrees with that table, it is treated as an
                |   off-menu proposal and routed to a human.
                +-- if the LLM disagrees with the rules hint AND its own
                    confidence is low -> human (second-opinion rule)
"""

from __future__ import annotations
from .schema import EvidencePacket, CAUSE_ACTION_POLICY
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
            "human_reason": None,
            "basis": hint["basis"],
            "draft_message": None,
            "llm_model": None,
        }

    llm = llm_agent.diagnose(evidence, rules_hint=hint, live=live)
    root = llm["root_cause"]
    policy_action = CAUSE_ACTION_POLICY[root]

    reasons = []
    if root != hint["root_cause"] and llm["confidence"] < DISAGREEMENT_CONFIDENCE_THRESHOLD:
        reasons.append(f"disagrees with rules hint ({hint['root_cause']}) at confidence {llm['confidence']:.2f}")
    if llm.get("action") not in (None, policy_action):
        reasons.append(f"proposed action '{llm.get('action')}' inconsistent with cause '{root}'")
    routed_to_human = bool(reasons)

    return {
        "root_cause": root,
        "confidence": llm["confidence"],
        "action": "escalate_human" if routed_to_human else policy_action,
        "source": llm.get("source", "llm"),
        "routed_to_llm": True,
        "routed_to_human": routed_to_human,
        "human_reason": "; ".join(reasons) or None,
        "basis": f"rules_hint={hint['root_cause']} ({hint['basis']}); llm={root}",
        "draft_message": llm.get("draft_message"),
        "llm_model": llm.get("model"),
    }