# Internal Operations user onboarding

The private cockpit uses administrator-managed Cognito users. There is no
self-service registration, shared password, or public demonstration account.

## First access

1. An identity administrator creates a named user using the person's real
   organizational identity and assigns exactly one initial group: `viewer`,
   `operator`, `approver`, or `administrator`.
2. The user opens the private staging sign-in page and completes the Cognito
   invitation/temporary-password flow. Delivery delay does not justify creating
   a shared account or exposing a password in chat, logs, or documentation.
3. After sign-in, verify aggregate access first. `viewer` must receive 403 for
   shipment entities and all mutations.
4. Escalate role only after the identity owner approves the business need.

## Role intent

- `viewer`: aggregate and governed read-only evidence;
- `operator`: shipment evidence, Action assignment/edit, and completion;
- `approver`: approve or reject an Action, but cannot complete or edit it;
- `administrator`: all staging permissions and identity administration.

Action actors always come from signed claims. An assigned Action owner is
business metadata and never replaces the authenticated actor or approval rule.

## Offboarding and recovery

Disable access immediately when it is no longer required. Preserve Action audit
events under the signed historical actor identity; do not rewrite them when a
user is disabled. Password reset and account recovery remain Cognito-owned and
must not be simulated in the public product.
