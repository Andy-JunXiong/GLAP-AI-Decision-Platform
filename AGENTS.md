# Repository agent guidance

These instructions apply to every task in this repository.

## Development completion explanation

After completing any meaningful development deliverable, explain it to the user
in plain, non-technical language. Do not finish with only a list of changed
files, implementation details, tests, or workflow results.

For each completed deliverable, the final handoff must answer all four questions:

1. **What is it?** Describe what was built or changed and what a user or operator
   can now do. Start with everyday language; add technical terms only when they
   improve clarity.
2. **What previous capability does it connect to?** Name the upstream feature,
   data, workflow, or decision that supplies its inputs or made this work
   possible. Explain the connection, not just the component name.
3. **What next capability does it connect to?** Name the downstream consumer or
   the next logical product capability this work enables. If nothing is
   connected yet, state that boundary and what must happen before it can be
   connected.
4. **How does it help the overall project?** Explain the concrete project-level
   benefit, such as improving the operator journey, data continuity,
   reliability, auditability, delivery speed, decision quality, cost control, or
   risk reduction.

Use the user's language and this compact structure unless the user asks for
another format:

```text
Completed: <plain-language explanation of what it is>
Upstream connection: <the previous capability and how this uses it>
Downstream connection: <the next capability or the explicit boundary>
Project value: <the concrete benefit to the overall project>
Verification: <tests, quality gates, deployment, or runtime evidence>
```

When several deliverables are completed together, give each meaningful
deliverable its own four-part explanation or use a table with the same four
relationships. Clearly distinguish what is already implemented and verified
from what is only enabled, recommended, or planned next.
