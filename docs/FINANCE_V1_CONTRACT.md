# Tori Finance / Budgeting V1 Contract

**Status:** Finance V1 implemented and human accepted with synthetic financial data
**Authority:** Living technical contract subordinate to the seven founding documents, `docs/ARCHITECTURE_GOVERNANCE.md`, and `docs/TARGET_ARCHITECTURE.md`

## 1. Purpose

Finance V1 is a local-first budgeting notebook and financial-planning capability that Tori understands. It helps the user organize user-supplied financial facts, calculate practical budgeting answers, preview statement imports, and reason about bills, debts, goals, and discretionary purchases.

Finance V1 is informational and advisory. It is not a bank, payment system, accounting suite, tax product, investment platform, or autonomous financial decision maker.

This contract fixes the V1 product semantics and remains authoritative for the implementation. Enabling Finance and creating its external workbook remain explicit user-controlled actions; repository checkout or ordinary startup creates no Finance data.

## 2. Product principles

Finance V1 follows these rules:

- The user supplies the financial data.
- Data remains local, user-owned, understandable, and manually inspectable.
- Tori calculates deterministically and explains conversationally.
- Read-only analysis normally needs no confirmation.
- A Tori-authored durable change requires an exact proposal and explicit confirmation.
- Missing, ambiguous, or stale data is reported rather than silently guessed.
- Useful, narrow workflows take priority over financial-software completeness.
- Finance semantics belong to Tori, not to a model, spreadsheet library, parser, or future storage backend.

## 3. Architecture and ownership

The V1 boundary is:

```text
Conversation / future Finance client
                |
                v
FinanceService
  - domain validation
  - deterministic calculations
  - import policy and preview
  - mutation proposals/results
                |
                v
FinanceRepository
  - typed reads and writes
  - opaque revision / conflict checks
  - atomic persistence and verification
                |
                v
WorkbookFinanceRepository
                |
                v
User-owned workbook and import area
```

Tori owns intent interpretation, domain meaning, calculation policy, authority, confirmation, failure honesty, and presentation. `FinanceService` is presentation-neutral and accepts and returns Finance domain values rather than cell addresses or spreadsheet-library objects.

`FinanceRepository` owns the durable-storage contract. Its first adapter may read and write an Excel workbook, but workbook mechanics do not become Finance semantics. A future SQLite or other repository may replace it without changing Conversation, calculations, authority rules, or the meaning of Finance records.

The model may interpret a question and express a FinanceService result as Tori. It does not read arbitrary cells, parse statements, calculate totals, choose durable mutations, authorize imports, or invent missing values.

## 4. Finance data root

Finance V1 uses one explicitly configured, user-owned local data root. The recommended first-run experience is to ask the user to choose or approve a directory, with a human-friendly suggestion such as:

```text
~/Documents/Tori Finance/
```

An explicit configured path always wins. Implementations may use the operating system's configured Documents directory when suggesting a location, but must not assume that `~/Documents` exists or create a directory before approval.

The data root must be:

- outside Git-tracked project content;
- outside `<tori-root>/runtime/`;
- local and user-owned;
- configurable by exact path;
- easy for the user to open with ordinary desktop tools;
- suitable for the user's normal backup approach; and
- rejected if it resolves through an unsafe or unexpected symlink boundary.

Finance usage must not require canonical Tori-runtime mutation. Configuration may identify the root, but credentials and financial account identifiers do not belong in tracked configuration.

The V1 layout is:

```text
finance-data-root/
├── tori_finance.xlsx
└── imports/
    ├── incoming/
    └── processed/
```

The workbook is authoritative Finance state. `incoming/` contains user-placed source statements awaiting preview. `processed/` contains source artifacts associated with approved import batches. Tori does not watch either directory automatically in V1.

Moving a statement from `incoming/` to `processed/` occurs only as part of a successfully approved and verified import. Rejected or cancelled previews do not move or delete the source. Tori does not automatically delete processed statements. File names used by Tori must be sanitized and must not introduce account numbers into generated names.

## 5. Workbook-wide conventions

The workbook contains exactly these V1 sheets, in this order:

1. `Transactions`
2. `Merchant Rules`
3. `Bills`
4. `Debts`
5. `Budget`
6. `Goals`
7. `Summary`

All durable source records live in the first six sheets. `Summary` is a rebuildable projection and is never the source of canonical balances, transactions, rules, bills, budgets, or goals.

V1 uses one configured ISO 4217 currency per workbook. Currency conversion and mixed-currency arithmetic are out of scope. The selected currency and Finance contract version are displayed in the visible Summary metadata block.

