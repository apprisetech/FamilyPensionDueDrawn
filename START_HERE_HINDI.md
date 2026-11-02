# कैसे इस्तेमाल करें

1. ZIP को Extract करें। Python 3.12 (64-bit) और Google Chrome installed होने चाहिए।
2. पहली बार `INSTALL.bat` चलाएँ। Scanned PDF के लिए `INSTALL_OCR.bat` भी चलाएँ।
3. `START.bat` से tool खोलें।
4. **Open Chrome / Login** दबाएँ और उसी Chrome window में SAMPANN login तथा OTP पूरा करें।
5. 15-digit pension number भरें और **Collect case** दबाएँ।
6. Order, original pension और migrated details से भरे fields review करें। कोई field खाली हो तो source देखकर भरें या **Import PDF** इस्तेमाल करें।
   Death date को conversion w.e.f. से एक दिन पहले की date से compare किया जाएगा। Match पर स्वीकार होगी। Mismatch / missing record पर सही date भरकर **Confirm reviewed death date** दबाएँ; discrepancy का note Excel में रहेगा।
7. अपना updated `DR_Master.xlsx` चुनें। IDA या CDA source के अनुसार select करें।
8. **Payments / allocation** में report और March–April mapping देखें। बिना payment वाले महीने tool zero रखेगा।
9. Review checkbox tick करें और **Calculate and export Excel** दबाएँ।

Account number, IFSC, dates और amounts source order से मिलाएँ। OCR में गलत digit आने की संभावना रहती है। अस्पष्ट field को tool अनुमान से नहीं भरेगा।

Output का नाम: `15digitPPO_FAMILY_PENSIONER_NAME.xlsx`।

**पहला live run अभी जरूरी है:** calculation, export और death-date comparison के 27 tests पास हुए हैं। इस नए environment से आपके SAMPANN login पर collector चलाकर verify नहीं किया जा सका है। Portal के किसी बदले हुए field/viewer के लिए पहली बार छोटा adjustment लग सकता है।

पूरा तरीका और limitations `README.md` में हैं।
