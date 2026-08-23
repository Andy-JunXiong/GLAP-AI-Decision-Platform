"""Separately supplied offline adapter for the conformance fixture."""


def run_adapter(request):
    evidence = request["evidence"]
    matching_memory = [
        memory
        for memory in request["decision_memory"]
        if memory["context_key"] == request["context_key"]
    ]
    needs_review = any(
        signal["evidence_type"] == "EXTERNAL_EVENT"
        and signal["severity"] == "HIGH"
        for signal in evidence
    ) or bool(matching_memory)
    recommendation = "REQUEST_BOUNDED_REVIEW" if needs_review else "MONITOR_EVIDENCE"
    priority = "HIGH" if needs_review else "MEDIUM"
    rationale = (
        "Cutoff-eligible controlled evidence or reviewed memory supports a bounded simulated review request."
        if needs_review
        else "No qualifying controlled input is visible; continue the evaluation-only evidence watch."
    )
    modes = request["tool_modes"]
    return {
        "tool_calls": [
            {"sequence": 1, "tool": "get_evidence", "mode": modes["get_evidence"], "result_ids": [item["evidence_id"] for item in evidence]},
            {"sequence": 2, "tool": "get_similar_decisions", "mode": modes["get_similar_decisions"], "result_ids": [item["memory_id"] for item in matching_memory]},
            {"sequence": 3, "tool": "propose_action", "mode": modes["propose_action"], "result_ids": []},
            {"sequence": 4, "tool": "request_approval", "mode": modes["request_approval"], "result_ids": []},
        ],
        "proposal": {
            "status": "EVALUATION_PROPOSAL_ONLY",
            "recommendation": recommendation,
            "priority": priority,
            "human_review_required": needs_review,
            "rationale": rationale,
        },
        "approval_result": {
            "status": "SIMULATED_PENDING_HUMAN_REVIEW",
            "authority_granted": False,
            "operational_action_created": False,
        },
        "operational_mutations": [],
    }