Types have the following meanings:

- **Identifier:** Stable opaque text generated by Tori; users may view it but should not need to edit it.
- **Text:** Trimmed Unicode text with no NUL or control-line injection.
- **Date:** A civil calendar date, displayed as `YYYY-MM-DD`; it has no time zone or time of day.
- **Month:** `YYYY-MM`.
- **Money:** Numeric decimal currency, calculated with decimal arithmetic and rounded to the currency's minor unit at defined result boundaries; binary floating-point is not authoritative.
- **Percent:** Numeric annual percentage points, so `24.99` means 24.99%, not 0.2499.
- **Boolean:** `TRUE` or `FALSE`.
- **Enum:** One documented value, compared case-insensitively on input and written canonically.

Blank optional cells mean unknown or not applicable. Blank never means zero. Formulas may improve manual readability, but FinanceService must be able to reproduce every authoritative calculation without trusting workbook formula caches.

Every repository read validates sheet names, required headers, types, identifiers, references, and bounded record counts. Unknown extra columns may be preserved when safe but have no V1 semantics. Missing required columns, duplicate identifiers, invalid cross-references, or malformed values make the relevant operation fail clearly rather than silently repairing user data.

## 6. Transactions sheet

`Transactions` contains committed normalized activity only. Import candidates do not appear here before approval.

| Field | Type | Required | Owner | Meaning and validation |
|---|---|---:|---|---|
| `Transaction ID` | Identifier | Yes | Tori-derived | Stable identity assigned only when a transaction is committed; unique within the workbook. |
| `Date` | Date | Yes | User/source | Effective transaction date used for budgeting. |
| `Merchant` | Text | Yes | Tori-derived or user-reviewed | Friendly normalized merchant/payee. Manual entries may use the entered description. |
| `Original Description` | Text | Yes | User/source | Original statement description, preserved for audit and rule review; manual entries may repeat `Merchant`. |
| `Amount` | Money | Yes | Tori-normalized | Signed budget effect defined below; nonzero. |
| `Transaction Type` | Enum | Yes | Tori-normalized or user-reviewed | `income`, `expense`, `refund`, `transfer`, `debt_payment`, `savings`, or `adjustment`. |
| `Category` | Text | Yes | Rule/user | A configured Finance category. Refunds normally retain the original purchase category. |
| `Account Label` | Text | Yes | User | Friendly source label such as `Checking` or `Citi Card`; never an account number. |
| `Import Source` | Text | Yes | Tori-derived/user | `manual` or a bounded human-readable source label such as institution/export type; not a path containing sensitive metadata. |
| `Import Batch ID` | Identifier | No | Tori-derived | Stable approved import-batch identity; blank for manual entries. |
| `Source Transaction ID` | Text | No | Source | Institution/export reference when safely available; must not be an account number. |
| `Duplicate Fingerprint` | Text | Yes | Tori-derived | Stable deterministic digest used for duplicate review; based on source facts, not mutable categorization. |
| `Related Bill ID` | Identifier | No | User/Tori-reviewed | References one `Bills` record when this is payment of that bill. |
| `Related Debt ID` | Identifier | No | User/Tori-reviewed | References one `Debts` record when this is a debt payment. |
| `Notes` | Text | No | User | Optional context; never required for calculations. |

### Amount and type semantics

Canonical `Amount` represents the transaction's effect on the user's monthly resources, not the source statement's institution-specific sign convention:

- Positive: income or a refund/credit that restores resources.
- Negative: an expense, debt payment, savings allocation, or other use of resources.
- Transfer: signed from the selected source's direction but excluded from income and spending totals by default.
- Adjustment: either sign and included only when its category and stated purpose make the calculation applicable.

Import adapters must explicitly map each source's debit/credit convention into these semantics. They may not copy raw signs without knowing the format. A credit-card purchase is a negative `expense`. One user-level payment toward debt is a negative `debt_payment`; a mirrored credit on the liability statement must be normalized as the other side of a `transfer` or excluded explicitly during preview, never committed as a second debt-payment outflow. Cross-account payment candidates with equal absolute amounts and nearby dates are flagged for transfer review rather than silently paired. If the same movement appears in multiple imported accounts, duplicate/transfer review must prevent double counting.

Consumption spending is the net of `expense`, category-linked `refund`, and applicable `adjustment` rows. `income`, `transfer`, `debt_payment`, and `savings` remain separate financial flows.

## 7. Merchant Rules sheet

Merchant rules are understandable deterministic mappings. V1 has no machine learning, embeddings, fuzzy scoring, or model-owned categorization.

