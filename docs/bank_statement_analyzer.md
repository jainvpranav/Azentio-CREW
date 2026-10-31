Handoff: Azentio Bank Statement Analyzer
Repository: Azentio-CREW
Project: Bank Statement Analyzer
Goal
Implement a multi-format bank-statement pipeline for PDF, CSV, JSON, and scanned images. Extract structured financial data, validate document integrity, flag suspicious indicators, and support multiple countries/currencies.

Critical constraint: never convert currencies. Preserve original monetary units and maintain auditable extraction, validation, and review records.

1. Ingestion and parsing
   Detect file type at upload and route to the correct handler.
   Format Required behavior
   PDF Try native text extraction first. If text is insufficient/unusable, render pages and OCR them. Preserve page-level source references where practical.
   CSV Parse rows, headers, delimiters, empty cells, and common date/amount formats into consistent records/string representations for analysis.
   JSON Ingest natively; support transaction arrays and account/statement metadata; map to the common internal model.
   PNG/JPG/JPEG OCR text directly; retain OCR confidence/diagnostics when supported.
2. Fraud detection and validation
   Flags indicate review is required, not proof of fraud.
   2.1 Visual, structural, and metadata checks

- Inspect font-family/size shifts, transaction-table alignment, unusual layout changes, and text overlays.
- Treat formatting differences as indicators only; legitimate exports/scans can vary.
- Inspect available PDF metadata (creation/modification timestamps, producer/software signatures).
- Compare timestamps with statement period/context. Record missing or inconsistent metadata; metadata alone does not prove tampering.
  2.2 Accounting and transaction-pattern checks
  For each account and exact currency, validate:

Previous Balance + Deposits - Withdrawals = Ending Balance

- Recalculate each running balance using debit/credit direction and compare with extracted balances.
- Raise a high-priority validation flag when the difference exceeds configured precision/rounding tolerance.
- Record expected value, observed value, difference, and transaction reference.
- Detect repeated identical/uniform round-number amounts and transaction-volume or cash-flow velocity spikes.
- Compare with historical baselines for the same account and currency. Without history, use configurable heuristics and label them as such—not as historical deviations.
  2.3 Chronology and institution checks
- Detect out-of-order transaction dates.
- Detect missing/irregular reference sequences only when the institution's numbering convention is known.
- Flag banking-holiday dates only when the institution/jurisdiction's settlement rules indicate settlement should not occur.
- Account for weekends, pending/backdated entries, and institution-specific exceptions.
- Validate statement headers against known institution templates; check branch/routing/other identifiers against trusted reference data when available.
- Unknown templates/identifiers require review; do not automatically classify them as fraud.
  2.4 Duplicate-document checks
- Compute SHA-256 for each submission and compare with historical submissions for exact duplicates.
- If minor iterative tampering detection is required, supplement exact hashes with suitable similarity/content-fingerprint checks; changed files generally have different SHA-256 hashes.
- Store hash, comparison result, and related prior-document reference.

3. Multi-country and multi-currency rules
   3.1 No conversion

- Never convert amounts/balances to a base currency (e.g. USD/EUR).
- Never infer exchange rates or calculate converted equivalents.
- Preserve source currency and original amount text, plus parsed numeric value and currency identifier.
  3.2 Currency identification
  Capture symbols and three-letter ISO codes wherever present, including $, €, £, ¥, ₹, USD, EUR, GBP, INR, and CAD.
- Extract currency from transaction amounts, debit/credit columns, and balance headers.
- Use statement-level currency declarations when rows omit currency.
- If currency is uncertain, store it as unknown/unresolved and flag for review. Never infer it solely from user country or bank location.
  3.3 Monetary representation
  Keep each amount explicitly linked to its currency. Logical example:
  {
  "raw_amount": "1,250.00",
  "amount": 1250.00,
  "currency": "USD"
  }
- Preserve printed amount text, separators, and signs.
- Use an exact decimal type (not binary floating point) where financial precision requires it.
- Apply consistently to transaction amounts, opening/closing balances, and running balances.
  3.4 Currency-isolated accounting
  All monetary calculations must use records from the same account and exact currency identifier:

Opening Balance + Deposits - Withdrawals = Closing Balance

- Never add, subtract, compare, or reconcile across currencies.
- Maintain separate balance calculations for each currency.
- Exclude missing/ambiguous-currency transactions from currency-specific calculations until resolved; record the validation limitation.

4. Database and audit records
   Retain extracted source data, normalized transactions, currency attributes, validation outcomes, fraud flags, and audit metrics.
   4.1 Document record (where available)

- Document ID; original filename/type; SHA-256.
- Upload/ingestion timestamp; institution/country; statement period.
- Extraction method (native PDF, CSV, JSON, OCR), processing status, and diagnostics.
  4.2 Transaction record (where available)
- Transaction ID and document link; date; description; reference/UTR.
- Debit, credit, and running-balance values, each with currency.
- Original amount text; extraction confidence or source-page reference when supported.
  4.3 Validation/fraud flag record
  Link each flag to its document and, where relevant, transaction. Store:
- Flag ID; rule/category; severity/priority.
- Explanation; expected/observed values where applicable.
- Detection timestamp; review status and reviewer outcome when available.
  Expose these records to the frontend so reviewers can understand each finding and trace it to its source.

5. Deliverables
6. Parser service: connect PDF/CSV/JSON/OCR handlers; detect and route formats; use native-PDF extraction with OCR fallback; extract currency while preserving original amounts; return a consistent payload.
7. Fraud/validation engine: implement balance, structural, metadata, chronology, pattern, and duplicate checks; produce evidence-backed, traceable flags; isolate calculations by account and currency.
8. Database integration: persist document/transaction/balance currency attributes, raw and precise numeric amounts, flags, validation results, hashes, and audit metrics with document/transaction links.
9. Frontend review support: expose document- and transaction-level flags with rule, reason, and relevant values. Distinguish confirmed validation failures, heuristic anomaly indicators, and unresolved extraction issues.
   Non-negotiable invariants
10. No currency conversion at any stage.
11. No cross-currency arithmetic; scope accounting to the same account and exact currency.
12. Preserve source evidence, original monetary text, and extraction provenance.
13. Auditable flags: include reasons and supporting values.
14. Do not overclaim fraud: anomalies trigger investigation, not automatic fraud conclusions.
15. Graceful PDF fallback: OCR when native extraction is insufficient; record the method.
16. Institution-aware checks: use bank templates, identifiers, holiday calendars, and reference rules only with reliable reference data.
