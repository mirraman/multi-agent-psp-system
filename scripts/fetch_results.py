"""
Fetch completed results for jobs 28-37 and dump all key fields.
"""
import json, urllib.request, urllib.error

BASE_URL = "http://localhost:8000"
JOB_IDS = list(range(28, 38))

EVAL_PROTEINS = {
    "P04637": {"name": "TP53",              "group": "G1", "expected": "experimental"},
    "P00533": {"name": "EGFR",              "group": "G1", "expected": "experimental"},
    "P37840": {"name": "Alpha-synuclein",   "group": "G2", "expected": "alphafold_db"},
    "Q99720": {"name": "SIGMAR1",           "group": "G2", "expected": "alphafold_db"},
    "Q8N6T3": {"name": "LRRC32",           "group": "G3", "expected": "esmfold"},
    "P0DTD1": {"name": "SARS-CoV-2 Rep",   "group": "G3", "expected": "esmfold"},
    "Q9Y243": {"name": "AKT3",             "group": "G3", "expected": "esmfold"},
    "P04049": {"name": "RAF1",             "group": "G4", "expected": "esmfold/modal"},
    "P06280": {"name": "Alpha-GalA",       "group": "G4", "expected": "experimental"},
    "O15297": {"name": "PTPN22",           "group": "G4", "expected": "esmfold"},
}

def get(url):
    r = urllib.request.urlopen(url, timeout=15)
    return json.loads(r.read())

all_data = []
for jid in JOB_IDS:
    job = get(f"{BASE_URL}/jobs/{jid}")
    acc = job.get("input_value", "")
    meta = EVAL_PROTEINS.get(acc.upper(), {"name": acc, "group": "?", "expected": "?"})
    
    result = None
    if job.get("status") == "completed":
        try:
            result = get(f"{BASE_URL}/jobs/{jid}/result")
        except Exception as e:
            result = {"error": str(e)}
    
    all_data.append({
        "job_id": jid,
        "accession": acc,
        "name": meta["name"],
        "group": meta["group"],
        "expected": meta["expected"],
        "status": job.get("status"),
        "execution_time": job.get("execution_time"),
        "result": result,
    })
    print(f"Collected job {jid}: {acc} ({meta['name']}) - {job.get('status')}")

with open("scripts/eval_results_raw.json", "w", encoding="utf-8") as f:
    json.dump(all_data, f, indent=2, default=str)
print(f"\nSaved {len(all_data)} results to scripts/eval_results_raw.json")

# Print summary table
print("\n" + "="*140)
print(f"{'#':<3} {'Grp':<5} {'Acc':<10} {'Name':<22} {'Expected':<16} {'Best Model':<22} {'Scenario':<26} {'Quality':<18} {'HC Pockets':<12} {'RMSD Pairs'}")
print("="*140)

order = [
    "P04637","P00533","P37840","Q99720","Q8N6T3","P0DTD1","Q9Y243","P04049","P06280","O15297"
]

for i, acc in enumerate(order, 1):
    row = next((d for d in all_data if d["accession"].upper() == acc.upper()), None)
    if not row:
        print(f"{i:<3}  {acc} -- not found")
        continue
    
    grp = row["group"]
    name = row["name"][:20]
    exp = row["expected"][:14]
    
    if row["status"] != "completed" or not row["result"]:
        print(f"{i:<3} {grp:<5} {acc:<10} {name:<22} {exp:<16} {row['status']}")
        continue
    
    r = row["result"]
    synthesis = r.get("synthesis") or {}
    metrics = r.get("metrics") or {}
    pockets = r.get("pockets") or {}
    analysis = r.get("analysis") or {}
    
    best_model = synthesis.get("best_model") or "—"
    scenario = synthesis.get("scenario") or "—"
    exp_pdb_id = synthesis.get("experimental_pdb_id") or ""
    
    pdb_res = metrics.get("pdb_best_resolution")
    af_plddt = metrics.get("alphafold_confidence") or metrics.get("alphafold_db_plddt_mean")
    esm_plddt = metrics.get("esmfold_plddt_mean")
    pdb_count = metrics.get("pdb_count", 0)
    
    if isinstance(pdb_res, (int, float)):
        quality = f"{pdb_res}Å ({exp_pdb_id})"[:16]
    elif isinstance(af_plddt, (int, float)):
        quality = f"pLDDT {af_plddt:.1f} (AF)"
    elif isinstance(esm_plddt, (int, float)):
        quality = f"pLDDT {esm_plddt:.1f} (ESM)"
    else:
        quality = str(synthesis.get("confidence_score", "?"))[:16]
    
    pocket_summary = pockets.get("pocket_summary") or {}
    hc = str(pocket_summary.get("high_confidence", "?"))
    
    pairwise_rmsd = analysis.get("pairwise_rmsd") or {}
    rmsd_str = "; ".join(f"{k.split('_vs_')[0][:3]}↔{k.split('_vs_')[1][:3]}:{v}Å" for k, v in pairwise_rmsd.items()) if pairwise_rmsd else "—"
    
    exp_expected = exp.lower().replace("/", "|")
    match = "✓" if any(e.strip() in best_model.lower() for e in exp_expected.split("|")) else "✗"
    
    exec_t = row.get("execution_time")
    exec_str = f"({exec_t:.0f}s)" if isinstance(exec_t, (int, float)) else ""
    
    print(f"{i:<3} {grp:<5} {acc:<10} {name:<22} {exp:<16} {best_model:<22} {scenario:<26} {quality:<18} {hc:<12} {rmsd_str} {match} {exec_str}")

print("="*140)
print(f"\nAvailable structures per protein:")
for d in all_data:
    if d.get("result"):
        s = d["result"].get("synthesis") or {}
        avail = s.get("available_structures", [])
        print(f"  {d['accession']}: {avail}")
