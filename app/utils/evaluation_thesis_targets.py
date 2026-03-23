"""
Curated UniProt accessions for thesis evaluation (10 proteins).

Categories:
- no_or_weak_experimental: AlphaFold / ensemble adds most value
- poor_quality_experimental: moderate resolution or incomplete; ensemble rationale matters
- high_quality_experimental: synthesis should recommend crystal structure
"""

from typing import Dict, List

EVALUATION_THESIS_TARGETS: List[Dict[str, str]] = [
    {
        "accession": "Q9Y6K9",
        "category": "no_or_weak_experimental",
        "note": "IDR / disordered regions — often no clean PDB; AF useful",
    },
    {
        "accession": "P04637",
        "category": "high_quality_experimental",
        "note": "p53 — many high-resolution structures; prefer experimental when available",
    },
    {
        "accession": "P01308",
        "category": "high_quality_experimental",
        "note": "Insulin — extensive crystallography",
    },
    {
        "accession": "P37840",
        "category": "poor_quality_experimental",
        "note": "Alpha-synuclein — fibril/snapshot structures; resolution varies",
    },
    {
        "accession": "Q14192",
        "category": "no_or_weak_experimental",
        "note": "FUS — low coverage in PDB; AF fills gaps",
    },
    {
        "accession": "P10636",
        "category": "poor_quality_experimental",
        "note": "Tau — heterogeneous constructs; compare AF vs PDB",
    },
    {
        "accession": "P00533",
        "category": "poor_quality_experimental",
        "note": "EGFR — mix of excellent and lower-res complexes",
    },
    {
        "accession": "P00734",
        "category": "high_quality_experimental",
        "note": "Thrombin — classic well-resolved drug target",
    },
    {
        "accession": "O60260",
        "category": "no_or_weak_experimental",
        "note": "Parkin RBR — limited full-length experimental coverage",
    },
    {
        "accession": "P08559",
        "category": "poor_quality_experimental",
        "note": "CD45 — membrane protein; experimental data often challenging",
    },
]
