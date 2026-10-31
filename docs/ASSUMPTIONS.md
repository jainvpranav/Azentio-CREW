# Assumptions

Provisional beliefs adopted because the handoff, data, or metadata are incomplete.
These are **not facts**. Each must be confirmed or revisited before being relied on
for a real lending decision. See [DECISIONS.md](DECISIONS.md) for choices actually
made (as opposed to things merely assumed).

| Field | Meaning |
|---|---|
| ID | `A-###`, stable once assigned |
| Date | when the assumption was first recorded |
| Area | subsystem it affects |
| Assumption | what we are provisionally treating as true |
| Reason | why we had to assume rather than confirm |
| Impact | what breaks / changes if the assumption is wrong |
| Confidence | low / medium / high |
| Confirmation needed | who/what would confirm it, and whether it blocks further work |

---

### A-001 — Entity type selection
**Date:** 2026-10-31 **Area:** Borrower assessment / reports
**Assumption:** The user (analyst) explicitly selects "Individual" or "SME" per account/customer at upload or review time; the system does not try to infer entity type from transaction patterns alone.
**Reason:** Handoff Q1 asks whether the user selects or the system infers. Inference from statement patterns alone (e.g. "has business receipts") is unreliable and risks mislabeling a salaried individual with a side hustle as an SME, or vice versa.
**Impact:** Individual vs SME metric sets and reports are chosen by a stored field, not a classifier. If auto-inference is actually wanted, the assessment-selection UI/API changes but the metrics themselves don't.
**Confidence:** medium
**Confirmation needed:** Yes — product decision. Not blocking: default is manual selection, defaulting to "Individual" if unset.

### A-002 — Multi-account ownership mapping
**Date:** 2026-10-31 **Area:** Internal transfer detection, consolidated balance
**Assumption:** Multiple accounts belonging to one customer are linked by uploading them together and matching on `holder_name` token overlap (existing `XFER_SELF` heuristic) plus an explicit `customer_id` the analyst can assign/correct in the UI. There is no external KYC/CRM feed providing verified ownership.
**Reason:** Handoff Q2 leaves this open. The current codebase has no `customer_id` concept at all — `Account.holder_name` is the only linking signal today.
**Impact:** Ownership mapping is best-effort and user-correctable, not verified. Wrongly linked accounts would incorrectly suppress real income/expenses as internal transfers.
**Confidence:** medium
**Confirmation needed:** Yes, before relying on consolidated NAMB/liquidity views across accounts. Not blocking: single-account analysis is unaffected.

### A-003 — CC/OD sanctioned limit and facility metadata
**Date:** 2026-10-31 **Area:** SME CC/OD utilization metric
**Assumption:** Sanctioned credit limit, facility type, and relevant balance are supplied as manually-entered metadata per account (new `Facility` fields), not parsed from statement text, since bank statements rarely state the sanctioned limit explicitly.
**Reason:** Handoff Q3; explicit instruction not to infer a sanctioned limit from transaction swings.
**Impact:** Until an analyst enters this metadata, CC/OD Utilization returns `NOT_AVAILABLE` with a message naming the missing fields, per handoff Phase 2/SME metrics.
**Confidence:** high
**Confirmation needed:** Confirm the metadata entry point (manual form vs. upload of a sanction letter) — not blocking functional delivery of the `NOT_AVAILABLE` path.

### A-004 — Statement scope: bank statements only, no card statements
**Date:** 2026-10-31 **Area:** Ingestion
**Assumption:** Only bank account statements (PDF/CSV/XLSX/JSON) are in scope. Credit-card statements are out of scope; existing `CARD_PAYMENT` classification only captures card bill *payments* seen on the bank statement, not card-level spend detail.
**Reason:** Handoff Q4. No credit-card statement parser or model exists in the repo.
**Impact:** FOIR/DTI's caution about double-counting card purchases vs. card bill payments is handled by only counting the bill payment (visible on the bank statement) as the obligation, and disclosing that card-level spend detail is unavailable.
**Confidence:** high
**Confirmation needed:** Confirm if credit-card statements will be supplied later; not blocking.

### A-005 — LLM/provider for the AI Reviewer (Phase 6)
**Date:** 2026-10-31 **Area:** AI Reviewer
**Assumption:** No LLM provider, API key, or RAG integration currently exists in this repo (`requirements.txt` has no `anthropic`/`openai` client; no vector store). We will build the AI Reviewer against the Anthropic API (Claude) behind a thin, swappable interface (`app/ai/reviewer.py` with a `LLMClient` protocol), reading the API key from an environment variable, so it can be swapped later without touching the pipeline.
**Reason:** Handoff Q5 explicitly defers this; nothing in the repo answers it.
**Impact:** AI Reviewer is inert (returns `NEEDS_INFORMATION`/skipped with a clear message) if no API key is configured, rather than failing the pipeline or fabricating a review.
**Confidence:** medium
**Confirmation needed:** Confirm provider/key availability before enabling live calls in any judged/demo environment.

### A-006 — Threshold configuration location
**Date:** 2026-10-31 **Area:** Rule evaluation engine
**Assumption:** Thresholds (FOIR bands, DSCR bands, CC/OD utilization, low-balance %, round-tripping window, etc.) live in a single versioned JSON/Python config module (`app/config/thresholds.py` or `thresholds.json`), not a database-backed admin UI, consistent with "Prefer the current implementation" and the project's current no-admin-UI state.
**Reason:** Handoff Q6; the existing codebase has no settings/admin table.
**Impact:** Changing a threshold requires a file edit + redeploy, not a UI action, until/unless an admin UI is requested.
**Confidence:** high
**Confirmation needed:** Low priority; revisit if a non-technical user needs to tune thresholds at runtime.

