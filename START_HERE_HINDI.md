# कैसे इस्तेमाल करें

1. ZIP को Extract करें। Python 3.12 (64-bit) और Google Chrome installed होने चाहिए।
2. पहली बार `INSTALL.bat` चलाएँ। Scanned PDF के लिए `INSTALL_OCR.bat` भी चलाएँ।
3. `START.bat` से tool खोलें।
4. **Open Chrome / Login** दबाएँ और उसी Chrome window में SAMPANN login तथा OTP पूरा करें।
5. 15-digit pension number भरें और **Collect case** दबाएँ।
6. Order, original pension और migrated details से भरे fields review करें। कोई field खाली हो तो source देखकर भरें या **Import PDF** इस्तेमाल करें।
   Death date को conversion w.e.f. से एक दिन पहले की date से compare किया जाएगा। Match पर स्वीकार होगी। Mismatch / missing record पर सही date भरकर **Confirm reviewed death date** दबाएँ; discrepancy का note Excel में रहेगा।
7. अपना updated `DR_Master.xlsx` चुनें। IDA या CDA source के अनुसार select करें।
8. **Payments / allocation** में report और March–April mapping देखें। पूरी सफल query में payment न मिलने पर ही zero माना जाएगा; error या अधूरी report को zero नहीं माना जाएगा।
9. Review checkbox tick करें और **Calculate and export Excel** दबाएँ।

Account number, IFSC, dates और amounts source order से मिलाएँ। OCR में गलत digit आने की संभावना रहती है। अस्पष्ट field को tool अनुमान से नहीं भरेगा।

Output का नाम: `15digitPPO_FAMILY_PENSIONER_NAME.xlsx`।

Normal SAMPANN में Form 14 का HTML modal पढ़ा जाएगा। Migrated SAMPANN में Form 14 छोड़कर profile के अलग-अलग sections पढ़े जाएँगे। Category केवल स्पष्ट IDA/CDA source से ली जाएगी।

**Show saved steps / diagnostics** से हर run का record खोलें। Error पर किए गए steps, partial data और उपलब्ध screenshot/page snapshot अपने-आप local folder में बचेंगे। Login/OTP screens record नहीं होंगी। यह private data है; अपने-आप कहीं upload नहीं होगा। Partial case JSON को load करके review जारी रख सकते हैं; फिर payment report refresh करें।

**Live comparison बाकी है:** local calculation, source parsing, Excel export और अलग test Chrome पर menu से PDF download तक के tests पास हैं। इस version से तीनों असली cases की पूरी collection और final Excel comparison को अभी verified न मानें। नया EXE नहीं बनाया गया है; source के लिए START.bat चलाएँ।

पूरा तरीका और limitations `README.md` में हैं।
