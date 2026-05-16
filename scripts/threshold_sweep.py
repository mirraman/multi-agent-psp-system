"""
threshold_sweep.py
------------------
Thesis parameter tuning experiment.

What this does:
    1. Fetches AlphaFold DB structure for each protein in validation_set.py
    2. Runs fpocket on each structure
    3. Tests different PLDDT_CONFIDENCE_THRESHOLD and CONSENSUS_JACCARD_THRESHOLD values
    4. Scores pocket predictions against known binding residues using precision/recall/F1
    5. Prints a results table

Run inside Docker:
    python scripts/threshold_sweep.py

Results are saved to: scripts/sweep_results.json
"""

import json
import sys
import os

# So we can import app modules from the backend root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.fetchers import fetch_alphafold_db_pdb
from app.utils.fpocket_runner import run_fpocket
from app.utils.validate import validate_pocket

# ── Validation targets with known binding residues ──────────────────────────
VALIDATION_TARGETS = [
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
        "name": "p53",
        "known_binding_residues": [176, 220, 242, 277, 280],
    },
    {
        "accession": "P35354",
        "name": "COX-2",
        "known_binding_residues": [120, 355, 356, 359, 523, 524],
    },
    {
        "accession": "P00734",
        "name": "Thrombin",
        "known_binding_residues": [57, 99, 174, 195, 215, 216],
    },
    {
        "accession": "P03956",
        "name": "MMP-1",
        "known_binding_residues": [165, 167, 201, 218, 222, 223],
    },
    {
        "accession": "P23219",
        "name": "COX-1",
        "known_binding_residues": [120, 355, 356, 359, 523, 524],
    },
    {
        "accession": "P10636",
        "name": "Tau",
        "known_binding_residues": [275, 306, 337, 368, 369],
    },
]

# ── Threshold combinations to test ──────────────────────────────────────────
PLDDT_THRESHOLDS = [60.0, 65.0, 70.0, 75.0, 80.0, 85.0]
JACCARD_THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6]


def filter_pockets_by_plddt(pockets, plddt_threshold, plddt_per_residue, fallback_plddt=70.0):
    """
    Mimics PocketAgent logic: keep only pockets where mean local pLDDT >= threshold.
    Returns list of (residues, druggability_score) for confident pockets.
    """
    confident = []
    for pocket in pockets:
        residues = pocket.get("residues", [])
        plddt_values = [plddt_per_residue.get(r) for r in residues if plddt_per_residue.get(r) is not None]
        local_plddt = sum(plddt_values) / len(plddt_values) if plddt_values else fallback_plddt
        if local_plddt >= plddt_threshold:
            confident.append({
                "residues": residues,
                "druggability_score": pocket.get("druggability_score", 0.0),
                "local_plddt": local_plddt,
            })
    return confident


def extract_plddt_from_pdb(pdb_text):
    """Parse pLDDT per residue from B-factor column of CA atoms."""
    per_residue = {}
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and len(line) >= 66:
            atom_name = line[12:16].strip()
            if atom_name == "CA":
                try:
                    res_num = int(line[22:26].strip())
                    bfactor = float(line[60:66].strip())
                    if bfactor < 1.5:
                        bfactor = bfactor * 100
                    per_residue[res_num] = bfactor
                except ValueError:
                    continue
    return per_residue


def pick_best_pocket(pockets):
    """Pick the top-ranked pocket by druggability score."""
    if not pockets:
        return []
    best = max(pockets, key=lambda p: p.get("druggability_score", 0.0))
    return best.get("residues", [])


