# Development handoff — 7 August 2026

## Completed today

The repository now contains the authenticated path that lets an internal user
open the operational Action queue and approve, reject, or complete an Action.
The API takes the person's name and role from a validated identity token rather
than trusting fields supplied by the browser. The existing append-only audit
history and retry-safe request IDs remain the final write authority.

The Decision Queue and new Action Board use this path only when an internal
HTTPS API URL and authenticated session token are present. The public
demonstration remains read-only and sends no Action request.

A separate staging template adds JWT authorization, least-privilege access,
API Gateway rate and burst limits, failure/throttling alarms, and an encrypted
DLQ. The deployment tool is plan-first. The dedicated Cognito identity,
manually hosted Amplify frontend, and Operations API stacks were deployed to
staging today. No schedule, production alias, repository-connected hosting, or
public Pages write path was created.

The frontend dependency baseline was upgraded from Next.js 16.2.6 to 16.3.0
after the production dependency audit reported high-severity advisories. The
post-upgrade production audit reports zero known vulnerabilities.

Risk Hotspots is now the first authenticated cockpit surface in that journey.
It reads the latest open operational Alerts through `GET /v1/risks`, applies
the Australia/Sydney business-date cutoff, and excludes future simulations.
Selecting a Risk leads to the existing Decision Queue, using the same Alert
fingerprint that links lifecycle Alerts to Actions. The private frontend and
API were deployed to staging; public Pages continues to use synthetic examples.

## Verification

- Pull requests `#31`, `#36`-`#41` were merged; they cover the authenticated
  API, protected configuration, dedicated identity/hosting, deployment fixes,
  and staging quota compatibility.
- 185 Python repository tests passed after adding Risk Hotspots and reliability
  verification.
- The standard frontend build, the internal static export, and all 3
  rendered-output/connection tests passed.
- ESLint passed with no errors.
- `npm audit --omit=dev --audit-level=high` reported zero vulnerabilities after
  the Next.js upgrade.
- PowerShell parsing and repository whitespace checks passed during this slice.
- Both staging stacks are stable, the API Lambda is active, and both alarms are
  present. The internal frontend returns HTTP 200 and renders its sign-in entry.
- Unauthenticated API requests return 401. CORS preflight succeeds only for the
  exact internal Amplify origin. Protected URLs and identifiers were not logged.
- The complete authenticated role matrix passed in staging: all four roles read
  both Risk Hotspots and the queue with HTTP 200; viewer, operator, approver,
  and administrator allow and deny boundaries matched the contract.
- Risk Hotspots returned 15 open operational Alerts. Their response contract,
  `OPEN` filter, and Sydney cutoff dates passed runtime checks.
- The governed Alert table, Action view, and both direct backing tables have
  exact Glue and Lake Formation read permissions. No data write or grant option
  was added.
- The four isolated Cognito test users were deleted, and the temporary Lake
  Formation administrator list was restored to zero entries.
- Existing audit evidence was replayed sequentially and concurrently through
  the authenticated API; every response reused the same event and the audit
  count remained one.
- A controlled staging dependency failure returned 503, recovered to the
  expected domain 404 after restoration, and moved the failure alarm from
  `OK` through `ALARM` and back to `OK`.
- A bounded throttle exercise observed 429 responses, restored the original API
  rate/burst settings, and moved the throttle alarm through `ALARM` and back to
  `OK`. The synchronous API DLQ remained empty and the temporary user was
  removed and confirmed absent.

## Next connection

1. Connect Outcome Review to completed Actions and mature Outcomes through this
   proven API boundary, while keeping pending `2026-08-09` data out of observed
   evidence until that Sydney business date arrives.
2. Keep public Pages built without the internal API URL.
3. On or after the Sydney business date `2026-08-09`, run the actual-calendar
   observation for the pending Outcome. As of `2026-08-07`, it is still pending
   and is not observed evidence.