| Field | Type | Required | Owner | Meaning and validation |
|---|---|---:|---|---|
| `Rule ID` | Identifier | Yes | Tori-derived | Stable unique rule identity. |
| `Match Type` | Enum | Yes | User | `exact`, `starts_with`, or `contains`; no regular expressions in V1. |
| `Match Text` | Text | Yes | User | Case-insensitive normalized text matched against `Original Description`; minimum meaningful length for `contains`. |
| `Account Scope` | Text | No | User | Optional exact friendly account label; blank applies to all sources. |
| `Normalized Merchant` | Text | Yes | User | Friendly merchant written to matching candidates. |
| `Category` | Text | Yes | User | Category written to matching candidates. |
| `Priority` | Integer | Yes | User | `1` through `999`; lower values run first. |
| `Active` | Boolean | Yes | User | Inactive rules remain visible but do not apply. |
| `Notes` | Text | No | User | Optional explanation. |

Rules are evaluated by active state, account scope, ascending priority, then deterministic specificity (`exact`, `starts_with`, `contains`). Two rules that remain equally applicable but disagree produce an uncertain candidate; Tori does not choose one silently.

Known unambiguous rules apply automatically during import preview. Unknown merchants and conflicts are flagged. A new or changed rule is itself a durable Finance mutation requiring confirmation. Changing a rule affects future previews only; reclassifying committed transactions requires a separate preview and confirmation.

The starting category registry is:

- `Income`
- `Housing`
- `Utilities`
- `Groceries`
- `Dining / Fast Food`
- `Shopping`
- `Amazon`
- `Transportation`
- `Entertainment`
- `Subscriptions`
- `Healthcare`
- `Personal`
- `Debt Payment`
- `Savings`
- `Transfer`
- `Other`

FinanceService owns the category registry and its budget-group mapping. The V1 defaults group Housing, Utilities, Groceries, Transportation, and Healthcare as essential; Dining / Fast Food, Shopping, Amazon, Entertainment, Subscriptions, Personal, and Other as discretionary; Debt Payment and Savings as financial allocations; and Income and Transfer as non-consumption flows. Bills remain obligations regardless of category. A later user-extensible registry can add categories without changing transaction storage or repository boundaries.

## 8. Bills sheet

`Bills` records expected obligations. Finance owns bill facts; it does not schedule reminders.

| Field | Type | Required | Owner | Meaning and validation |
|---|---|---:|---|---|
| `Bill ID` | Identifier | Yes | Tori-derived | Stable unique bill identity. |
| `Name` | Text | Yes | User | Friendly name such as `Electric` or `Internet`. |
| `Category` | Text | Yes | User | Finance category. |
| `Amount Kind` | Enum | Yes | User | `fixed` or `variable`. |
| `Expected Amount` | Money | Yes | User | Nonnegative expected obligation. For variable bills, the user's present planning estimate. |
| `Rolling Average` | Money | No | Tori-derived | Rebuildable average of recent linked payments; never replaces `Expected Amount` silently. |
| `Next Due Date` | Date | Yes | User | Next known civil due date. |
| `Frequency` | Enum | Yes | User | `weekly`, `biweekly`, `monthly`, `quarterly`, `annual`, or `one_time`. |
| `Due Day` | Integer | No | User | Day 1–31 for monthly/quarterly/annual rules; if absent, `Next Due Date` remains the anchor. A day beyond a month resolves to that month's last day. |
| `Autopay` | Boolean | Yes | User | Informational only; grants no payment authority. |
| `Active` | Boolean | Yes | User | Inactive bills are excluded from upcoming obligations. |
| `Notes` | Text | No | User | Optional context. |

Projected occurrences are calculated from `Next Due Date`, `Frequency`, and optional `Due Day` without mutating the bill. Finance does not create Scheduled Work. A linked committed transaction may mark an occurrence paid for calculation purposes; an uncertain match is reported rather than assumed.

The displayed rolling average defaults to the most recent three linked paid occurrences when available. The answer must state the sample count. A different bounded window may be requested explicitly.

## 9. Debts sheet

`Debts` covers user-supplied credit-card and loan planning facts without account numbers.

