# Family Pension Conversion Tool — Windows desktop v0.2.1

This is a local Python application. It reads SAMPANN reports through your own
signed-in Chrome window, lets you review extracted data, and creates an Excel
due/drawn statement using the approved single-sheet layout.

**Status:** the calculation/parser/export tests pass locally. The SAMPANN
collector is implemented against the report routes and controls observed in
your session, but has NOT yet been run against your live portal from this new
environment. First run one known case and compare the downloaded source data.
This is a source-code package, not a precompiled Windows executable.

## First setup

1. Extract this entire ZIP into a folder you can write to.
2. Install Python **3.12 (64-bit)** from https://www.python.org/downloads/windows/.
   Include the Python launcher and Tcl/Tk components (standard installer).
3. Double-click `INSTALL.bat`. Internet access is needed to install Python
   dependencies. Google Chrome must already be installed.
4. For scanned PDFs, also run `INSTALL_OCR.bat` once. OCR means Optical
   Character Recognition: local recognition of text from images. Initial
   dependency/model installation needs internet; PDFs are processed locally.
5. Double-click `START.bat`.

## Each case

1. Click **Open Chrome / Login**. Use THIS dedicated Chrome window. Complete
   SAMPANN login and OTP yourself. Your normal Chrome/Firefox session is not
   changed. Keep the tool browser open while collecting.
2. Enter the **15-digit PPO (Pension Payment Order) number** and click
   **Collect case**. Revision Authority Documents are checked first. Cases
   without those documents are skipped. A document must also identify a
   conversion/updation/absorption order before its fields are used.
3. Review Case fields. Select **IDA (Industrial Dearness Allowance)** or
   **CDA (Central Dearness Allowance)** if the source is ambiguous. These
   categories select the corresponding Dearness Relief rate schedule.
4. Missing/conflicting fields remain for your review; they are never filled
   by guessed names/dates/digits. Use **Import PDF / profile text** for a current
   Form14, original EPPO (Electronic Pension Payment Order), commutation
   revision, or a PDF viewer the collector could not download. Open downloaded
   originals with **Show downloaded sources**. Read the Sources tab as well.
5. If the effective date was edited, click **Fetch / refresh payment report**.
   The query must complete successfully before a blank month becomes zero.
6. Select your updated **DR_Master.xlsx** and an output folder. The default
   calculation end is the last day of the previous month. You may choose an
   earlier month-end to reproduce a reviewed historical case.
7. Review payment entries and allocation. In exceptional cases edit the
   `allocated_month` field (`YYYY-MM`) or `include` (`true`/`false`) in Payments.
8. Tick the review checkbox and click **Calculate and export Excel**.

The filename is `15digitPPO_FAMILY_PENSIONER_NAME.xlsx`. Existing files are
never overwritten silently. Choose another output folder for a revision.
Save case JSON to resume review later; it includes the source/query provenance.

## Calculation and allocation rules

- Death-date cross-check: expected death date is conversion sanction w.e.f.
  minus one calendar day. Independently recorded death dates from Form14,
  migrated profile and original pension documents are retained with source names.
  All recorded dates matching expected permits automatic acceptance. Mismatch,
  conflicting recorded dates or no recorded date leaves death date unaccepted;
  expected is displayed as a suggestion, not proof. Enter the reviewed date and
  click **Confirm reviewed death date** before export. The discrepancy and selected
  date remain in Excel notes. Changing effective/selected date or source evidence
  invalidates that confirmation. Saved case JSON preserves the comparison evidence.
- Bank account and IFSC extraction remains restricted to conversion sanction
  PDFs. Other pension documents are not used to fill these bank fields.

- Start on the first day of the conversion effective-date month; end on the
  selected previous/completed month-end.
- Original pension applies before conversion. Monthly commuted portion is
  deducted only for applicable original-pension days before restoration.
- Enhanced/normal family rates switch on the order dates. **No commutation is
  deducted from either family rate**, even before restoration.
- Additional quantum uses the active beneficiary's own date of birth; slabs
  are 20%, 30%, 40%, 50%, 100% at ages 80, 85, 90, 95, 100, effective from the
  birthday month. Confirm scheme applicability during source review.
