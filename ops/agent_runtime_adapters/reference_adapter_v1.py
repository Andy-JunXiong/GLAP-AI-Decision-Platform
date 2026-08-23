"""Deterministic reference implementation for Agent Runtime v1."""


def run_adapter(request):
    evidence = request["evidence"]
    matching_memories = [
        item
        for item in request["decision_memory"]
        if item["context_key"] == request["context_key"]
    ]
    request_review = any(
        item["evidence_type"] == "EXTERNAL_EVENT" and item["severity"] == "HIGH"
        for item in evidence
    ) or bool(matching_memories)
    proposal = {
        "status": "EVALUATION_PROPOSAL_ONLY",
        "recommendation": "REQUEST_BOUNDED_REVIEW" if request_review else "MONITOR_EVIDENCE",
        "priority": "HIGH" if request_review else "MEDIUM",
        "human_review_required": request_review,
        "rationale": (
            "Cutoff-eligible controlled evidence or reviewed memory supports a bounded simulated review request."
            if request_review
            else "No qualifying controlled input is visible; continue the evaluation-only evidence watch."
        ),
    }
    modes = request["tool_modes"]
    return {
        "tool_calls": [
            {"sequence": 1, "tool": "get_evidence", "mode": modes["get_evidence"], "result_ids": [item["evidence_id"] for item in evidence]},
            {"sequence": 2, "tool": "get_similar_decisions", "mode": modes["get_similar_decisions"], "result_ids": [item["memory_id"] for item in matching_memories]},
            {"sequence": 3, "tool": "propose_action", "mode": modes["propose_action"], "result_ids": []},
            {"sequence": 4, "tool": "request_approval", "mode": modes["request_approval"], "result_ids": []},
        ],
        "proposal": proposal,
        "approval_result": {
            "status": "SIMULATED_PENDING_HUMAN_REVIEW",
            "authority_granted": False,
            "operational_action_created": False,
        },
        "operational_mutations": [],
    }