| Field | Type | Required | Owner | Meaning and validation |
|---|---|---:|---|---|
| `Debt ID` | Identifier | Yes | Tori-derived | Stable unique debt identity. |
| `Name` | Text | Yes | User | Friendly name such as `Citi Card` or `Auto Loan`. |
| `Debt Type` | Enum | Yes | User | `credit_card`, `loan`, or `other`. |
| `Current Balance` | Money | Yes | User | Nonnegative outstanding principal/balance. |
| `APR` | Percent | Yes | User | Nonnegative annual percentage rate; zero is allowed. |
| `Minimum Payment` | Money | Yes | User | Nonnegative required planning payment. |
| `Target Payment` | Money | Yes | User | Planned payment, at least the minimum unless the record is explicitly incomplete and excluded from payoff projections. |
| `Next Due Date` | Date | Yes | User | Next known civil payment due date. |
| `Due Day` | Integer | No | User | Optional monthly day 1–31; beyond-month values resolve to the month's last day. |
| `Priority` | Integer | Yes | User | `1` through `999`; lower means higher user priority. This is not an automatic payment order. |
| `Balance As Of` | Date | Yes | User | Date on which `Current Balance` was known. |
| `Active` | Boolean | Yes | User | Inactive/paid debts are excluded from active totals and recommendations. |
| `Notes` | Text | No | User | Optional context. |

Every balance answer includes `Balance As Of`. A balance older than 31 days receives a stale-data warning by default; the date is never silently promoted to “current.” Payoff and affordability results identify stale balances and may decline a confident conclusion when staleness is material.

Debt payments are represented in `Transactions` as negative `debt_payment` rows linked by `Related Debt ID`. A debt's manually supplied balance remains authoritative; transactions do not silently rewrite it.

## 10. Budget sheet

`Budget` has at most one row per calendar month. It is a lightweight planning frame, not zero-based or envelope budgeting.

| Field | Type | Required | Owner | Meaning and validation |
|---|---|---:|---|---|
| `Month` | Month | Yes | User | Unique budget month. |
| `Expected Income` | Money | Yes | User | Nonnegative total income expected for the month. Actual income is reported separately rather than added twice. |
| `Starting Available Funds` | Money | No | User | Spendable funds carried into the month; blank means unknown, not zero. |
| `Essential Spending Target` | Money | Yes | User | Nonnegative planning target for essential consumption. |
| `Discretionary Target` | Money | Yes | User | Nonnegative cap for discretionary consumption. |
| `Savings Target` | Money | Yes | User | Nonnegative intended savings allocation. |
| `Extra Debt Payment Target` | Money | Yes | User | Nonnegative amount above required minimum debt payments. |
| `Reserve Buffer` | Money | Yes | User | Nonnegative amount intentionally left uncommitted. |
| `Notes` | Text | No | User | Optional assumptions. |

Targets are planning values, not transactions and not obligations. FinanceService reports actuals and targets separately. It does not force every expected dollar into a category or silently rebalance targets.

For “discretionary money left,” FinanceService calculates both:

1. `discretionary target remaining = discretionary target - recorded discretionary spending`; and
2. `cash capacity = starting available funds + expected income - recorded non-transfer outflows - remaining upcoming bills - remaining required debt payments - remaining savings target - remaining extra-debt target - reserve buffer`.

When all required inputs are known, conservative discretionary capacity is the lesser of those two values, never below zero. The answer also shows both components so the assumption is understandable. A missing starting-funds value, incomplete budget, unmatched paid bill, or stale debt balance produces a conditional answer rather than false certainty.

Recorded outflows and remaining obligations must not be double counted. Linked bill/debt transactions reduce only the matching remaining occurrence or required payment. Unlinked possible payments are surfaced as uncertainty.

## 11. Goals sheet

| Field | Type | Required | Owner | Meaning and validation |
|---|---|---:|---|---|
| `Goal ID` | Identifier | Yes | Tori-derived | Stable unique goal identity. |
| `Name` | Text | Yes | User | Friendly name such as `New Guitar` or `Emergency Fund`. |
| `Goal Type` | Enum | Yes | User | `purchase`, `savings`, or `debt_payoff`. |
| `Target Amount` | Money | Yes | User | Positive desired amount or balance reduction. |
| `Current Amount` | Money | No | User/derived | Nonnegative accumulated amount for purchase/savings goals. Blank for a linked debt-payoff goal when progress is derived. |
| `Linked Debt ID` | Identifier | No | User | Required for `debt_payoff`; forbidden otherwise. |
| `Debt Starting Balance` | Money | No | User | Required for `debt_payoff`; baseline from which progress is measured. |
| `Target Date` | Date | No | User | Optional desired completion date, not a promise or scheduler event. |
| `Priority` | Integer | Yes | User | `1` through `999`; lower means higher user priority. |
| `Status` | Enum | Yes | User | `active`, `paused`, or `completed`. |
| `Amount As Of` | Date | Yes | User/Tori-derived | Date on which the current amount or debt baseline comparison was known. |
| `Notes` | Text | No | User | Optional context. |

