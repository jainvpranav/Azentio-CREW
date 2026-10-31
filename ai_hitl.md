````
# Financial Intelligence Layer â€” Implementation Handoff

> **Read this first:** The rule-based engine already works and already returns FOIR, VNMI and the other required values. Do not rebuild it. Extend the existing code with (1) transaction-level analyst review before metric calculation, (2) explainable cross-metric intelligence, (3) AI summary/recommendation/scheme analysis, and (4) final analyst review. Inspect the repository and use its real schemas. Keep changes minimal, auditable and backward-compatible.


## 1. Project context and current status

We already have a working **rule-based bank-statement engine**. It processes the available statement/customer data and produces financial metrics, including (but not limited to):

- FOIR / DTI
- VNMI (Verified Net Monthly Income)
- NAMB (Net Average Monthly Balance)
- Discretionary spending ratio
- NSF / bounce counts
- Round-tripping / possible circular-flow indicators
- EOD balance stress metrics
- Other values already exposed by the current engine

**The existing engine has been run successfully. The next task starts after its output.**

Do not rebuild the transaction parser, classification engine, metric calculations, or existing rule engine unless repository inspection proves a specific defect or missing requirement. Do not recalculate FOIR, VNMI, or any other metric in the new layer. Treat the existing engine's output as the source of truth.

The objective is to add a small, explainable **Financial Intelligence / Assessment layer** on top of the existing output. This layer should combine the existing metrics and rule results, detect relationships and patterns, produce structured assessment indicators, and then pass evidence to an AI component for a clear summary and interpretation.

The system should support both individual and SME profiles wherever the existing engine provides the required inputs.

---

## 2. Primary objective

Build the following pipeline by extending the current application:

```text
Bank statement / customer data
            |
            v
Transaction review + analyst flags (CHECKPOINT 1)
            |
            v
Existing transaction + rule-based engine
            |
            v
Existing calculated metrics and rule results
(FOIR, VNMI, NAMB, EMI, spending, bounces, stress, etc.)
            |
            v
NEW: Financial Intelligence Engine
            |
            +--> Cross-metric analysis
            +--> Behaviour and trend analysis
            +--> Explainable risk / strength indicators
            +--> Optional lightweight ML anomaly model
            |
            v
AI interpretation + recommendation / scheme analysis
            |
            v
Analyst review and notes (CHECKPOINT 2)
            |
            v
Final structured assessment / recommendation
            |
            v
Existing frontend / API / audit workflow
````

The new layer must be additive. Preserve existing APIs and behaviour wherever possible. Add a new endpoint, service, or response section only where it fits the current architecture.

### What the new layer must answer

1. What does the customer's financial position look like when all available metrics are considered together?
2. Which metrics reinforce or contradict each other?
3. Are there meaningful patterns across income, obligations, balances, spending and payment behaviour?
4. What are the customer's strongest financial indicators?
5. What are the main concerns, and what evidence supports them?
6. What additional information is needed before making a stronger assessment?
7. How can these findings be explained in clear, concise language?

The output is an **assessment and decision-support report**, not an automatic loan approval or rejection.

---

## 3. Bank analyst workflow â€” mandatory product requirement

**Product context:** This is a bank-facing financial analysis product. Bank analysts must be able to add notes, flags and corrections at two distinct points. Treat analyst input as a first-class, auditable part of the workflowâ€”not as free text that the AI may silently reinterpret.

### Checkpoint 1 â€” transaction review, before metrics are calculated

An analyst reviews individual transactions and can:

- Flag a transaction as salary/income, EMI, business receipt, internal transfer, refund, cash deposit, unusual item, or another supported category.
- Mark a transaction as correctly classified, incorrectly classified, uncertain, duplicate, or requiring investigation.
- Add a short note and reason; link it to the transaction ID.
- Suggest a category/classification correction. Apply it only through an explicit, permission-controlled override process.

**Flow:** raw transactions â†’ analyst flags/approved overrides â†’ existing classification and rule-based engine â†’ FOIR, VNMI and all other existing metrics.

Rules:

- Preserve the original transaction, original system classification, analyst's suggested classification, final approved classification, author, timestamp and reason.
- Never overwrite source transaction data.
- Do not apply an analyst suggestion automatically. Define who can approve overrides and whether a second approval is required.
- Once an approved override changes an input classification, rerun the existing calculation engine so its metrics remain internally consistent. Do not create a second formula for FOIR/VNMI.
- If the current product has already calculated metrics before analyst review, support a controlled review-and-reprocess path; do not pretend the notes affected the earlier calculation.
- Keep unresolved flags visible as review items and show whether they could affect a metric.

### Checkpoint 2 â€” AI assessment, recommendation and scheme review

After the intelligence engine and AI have produced the financial interpretation, recommendations and any scheme analysis, the analyst can:

- Add context or corrections to the interpretation.
- Agree, disagree or request more evidence for a finding.
- Accept, edit, reject or defer a recommendation/scheme suggestion.
- Add a final rationale, follow-up request or decision note.
- Mark the case as reviewed, pending information or escalated.

Rules:

- Show the AI's original output separately from the analyst's final decision/comment.
- Analyst notes can guide or amend the final recommendation, but must not silently change calculated metrics or historical engine outputs.
- If an analyst disputes a metric, route it back to Checkpoint 1 or a data-correction workflow; retain the original value and audit trail.
- Scheme eligibility must still be checked against current official criteria. An analyst note is context, not proof of eligibility.
- Clearly label the final output as AI-generated, analyst-reviewed, or analyst-amended.

### Shared analyst-note structure

Use a compact structured record, adapting names to the existing code:

```json
{
  "note_id": "NOTE_001",
  "stage": "TRANSACTION_REVIEW",
  "target_id": "TRANSACTION_123",
  "note": "Likely internal transfer between the customer's own accounts.",
  "flag": "POSSIBLE_INTERNAL_TRANSFER",
  "suggested_value": "INTERNAL_TRANSFER",
  "status": "PENDING_APPROVAL",
  "author_id": "ANALYST_01",
  "created_at": "2026-10-31T10:30:00Z",
  "reviewed_by": null,
  "reviewed_at": null
}
```

For Checkpoint 2, use `stage: "FINAL_ASSESSMENT_REVIEW"` and link the note to a finding, recommendation or scheme ID. Do not force transaction-only fields onto final-review notes.

Every note must retain its author, timestamp, target, stage, status and change history. Apply role-based access, privacy controls and audit logging. Keep analyst input separate from raw bank data and AI-generated content.

### How the AI must use analyst input

- Include approved transaction-review decisions and relevant unresolved flags in the evidence package.
- Treat analyst notes as attributed human observations, not verified facts unless explicitly approved.
- At final review, provide the AI output and analyst notes as separate fields.
- Do not let the AI erase, rewrite or misattribute an analyst's note.
- If analyst input conflicts with system evidence, surface the conflict and request review.
- Keep prompts compact: send only relevant notes, linked IDs and statuses; do not send the full note history or full statement unless needed.

### Required acceptance checks

- [ ] Analysts can flag and annotate transactions before metric calculation.
- [ ] Approved classification overrides flow through the existing engine; FOIR/VNMI are not independently recalculated.
- [ ] Analysts can review AI interpretation, recommendations and scheme analysis at the final stage.
- [ ] AI output and analyst-authored decisions remain distinguishable.
- [ ] Every note and override is attributable and auditable.
- [ ] Pending or disputed notes are visible and are not silently treated as approved.

---

## 4. First action: inspect the existing repository

Before writing or changing code:

1. Inspect the repository structure, language, framework, entry points and API flow.
2. Find the exact module/function that produces the existing financial metrics.
3. Inspect the actual output schema and representative output. Do not assume field names or data types from this document.
4. Identify how individual and SME cases are represented.
5. Find the current rule results, thresholds, transaction evidence and confidence/completeness fields.
6. Identify the existing frontend/report response format and tests.
7. Identify whether an LLM client, model provider, prompt framework or RAG layer already exists.
8. Identify the best integration point immediately after the current engine completes.

Create a short repository assessment before implementation:

- Existing components that will be reused
- Actual metric fields and their types
- Existing rule outputs
- Missing information required by the new layer
- Proposed files/modules to add or modify
- Compatibility risks and tests to run

**Do not claim that something is missing until the repository has been inspected. Do not replace working code just to match the suggested names in this document.**

---

## 5. Design principle: deterministic intelligence first, AI second

Use separate responsibilities.

| Component                         | Responsibility                                                                                 | Must it be deterministic?            |
| --------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------ |
| Existing calculation engine       | Produce FOIR, VNMI and all existing financial metrics                                          | Yes â€” already implemented          |
| Existing rule engine              | Apply current configured rules and thresholds                                                  | Yes â€” already implemented          |
| New Financial Intelligence Engine | Combine metrics, calculate derived indicators, compare patterns and assign explainable signals | Yes, for core assessment             |
| Optional small ML model           | Detect unusual combinations or deviations from historical behaviour                            | Reproducible and validated           |
| AI interpretation layer           | Explain the findings, summarize strengths/risks and suggest next checks                        | Evidence-grounded; not authoritative |
| Human review / policy layer       | Make decisions that require human or lender-policy judgment                                    | According to existing policy         |

Do not use a neural network to reproduce calculations that the current engine already performs. Do not let a model invent or alter financial values.

### Recommended approach

Start with a **small deterministic assessment engine**, not a neural network. This is the simplest, fastest and most explainable option for a hackathon or early product.

The engine should:

- Consume the existing engine's output as structured data.
- Validate required fields and distinguish missing values from zero.
- Derive only genuinely new indicators that are not already supplied.
- Evaluate relationships between metrics.
- Combine existing rule findings without duplicating them.
- Produce evidence-backed signals and a compact assessment object.

Only add a small ML model if there is a clear use case, sufficient representative data and a way to validate it. A neural network trained on a tiny or synthetic dataset may appear intelligent but can be unstable, difficult to explain and misleading.

---

## 6. New component A â€” Financial Intelligence Engine

Create a module that consumes the existing engine response. Adapt the proposed names below to the repository's conventions.

Suggested conceptual structure:

```text
financial_intelligence/
    __init__.py
    input_adapter.py
    validation.py
    cross_metric_engine.py
    behavioural_analysis.py
    assessment.py
    evidence.py
    schemas.py
    tests/
