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

## Verification

- Pull requests `#31`, `#36`-`#41` were merged; they cover the authenticated
  API, protected configuration, dedicated identity/hosting, deployment fixes,
  and staging quota compatibility.
- 173 Python repository tests passed after adding deployment verification.
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
- Named authenticated role and recovery evidence does not exist yet because no
  Cognito user is created automatically.

## Next connection

1. Create named staging test identities and assign viewer, operator, approver,
   and administrator groups.
2. Verify the role-specific allow and deny cases through the deployed API.
3. Exercise same-request retries, concurrent updates, throttling, alarms, and
   failure recovery, then record sanitized evidence.
4. Keep public Pages built without the internal API URL.
5. On or after the Sydney business date `2026-08-09`, run the actual-calendar
   observation for the pending Outcome. As of `2026-08-07`, it is still pending
   and is not observed evidence.
