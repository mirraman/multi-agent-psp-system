"""
Collect results for jobs 28-37 (our eval run jobs).
Polls until all complete or timeout, then saves final results.
"""
import time, json, urllib.request, urllib.error

BASE_URL = "http://localhost:8000"

# Map accession -> our metadata
EVAL_PROTEINS = {
    "P04637": {"name": "TP53",              "group": "G1", "expected": "experimental"},
    "P00533": {"name": "EGFR",              "group": "G1", "expected": "experimental"},
    "P37840": {"name": "Alpha-synuclein",   "group": "G2", "expected": "alphafold_db"},
    "Q99720": {"name": "SIGMAR1",           "group": "G2", "expected": "alphafold_db"},
    "Q8N6T3": {"name": "LRRC32",           "group": "G3", "expected": "esmfold"},
    "P0DTD1": {"name": "SARS-CoV-2 Rep",   "group": "G3", "expected": "esmfold"},
    "Q9Y243": {"name": "AKT3",             "group": "G3", "expected": "esmfold"},
    "P04049": {"name": "RAF1",             "group": "G4", "expected": "esmfold/modal"},
    "P06280": {"name": "α-GalA",           "group": "G4", "expected": "experimental"},
    "O15297": {"name": "PTPN22",           "group": "G4", "expected": "esmfold"},
}

JOB_IDS = list(range(28, 38))

def get_job(jid):
    try:
        r = urllib.request.urlopen(f"{BASE_URL}/jobs/{jid}", timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {"id": jid, "error": str(e)}

def get_result(jid):
    try:
        r = urllib.request.urlopen(f"{BASE_URL}/jobs/{jid}/result", timeout=10)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return None  # not complete
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}

def poll_all(job_ids, max_secs=600, interval=20):
    pending = set(job_ids)
    results = {}
    deadline = time.time() + max_secs
    
    while pending and time.time() < deadline:
        for jid in list(pending):
            status_data = get_job(jid)
            status = status_data.get("status", "unknown")
            acc = status_data.get("input_value", f"job{jid}")[:10]
            print(f"  job {jid} ({acc}): {status}", flush=True)
            
            if status == "completed":
                result_data = get_result(jid)
                results[jid] = {
                    "job_id": jid,
                    "accession": status_data.get("input_value", ""),
                    "status": "completed",
                    "result": result_data,
                    "execution_time": status_data.get("execution_time"),
                }
                pending.discard(jid)
            elif status == "failed":
                results[jid] = {
                    "job_id": jid,
                    "accession": status_data.get("input_value", ""),
                    "status": "failed",
                    "error": status_data.get("error_message", "unknown"),
                    "result": None,
                }
                pending.discard(jid)
        
        if pending:
            remaining = int(deadline - time.time())
            print(f"\n  {len(pending)} pending. Sleeping {interval}s... ({remaining}s left)", flush=True)
            time.sleep(interval)
    
    for jid in pending:
        results[jid] = {"job_id": jid, "status": "timeout", "result": None}
    
    return results

def extract_key_metrics(result_data):
    if not result_data:
        return {}
    synthesis = result_data.get("synthesis") or {}
    metrics = result_data.get("metrics") or {}
    pockets = result_data.get("pockets") or {}
    analysis = result_data.get("analysis") or {}
    
    pocket_summary = pockets.get("pocket_summary") or {}
    pairwise_rmsd = analysis.get("pairwise_rmsd") or {}
    
    return {
        "best_model":        synthesis.get("best_model"),
        "best_model_source": synthesis.get("best_model_source"),
        "scenario":          synthesis.get("scenario"),
        "confidence_score":  synthesis.get("confidence_score"),
        "synthesis_summary": synthesis.get("summary"),
        "exp_pdb_id":        synthesis.get("experimental_pdb_id"),
        "models_used":       result_data.get("models_used", []),
        "esmfold_plddt":     metrics.get("esmfold_plddt_mean"),
        "pdb_best_res":      metrics.get("pdb_best_resolution"),
        "af_plddt":          metrics.get("alphafold_confidence") or metrics.get("alphafold_db_plddt_mean"),
        "pdb_count":         metrics.get("pdb_count"),
        "total_pockets":     pocket_summary.get("total"),
        "high_conf_pockets": pocket_summary.get("high_confidence"),
        "pairwise_rmsd":     pairwise_rmsd,
        "available_structures": synthesis.get("available_structures", []),
    }

