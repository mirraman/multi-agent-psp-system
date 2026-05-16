# CASP Benchmark Setup Guide

This directory contains the CASP15/CAMEO benchmark for validating the ensemble protein structure prediction system.

## Directory Structure

```
casp_benchmark/
├── sequences/           # Protein sequences in FASTA format
├── experimental_structures/  # Ground truth PDB files
├── results/
│   ├── esmfold/        # ESMFold baseline results
│   ├── colabfold/      # ColabFold baseline results
│   ├── alphafold_db/   # AlphaFold DB baseline results
│   └── ensemble/       # Your ensemble results
└── README.md
```

## Step 1: Download CASP15 Target Data

### Option A: CASP15 Official Targets (Recommended)

1. Visit the CASP15 prediction center:
   ```
   https://www.predictioncenter.org/casp15/targetlist.cgi
   ```

2. Select 30-40 targets from categories:
   - Difficulty: **Medium** and **Hard** (skip Easy)
   - Type: Free modeling (FM) and template-based modeling (TBM)
   - Domains with confirmed experimental structures

3. Download sequences:
   ```bash
   # Download FASTA sequences for each target
   # Example targets: T1104, T1106, T1108, T1124, etc.
   wget https://www.predictioncenter.org/casp15/target.cgi?target=T1104&view=sequence
   ```

4. Download experimental structures:
   ```bash
   # After CASP15 ended, experimental structures are released
   wget https://www.predictioncenter.org/casp15/target.cgi?target=T1104&view=native
   ```

### Option B: CAMEO Continuous Evaluation (Faster)

CAMEO provides weekly protein targets with quick experimental validation:

1. Visit CAMEO: https://www.cameo3d.org/
2. Download recent week's targets (30-40 proteins)
3. Extract sequences and experimental structures

### Option C: Use Pre-Curated Benchmark Set

If you have access to a curated benchmark dataset (e.g., from research papers or databases), place:
- Sequences in `sequences/targets.fasta`
- Experimental PDBs in `experimental_structures/<target_id>.pdb`

## Step 2: Prepare Target Metadata

Create `sequences/targets.json` with metadata:

```json
[
  {
    "target_id": "T1104",
    "length": 256,
    "difficulty": "hard",
    "category": "FM",
    "uniprot_id": "Q9Y6K9",
    "experimental_pdb": "8ABC",
    "notes": "Intrinsically disordered region"
  },
  ...
]
```

## Step 3: Combine with Thesis Targets

The 10 thesis targets from `app/utils/evaluation_thesis_targets.py` will be automatically included:
- Q9Y6K9 (IDR)
- P04637 (p53)
- P01308 (Insulin)
- P37840 (Alpha-synuclein)
- Q14192 (FUS)
- P10636 (Tau)
- P00533 (EGFR)
- P00734 (Thrombin)
- O60260 (Parkin RBR)
- P08559 (CD45)

## Step 4: Run Baseline Evaluations

See `scripts/eval_*.py` for running each tool:

```bash
# ESMFold baseline
python scripts/eval_esmfold_baseline.py

# ColabFold baseline (run in Google Colab or local)
python scripts/eval_colabfold_baseline.py

# AlphaFold DB baseline (API lookups)
python scripts/eval_alphafold_baseline.py

# Your ensemble system
python scripts/eval_ensemble.py
```

## Step 5: Calculate Metrics

```bash
# Calculate RMSD, pLDDT, and other metrics
python scripts/calculate_metrics.py

# Statistical analysis (t-tests, p-values)
python scripts/statistical_analysis.py

# Generate visualizations for thesis
python scripts/generate_thesis_visualizations.py
```

## Expected Timeline

- **Data setup**: 1-2 days
- **Baseline runs**: 2-3 days (parallelized)
- **Analysis**: 2-3 days
- **Total**: ~1 week

## Notes

- If you don't have time for full CASP download, start with just the 10 thesis targets
- Can expand to 30-40 proteins later for more rigorous validation
- Make sure experimental structures are available for all targets (required for RMSD calculation)
