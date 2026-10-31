# Bank Statement Intelligence --- Agent Handoff

## Mission

Extend the **existing** bank-statement rule engine into an explainable
financial-analysis system for **individuals and SMEs**.

The system must: - Normalize bank transactions from PDF (at least two
layouts), CSV, Excel and JSON. - Classify transactions across the six
categories below. - Calculate borrower-specific financial metrics. -
Analyse historical financial behaviour and flag deviations. - Run an AI
Reviewer after deterministic anomaly detection and before human
review. - Produce explainable reports with transaction-level evidence
and an audit trail.

**Do not rebuild from scratch.** First inspect the repository,
understand what already works, map existing functionality to this plan,
and identify gaps. Reuse existing models, APIs and components wherever
practical.

## Required handoff artefacts

Create and maintain these **two separate Markdown files** in the
project:

1.  `ASSUMPTIONS.md`
    -   Record assumptions made because requirements, data or metadata
        are incomplete.
    -   For each assumption, include its ID, date, area, assumption,
        reason, impact, confidence, and whether confirmation is needed.
    -   Do not silently turn assumptions into facts.
    -   Update this file whenever an implementation depends on an
        assumption.
2.  `DECISIONS.md`
    -   Record implementation and product decisions actually taken.
    -   For each decision, include its ID, date, context/problem,
        options considered where useful, chosen decision, rationale,
        consequences, and affected files/modules.
    -   Record important changes to formulas, thresholds, schemas,
        matching logic, model/provider choices and escalation policies.
    -   Keep assumptions and decisions separate: an assumption is
        something temporarily believed; a decision is a deliberate
        choice made.

Link to or reference these files in the project README or main developer
documentation. Do not combine them into one file.

## Current state and first task

A simple rule-based engine already exists. Begin with repository
inspection:

1.  Identify language, framework, database, API structure and
    application entry points.
2.  Find transaction schemas, extraction/normalization code,
    classification rules and metric calculations.
3.  Identify which of the six categories, metrics and anomaly rules
    already exist.
4.  Note existing tests, frontend integration and LLM/RAG components.
5.  Produce a concise gap analysis and proposed implementation sequence
    before major changes.
6.  Create `ASSUMPTIONS.md` and `DECISIONS.md` as described above.

Do not claim a feature is missing until the codebase has been inspected.
Do not break working functionality.

## Core transaction model

Normalize statement rows into a common structure. Reuse the existing
schema if suitable; otherwise ensure the model can represent:

-   `transaction_id`, `customer_id`, `account_number`
-   `date` (and time when available)
-   `description` (preserve original narration)
-   `debit`, `credit`, `balance`
-   `transaction_type`
-   `counterparty` and `counterparty_account` when available
-   `reference_number` (UTR, bank reference, RRN or equivalent)
-   `category`, `subcategory`, `classification_confidence`
-   `linked_transaction_id` / original transaction link where relevant
-   `source_file`, `source_page` and provenance metadata

Preserve raw source values. Keep derived classifications separate from
original statement data. Support missing fields without fabricating
values.

## Phase 1 --- Transaction classification

All six categories must feed the individual and SME analyses. Keep
category classification separate from anomaly detection: an unusual
transaction can still be legitimate.

### 1. Internal transfers

Classify movements between accounts owned by the same customer as
`INTERNAL_TRANSFER`.

Detection/matching evidence: account ownership mapping, reference,
amount, debit/credit direction, date proximity, counterparty and
narration. For synthetic data, use customer IDs linked to multiple
accounts.

Anomalies to detect: - Unmatched transfer - Possible duplicate
transfer - Debit/credit amount mismatch - Unusual transfer frequency -
Unusually large transfer - Delayed matching credit

Do not count matched internal transfer credits as income or matched
debits as expenses. Retain them for liquidity and balance analysis. Do
not assume every transfer between similar names is an own-account
transfer.

### 2. Salary

Classify recurring, supported employer payments as `SALARY`.