def print_table(all_results):
    print("\n" + "="*130)
    print(f"{'#':<3} {'Grp':<5} {'Accession':<10} {'Name':<20} {'Status':<10} {'Best Model':<20} "
          f"{'Scenario':<25} {'Conf/Res/pLDDT':<16} {'HC Pockets':<11} {'PDB Count':<10} {'Match?'}")
    print("="*130)
    
    order = [
        ("P04637","G1"),("P00533","G1"),
        ("P37840","G2"),("Q99720","G2"),
        ("Q8N6T3","G3"),("P0DTD1","G3"),("Q9Y243","G3"),
        ("P04049","G4"),("P06280","G4"),("O15297","G4"),
    ]
    
    for i, (acc, grp) in enumerate(order, 1):
        meta = EVAL_PROTEINS.get(acc, {})
        name = meta.get("name", acc)[:18]
        expected = meta.get("expected", "?")
        
        # Find job for this accession
        job = None
        for jid, r in all_results.items():
            if r.get("accession", "").upper() == acc.upper():
                job = r
                break
        
        if not job:
            print(f"{i:<3} {grp:<5} {acc:<10} {name:<20} {'NOT FOUND':<10}")
            continue
        
        status = job.get("status", "?")
        exec_t = job.get("execution_time")
        exec_str = f"{exec_t:.0f}s" if isinstance(exec_t, (int, float)) else "?"
        
        if status != "completed" or not job.get("result"):
            err = job.get("error", "")[:30]
            print(f"{i:<3} {grp:<5} {acc:<10} {name:<20} {status:<10} {err}")
            continue
        
        m = extract_key_metrics(job["result"])
        best = (m.get("best_model") or "—")[:18]
        scenario = (m.get("scenario") or "—")[:23]
        
        pdb_res = m.get("pdb_best_res")
        af_plddt = m.get("af_plddt")
        esm_plddt = m.get("esmfold_plddt")
        exp_id = m.get("exp_pdb_id") or ""
        
        if isinstance(pdb_res, (int, float)):
            conf_str = f"{pdb_res}Å {exp_id}"[:14]
        elif isinstance(af_plddt, (int, float)):
            conf_str = f"pLDDT {af_plddt:.0f}"
        elif isinstance(esm_plddt, (int, float)):
            conf_str = f"pLDDT {esm_plddt:.0f}"
        else:
            conf_str = str(m.get("confidence_score", "?"))[:14]
        
        hc = str(m.get("high_conf_pockets", "?"))
        pdb_cnt = str(m.get("pdb_count", "?"))
        
        exp_lower = expected.lower().replace("/", "|")
        match = "✓" if any(e.strip() in best.lower() for e in exp_lower.split("|")) else "✗"
        
        print(f"{i:<3} {grp:<5} {acc:<10} {name:<20} {status:<10} {best:<20} {scenario:<25} {conf_str:<16} {hc:<11} {pdb_cnt:<10} {match} ({exec_str})")
    
    print("="*130)

def print_rmsd_section(all_results):
    print("\n--- Ensemble RMSD (pairwise, Angstroms) ---")
    for jid, job in all_results.items():
        if not job.get("result"):
            continue
        acc = job["accession"]
        m = extract_key_metrics(job["result"])
        rmsd = m.get("pairwise_rmsd") or {}
        if rmsd:
            print(f"{acc}: {json.dumps(rmsd)}")
        else:
            print(f"{acc}: no pairwise RMSD (single model)")

if __name__ == "__main__":
    print("=== Collecting Evaluation Results ===")
    print(f"Polling jobs {JOB_IDS[0]}-{JOB_IDS[-1]} ...\n")
    
    all_results = poll_all(JOB_IDS, max_secs=600, interval=20)
    
    print("\n[TABLE]")
    print_table(all_results)
    print_rmsd_section(all_results)
    
    # Save raw results
    with open("scripts/eval_results_raw.json", "w") as f:
        json.dump(list(all_results.values()), f, indent=2, default=str)
    print("\nRaw results saved to scripts/eval_results_raw.json")
