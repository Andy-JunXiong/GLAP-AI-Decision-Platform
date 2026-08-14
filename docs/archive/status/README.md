# GLAP Status Archive

This directory preserves completed history and session evidence. This archive
is not current authority. It must not define priority or implementation state
and must not be read by default when planning a new slice.

Use the active documents instead:

- repository rules: [`AGENTS.md`](../../../AGENTS.md);
- long-term direction: [`DEVELOPMENT_PLAN.md`](../../../DEVELOPMENT_PLAN.md);
- current reality and Next Up:
  [`CURRENT_DEVELOPMENT_STATUS.md`](../../../CURRENT_DEVELOPMENT_STATUS.md).

## Contents

- [`CHANGELOG.md`](CHANGELOG.md): feature-level completed history;
- [`daily-logs/`](daily-logs/): monthly session evidence ledgers;
- [`handoffs/`](handoffs/): preserved dated handoff documents created before
  Documentation Architecture v1;
- [`legacy/`](legacy/): frozen snapshots of the former mixed-purpose TODO and
  implementation roadmap.

## Archive rules

1. Archived files preserve historical evidence but never redefine authority.
2. Current or pending work must be restated in
   `CURRENT_DEVELOPMENT_STATUS.md`; readers must not infer current state from an
   old handoff.
3. Completed capability summaries belong in `CHANGELOG.md`; detailed commands,
   workflow results, user-reported validation, and remaining items belong in
   the monthly daily log.
4. On the first development session on or after Monday, close the previous
   Monday–Sunday window and move expired current-week detail into the monthly
   log. This check occurs only when an agent session is active.
5. Never rewrite historical maturity. A fact recorded as local, staged,
   deployed, runtime-verified, or human-approved keeps that label.