Use credit direction, recurring monthly timing, employer/counterparty,
narration and amount pattern. Amounts can vary; a raise or bonus must
not automatically invalidate salary classification.

Anomalies: - Sudden salary increase/decrease - Missing or delayed
expected salary - Change in salary source - Unusual payment frequency

Separate classification from anomaly detection. Distinguish regular
salary from bonus/irregular credits when evidence supports it.

### 3. Business receipts

Classify supported customer/client payments as `BUSINESS_RECEIPT`.

Use counterparty history, business descriptors, invoice/payment
references, recurring patterns and business-account context. Business
receipts are turnover, not profit.

Anomalies: - Sudden increase in receipts - Unusually large single
credit - Possible duplicate payment - New/unknown counterparty or
unverified credit - Multiple payments from one sender in a short
period - Credit followed by rapid withdrawal

A new sender is not inherently suspicious. A recurring credit from an
individual does not prove business income. Use `UNVERIFIED_CREDIT` or
`POSSIBLE_BUSINESS_RECEIPT` when purpose is unclear.

### 4. Refunds and reversals

Use separate classifications: `REFUND` and `REVERSAL`.

Match to original debits using an explicit original-transaction
reference when available; otherwise use merchant/counterparty, amount,
date proximity and other evidence. Refund reference numbers may differ
from original payment references.

Anomalies: - Refund without identifiable original payment - Possible
duplicate refund - Partial refund (track it; not inherently anomalous) -
Refund total exceeding original payment - Delayed refund - Multiple
refunds against one original payment - Counterparty mismatch - Repeated
failed transactions/reversals

Refunds and reversals are not income. Track cumulative refunded amount
against the original payment.

### 5. Loan instalments / EMI

Classify recurring lender repayments as `LOAN_EMI`, using narration,
lender, ACH/NACH/ECS patterns, amount and date.

Anomalies: - Expected EMI missing - Possible duplicate EMI - Unexpected
EMI increase/decrease - Debit followed by reversal - Unexpected change
in number/frequency of loan deductions - New recurring loan repayment

Multiple EMIs from different lenders may be legitimate. Missing
deductions do not prove default. EMI changes can result from rate
changes or restructuring. Update monthly obligations when a new
recurring repayment is supported by evidence.

### 6. Common expenses and spending patterns

Classify eligible debits into categories such as groceries, shopping,
dining, entertainment, transport, utilities, healthcare, rent,
insurance, education, cash withdrawals, subscriptions and other
expenses.

Anomalies: - Sudden increase in total spending - Unusually large
purchase - Possible duplicate debit - Unusual spending frequency - New
recurring subscription - Unusual cash withdrawals - Category-level
spending spike where useful

Compare against the customer's own history. One large purchase or new
subscription is not automatically suspicious. Confirm recurrence before
labelling a payment as a subscription.

## Phase 2 --- Financial metric engine

Implement reusable, deterministic calculation functions. Every metric
must return its value, period, formula/method, supporting transaction
IDs, exclusions, data completeness and limitations. Never silently treat
missing data as zero.

### Individual metrics

**Verified Net Monthly Income (VNMI)**\
Average monthly verified recurring primary income over the available
lookback. Include supported salary and other verified primary income.
Exclude internal transfers, refunds/reversals, loan disbursements and
unverified credits. Distinguish regular income from exceptional bonuses
where possible.

**Net Average Monthly Balance (NAMB)**\
Prefer average daily closing balance: sum of daily closing balances
divided by number of days. Reconstruct daily balances only when opening
balance and transaction sequence are reliable. State whether calculation
is per account or consolidated across linked accounts. Do not substitute
month-end balance for average daily balance without labelling it as an
approximation.

**FOIR / DTI**\
`(Monthly fixed debt obligations / VNMI) * 100`\
Include identifiable EMI and other recurring debt obligations. Handle
credit-card obligations carefully: do not double-count card purchases
and card bill payments. If the actual obligation cannot be established,
disclose the limitation.

