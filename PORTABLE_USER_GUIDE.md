# Family Pension Tool

1. Extract the entire ZIP into a writable folder.
2. Double-click FamilyPensionTool.exe; keep the _internal folder beside it. No Python installation is required.
3. Open the browser from the application and log in to SAMPANN using your own credentials and OTP.
4. Select your updated DR_Master.xlsx, enter the 15-digit PPO, and collect reports.
5. Review extracted sanction details, bank account and IFSC, dates, pension rates, and payment report coverage. Resolve flagged discrepancies before export.
6. Export the Excel calculation and check all review notes before using it.
7. If collection/export stops, use **Show saved steps / diagnostics**. The local
   run folder includes action history, partial progress and available failure
   evidence. Never upload these private files to the public repository.

Normal cases use the HTML Form 14 modal; migrated cases use their one-pager and
skip Form 14. Reports are opened by clicking the sidebar. An incomplete report
is never treated as proof of zero payment. A partial case JSON can be loaded for
continued review; refresh payments before export.

Internet is required for SAMPANN. Browser login and OTP remain manual. Use the
tool's own Chrome window. Keep downloaded reports and generated calculations
secure. Full collection and final Excel comparison of the three real cases
remain pending for this version. This guide applies to a portable build only;
the source update does not itself create a new EXE.
