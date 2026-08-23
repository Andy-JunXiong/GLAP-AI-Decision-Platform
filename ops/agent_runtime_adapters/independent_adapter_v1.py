"""Independent local implementation of the frozen Agent Runtime v1 behavior."""


def run_adapter(request):
    visible_evidence = request["evidence"]
    visible_memory = request["decision_memory"]
    matching_memory_ids = [
        memory["memory_id"]
        for memory in visible_memory
        if memory["context_key"] == request["context_key"]
    ]
    high_external_ids = [
        signal["evidence_id"]
        for signal in visible_evidence
        if (signal["evidence_type"], signal["severity"])
        == ("EXTERNAL_EVENT", "HIGH")
    ]
    bounded_review_required = len(high_external_ids) + len(matching_memory_ids) > 0
    if bounded_review_required:
        recommendation, priority = "REQUEST_BOUNDED_REVIEW", "HIGH"
        rationale = "Cutoff-eligible controlled evidence or reviewed memory supports a bounded simulated review request."
    else:
        recommendation, priority = "MONITOR_EVIDENCE", "MEDIUM"
        rationale = "No qualifying controlled input is visible; continue the evaluation-only evidence watch."

    tool_names = (
        "get_evidence",
        "get_similar_decisions",
        "propose_action",
        "request_approval",
    )
    result_sets = (
        [signal["evidence_id"] for signal in visible_evidence],
        matching_memory_ids,
        [],
        [],
    )
    calls = [
        {
            "sequence": position,
            "tool": name,
            "mode": request["tool_modes"][name],
            "result_ids": result_sets[position - 1],
        }
        for position, name in enumerate(tool_names, start=1)
    ]
    return {
        "tool_calls": calls,
        "proposal": {
            "status": "EVALUATION_PROPOSAL_ONLY",
            "recommendation": recommendation,
            "priority": priority,
            "human_review_required": bounded_review_required,
            "rationale": rationale,
        },
        "approval_result": {
            "status": "SIMULATED_PENDING_HUMAN_REVIEW",
            "authority_granted": False,
            "operational_action_created": False,
        },
        "operational_mutations": [],
    }
