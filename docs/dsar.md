# DSAR downstream employment handoff (DUTH-69)

Erasure of a hired candidate must be forwarded to the HRIS and directory owner
using the onboarding saga step `external_ref` ids. Anonymizing the ATS case does
not delete downstream employment records retained under DUTH-64 decision R4.
For `compensation_failed`, check the `onboarding_erasure_cleanup_required` audit
and counter and arrange manual ownership-checked cleanup. See
[onboarding operations](onboarding.md#compensation-failure-and-erasure-s10).

The complete DSAR workflow is owned by DUTH-69; this page records its binding
S10 integration requirement without claiming that workflow is implemented.
