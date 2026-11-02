# Family Pension Conversion Tool — Windows desktop v0.3.0

This is a local Python application. It reads SAMPANN reports through your own
signed-in Chrome window, lets you review extracted data, and creates an Excel
due/drawn statement using the approved single-sheet layout.

**Status:** local calculation, parser, export and isolated Chrome workflow tests
pass. Tests cover inline PDF viewer downloads, Normal/Migrated routing, native
menus/date-pickers, complete payment queries and failure evidence. A synthetic
case also runs from downloaded sources through the standard Excel export.
Saved live source documents were checked separately. Full collection of the
three real cases using this version and comparison of their final Excel results
remain pending. This is source code; no new EXE was built. Windows portable
builds remain manual only.

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
   **Collect case**. Revision Authority Documents are checked first. Missing
   required sources stop for review with a saved record. A document must identify a
   conversion/updation/absorption order before its fields are used.
3. Review Case fields. Select **IDA (Industrial Dearness Allowance)** or
   **CDA (Central Dearness Allowance)** if the source is ambiguous. These
   categories select the corresponding Dearness Relief rate schedule.
4. Missing/conflicting fields remain for your review; they are never filled
   by guessed names/dates/digits. Use **Import PDF / profile text** for a current
   original EPPO (Electronic Pension Payment Order), commutation
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
- Normal SAMPANN cases read claimant/death fields from the visible HTML Form 14
  modal, original EPPO/commutation PDFs, and explicit Pension Type/restoration
  from DCRG & Commuatation Payment Report. Migrated cases use the labelled
  one-pager sections and do not attempt Form 14, even if its generic link exists.
  Repeated DOB labels are scoped to their original/family sections.
- Menus, links, calendar controls and viewer Download buttons are clicked
  normally. Required controls are scrolled into view. No report address is
  opened directly, no document URL is refetched, and no JavaScript click or
  sidebar/date-field mutation is used. Downloaded files must contain PDF data;
  extracted sources must positively identify the requested PPO. A unique matching
  family conversion PDF is copied to `family pensioner_<PPO>.pdf`.
- An identified, dated commutation revision may supersede an earlier original
  basic/commuted value; both sources are retained. Other conflicts remain blank
  for review. Generic IDA boilerplate is not category evidence.
- PDF layouts and portal markup can change. The exact original Basic, monthly
  commuted portion and Form14 labels may need parser adaptation after the first
  live run. Mandatory inputs and the review checkbox prevent a partially read
  case being exported silently.
- No portal Send, approval, update or payment action is performed. Collection
  navigates read-only report pages and submits report searches only.
- The dedicated Chrome profile stores the browser session locally. Close the
  browser when finished. Do not share `cases`, `output`, the Chrome profile, or
  saved case JSON with others; those may contain pension/bank data.

## Saved steps and failure recovery

Every collection/payment refresh and calculate/export run has a distinct folder
under `cases/<PPO>/runs/`. **Show saved steps / diagnostics** opens the latest run.
`steps.jsonl` saves the action, expected/actual result, UTC time and duration;
`progress.json` saves partial fields, source branch, documents and query coverage.
`partial_case.json`, when available, can be loaded through **Load saved case JSON**
to continue review, then refresh payments. This is a review checkpoint, not an
automatic replay of interrupted clicks.

On failure the folder includes available rendered-page PNG/HTML/TXT evidence and
`diagnostics.zip`. Login/password/OTP screens are omitted. DOM evidence removes
scripts, hidden/credential fields and link queries. Network payloads, headers,
cookies and browser storage are not recorded. The pack can still contain pension
and bank data: keep it local and share only after reviewing it. Nothing uploads
automatically. Connection failure produces a record even without a screenshot.

Waits are bounded. Only scrolling gets a safe retry; the tool does not repeat an
uncertain click or invent missing values. Failed/partial/filtered payment queries
never become zero Drawn. Resolve the reported cause and collect/refresh again.

## Tests and troubleshooting

Run `.venv312\Scripts\python.exe -m unittest discover -s tests -v`.

For isolated browser tests, install Playwright Chromium, set `RUN_BROWSER_TESTS=1`
and run the same command. Alternatively set `TEST_BROWSER_CHANNEL=chrome` to use
installed Chrome. Tests use temporary profiles, synthetic data and a loopback
server; they do not use your SAMPANN session. See `TEST_RESULTS.txt`.

- Connection failure: a normal open Chrome window is insufficient. Open the
  browser using the tool button, complete login/OTP there, and retry.
- No revision: collection stops for source review; inspect the saved steps.
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