### A-007 — Final deliverable scope
**Date:** 2026-10-31 **Area:** Reports / risk output
**Assumption:** The product delivers a financial health report with explainable indicators and an optional configurable risk tier (e.g. lower/elevated/higher burden bands as in the illustrative thresholds). It does **not** produce an automated credit-eligibility decision (approve/reject) or any fraud/default determination — consistent with the handoff's explicit prohibition.
**Reason:** Handoff Q7, and the repeated instruction not to implement automatic REJECT/DEFAULT/fraud decisions.
**Impact:** UI/report language will say "indicator" / "tier" / "requires review", never "approved"/"rejected"/"fraud".
**Confidence:** high
**Confirmation needed:** Confirm if a credit-eligibility recommendation is wanted later as a distinct, clearly-labeled advisory output.

### A-008 — AI Reviewer outcomes requiring human review
**Date:** 2026-10-31 **Area:** AI Reviewer / escalation policy
**Assumption:** Only `LIKELY_LEGITIMATE` cases with confidence above a configurable threshold (initial: 0.75) and no HIGH-severity underlying flag may be auto-resolved (closed without a human click, but still fully logged and re-openable). `NEEDS_INFORMATION` and `ESCALATE_TO_HUMAN` always require a human decision before the case is closed, as do all HIGH-severity-flag cases regardless of AI recommendation.
**Reason:** Handoff Q8 defers this explicitly; it is a policy choice, not something derivable from code.
**Impact:** Determines queue size and how much is "auto-closed" vs. sent to the Review screen.
**Confidence:** low
**Confirmation needed:** Yes — this is a risk-policy decision for the business owner, not an engineering one. Treated as provisional/off (i.e. nothing auto-closes) until confirmed.

### A-010 — OD/CC drawn balance sign convention
**Date:** 2026-10-31 **Area:** SME CC/OD Utilization metric
**Assumption:** For an account with an OD/CC `Facility`, the statement's running `balance` column reflects the account convention where a negative balance means the account is overdrawn by that amount (i.e. "drawn" = `-balance` when `balance < 0`, else `0`). We do not attempt to parse a separate "limit remaining" or "drawing power" column, since none of the current ingestion paths extract one.
**Reason:** Bank statement balance-column conventions for OD accounts vary by bank; the handoff gives a formula (`Average Drawn Balance / Sanctioned Credit Limit`) but not a parsing convention, and none of the synthetic/real sample data in this repo currently includes an OD-type account to verify against.
**Impact:** If a bank's OD statement instead always shows a positive "amount utilized" column, this logic would compute 0% utilization (treating a positive balance as not drawn). The function labels its method and caveats so this is visible, not silent.
**Confidence:** low
**Confirmation needed:** Yes, before trusting CC/OD Utilization output on a real OD statement - confirm against an actual sample.

### A-011 — SALARY_RECUR clustering can misfire on a recurring B2B receipt
**Date:** 2026-10-31 **Area:** Classification (inherited `SALARY_RECUR` rule, `app/pipeline/pairing.py:find_salary_clusters`)
**Assumption:** `find_salary_clusters` (pre-existing, not changed in this pass) clusters purely on amount+timing (gap 25-35 days, consistent day-of-month OR salary keyword). It has no awareness of entity type or account context, so a genuinely recurring B2B receipt from one customer that happens to land on a consistent day-of-month each month, with a stable amount, will be classified SALARY instead of BUSINESS_RECEIPT. We are treating this as an accepted, disclosed limitation rather than fixing it in this pass, because distinguishing "payroll" from "one very reliable customer" from statement data alone is itself ambiguous without an entity-type or employer-registry signal.
**Reason:** Found while writing tests for the new SME business-receipt metrics/anomalies (test_sme_metrics.py, test_anomalies.py both had to pick irregular transaction dates specifically to avoid tripping this).
**Impact:** On real SME statements with a very regular single customer, GBT/customer-concentration could under-count that customer's inflow (it would land in VNMI/SALARY instead). The Individual vs SME entity-type selection (A-001) does not currently feed back into classification to prevent this.
**Confidence:** medium
**Confirmation needed:** Low priority for now; worth revisiting if demo/real data shows this misfiring. A future fix would gate `SALARY_RECUR` on `Customer.entity_type == INDIVIDUAL` (or require the keyword match when entity_type is SME) rather than accepting day-of-month alone as sufficient evidence for an SME account.

### A-009 — `customer_id` is new; not previously modeled
**Date:** 2026-10-31 **Area:** Core transaction model
**Assumption:** The existing schema (`Account`, `Transaction`) has no `customer_id`, `counterparty`, `counterparty_account`, `reference_number`, `transaction_type`, or `linked_transaction_id` fields. We will add these as nullable columns (additive migration) rather than altering existing fields, to avoid breaking the working Level-1 pipeline.
**Reason:** Required by the handoff's "Core transaction model" section; confirmed absent by reading `app/models.py`.
**Impact:** Existing data (current `statements.db`) will have these columns as `NULL` for pre-existing rows; code must treat `NULL` as "not available", never fabricate.
**Confidence:** high
**Confirmation needed:** No — this is a straightforward additive schema change; recorded here because it changes what "complete" transaction data means going forward.
