# GLAP Independent Blinded Review Survey

Bilingual review application for the frozen GLAP Historical Replay
decision-quality study. The corrected Human Evaluation candidate uses an
authenticated story-based review client. Frozen cases, saved progress, and
submission require the dedicated reviewer account.

## Reviewer flow

1. Sign in with the dedicated reviewer username and password; no ChatGPT account is required.
2. Confirm independence, no conflict, and no access to the blind key.
3. Review ten distinct stories, each with three frozen point-in-time moments. Every moment says who you are, what has just happened, what is still unknown, what you need to protect, and what decision is needed now.
4. When the systems disagree, compare two genuinely different courses of action with five plain-language A/B/Tie questions.
5. Record an overall preference and confidence.
6. Review completion and submit once. Final answers are locked.

When both systems produce the same visible plan, the page shows that shared plan once and asks the reviewer to confirm it. It never renders two identical A/B cards or asks the reviewer to manufacture a difference. The notice does not reveal system identities or alter the frozen package.

The English package content is the frozen source of truth. Chinese copy is a display-only translation layer identified as `glap-review-zh-v3`. The v3 handoff distinguishes the complete historical case label from cutoff-visible facts and labels every benefit as expected rather than observed.

The v3 bundle remains the frozen evidence source. The corrected story presentation uses collection `human-evaluation-story.v2`, isolated from the rejected `human-evaluation-story.v1` presentation and from any earlier questionnaire draft. None of those earlier records are loaded into or counted toward the new collection.

## Formal Human Evaluation entry

The local `/pilot/human-evaluation` v2 candidate uses ten plain-language stories,
progressively revealed three-moment timelines, and anonymous choices while
covering all ten frozen Historical Replay cases and 30 point-in-time packages.
Internal cohort IDs, contract jargon, raw evidence language, and technical
option payloads are not presented to the reviewer. It requires the three reviewer
attestations, saves committed moments through `/api/review`, enforces story
order on the server, and locks a complete submission. Public Sites v9 contains
the user-rejected technical presentation and must be treated as paused; the v2
story candidate is locally verified but has not yet been released.
The five-case browser-only pilot remains
available only for development at `/pilot/baltimore`, and its local answers are
never imported into formal evidence.

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

The candidate uses Next.js `16.3.1`; its production-only audit must remain at
zero vulnerabilities before a corrected release.