**Salary-to-Obligation Cleansing Cycle**\
Measure days from salary credit to clearance of recurring obligations
and/or the time until balance falls below a configurable low-balance
threshold. Report salary date, obligation dates, post-obligation balance
and time to low balance. Do not assume a low balance alone proves
distress.

**Discretionary Spending Ratio**\
`(Eligible discretionary outflows / Total eligible monthly outflows) * 100`\
Potential discretionary categories include dining, entertainment,
shopping, travel and non-essential subscriptions. Exclude internal
transfers and avoid double-counting refunds. Keep unknown expenses
unclassified rather than forcing a category.

### SME metrics

**Gross Banking Turnover (GBT)**\
Sum eligible verified business credit inflows over the period. Exclude
internal transfers, refunds/reversals, loan disbursements and
unverified/non-business credits. Distinguish verified business turnover
from total account credits.

**Debt Service Coverage Ratio (DSCR)**\
`Net Operating Cash Flow / Total Debt Service`\
Estimate operating cash flow from eligible operating inflows less
eligible operating outflows. Debt service includes principal and
interest. If principal/interest cannot be separated, disclose the
approximation and its limitations.

**Customer Concentration Risk**\
Calculate top-one and top-three customer shares: customer inflows
divided by total verified business inflows. Use identifiable
counterparties; exclude own-account transfers and unverified credits.

**CC/OD Utilization**\
`Average Drawn Balance / Sanctioned Credit Limit * 100`\
Requires account/facility type, sanctioned limit and relevant balance
data. Do not infer or invent a sanctioned limit from transaction swings.
If missing, return `NOT_AVAILABLE` and identify required metadata.

**Trade Inflow-to-Outflow Ratio**\
`Verified Business Receipts / Verified Business Payables * 100`\
Identify customer receipts and supplier/payable outflows. Exclude
internal transfers and unrelated personal expenses. Define treatment
when payables are zero or unavailable.

## Phase 3 --- Red-flag metrics

**NSF / Bounce Counter**\
Identify failed payments using narration such as NSF, Bounce,
Insufficient Funds, NACH Return, ECS Return and ACH Return. Link
debit/reversal events where possible to avoid double-counting one
failure. Report total and monthly counts, lender/payee and supporting
transaction IDs.

**Round-tripping / possible circular flow**\
Look for rapid outgoing and incoming flows with matching/near-matching
amounts, repeated movements among counterparties/accounts, and possible
circular paths within configurable windows (initially consider 24--48
hours). Exclude verified own-account transfers and legitimate
refunds/reversals where matched. Label as `POSSIBLE_CIRCULAR_FLOW` or
equivalent; never assert money laundering from a pattern alone.

**End-of-Day (EOD) Balance Stress**\
Calculate daily closing balances, negative-balance days, days below a
configurable liquidity threshold, consecutive stress days and lowest
balance. A possible initial threshold is 5% of average monthly balance,
but it must be configurable and documented---not treated as a universal
standard.

## Phase 4 --- Behavioural analysis

Compare activity with the customer's own historical pattern, not only
universal fixed thresholds.

Analyse: - Income consistency, source changes and monthly trends -
Business receipt trends and customer concentration - Spending totals,
category changes, large purchases and frequency - Recurring obligations
and EMI behaviour - Average/daily balances, low-balance periods and
withdrawals - New counterparties, transaction timing and rapid
inflow/outflow patterns

Use suitable methods such as historical mean/median, standard deviation,
percentage deviation, frequency counts and time-window comparisons. Use
robust methods where outliers distort averages. Make thresholds
configurable and account for short or incomplete histories.

A single deviation should generally prompt explanation/review, not a
fraud conclusion.

## Phase 5 --- Rule evaluation and borrower assessment

Extend the existing rule engine with configurable, explainable rules.
Prefer the current implementation; use Python functions or JSON
configuration if that fits the codebase. Do not add a new rules library
without a clear benefit.

