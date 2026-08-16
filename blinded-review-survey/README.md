# GLAP Independent Blinded Review Survey

Bilingual survey for the frozen GLAP Historical Replay decision-quality review.
Both the root route and `/pilot/human-evaluation` expose the authenticated
formal review client. Frozen cases, saved progress, and submission require the
dedicated reviewer account.

## Reviewer flow

1. Sign in with the dedicated reviewer username and password; no ChatGPT account is required.
2. Confirm independence, no conflict, and no access to the blind key.
3. Review each of the 30 frozen point-in-time packages. Every case explains the story so far, decision pressure, difficulties, and conditional downstream risks. Every option then shows the problem it addresses, immediate/short-term/long-term solution paths, intended benefits and measurement signals, trade-offs, and authority boundary.
4. Score OPTION A and OPTION B independently across five rubric dimensions.
5. Record an overall preference, confidence, and optional notes.
6. Review completion and submit once. Final answers are locked.

When both options have identical visible content, the page identifies the case as a frozen control sample and explains that the reviewer may select a tie. The notice does not reveal option identities or alter the frozen package.

The English package content is the frozen source of truth. Chinese copy is a display-only translation layer identified as `glap-review-zh-v3`. The v3 handoff distinguishes the complete historical case label from cutoff-visible facts and labels every benefit as expected rather than observed.

The v3 bundle is a new review session. Any v1 or v2 draft remains stored under its original bundle ID but is not loaded into or counted toward the v3 review.

## Formal Human Evaluation entry

The `/pilot/human-evaluation` route now opens the same authenticated formal v3
flow as the root route. It covers all ten frozen Historical Replay cases and 30
point-in-time packages, requires the three reviewer attestations, saves through
`/api/review`, and locks a complete submission. The former five-case,
15-moment browser-only presentation remains available only through the
development-only `/pilot/baltimore` route; its local answers are never migrated
into or counted by the formal review.

## Evidence and authority boundary

- Unauthenticated responses do not contain the reviewer-safe bundle or its translations.
- The authenticated review API contains the reviewer-safe bundle only.
- It does not contain the owner key or option-identity mapping.
- It evaluates point-in-time decision quality only.
- Formal Human Evaluation answers are bundle-scoped, server-saved, and locked
  only after all 30 packages pass completeness checks.
- Development-only preview answers remain browser-local and ineligible.
- It does not support business-outcome, production-readiness, or real-logistics-performance claims.
- The site has no operational write or execution authority.

## Authentication boundary

- Passwords are verified against a PBKDF2-SHA256 hash supplied through the hosting environment; plaintext credentials are not stored in the repository.
- PBKDF2 uses the hosting runtime's supported maximum of 100,000 iterations together with a strong generated reviewer password.
- Signed, HTTP-only, SameSite=Strict sessions expire after eight hours.
- Five failed attempts within 15 minutes trigger a 15-minute lockout.
- Review mutations require both a valid session and a same-origin request.

## Local development

```bash
npm install
npm run db:generate
npm run dev
```

Apply the generated migration to the local D1 database before exercising persistence.

## Validation

```bash
npm run lint
npm test
npm audit --omit=dev
```

The formal release candidate uses Next.js `16.3.1`; its production-only audit
must remain at zero vulnerabilities before release.
