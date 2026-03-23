"""
Parse eval_results_raw.json and extract a clean summary table.
"""
import json

with open("scripts/eval_results_raw.json", encoding="utf-8") as f:
    data = json.load(f)

ORDER = [
    "P04637","P00533","P37840","Q99720","Q8N6T3","P0DTD1","Q9Y243","P04049","P06280","O15297"
]

EXPECTED = {
    "P04637": "experimental", "P00533": "experimental",
    "P37840": "alphafold_db", "Q99720": "alphafold_db",
    "Q8N6T3": "esmfold", "P0DTD1": "esmfold", "Q9Y243": "esmfold",
    "P04049": "esmfold/modal", "P06280": "experimental", "O15297": "esmfold",
}

GROUPS = {
    "P04637":"G1","P00533":"G1","P37840":"G2","Q99720":"G2",
    "Q8N6T3":"G3","P0DTD1":"G3","Q9Y243":"G3",
    "P04049":"G4","P06280":"G4","O15297":"G4",
}

lookup = {d["accession"]: d for d in data}

rows = []
for acc in ORDER:
    d = lookup.get(acc, {})
    r = d.get("result") or {}
    synthesis = r.get("synthesis") or {}
    metrics = r.get("metrics") or {}
    pockets = r.get("pockets") or {}
    analysis = r.get("analysis") or {}
    
    grp = GROUPS[acc]
    exp = EXPECTED[acc]
    name = d.get("name", acc)
    status = d.get("status", "?")
    exec_t = d.get("execution_time")
    exec_s = f"{exec_t:.0f}s" if isinstance(exec_t, (int, float)) else "—"
    
    best_model = synthesis.get("best_model") or "—"
    scenario = synthesis.get("scenario") or "—"
    exp_pdb_id = synthesis.get("experimental_pdb_id") or ""
    conf = synthesis.get("confidence_score")
    summ = (synthesis.get("summary") or "")[:90]
    
    pdb_res = metrics.get("pdb_best_resolution")
    af_plddt = metrics.get("alphafold_confidence") or metrics.get("alphafold_db_plddt_mean")
    esm_plddt = metrics.get("esmfold_plddt_mean")
    pdb_count = metrics.get("pdb_count", 0)
    seq_len = metrics.get("sequence_length", "?")
    
    pocket_summary = pockets.get("pocket_summary") or {}
    hc_pockets = pocket_summary.get("high_confidence", "—")
    total_pockets = pocket_summary.get("total", "—")
    
    pairwise_rmsd = analysis.get("pairwise_rmsd") or {}
    models_used = r.get("models_used") or []
    available = synthesis.get("available_structures") or []
    
    exp_lower = exp.lower().replace("/", "|")
    match = "✓" if any(e.strip() in best_model.lower() for e in exp_lower.split("|")) else "✗"
    
    rows.append({
        "acc": acc, "name": name, "grp": grp, "expected": exp,
        "status": status, "exec_s": exec_s,
        "best_model": best_model, "scenario": scenario,
        "exp_pdb_id": exp_pdb_id, "conf": conf,
        "pdb_res": pdb_res, "af_plddt": af_plddt, "esm_plddt": esm_plddt,
        "pdb_count": pdb_count, "seq_len": seq_len,
        "hc_pockets": hc_pockets, "total_pockets": total_pockets,
        "pairwise_rmsd": pairwise_rmsd, "models_used": models_used,
        "available": available, "match": match, "summary": summ,
    })

print("RAW TABLE:")
print("-"*160)
for i, row in enumerate(rows,1):
    # Quality metric
    if isinstance(row["pdb_res"], (int, float)):
        quality = f"{row['pdb_res']}Å ({row['exp_pdb_id']})"
    elif isinstance(row["af_plddt"], (int, float)):
        quality = f"pLDDT {row['af_plddt']:.1f}"
    elif isinstance(row["esm_plddt"], (int, float)):
        quality = f"pLDDT {row['esm_plddt']:.1f}"
    else:
        quality = str(row["conf"] or "—")
    
    rmsd_str = "; ".join(f"{k}:{v}Å" for k,v in row["pairwise_rmsd"].items()) or "—"
    
    print(f"\n#{i} {row['grp']} | {row['acc']} | {row['name']}")
    print(f"  Status: {row['status']} | Time: {row['exec_s']} | SeqLen: {row['seq_len']}")
    print(f"  Best Model: {row['best_model']} | Scenario: {row['scenario']} | {row['match']} (expected: {row['expected']})")
    print(f"  Quality: {quality} | PDB Count: {row['pdb_count']}")
    print(f"  Pockets HC: {row['hc_pockets']} / Total: {row['total_pockets']}")
    print(f"  RMSD: {rmsd_str}")
    print(f"  Models Used: {row['models_used']}")
    print(f"  Available: {row['available']}")
    print(f"  Summary: {row['summary']}")