For a linked debt-payoff goal, progress is `Debt Starting Balance - current linked debt balance`, bounded from zero through `Target Amount`; the workbook does not duplicate that derived value as canonical state. Purchase and savings progress uses `Current Amount`. FinanceService reports amount, percentage, remaining amount, data dates, and whether a target date appears feasible under an explicitly stated contribution assumption.

## 12. Summary sheet

`Summary` is generated by FinanceService and may be regenerated at any time. Manual edits to derived cells are not authoritative and are replaced on the next refresh.

Its visible metadata block contains:

- Finance contract version;
- configured currency;
- generation local date/time;
- latest transaction date included; and
- warnings about missing, invalid, or stale source data.

Its V1 sections contain:

- month-to-date income and consumption spending;
- category and merchant spending totals;
- comparison with the prior month and recent three-month average;
- bills due in the next 7 and 30 days and total expected obligations;
- active debt total, minimum/target payments, and highest APR;
- discretionary target remaining and conservative cash capacity;
- savings, purchase, and debt-payoff goal progress; and
- unresolved import, duplicate, or data-quality warnings when applicable.

Summary never creates a second canonical copy of records. FinanceService reads source sheets and calculates fresh results even if Summary is missing or stale.

## 13. Statement import contract

The required workflow is:

```text
user-selected source statement
        |
        v
format-specific parser adapter
        |
        v
normalized candidate transactions
        |
        v
merchant rules and category mapping
        |
        v
duplicate analysis
        |
        v
unknown/conflicting items flagged
        |
        v
bounded import preview and exact proposal
        |
        v
explicit user approval
        |
        v
revision-checked atomic workbook commit
        |
        v
verified result and processed-source move
```

No parser writes the workbook. All formats normalize into one presentation-neutral candidate structure before FinanceService applies rules or policy. A candidate contains source row/page reference, transaction date, original description, source amount/sign information, normalized canonical amount and type, friendly account label, optional safe source transaction ID, proposed merchant/category, matched rule ID, duplicate state, and uncertainty flags.

The preview reports at least source identity, file digest identity, candidate count, date range, inflow/outflow totals, known-rule matches, unknown merchants, category/rule conflicts, definite duplicates, possible duplicates, rejected rows, and every assumption requiring review. The user may correct candidates and optionally propose merchant rules before approval.

The approval is bound to the exact source-file digest, normalized-candidate digest, workbook revision, account label, corrections, and proposed reusable rules. It is one-use and cannot authorize a changed file, changed workbook, or different candidate set. Cancellation, expiry, restart loss, conflict, or apply failure writes no transactions and creates no rules.

Applying an import commits the reviewed transactions and separately approved rules atomically from FinanceService's perspective, verifies the resulting workbook, and only then moves the source into `processed/`. If workbook commit succeeds but the source move fails, Tori reports partial completion truthfully and must not reapply the batch; the committed `Import Batch ID` remains duplicate evidence.

### Format order

1. **CSV:** Preferred when the export has stable columns. Each institution/layout requires an explicit column/sign/date mapping. Unknown layouts require mapping review rather than guessed import.
2. **OFX/QFX:** Preferred structured fallback. Safe transaction IDs and posted dates may improve duplicate detection. Account/routing/card identifiers are discarded after transient source recognition and are never normalized into Finance records.
3. **PDF:** Conservative fallback. Use embedded text extraction when available and only a known layout adapter when fields can be validated. PDF preview is always mandatory. Scanned/image-only PDFs fail as unsupported in the first implementation unless a separately reviewed OCR path is later authorized. OCR is not the default and low-confidence extraction never commits silently.

Parser adapters return data, warnings, and evidence. They own no Finance authority and cannot create categories, rules, transactions, or account labels independently.

## 14. Duplicate detection

Duplicate handling is deterministic and count-aware:

1. The same approved `Import Batch ID` or exact source-file digest is a definite re-import.
2. The same nonblank `Account Label` plus `Source Transaction ID` is a definite duplicate unless the source demonstrably reuses IDs, in which case that adapter must not expose them as stable IDs.
3. Without a safe source ID, FinanceService builds `Duplicate Fingerprint` from account label, transaction date, canonical signed amount, transaction type, and a normalized original description. Merchant/category/rule changes do not alter it.
4. Composite matches are compared as a multiset so two legitimate identical same-day purchases can coexist. A candidate beyond the already committed occurrence count is not silently discarded.

