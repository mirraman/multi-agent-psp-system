Group 1 — System should pick experimental (tests your synthesis hierarchy fix)
P04637 — TP53 tumor suppressor. Cancer's most mutated protein. Tons of crystal structures. Your system should correctly defer to experimental PDB.
P00533 — EGFR. Major lung cancer drug target, excellent experimental data. Same — should pick experimental.

Group 2 — AlphaFold DB should win (limited experimental, good AF confidence)
P37840 — Alpha-synuclein. Parkinson's disease. Intrinsically disordered, poor experimental coverage, AlphaFold DB handles it better than crystal structures suggest.
Q99720 — SIGMAR1. Sigma receptor, implicated in neurodegeneration and COVID-19. Limited high-res experimental data.

Group 3 — ESMFold is the only option (no/minimal experimental structure — your system actually shines here)
Q8N6T3 — LRRC32. Poorly characterized, disease associations, minimal structural data.
P0DTD1 — This is SARS-CoV-2 replicase polyprotein. Novel enough that predictions are genuinely useful.
Q9Y243 — AKT3. Cancer relevant kinase with limited structural coverage compared to AKT1/AKT2.

Group 4 — Stress tests
P04049 — RAF1. Long sequence, tests your Modal/ESMFold routing threshold.
P06280 — Alpha-galactosidase A. Fabry disease — rare genetic disorder. Good story for why the tool matters.
O15297 — PTPN22. Autoimmune disease target, rheumatoid arthritis, type 1 diabetes. Limited structural data, real drug discovery relevance.