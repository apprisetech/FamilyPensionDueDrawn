# Source update — 12 November 2026

Backups taken before this update: local backups/before_unified_rules_20261112_130422. Work is on a separate feature branch; no EXE was built.

## Agreed defaults

- Drawn includes Gross + separate arrear. Supplementary and arrear bills default to payment month. March monthly paid April belongs to March. Reviewer allocation wins.
- Death/conversion month additional quantum and FMA are proportionate to each beneficiary's payable days. Age quantum follows that beneficiary's DOB; birthday-month rate starts on the first day. FMA is outside DR.
- Progressive migrated commutation amounts are incremental portions, with individual restoration dates; equal consecutive totals yield a zero increment. Dated SAMPANN replacement/additional sanctions are retained separately.
- All fields and records remain editable. Changes invalidate old calculations. Original/selected values and diagnostics are retained where available.
- A4 portrait, one page wide with multi-page statements allowed. Preserve the FP print layout; General and Pay Revision use the approved 12-column statement style.

## Verification scope and limits

Synthetic calculation, export and offline navigation checks are recorded in TEST_RESULTS files. Live SAMPANN testing was explicitly deferred by the user for this build.

Pay Revision/General formula-driven supporting schedules rebuild intervals when existing stage/restoration dates change. Changing the overall calendar range or adding schedule rows requires a fresh export. FP retains its existing period-row layout; date edits that require a different set of rows also require regeneration from the app. Do not claim these structural Excel changes are automatic.

General source collection still requires historical-baseline and beneficiary-classification review; a current profile is not sufficient proof of historical rates. Its full-data review editor is structured JSON. Missing or conflicting evidence must be reviewed; this build is not represented as a fully live-validated production release.