Definite duplicates default to exclusion but remain visible in preview. Composite/fuzzy-looking collisions are `possible duplicate` and require a user decision. V1 does not silently delete or merge committed transactions.

## 15. Deterministic FinanceService calculations

FinanceService, not the LLM, owns:

- period and month-to-date spending totals;
- category and merchant totals;
- income, refund, debt-payment, savings, and transfer separation;
- month-over-month and rolling three-month comparisons;
- linked bill-payment recognition and average bill amounts;
- upcoming bill and minimum-debt obligations;
- budget target actual/remaining values;
- conservative discretionary capacity;
- active debt totals and APR ordering;
- debt payoff projections and interest comparisons;
- goal amount, percentage, remaining amount, and pace projections;
- affordability scenarios;
- import normalization, rule application, validation, and duplicate analysis; and
- data age, missing-input, conflict, and uncertainty warnings.

Spending totals are displayed as positive expenditure values derived from signed records. Category net spending is the negated signed sum of applicable expenses, refunds, and adjustments; a net credit is reported honestly rather than clamped to zero. Transfers, debt payments, and savings allocations are reported separately and excluded from consumption comparisons.

The model may explain or discuss a structured bounded result. It may not replace FinanceService arithmetic with prose arithmetic or present an unsupported recommendation as a calculated fact.

## 16. Affordability scenarios

For a question such as “Can I afford a $900 guitar this month?”, FinanceService accepts the purchase amount, target month, and optional explicit scenario overrides. It calculates:

```text
starting available funds
+ expected income for the month
- recorded non-transfer outflows
- unpaid upcoming bills in the month
- remaining required debt payments
- remaining planned savings
- remaining planned extra debt payments
- configured reserve buffer
= estimated cash capacity
```

It also calculates discretionary-target remaining. The primary conservative capacity is the lesser nonnegative value when both are available.

The result contains the proposed purchase amount, both capacity measures, post-purchase buffer, obligations included, data-through dates, stale facts, missing values, and assumptions. It may conclude `within current plan`, `outside current plan`, or `insufficient data`; it does not make the purchase or represent an estimate as a guarantee.

Expected income is a monthly total and is not added again when matching income transactions appear. Actual income may be compared with expectation and may support an explicit alternate actual-to-date scenario.

## 17. Debt payoff scenarios

FinanceService supports one-debt fixed-payment estimates using the entered balance, APR, minimum or target payment, and additional monthly payment. It calculates a baseline and comparison scenario.

V1 uses monthly compounding for an estimate:

1. monthly rate = APR / 12;
2. monthly interest is applied to the remaining balance and rounded to currency minor units;
3. the selected payment, including extra payment, is applied without exceeding amount due;
4. iteration continues to payoff or a bounded maximum of 1,200 months.

The result includes balance-as-of date, assumed payment, extra payment, estimated months and payoff month, approximate total interest, baseline comparison, time saved, and interest difference. If payment does not exceed accruing interest, required fields are stale/missing, or the bound is reached, FinanceService reports that a reliable payoff estimate is unavailable.

This is a planning estimate, not a lender amortization statement. Fees, daily compounding, changing minimum formulas, promotional rates, new charges, and lender-specific rules are excluded unless later represented explicitly. Tori may explain highest-APR-first and lowest-balance-first as common strategies, clearly separating user facts, deterministic scenarios, and recommendations.

## 18. Conversational access and authority

Read-only Finance questions and deterministic calculations normally require no confirmation. Conversation asks FinanceService for a bounded domain result and supplies only the relevant result to the selected model for explanation. Raw workbook cells, entire transaction history, original statements, and repository implementation details are not dumped into model context.

No confirmation is normally required for:

- summaries, totals, comparisons, and projections;
- bill/debt/goal status reads;
- import parsing and preview that writes nothing; and
- hypothetical affordability or payoff scenarios.

Explicit confirmation is required before Tori:

- applies an import;
- creates, edits, activates/deactivates, or deletes a bill;
- creates, edits, activates/deactivates, or deletes a debt;
- changes a balance, APR, minimum, target payment, or balance date;
- creates, edits, pauses/completes, or deletes a goal;
- creates or changes a monthly Budget row;
- creates, changes, activates/deactivates, or deletes a merchant rule;
- adds, edits, reclassifies, or deletes committed transactions; or
- creates the initial Finance data root or workbook.

Every proposal shows the exact affected records and meaningful before/after values, binds an opaque workbook revision and exact target identities, is one-use, and expires. Confirmation rereads the workbook and fails closed if it changed. The operation is verified after persistence before Tori reports success. Model output, a hypothetical discussion, an import preview, or a workbook calculation never grants mutation authority.

