from typing import Dict, List

# Known drug-target binding residues for validation benchmarking.
# Residues are 1-based sequence positions from literature/structure annotations.
VALIDATION_TARGETS: List[Dict[str, object]] = [
    {
        "accession": "P00918",
        "name": "Carbonic anhydrase 2",
        "known_binding_residues": [91, 92, 94, 96, 119, 199, 200, 202],
    },
    {
        "accession": "P07900",
        "name": "HSP90-alpha",
        "known_binding_residues": [98, 138, 172, 174, 176, 184],
    },
    {
        "accession": "P00533",
        "name": "EGFR",
        "known_binding_residues": [719, 721, 766, 768, 790, 793],
    },
    {
        "accession": "P24941",
        "name": "CDK2",
        "known_binding_residues": [10, 33, 81, 83, 145, 146],
    },
    {
        "accession": "P04637",
        "name": "Tumor protein p53",
        "known_binding_residues": [176, 220, 242, 277, 280],
    },
    {
        "accession": "P35354",
        "name": "Prostaglandin G/H synthase 2",
        "known_binding_residues": [120, 355, 356, 359, 523, 524],
    },
    {
        "accession": "P00734",
        "name": "Prothrombin",
        "known_binding_residues": [57, 99, 174, 195, 215, 216],
    },
    {
        "accession": "P03956",
        "name": "Matrix metalloproteinase-1",
        "known_binding_residues": [165, 167, 201, 218, 222, 223],
    },
    {
        "accession": "P23219",
        "name": "Prostaglandin G/H synthase 1",
        "known_binding_residues": [120, 355, 356, 359, 523, 524],
    },
    {
        "accession": "P10636",
        "name": "Tau protein",
        "known_binding_residues": [275, 306, 337, 368, 369],
    },
]
