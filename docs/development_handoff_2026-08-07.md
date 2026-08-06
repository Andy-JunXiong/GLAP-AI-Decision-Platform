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
bounded concurrency, throttling, failure alarms, and an encrypted DLQ. The
deployment tool is plan-first. No stack was deployed today, and no schedule,
production alias, or public write path was created.

The frontend dependency baseline was upgraded from Next.js 16.2.6 to 16.3.0
after the production dependency audit reported high-severity advisories. The
post-upgrade production audit reports zero known vulnerabilities.

## Verification

- 168 Python repository tests passed.
- The frontend production build passed and all 3 rendered-output/connection
  tests passed.
- ESLint passed with no errors.
- `npm audit --omit=dev --audit-level=high` reported zero vulnerabilities after
  the Next.js upgrade.
- PowerShell parsing and repository whitespace checks passed during this slice.
- AWS runtime authorization, alarm, concurrency, and recovery evidence does not
  exist yet because the new stack has not been deployed.

## Next connection

1. Approve the JWT issuer, audience, and exact internal HTTPS origin.
2. Deploy the staging API manually and verify viewer/operator/approver/admin
   allow and deny cases with named test identities.
3. Exercise same-request retries, concurrent updates, throttling, alarms, and
   failure recovery, then record sanitized evidence.
4. Keep public Pages built without the internal API URL.
5. On or after the Sydney business date `2026-08-09`, run the actual-calendar
   observation for the pending Outcome. As of `2026-08-07`, it is still pending
   and is not observed evidence.