Direct manual edits made by the user in the workbook are user actions, not Tori actions. FinanceRepository validates and observes them on the next read. Tori never overwrites a newer manual edit using a stale proposal.

## 19. Repository, revision, and failure contract

FinanceRepository semantically supports:

- status and current opaque workbook revision;
- typed snapshots of transactions, rules, bills, debts, budgets, and goals;
- one atomic mutation against an expected revision;
- import-batch identity lookup;
- Summary replacement from a computed projection; and
- verified creation of an initially empty V1 workbook after explicit approval.

Exact Python names are deliberately not frozen.

The workbook adapter opens fresh state for each operation, validates before use, and returns an opaque revision derived from safe file identity and content. A mutation writes a complete validated temporary workbook in the same directory, flushes and syncs it, atomically replaces the target, syncs the parent where supported, rereads the result, and verifies the expected domain effect. It must preserve unrelated safe workbook content it claims to support.

A workbook that is open and locked by another application, externally modified, missing, corrupt, of an unsupported contract version, or structurally invalid produces a bounded truthful failure. There is no automatic repair, migration, merge, fallback workbook, or success claim. Reads of valid source sheets remain possible even if Summary regeneration fails.

V1 has no background watcher and no concurrency queue. Optimistic revision checking protects manual edits and multiple clients. Backup remains the user's responsibility until a separate backup-scope mission explicitly integrates this external data root.

## 20. Privacy and security boundary

Finance V1 must not require or intentionally store:

- full bank or credit-union account numbers;
- routing numbers;
- debit or credit card numbers;
- CVVs;
- banking usernames or passwords;
- bank API tokens or aggregation credentials; or
- payment, transfer, or trading credentials.

Friendly labels are sufficient. Import adapters may transiently encounter sensitive header or metadata fields while parsing a user-supplied source, but must discard unnecessary identifiers before candidate normalization. They must not log statement text, raw metadata, account identifiers, or transaction descriptions. Safe errors identify the file and parser class without reproducing sensitive content.

Source statements remain user-owned files and may contain sensitive information outside Tori's normalized data. The import area therefore requires the same local privacy and backup care as the workbook. Tori does not upload, email, synchronize, or externally transmit Finance data in V1.

Finance data is not curated memory, conversation history, Project state, knowledge, or model training material. Only the minimum bounded result needed for the current user request may enter model context. Automatic memory extraction must not promote balances, transactions, income, debts, or statement content into curated memory.

## 21. Strictly no money movement

Finance V1 cannot:

- connect to or authenticate with a bank;
- send or schedule a payment;
- transfer funds;
- initiate or complete a purchase;
- modify a credit or loan account;
- open or close an account;
- trade securities; or
- present itself as having performed any financial action.

Any future money-moving capability requires a separate product, security, authority, and live-acceptance contract. Nothing in this document grants that authority.

## 22. Scheduled Work and proactive behavior

Finance facts may later support a separately authorized Scheduled Work connection, for example a reminder that an electric bill is due and its recent average is $159. Finance remains the source of bill facts; Scheduled Work remains the scheduler and delivery owner. Finance V1 creates no reminder or schedule automatically.

Finance may later provide observations to a proactive-companion system, such as an approaching large bill, unusual category spending, or goal progress. Finance V1 does not autonomously message the user, watch statements, create notifications, or decide what deserves interruption. Future initiative requires separate product and authority controls.

## 23. Human acceptance contract

Acceptance uses a disposable Finance root and synthetic financial data only. No Finance-domain storage beneath canonical runtime or real financial data is required; ordinary interaction history remains subject to the existing Conversation archive contract.

### Read and calculation cases

Tori must answer, from FinanceService results:

1. How much did I spend on fast food this month?
2. How much did I spend on Amazon?
3. What are my biggest spending categories?
4. What bills are due in the next seven days?
5. How much should I reserve for upcoming bills?
6. What is my average electric bill, and how many payments support that average?
7. What are my current credit-card and loan balances, including their as-of dates?
8. Which active debt has the highest APR?
9. If I pay an extra $200 per month toward Citi, what changes in estimated payoff time and interest?
10. Can I afford an $800 or $900 guitar this month under the current plan?
11. How much discretionary money remains, and what assumptions determine it?
12. Am I spending more on fast food than last month?
13. What materially changed over the last three months?

Acceptance must include missing budget inputs, a balance older than 31 days, an unmatched possible bill payment, and a non-amortizing debt scenario so Tori demonstrates honest uncertainty.

### Import and write cases

