import json

d = json.load(open("scripts/eval_results_raw.json"))
for item in d:
    acc = item["accession"]
    r = item.get("result") or {}
    s = r.get("synthesis") or {}
    m = r.get("metrics") or {}
    p = r.get("pockets") or {}
    a = r.get("analysis") or {}
    ps = p.get("pocket_summary") or {}
    et = item.get("execution_time")
    
    best = s.get("best_model")
    scenario = s.get("scenario")
    exp_pdb = s.get("experimental_pdb_id")
    pdb_res = m.get("pdb_best_resolution")
    af_plddt = m.get("alphafold_confidence") or m.get("alphafold_db_plddt_mean")
    esm_plddt = m.get("esmfold_plddt_mean")
    pdb_count = m.get("pdb_count")
    seq_len = m.get("sequence_length")
    hc = ps.get("high_confidence")
    rmsd = list(a.get("pairwise_rmsd", {}).items())
    used = r.get("models_used", [])
    summ = (s.get("summary") or "")[:120]
    exec_s = f"{et:.0f}" if isinstance(et, (int, float)) else "?"
    
    print(f"ACC={acc} BEST={best} SCENARIO={scenario} PDB_ID={exp_pdb} RES={pdb_res} AF_PLDDT={af_plddt} ESM_PLDDT={esm_plddt} PDB_COUNT={pdb_count} SEQ_LEN={seq_len} HC_POCKETS={hc} RMSD={rmsd} MODELS={used} TIME={exec_s}s SUMMARY={repr(summ)}")