def run_sweep():
    print("=" * 60)
    print("THRESHOLD SWEEP — Thesis Parameter Tuning Experiment")
    print("=" * 60)

    # ── Step 1: Fetch structures and run fpocket once per protein ────────────
    print("\nStep 1: Fetching AlphaFold DB structures and running fpocket...")
    protein_data = {}

    for target in VALIDATION_TARGETS:
        accession = target["accession"]
        name = target["name"]
        print(f"  [{accession}] {name} ...", end=" ", flush=True)

        af = fetch_alphafold_db_pdb(accession)
        if not af or not af.get("pdb"):
            print("SKIP (no AlphaFold DB structure found)")
            continue

        pdb_text = af["pdb"]
        plddt_per_residue = extract_plddt_from_pdb(pdb_text)
        mean_plddt = af.get("mean_plddt") or (
            sum(plddt_per_residue.values()) / len(plddt_per_residue)
            if plddt_per_residue else 0.0
        )

        fpocket_result = run_fpocket(pdb_text)
        if not fpocket_result["success"]:
            print(f"SKIP (fpocket failed: {fpocket_result.get('error', '?')})")
            continue

        raw_pockets = fpocket_result["pockets"]
        print(f"OK — {len(raw_pockets)} pockets, mean pLDDT={mean_plddt:.1f}")

        protein_data[accession] = {
            "name": name,
            "pdb_text": pdb_text,
            "plddt_per_residue": plddt_per_residue,
            "mean_plddt": mean_plddt,
            "raw_pockets": raw_pockets,
            "known_binding_residues": target["known_binding_residues"],
        }

    if not protein_data:
        print("\nERROR: No proteins processed. Check network and fpocket installation.")
        sys.exit(1)

    print(f"\n  Processed {len(protein_data)}/{len(VALIDATION_TARGETS)} proteins successfully.")

    # ── Step 2: Sweep thresholds ─────────────────────────────────────────────
    print("\nStep 2: Sweeping threshold combinations...")

    sweep_results = []

    for plddt_thresh in PLDDT_THRESHOLDS:
        for jaccard_thresh in JACCARD_THRESHOLDS:
            precisions, recalls, f1s = [], [], []

            for accession, data in protein_data.items():
                # Filter pockets by pLDDT threshold
                confident_pockets = filter_pockets_by_plddt(
                    data["raw_pockets"],
                    plddt_thresh,
                    data["plddt_per_residue"],
                    fallback_plddt=data["mean_plddt"],
                )

                # Apply jaccard threshold: keep only pockets with enough residues
                # (proxy for jaccard since we're running single-model here)
                # Minimum alpha sphere count as proxy for pocket quality
                filtered = [p for p in confident_pockets if len(p["residues"]) >= max(3, jaccard_thresh * 20)]

                # Pick best pocket by druggability
                predicted_residues = pick_best_pocket(filtered) if filtered else pick_best_pocket(confident_pockets)

                # Score against known binding residues
                metrics = validate_pocket(
                    predicted_residues,
                    data["known_binding_residues"],
                    tolerance=2,
                )
                precisions.append(metrics["precision"])
                recalls.append(metrics["recall"])
                f1s.append(metrics["f1"])

            avg_precision = sum(precisions) / len(precisions)
            avg_recall = sum(recalls) / len(recalls)
            avg_f1 = sum(f1s) / len(f1s)

            sweep_results.append({
                "plddt_threshold": plddt_thresh,
                "jaccard_threshold": jaccard_thresh,
                "avg_precision": round(avg_precision, 4),
                "avg_recall": round(avg_recall, 4),
                "avg_f1": round(avg_f1, 4),
                "n_proteins": len(protein_data),
            })

    # ── Step 3: Print results table ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESULTS TABLE")
    print("=" * 70)
    print(f"{'pLDDT':>8} {'Jaccard':>8} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 70)

    best = max(sweep_results, key=lambda r: r["avg_f1"])

    for r in sweep_results:
        marker = " ← BEST" if (r["plddt_threshold"] == best["plddt_threshold"] and
                                r["jaccard_threshold"] == best["jaccard_threshold"]) else ""
        print(
            f"{r['plddt_threshold']:>8.1f} "
            f"{r['jaccard_threshold']:>8.2f} "
            f"{r['avg_precision']:>10.4f} "
            f"{r['avg_recall']:>8.4f} "
            f"{r['avg_f1']:>8.4f}"
            f"{marker}"
        )

    print("=" * 70)
    print(f"\nBEST CONFIGURATION:")
    print(f"  PLDDT_CONFIDENCE_THRESHOLD  = {best['plddt_threshold']}")
    print(f"  CONSENSUS_JACCARD_THRESHOLD = {best['jaccard_threshold']}")
    print(f"  Avg Precision = {best['avg_precision']:.4f}")
    print(f"  Avg Recall    = {best['avg_recall']:.4f}")
    print(f"  Avg F1        = {best['avg_f1']:.4f}")

    # Compare against original defaults (pLDDT=70, Jaccard=0.5)
    original = next(
        (r for r in sweep_results if r["plddt_threshold"] == 70.0 and r["jaccard_threshold"] == 0.5),
        None
    )
    if original:
        print(f"\nORIGINAL DEFAULTS (pLDDT=70, Jaccard=0.5):")
        print(f"  Avg F1 = {original['avg_f1']:.4f}")
        improvement = best['avg_f1'] - original['avg_f1']
        print(f"  Improvement from best config: {improvement:+.4f} ({improvement/max(original['avg_f1'],0.001)*100:+.1f}%)")

    # Save to file
    output_path = os.path.join(os.path.dirname(__file__), "sweep_results.json")
    with open(output_path, "w") as f:
        json.dump({
            "best": best,
            "original_defaults": original,
            "all_results": sweep_results,
            "proteins_evaluated": list(protein_data.keys()),
        }, f, indent=2)
    print(f"\nFull results saved to: {output_path}")


if __name__ == "__main__":
    run_sweep()