Individual assessment inputs: - VNMI, NAMB, FOIR/DTI -
Salary-to-Obligation Cleansing Cycle - Discretionary Spending Ratio -
NSF/Bounce count - Round-tripping indicators - EOD Balance Stress

SME assessment inputs: - GBT, DSCR - Top-one/top-three customer
concentration - CC/OD utilization - Trade Inflow-to-Outflow Ratio -
NSF/Bounce count - Round-tripping indicators - EOD Balance Stress

Initial illustrative thresholds supplied for exploration: - Individual
FOIR: \<=40% lower burden; 40--55% elevated; \>55% higher burden. - SME
DSCR: \<1.0 indicates possible debt-service shortfall; \>=1.5 indicates
stronger coverage. - SME CC/OD utilization above 90% may indicate
liquidity pressure. - Customer concentration and other thresholds must
be configurable.

These are starting assumptions, not official or universal underwriting
standards. Do not implement automatic `REJECT`, `DEFAULT` or confirmed
fraud decisions based solely on these rules.

Output explainable indicators and, if required, configurable risk tiers.
Include rule ID, metric value, threshold, result, supporting
transactions, calculation period, confidence/data completeness and
limitations. Missing metrics must not be treated as zero or silently
used to penalize the customer.

## Phase 6 --- AI Reviewer before HITL

Pipeline:

`Normalized transactions -> Classification -> Metric calculation -> Deterministic anomaly detection -> AI Reviewer -> Human review when needed`

The AI Reviewer must: 1. Retrieve the flagged transaction and relevant
surrounding history. 2. Retrieve related transactions and matching
evidence. 3. Compare the behaviour with the customer's historical
pattern. 4. Identify supporting and contradicting evidence. 5. Consider
plausible legitimate explanations. 6. Explain what remains unknown. 7.
Produce a concise structured investigation summary. 8. Recommend whether
the case can be marked likely legitimate, needs more information or
should be escalated.

Required output fields: - Case ID and triggered rule/anomaly - Related
transaction IDs - Observed facts - Historical comparison - Supporting
and contradicting evidence - Possible legitimate explanations -
Unresolved questions - Recommendation and confidence - Human escalation
reason, if applicable

Use deterministic code for amounts, ratios, matching and rule
evaluation. Use the LLM for evidence-grounded reasoning and summaries.
The LLM must not invent facts, change financial calculations or silently
override deterministic results.

Possible outcomes: - `LIKELY_LEGITIMATE` --- evidence supports a
reasonable explanation; retain audit record. - `NEEDS_INFORMATION` ---
available statement data is insufficient. - `ESCALATE_TO_HUMAN` ---
ambiguity, high impact or multiple concerning indicators require human
judgment.

Do not remove human review for cases that policy requires a person to
decide.

## Phase 7 --- Reports and user experience

Provide separate Individual and SME reports.

Individual report: - VNMI, NAMB, FOIR/DTI - Salary-to-Obligation
Cleansing Cycle - Discretionary Spending Ratio - Monthly income/expense
trends - EMI obligations and spending breakdown - Red flags, grouped
anomalies and AI Reviewer findings

SME report: - GBT, DSCR - Top-one/top-three customer concentration -
CC/OD utilization (or clear unavailable status) - Trade
Inflow-to-Outflow Ratio - Monthly business inflow/outflow trends -
Customer receipts and supplier payments - Liquidity/working-capital
patterns - Red flags, grouped anomalies and AI Reviewer findings

Every metric must drill down to its formula, period, included/excluded
transaction categories, supporting transaction IDs, assumptions and
missing data. Group related alerts to reduce alert fatigue.

## Phase 8 --- Data, testing and validation

Use synthetic data for the hackathon. Create separate individual and SME
scenarios, including: - Individual with stable salary and EMIs -
Variable salary, bonus and changing obligations - Multiple linked
accounts and internal transfers - SME with recurring customers and
supplier payments - SME with high customer concentration - SME with
CC/OD metadata and utilization - Duplicate transactions - Refunds,
reversals and partial refunds - Rapid inflow/outflow and possible
circular flows - Missing balances, references or counterparty metadata