```

Do not create all these files blindly. Use the smallest structure that fits the existing project.

### 5.1 Input contract

The input must be the **actual output of the existing engine**, not a second copy of the raw statement parser.

The adapter should map the current output into a stable internal structure. Example only:

```json
{
  "customer_id": "CUSTOMER_001",
  "customer_type": "INDIVIDUAL",
  "analysis_period": {
    "start_date": "2026-07-01",
    "end_date": "2026-10-31",
    "months_covered": 4
  },
  "metrics": {
    "foir": 32.5,
    "vnmi": 80000,
    "namb": 42000,
    "discretionary_spending_ratio": 18.0,
    "emi_total": 26000,
    "nsf_count": 0,
    "round_tripping_count": 0,
    "eod_stress_days": 1
  },
  "rule_results": [],
  "metric_metadata": {},
  "evidence": {}
}
```

This is a mapping example, **not a demand to rename the existing API fields**.

Requirements:

- Reuse the existing response schema where practical.
- Keep original metric values and units unchanged.
- Document whether percentages are represented as `32.5` or `0.325`.
- Do not assume currency, period, account aggregation or customer type if it is absent.
- Missing, unavailable, invalid and zero values must remain distinct.
- Carry through calculation period, data completeness, formula/method, exclusions, limitations and supporting transaction IDs whenever available.
- Do not fabricate transaction IDs, customer details, missing months or metric values.
- Validate input and return a clear validation error or partial assessment when fields are unavailable.

### 5.2 Metric relationship analysis

The main value of this layer is to identify what the metrics mean **together**, rather than repeating each metric independently.

Implement explicit, testable relationship checks. Initial examples:

| Combination                               | Potential interpretation                                        | Required caution                                                        |
| ----------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Low FOIR + stable VNMI                    | Existing debt obligations may leave more repayment capacity     | Does not prove eligibility; check income continuity and proposed EMI    |
| High FOIR + low NAMB                      | High fixed obligations combined with a limited liquidity buffer | Check account coverage and analysis period                              |
| Stable VNMI + repeated EOD stress         | Income may be regular but cash may be depleted quickly          | Check salary timing, obligations and account transfers                  |
| High discretionary ratio + low NAMB       | Spending may be reducing available liquidity                    | Do not label spending as irresponsible; verify category quality         |
| High VNMI + volatile income history       | Average income may hide instability                             | Check the number of months and income-source consistency                |
| New or increased EMI + rising FOIR        | Debt commitments may have increased                             | Verify that the repayment is recurring and not duplicated               |
| NSF events + low balance around due dates | Payment failures may be associated with liquidity timing        | Link events and avoid double-counting reversals                         |
| High NAMB + high FOIR                     | Good observed liquidity can coexist with a high debt burden     | Do not treat balance as recurring income                                |
| Possible circular flows + high credits    | Gross credits may overstate genuine income or turnover          | Exclude verified internal transfers and matched refunds; request review |
| Low NAMB + no NSF events                  | A limited buffer exists, but no payment failure is observed     | Do not infer distress from balance alone                                |

These are interpretation patterns, not automatic lending rules. Implement only combinations supported by the actual fields available.

For each detected relationship, produce:

- Stable signal ID
- Signal category: `STRENGTH`, `CONCERN`, `NEUTRAL`, or `DATA_GAP`
- Short title
- Explanation
- Metrics involved and their exact values
- Supporting rule IDs and transaction IDs, if available
- Severity or priority, if configured
- Confidence/data-completeness indicator
- Caveats and follow-up checks

Do not create a concern merely because one optional metric is missing.

### 5.3 Behaviour and trend analysis

Use historical data already generated by the current application, if available. Do not infer a trend from a single aggregate value.

Potential analyses:

- Monthly VNMI consistency and income-source changes
- FOIR trend and new recurring obligations
- NAMB and daily/period balance movement
- Monthly expense and discretionary-spending changes
- EMI timing and payment-failure patterns
- EOD stress frequency and consecutive duration
- SME turnover trends and customer concentration
- Business cash-flow and debt-service coverage trends

Use simple, interpretable methods first:

- Month-over-month percentage change
- Mean and median
- Standard deviation or coefficient of variation where meaningful
- Robust median/MAD comparisons for outlier-prone values
- Frequency and recency counts
- Configurable time windows

Rules:

- State the number of periods used.
- Avoid percentage-change calculations when the baseline is zero or unavailable.
- Do not call a trend stable if there are too few periods.
- Do not treat missing months as zero.
- A statistical deviation is a review signal, not proof of fraud or default.
- Compare a customer primarily with their own history, not an unsupported universal benchmark.

### 5.4 Explainable assessment result

Create an assessment object that summarizes the deterministic engine's findings. Example:

```json
{
  "assessment_version": "1.0",
  "customer_type": "INDIVIDUAL",
  "overall_indicator": "MODERATE",
  "strengths": [],
  "concerns": [],
  "cross_metric_findings": [],
  "behavioural_findings": [],
  "data_gaps": [],
  "additional_checks": [],
  "confidence": {
    "level": "MEDIUM",
    "reason": "Four months of data are available; some supporting metadata is incomplete."
  },
  "human_review_required": true
}
```

The values above are illustrative. Define the actual labels and their meanings in configuration or documentation. Do not imply a calibrated probability when the system has not been statistically calibrated.

If an overall indicator is implemented:

- Keep its calculation deterministic and documented.
- Make weights and thresholds configurable.
- Return the contributing signals and values.
- Do not silently convert missing metrics to zero.
- Do not describe it as a credit score unless it has been designed, validated and governed as one.
- Do not let the overall label hide a serious individual concern or data gap.

---

## 7. Optional component B â€” Small ML model

A small ML model is optional and should be added only after the deterministic intelligence layer works.

### 6.1 When ML is justified

Use ML only if it solves a defined problem such as:

- Detecting unusual changes in a customer's own transaction/metric history.
- Grouping similar behavioural patterns.
- Prioritizing anomalies for review.

Do not train a model simply to output `GOOD`, `AVERAGE` or `BAD` from a handful of metrics without reliable labelled outcomes.

### 6.2 Preferred first experiment

For a small tabular dataset, test a simple baseline before a neural network:

- Isolation Forest for unsupervised anomaly prioritization, if enough representative observations exist.
- Logistic regression or a small tree-based model only if reliable labelled outcomes exist.
- A small multilayer perceptron only if there is sufficient labelled data and a measurable reason it performs better.

Do not introduce a heavy ML framework unless the project environment needs it. Check installed dependencies first.

### 6.3 ML input and output rules

Potential features may include existing engine outputs and historical changes, for example:

- FOIR
- VNMI
- NAMB
- Discretionary spending ratio
- NSF count
- EOD stress days
- Income variability
- FOIR change
- NAMB change

Use only features that exist and have consistent definitions. Do not use protected or sensitive personal characteristics, or proxies intended to infer them.

The ML component must:

- Return an anomaly score or review-priority signal, not a loan approval decision.
- Record model name/version, feature list, training-data version and timestamp.
- Handle missing values explicitly.
- Be tested against a simple baseline.
- Be validated on held-out data where possible.
- Be monitored for drift and false positives.
- Be clearly marked experimental if trained only on synthetic data.

Synthetic data can test code paths; it cannot establish real-world predictive performance.

### 6.4 Keep ML separate from policy

The ML output must not:

- Change FOIR, VNMI or other calculated values.
- Override deterministic rule results.
- Automatically reject or approve a borrower.
- Declare fraud, money laundering or default.
- Be presented as a calibrated probability unless calibration has been measured.

If there is not enough data, skip ML and return `NOT_RUN` with a reason.

---

## 8. New component C â€” AI Summary and Interpretation

After the deterministic Financial Intelligence Engine has produced its structured assessment, send that assessment and the relevant evidence to the AI layer.

The AI's job is to **explain**, not calculate.

### 7.1 AI responsibilities

The AI should:

1. Summarize the customer's financial position in plain language.
2. Explain the most important strengths.
3. Explain the most important concerns and why they matter.
4. Connect related metrics instead of describing each in isolation.
5. Explain conflicting signals, such as high income with low liquidity.
6. Identify missing information and limitations.
7. Suggest practical next checks or financial improvements tied to evidence.
8. Produce separate wording suitable for an internal analyst and a customer-facing report, if the product requires both.

### 7.2 AI must not

- Recalculate or modify financial metrics.
- Invent values, transaction details, income sources or customer attributes.
- Treat an anomaly as confirmed fraud.
- Treat a possible circular flow as proof of money laundering.
- Treat missing information as a negative value.
- Claim that a customer is eligible, approved or rejected without the applicable lender policy and required data.
- Recommend a government scheme as eligible without checking its current official criteria and the required customer/business information.
- Infer protected or sensitive traits.
- Hide uncertainty or contradict the deterministic findings without explicitly flagging a data inconsistency.

### 7.3 Evidence supplied to the AI

Pass only the information needed for the report:

- Customer type and analysis period
- Existing metric values and metadata
- Existing rule results
- New cross-metric findings
- Behavioural findings
- Relevant transaction evidence or IDs
- Data gaps and limitations
- Optional ML signal, clearly labelled experimental

Avoid sending the entire statement if a compact evidence package is sufficient. Apply the project's data privacy and access controls.

### 7.4 Suggested AI instruction

Use the following as a starting system instruction, adapting it to the LLM provider already used by the project:

> You are a financial analysis explanation assistant. The supplied metrics and rule results were produced by the application's deterministic financial engine and are the source of truth. Do not recalculate, modify or invent values. Explain the evidence in clear, neutral language. Connect related metrics, identify both supporting and contradicting evidence, and state what is unknown. Distinguish observed facts, calculated metrics, deterministic rule findings, statistical anomalies and your interpretation. Never claim fraud, default, loan approval or loan rejection from bank-statement patterns alone. Do not infer sensitive personal characteristics. If evidence is incomplete, say so. Return only the requested structured response.

### 7.5 AI output contract

Return valid JSON matching a schema enforced by the application. Example:

```json
{
  "executive_summary": "The available data indicates ...",
  "financial_position": {
    "assessment": "MODERATE",
    "explanation": "..."
  },
  "strengths": [
    {
      "title": "Manageable observed debt burden",
      "explanation": "...",
      "evidence_refs": ["FOIR"]
    }
  ],
  "concerns": [
    {
      "title": "Limited liquidity buffer",
      "explanation": "...",
      "evidence_refs": ["NAMB", "EOD_STRESS"]
    }
  ],
  "cross_metric_interpretation": [
    {
      "finding": "...",
      "evidence_refs": ["VNMI", "FOIR", "NAMB"]
    }
  ],
  "recommended_actions": [
    {
      "action": "...",
      "reason": "...",
      "evidence_refs": ["..."]
    }
  ],
  "missing_information": [],
  "limitations": [],
  "loan_considerations": {
    "status": "FURTHER_REVIEW",
    "explanation": "This is not an approval or eligibility decision."
  },
  "human_review_required": true
}
```

The schema is a starting contract. Align it with the frontend and existing API. Validate the LLM response; retry with a constrained repair prompt or return a safe error/fallback if invalid. Never silently accept malformed JSON.

The AI should cite metric names, values and evidence references in its explanation. The application should verify that every referenced metric or evidence ID exists in the input.

---

## 9. Loan considerations and recommendations

The system may produce **loan-related considerations**, not a final lending decision.

Possible analysis:

- Existing debt burden relative to verified income
- Observed liquidity and cash-flow consistency
- EMI repayment patterns
- Income continuity
- Potential room for a proposed EMI, only if the proposed amount, term, rate and applicable policy are supplied
- Missing credit bureau, employment, collateral or lender-specific information

Do not calculate a proposed EMI affordability amount unless the required inputs and an approved method are supplied. Do not invent lender-specific thresholds.

Use neutral statuses such as:

- `POTENTIALLY_SUPPORTIVE_INDICATORS`
- `MIXED_INDICATORS`
- `FURTHER_REVIEW`
- `INSUFFICIENT_DATA`

These are internal assessment labels, not eligibility decisions.

### Government and financial scheme discovery

Scheme recommendations are a later, optional feature. A bank statement alone is insufficient to establish most scheme eligibility.

Before suggesting a scheme as potentially relevant, the system may need:

- Individual or business profile
- Business activity/industry
- Udyam/MSME registration
- Business vintage and turnover
- Location
- Loan purpose and amount
- Current official scheme criteria

If those inputs or verified scheme sources are unavailable, return `NOT_ASSESSED` or `MORE_INFORMATION_REQUIRED`. Do not fabricate scheme eligibility.

---

## 10. API and integration requirements

Integrate at the point where the existing engine returns its completed result.

Preferred flow:

```python
# Checkpoint 1: collect and approve transaction-level analyst flags first.
reviewed_input = transaction_review.apply_approved_overrides(
    input_data=input_data,
    analyst_notes=transaction_notes
)

