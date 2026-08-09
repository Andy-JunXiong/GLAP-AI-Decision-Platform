# Incremental refresh contract

**Status:** designed, not scheduled or materialized

All current multimodal assets remain Athena views. This contract defines how a
future materialized or recurring consumer must advance without full rescans or
silent history changes.

| View | Source watermark | Idempotent key | Late-arrival rule | Reconciliation |
| --- | --- | --- | --- | --- |
| `vw_multimodal_shipment_daily_v1` | validated `metric_date` per temporal scope | shipment, metric date, scope | reopen only the affected date/scope through explicit recovery | one shipment/metric row; no duplicate shipment-date keys |
| `vw_multimodal_ops_daily_v1` | latest reconciled shipment date | date, mode, scope | rebuild the affected aggregate date | mode totals equal shipment-daily total |
| `vw_multimodal_provider_daily_v1` | latest reconciled shipment date | date, mode, provider, scope | rebuild affected provider/date rows | provider totals equal shipment-daily total |
| `vw_multimodal_mode_decision_v1` | latest reconciled shipment date | date, lane, mode, scope | recompute both Air and Ocean comparison rows | every Air row has its Ocean reference |
| `vw_multimodal_forecast_feature_daily_v1` | last closed and validated feature date | feature date, mode, provider, scope | regenerate the affected date and all later lag windows | lag windows end before the feature date |
| `vw_multimodal_outcome_label_v1` | latest validated shipment snapshot | shipment, scope | replace only through latest-row ranking after delivery | pending labels remain null; one latest row per shipment/scope |
| `vw_multimodal_operational_baseline_v1` | explicitly reviewed Sydney as-of date | as-of date, dimension type/value | no automatic late update; rebuild by reviewed command | ten checks and equal overall/mode/provider/lane totals |

## Execution rules

- Exactly one `temporal_scope_id` is processed at a time.
- Operational refreshes accept only `OPERATIONAL` / `ACTUAL_CALENDAR` dates on
  or before the system-derived Sydney date.
- A watermark advances only after lifecycle, compatibility, analytics, cost,
  and reconciliation checks all pass.
- A failed or partial refresh leaves the prior aggregate available but marked
  stale; it never advances the watermark.
- Recovery names the failed date and scope and preserves the original failure
  evidence.
- Future simulations use named context views and isolated watermarks. They
  cannot update operational defaults, readiness, or public OPS evidence.

No incremental table or schedule is authorized by this document.