Use 3--6 months of history where feasible. Each test dataset should
contain normal activity, deliberately introduced anomalies and expected
outputs. Manually verify financial calculations.

Test different PDF layouts, CSV/Excel/JSON, overlapping periods,
duplicate rows, missing balances, missing metadata, refunds, reversals,
unmatched transfers and short histories.

## Lookback windows and missing data

Initial suggested windows: - Individual: 3--6 months. - SME: 6 months.

Make windows configurable. For shorter histories, calculate only
supported metrics, label them provisional where appropriate and disclose
insufficient evidence. Do not treat missing months as zero income.

For missing metadata (for example, CC/OD sanctioned limit), return
`NOT_AVAILABLE`, explain what is missing and request input or review. Do
not fabricate values.

## Auditability and reproducibility

Every classification, metric, anomaly and AI review must be traceable.

Example rule explanation:
`Rule_Ind_FOIR_Exceeded: calculated FOIR 62%; configured threshold 55%; supporting EMI transactions: TXN101, TXN205; period: last 3 months.`

Record rule ID/version, inputs, metric value, threshold, supporting
transaction IDs, timestamp, AI summary and any human decision. The same
input data and rule configuration should reproduce the same
deterministic calculations.

## Implementation sequence

1.  Inspect repository and document current architecture/features.
2.  Create `ASSUMPTIONS.md` and `DECISIONS.md`.
3.  Produce a gap analysis against this handoff.
4.  Improve transaction normalization and six-category classification.
5.  Implement and test individual metrics.
6.  Implement and test SME metrics.
7.  Implement red-flag metrics.
8.  Add behavioural comparisons and configurable thresholds.
9.  Extend the existing rule evaluation engine.
10. Add AI Reviewer and escalation workflow.
11. Integrate Individual and SME reports.
12. Validate with synthetic datasets and edge cases.

## Development constraints

-   Extend, do not unnecessarily replace, existing functionality.
-   Preserve raw statement data and source provenance.
-   Keep calculations deterministic, reusable and testable.
-   Keep thresholds configurable and document their source/status.
-   Exclude internal transfers from income/expense/turnover
    calculations.
-   Exclude refunds/reversals from income.
-   Exclude loan disbursements from business turnover.
-   Do not assume new counterparties or unusual transactions are
    suspicious.
-   Do not declare fraud/default from statement patterns alone.
-   Do not fabricate missing metadata.
-   Maintain explanations and transaction-level audit trails.
-   Clearly distinguish observed facts, calculated metrics, statistical
    anomalies and AI interpretations.

## Questions to resolve after repository inspection

Do not block initial inspection on these questions. Record provisional
assumptions in `ASSUMPTIONS.md` and seek confirmation where needed.

1.  Does the user select Individual/SME, or should the system infer
    entity type?
2.  Will multiple accounts be uploaded together with a
    customer-to-account ownership mapping?
3.  How will CC/OD sanctioned limits and facility details be supplied?
4.  Are credit-card statements available, or only bank statements?
5.  Which LLM/provider and existing RAG integration are available?
6.  Where should rule thresholds be configured (JSON, database or
    existing admin UI)?
7.  Is the final product expected to provide a financial health report,
    borrower risk tier, credit eligibility recommendation, or all three?
8.  Which AI Reviewer outcomes may be resolved automatically under
    policy, and which always require human review?

## Expected outcome

A working extension of the existing application that supports Individual
and SME bank-statement analysis, six-category transaction
classification, the specified financial metrics, behavioural analysis,
explainable red flags, an AI Reviewer before HITL, separate financial
reports and a reproducible audit trail.

**First response expected from the agent:** repository findings,
current-feature inventory, gap analysis, proposed implementation order,
and confirmation that `ASSUMPTIONS.md` and `DECISIONS.md` have been
created. Do not begin major refactoring before this review.