# Reuse the existing engine. It remains the only source of calculated metrics.
engine_result = existing_financial_engine.run(reviewed_input)

assessment = financial_intelligence_engine.analyse(
    engine_result=engine_result,
    analyst_notes=transaction_notes
)

interpretation = ai_interpreter.generate(
    assessment=assessment,
    evidence=assessment.get("evidence"),
    relevant_analyst_notes=transaction_notes
)

# Checkpoint 2: analyst reviews AI findings, recommendations and scheme analysis.
final_report = report_builder.build(
    engine_result=engine_result,
    assessment=assessment,
    interpretation=interpretation,
    final_analyst_notes=final_review_notes,
    analyst_review_status=review_status
)
```

This is illustrative pseudocode. Use the repository's actual interfaces, naming and dependency-injection patterns.

Requirements:

- Existing engine invocation and response must continue to work.
- The new layer must be independently testable.
- If the AI provider is unavailable, still return the deterministic assessment.
- If the optional ML model is unavailable, continue without it.
- Keep timeouts, retries and error handling bounded.
- Do not block the core metric calculation on an LLM call.
- Version the new assessment and response schemas.
- Avoid breaking existing frontend consumers; add fields compatibly or introduce a versioned endpoint.
- Log errors without exposing sensitive statement contents.

---

## 11. Testing and acceptance criteria

Add tests around the new layer. Do not rewrite existing tests unless necessary.

### Required deterministic test scenarios

1. Low FOIR, stable VNMI, healthy NAMB and no detected payment failures.
2. High FOIR with low NAMB.
3. Stable VNMI but recurring EOD balance stress.
4. High income with volatile month-to-month income.
5. New EMI causing a rise in FOIR.
6. Low NAMB without any NSF events.
7. High NAMB alongside high FOIR.
8. Possible circular flow alongside high gross credits.
9. Missing NAMB or unavailable CC/OD limit.
10. Short history with only one or two months of data.
11. Conflicting or incomplete rule results.
12. SME with high turnover but weak DSCR.
13. SME with high customer concentration.
14. AI provider unavailable.
15. Invalid or incomplete AI JSON response.

### Acceptance criteria

The task is complete when:

- [ ] The existing financial engine remains unchanged in its core calculations and still passes its tests.
- [ ] The new layer consumes the existing engine output directly.
- [ ] FOIR, VNMI and other existing metrics are not recalculated.
- [ ] Missing values are not silently converted to zero.
- [ ] Cross-metric findings are deterministic, explainable and covered by tests.
- [ ] Historical trends are only produced when sufficient history exists.
- [ ] Any ML component is optional, versioned and clearly separated from policy.
- [ ] AI summaries use only supplied metrics and evidence.
- [ ] AI output is schema-validated.
- [ ] The deterministic report remains available when the AI provider fails.
- [ ] Existing API/frontend functionality is not broken.
- [ ] Findings can be traced to source metrics, rule IDs and transaction evidence where available.
- [ ] No automatic loan approval, rejection, default or fraud decision is introduced.

---

## 12. Auditability and reproducibility

For each assessment, record:

- Assessment ID and timestamp
- Customer reference using the project's privacy-safe identifier
- Existing engine version
- Input metric snapshot or secure reference to it
- New intelligence-engine version
- Rules/configuration version
- Findings and their evidence references
- Optional ML model/version and result
- AI provider/model and prompt/schema version
- AI output or secure reference to it
- Human review outcome, if any

The deterministic part must return the same result for the same metric input and configuration.

Do not log full account numbers, unnecessary personal data or raw statement content in ordinary application logs.

---

## 13. Assumptions and implementation decisions

Maintain the project's existing separate files:

### `ASSUMPTIONS.md`

Record unresolved assumptions, including:

- Actual existing engine response schema and field names
- Which historical monthly series are available
- Whether individual and SME profiles are explicitly selected
- Whether transaction-level evidence is available to the new layer
- Which LLM provider and model are already configured
- Whether any labelled training data exists
- Which thresholds are approved for the intended product

Each entry should include ID, date, area, assumption, reason, impact, confidence and whether confirmation is needed.

### `DECISIONS.md`

Record decisions actually made, including:

- Integration point and adapter design
- Deterministic engine versus optional ML choice
- Any new derived indicator and its formula
- Assessment labels and configurable thresholds
- AI provider/model and prompt/schema versions
- API compatibility strategy
- Escalation and human-review behaviour

Do not record an undecided proposal as a completed decision.

---

## 14. Implementation order

Work in this order. Keep each step small and testable.

1. Inspect the repository and locate the successful existing engine output.
2. Document current architecture, metric schema and integration point.
3. Add an adapter/validator for the existing output; do not alter the calculations.
4. Implement deterministic cross-metric analysis.
5. Add historical trend analysis only for available historical series.
6. Produce a structured assessment with evidence references and data gaps.
7. Add tests for the scenarios in Section 10.
8. Integrate the AI summary using the existing provider/client if one exists.
9. Validate AI JSON and implement deterministic fallback behaviour.
10. Connect the report to the existing API/frontend without breaking current consumers.
11. Evaluate whether a small ML anomaly model is genuinely needed. If not, document why it was deferred.
12. Implement both analyst checkpoints, note permissions, approval states and audit history.
13. Update `ASSUMPTIONS.md`, `DECISIONS.md` and developer documentation.

**Do not begin by training a neural network. First deliver the deterministic intelligence layer and AI explanation.**

---

## 15. Expected first response from the coding agent

Before making major changes, report:

1. Which existing module produces FOIR, VNMI and the other values.
2. The actual output schema and a redacted example.
3. Which existing rule results and evidence can be reused.
4. The exact point where the new layer will be integrated.
5. Which new files are necessary and which existing files need minimal edits.
6. Whether historical data is available for trend analysis.
7. Whether an LLM provider/client already exists.
8. Whether there is enough labelled data to justify ML.
9. A concise implementation plan and compatibility risks.

Then implement the smallest working extension.

**Final product goal:** build a bank-facing analyst-assisted financial intelligence product on top of the working rule-based engine. Preserve its metrics as the numerical source of truth; capture analyst flags before calculation; connect the resulting metrics with a lightweight explainable intelligence layer; use AI for concise, evidence-backed interpretation and recommendation/scheme analysis; then let an analyst review and finalize the result. Do not rebuild the existing engine.

```

```
