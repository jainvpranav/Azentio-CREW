# Decisions

Deliberate implementation/product choices actually taken, as opposed to
[ASSUMPTIONS.md](ASSUMPTIONS.md) (things provisionally believed because data or
requirements are incomplete). An assumption can later be *resolved into* a decision
once confirmed — when that happens, link back to the assumption ID it replaces.

| Field | Meaning |
|---|---|
| ID | `D-###`, stable once assigned |
| Date | when decided |
| Context | the problem/question being resolved |
| Options considered | where useful |
| Decision | what was chosen |
| Rationale | why |
| Consequences | what this changes or constrains going forward |
| Affected files/modules | |

---

### D-001 — Extend the existing engine; no rewrite
**Date:** 2026-10-31
**Context:** The handoff explicitly extends a prior hackathon build (`BUILD_PLAN.md`, Level 1 MVP) into a fuller explainable financial-analysis system for individuals and SMEs.
**Options considered:** (a) rewrite the pipeline around a new data model; (b) extend the current FastAPI + SQLModel + SQLite pipeline in place.
**Decision:** (b). Repository inspection confirmed a working, tested Level-1 pipeline already covers: multi-format ingestion (2 PDF layouts + CSV/XLSX/JSON), reconciliation, dedupe, coverage, a 15-rule classification engine with pairing (reversals, refunds, cross-account transfers, salary/EMI clustering), traceable `MetricResult`-style metrics with included/excluded/caveats, and a flags engine. None of this needs to be rebuilt.
**Rationale:** Handoff explicitly says "Do not rebuild from scratch" / "Do not break working functionality." The existing architecture (deterministic rules + append-only classification + `MetricResult` breakdown contract) already matches the handoff's auditability requirements almost exactly.
**Consequences:** All new work (SME metrics, red-flag metrics, behavioral analysis, rule evaluation/risk tiers, AI Reviewer, reports) is additive: new modules under `app/pipeline/`, `app/ai/`, new API routes, new model fields (nullable/additive only). The six target categories are reorganized as a thin mapping over the existing richer 17-value `TransactionCategory` enum (see D-002) rather than replacing it.
**Affected files/modules:** all of `app/`.

### D-002 — Keep the existing 17-category enum; map it to the handoff's 6 top-level categories
**Date:** 2026-10-31
**Context:** The handoff defines 6 categories (Internal transfers, Salary, Business receipts, Refunds/Reversals, Loan EMI, Common expenses). The existing `TransactionCategory` enum already has 17 finer-grained values (e.g. `RENT`, `UTILITIES`, `CARD_PAYMENT`, `CASH_WITHDRAWAL`, `BANK_CHARGES`, `INTEREST`, `LOAN_DISBURSEMENT`, `RETURNED_PAYMENT`, `UNCLASSIFIED` in addition to the 6 handoff categories).
**Options considered:** (a) collapse the enum down to exactly 6 values; (b) keep the richer enum and introduce a `category_group` concept (6 groups) for handoff-level reporting/anomaly logic.
**Decision:** (b). `RENT`, `UTILITIES`, `CARD_PAYMENT`, `CASH_WITHDRAWAL`, `CASH_DEPOSIT`, `BANK_CHARGES`, `INTEREST`, `OTHER_EXPENSE` all become subcategories of the handoff's "Common expenses" group; `LOAN_DISBURSEMENT` and `RETURNED_PAYMENT` stay as their own tracked categories (needed for income exclusion and the NSF/Bounce red flag respectively) but are not one of the 6 primary groups; `UNCLASSIFIED` remains the explicit "we don't know" bucket.
**Rationale:** The finer categories carry real information the handoff's own expense list wants (groceries/dining/utilities/rent/etc.) and existing rules/tests already depend on them. Collapsing would lose information and break working tests for no benefit.
**Consequences:** A new `CATEGORY_GROUP` mapping constant will be added (likely in `app/models.py` or a new `app/pipeline/categories.py`) used by reports and behavioral analysis; classification rules themselves are unchanged.
**Affected files/modules:** `app/models.py`, new `app/pipeline/categories.py`, `app/pipeline/metrics.py`, `app/pipeline/flags.py`, report builders.

### D-004 — Fixed a pre-existing CSV/Excel column-matching bug found via integration testing
**Date:** 2026-10-31
**Context:** While smoke-testing the new assessment/report endpoints end-to-end against an uploaded CSV, SALARY credit rows silently disappeared (3 of 6 rows parsed). Root cause: `app/ingest/structured_parser.py:find_columns` matched columns by raw substring against a flat keyword list (`['credit', 'deposit', 'dep', 'cr', 'in']`), in column order, first match wins. A header literally named "Description" contains the substring "cr" (de-**scr**-iption) and sat before the real "Credit" column, so it was picked as the credit column; its text values failed to parse as an amount, so every credit row was silently dropped as "no amount" even though a perfectly normal `Date,Description,Debit,Credit,Balance` header was used.
**Options considered:** (a) leave as-is (out of scope - not asked for in the handoff); (b) fix it, since it silently drops real financial data on a very plausible real-world header and directly undermines "never invent/drop data" and the metrics this whole handoff is about.
**Decision:** (b), fixed. `find_columns` now: tries strong/full-word keywords (`debit`, `credit`, `withdrawal`, `deposit`) before short abbreviations (`dr`, `cr`, `wd`, `in`, `out`, `dep`); and excludes whatever column was already assigned to `date`/`description` from the debit/credit/balance search.
**Rationale:** This isn't scope creep - it's a correctness bug in existing ingestion that this engagement's own test data exposed, and it directly contradicts the project's own stated principle ("Never invent data... Unparseable page = surfaced error, never silently skipped" - here a parseable row was silently skipped instead of surfaced).
**Consequences:** Any CSV/Excel with a "Description"/"Narration"-style column ahead of its real Credit column in column order now parses correctly. Existing tests (`tests/test_structured_parser.py`) still pass; added `test_find_columns_does_not_mismatch_description_as_credit` as a regression test.
**Affected files/modules:** `app/ingest/structured_parser.py`, `tests/test_structured_parser.py`.

### D-003 — `ASSUMPTIONS.md` / `DECISIONS.md` linked from README, not merged
**Date:** 2026-10-31
**Context:** Handoff requires these as two separate files, referenced from the README.
**Decision:** Add a short "Project governance" section near the top of `README.md` linking both files; keep them as separate top-level markdown files (not under `docs/`), matching where the handoff file itself (`bank_statement_agent_handoff.md`) already lives.
**Rationale:** Discoverability; matches explicit handoff instruction to keep them separate and linked from docs.
**Affected files/modules:** `README.md`.

---

## Pending decisions (deferred to the review in this agent's first response)

The following are flagged in the agent's gap-analysis message as needing the user's
input before implementation proceeds, and are *not yet decided*:

- Scope and ordering of Phases 2–7 for this engagement (full handoff is very large;
  see the message accompanying this file for a proposed sequence and a request to
  confirm priority).
- Whether the AI Reviewer (Phase 6) should be built against a live LLM in this pass,
  or stubbed/deterministic-only for now (depends on API key availability — see
  ASSUMPTIONS.md A-005).
- Confirmation or correction of ASSUMPTIONS A-001 through A-009.