- FMA (Fixed Medical Allowance) is counted once per month in full. If the
  before/after entitlement differs in a split conversion month, export stops
  for a reviewed monthly override. Save case JSON, put e.g.
  `"fma_overrides": {"2026-09": "1000"}` inside `case`, then reload it.
- Basic for a partial period uses Excel ROUND to whole rupees. Each segment
  total uses ROUNDUP as in the supplied template. DR applies to basic plus
  additional quantum. There is one full-month Drawn value even when Due has
  multiple date segments.
- Two regular `MONTHLY BILL` payments in April: earlier date -> March Drawn;
  later date -> April Drawn. One or more than two April regular bills requires
  explicit allocation, rather than guessing. March supplementary/arrear-bill
  payments are included in March, alongside March pension paid in April.
- Other multiple payments and supplementary/arrear bill types are listed for
  review below the calculation. They use paid month unless manually reallocated.
- The **separate Arrear column** is excluded from Drawn and listed for review
  of its covered period. Bill-type arrear and this separate column are distinct.
- No payment returned for a month after a successful full report query means
  **Drawn = 0**. Login failure, table failure and incomplete pagination are
  errors, never zero-payment evidence.
- Duplicate payment rows stop export for reconciliation.
- Only the final amount has conditional background: positive = green / Arrear
  to be paid; negative = red / Recovery to be done; zero = no colour.
- Excel has no added source/status tabs, no coloured detail cells, and no
  borders on blank footer rows. Review notes, when needed, are below signatures.

## DR_Master format

Recognised headers (within the first 15 rows): `From Date`, `To Date`, `Rate`.
Use separate sheet names containing `IDA` / `CDA`, or a `Category` column.
Rates may be Excel percent cells (241.7% stored as 2.417) or plain values
(241.7). Plain fractions with a General format are **not** assumed percentages.
Every calculation segment must match exactly one applicable category/rate
period; gaps and overlaps stop export. Rate schedules are not invented or
downloaded automatically.

## Source handling and limits

- Text is extracted from PDFs first. Sparse/image pages require explicitly
  enabled local OCR. Account, IFSC, dates and amounts must be checked against
  the original, particularly after OCR. The app has no cloud AI/API dependency.
- SAMPANN-generated cases use original EPPO/commutation documents; migrated
  cases additionally collect the migrated pensioner details page. Conflicting
  sources are displayed rather than resolved by assumption. Some JavaScript-only
  Form14 viewers may require Import PDF.
- PDF layouts and portal markup can change. The exact original Basic, monthly
  commuted portion and Form14 labels may need parser adaptation after the first
  live run. Mandatory inputs and the review checkbox prevent a partially read
  case being exported silently.
- No portal Send, approval, update or payment action is performed. Collection
  navigates read-only report pages and submits report searches only.
- The dedicated Chrome profile stores the browser session locally. Close the
  browser when finished. Do not share `cases`, `output`, the Chrome profile, or
  saved case JSON with others; those may contain pension/bank data.
- The old `D:\...\pension_bot` project was not available in this new environment.
  This package is a new standalone implementation, not a verified patch of that
  old code. Upload that project's ZIP if its special navigation should be reused.

## Tests and troubleshooting

Run `.venv312\Scripts\python.exe -m unittest discover -s tests -v`.

- Connection failure: open the tool Chrome window, complete login/OTP and retry.
- No revision: case is skipped, even if some other pension document exists.
- Missing fields: open the originals, import the appropriate document and review.
- Missing DR: update the selected master; never use a substituted zero rate.
- Wrong April mapping: set the bill's explicit `allocated_month` in Payments.
- Changed date: refresh the payment query before export.
- Existing output: select a new output folder.
- Excel repair warning: do not use a repaired statement as the authoritative
  output; retain the file and error log for debugging. Exporter tests check
  the XML colour element order that caused the previous warning.

Technical references:
- https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp
- https://doppw.gov.in/sites/default/files/01012020_to_31122020_Eng.pdf

## Main source files

`engine.py`: arithmetic, allocation and validation.
`extract.py`: local PDF/OCR and field candidates.
`portal.py`: read-only report collector.
`exporter.py`: approved Excel output with formulas and cached results.
`desktop.py`: local review screen, setup and workflow.

Installer fix: explicitly selects Python 3.12 and uses .venv312. The old .venv and all case/output folders are preserved. Updating pip alone does not resolve an unsupported Python version.