- Preview a structured CSV containing known merchants, an unknown merchant, two legitimate identical purchases, one definite duplicate, and one ambiguous duplicate; preview writes nothing.
- Cancel the preview and verify workbook bytes/domain revision remain unchanged.
- Approve the exact preview and verify transactions are committed once, Summary is rebuildable, and the source is moved only after commit verification.
- Re-preview the same source and verify definite re-import detection without silent deletion.
- Preview representative XML OFX/QFX through the same candidate contract; legacy non-XML OFX/QFX remains deferred pending a reviewed adapter.
- Confirm arbitrary PDF input fails truthfully without writing; reviewed text/layout adapters remain deferred until a real statement shape can be validated.
- Add a merchant rule through an exact confirmed proposal and verify it applies automatically to the next preview.
- Edit a bill, debt balance/APR/as-of date, Budget row, and goal only after confirmation; cancellation writes nothing.
- Change the workbook manually between proposal and confirmation and verify the stale proposal is refused without overwrite.
- Confirm reads and calculations use a fake FinanceRepository identically to the workbook adapter, proving replacement boundaries.
- Confirm no Finance read or preview contacts a bank, moves money, creates Scheduled Work, mutates memory, or calls a second model.

### Human readability cases

- Open the generated disposable workbook in an ordinary spreadsheet application.
- Confirm all seven sheets, headers, dates, numeric money values, friendly labels, and Summary sections are understandable without Tori.
- Confirm no account number, credential, opaque serialized primary record, or hidden model-owned state is required to interpret the workbook.

## 24. Explicit V1 exclusions

Finance V1 excludes:

- bank API connectivity, Plaid, and equivalent aggregation;
- financial credentials and automatic account synchronization;
- payments, transfers, purchases, and money movement;
- investments, trading, portfolio management, and credit-score monitoring;
- tax preparation and complex accounting;
- multi-currency conversion;
- autonomous financial decisions;
- automatic statement watching or import;
- import without preview and explicit approval;
- OCR as a default parser strategy;
- automatic reminders or Scheduled Work creation;
- proactive financial messaging;
- finance-specific AI training or machine-learned categorization;
- full ledger reconciliation, double-entry accounting, and tax lots;
- a Finance database, schema migration, or canonical-runtime store; and
- Actual Budget or another full budgeting application as the V1 backend.

## 25. V1 implementation status

Finance V1 implements immutable domain values, `FinanceService`, the replaceable `FinanceRepository` protocol, and `WorkbookFinanceRepository` using pinned `openpyxl`. Finance is disabled by default and requires an explicit absolute user-owned data root outside the repository and canonical runtime. Initialization, imports, and typed record changes are revision-bound proposals; workbook writes use same-directory atomic replacement and reread verification.

CSV import is implemented through an explicit column/sign mapping and shared `CandidateTransaction` pipeline. XML-based OFX/QFX exports use the same pipeline and discard account metadata; legacy non-XML OFX/QFX requires a reviewed adapter. Arbitrary PDF parsing is deliberately deferred: the PDF adapter fails truthfully until a known text/layout adapter can validate a real statement shape. Preview never mutates Finance data, and unresolved merchants, rule conflicts, and possible duplicates prevent an import proposal.

Bounded application-owned conversation routes cover the V1 acceptance reads and calculations without provider contact. `/finance initialize` and `/finance import FILENAME | FRIENDLY ACCOUNT` are exact mutation-entry commands using Tori's existing confirmation envelope; imports resolve only a filename already present in the configured `imports/incoming/` directory so source paths do not become conversational metadata. The service also exposes typed revision-bound bill, debt, Budget, goal, merchant-rule, and transaction proposals without making workbook cells part of Conversation semantics.

Automated verification uses only synthetic data and disposable Finance roots. Human acceptance used a disposable external root and verified confirmation-bound initialization, ordinary seven-sheet workbook readability, safe CSV mapping failure, same-batch source-ID duplicate exclusion, bounded candidate review, reusable merchant rules, atomic verified import and source movement, deterministic calculations, manual workbook coexistence, historical rule reuse, and three-month trends. Unique case-insensitive active-debt shorthand resolves only when one debt matches; ambiguity fails closed. The live acceptance conversation remains legitimate canonical conversation history, while automated Web coverage injects a disposable archive.

Finance still performs no bank connection, credential handling, money movement, scheduling, proactive messaging, schema migration, or Finance-domain write beneath canonical runtime. Ordinary Finance conversation events use the existing Conversation archive. Legacy non-XML OFX/QFX and arbitrary PDF parsing remain deferred, and broader natural-language capability interpretation remains a separate product concern.
